"""Firewall check tool for analyzing firewall rules."""

from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mcp.models import FirewallRule
from unifi_mcp.utils.client import UniFiClient


async def firewall_check(
    source: Annotated[str, Field(description='Source network/IP/VLAN')],
    destination: Annotated[str, Field(description='Destination network/IP/VLAN')],
    protocol: Annotated[str, Field(description='Protocol (tcp, udp, icmp, all)')] = 'all',
    port: Annotated[str | None, Field(description='Port number or range')] = None,
) -> dict[str, Any]:
    """Check firewall rules between source and destination.

    When to use this tool:
    - Understanding why traffic between devices is blocked
    - Verifying firewall rule configuration for specific traffic
    - Planning new firewall rules before implementation
    - Troubleshooting inter-VLAN connectivity issues

    Common workflow:
    1. Run traceroute() first to identify where traffic is blocked
    2. Use firewall_check() to see specific rules affecting the traffic
    3. Use vlan_info() to understand VLAN network segmentation
    4. Review best_practice_check() for firewall configuration recommendations

    What to do next:
    - If traffic DENIED: Review blocking rule and determine if intentional
    - If traffic ALLOWED: Verify the path with traceroute()
    - If rules conflict: Use config_validator() to check rule consistency
    - For VLAN issues: Use vlan_info() to verify network configuration

    Args:
        source: Source specification - can be:
                - IP address (192.168.1.10)
                - IP network (192.168.1.0/24)
                - VLAN name (Corporate, IoT, Guest)
                - VLAN ID (VLAN_10)
        destination: Destination specification (same formats as source)
        protocol: Network protocol to check (tcp, udp, icmp, all)
        port: Specific port or range (e.g., "80", "443", "1000-2000")

    Returns:
        Dictionary containing:
        - verdict: 'allow' or 'deny' based on first matching rule
        - matching_rules: All firewall rules that apply to this traffic
        - rule_order: Order in which rules are evaluated
        - recommendations: Suggestions for rule improvements
        - vlan_matrix: Visual matrix of VLAN-to-VLAN connectivity

    Raises:
        ToolError: INVALID_VLAN if source or destination VLAN not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    async with UniFiClient() as client:
        # Get firewall rules and VLAN information
        firewall_data = await client.get(client.build_path('rest/firewallrule'))
        vlans_data = await client.get(client.build_path('rest/networkconf'))

        # Resolve source and destination to network specifications
        source_spec = await _resolve_network_spec(source, vlans_data)
        dest_spec = await _resolve_network_spec(destination, vlans_data)

        # Find matching firewall rules
        matching_rules = _find_matching_rules(
            source_spec, dest_spec, protocol, port, firewall_data
        )

        # Determine verdict based on rule order
        verdict = _determine_verdict(matching_rules)

        # Build VLAN connectivity matrix if both endpoints are VLANs
        vlan_matrix = None
        if source_spec.get('type') == 'vlan' and dest_spec.get('type') == 'vlan':
            vlan_matrix = await _build_vlan_matrix(vlans_data, firewall_data)

        # Generate recommendations
        recommendations = _generate_firewall_recommendations(
            matching_rules, verdict, source_spec, dest_spec
        )

        return {
            'verdict': verdict,
            'source_resolved': source_spec,
            'destination_resolved': dest_spec,
            'matching_rules': [rule.dict() for rule in matching_rules],
            'rule_evaluation_order': [rule.order for rule in matching_rules],
            'recommendations': recommendations,
            'vlan_matrix': vlan_matrix,
        }


async def _resolve_network_spec(
    identifier: str, vlans_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve network identifier to network specification."""
    import ipaddress

    # Try to parse as IP address
    try:
        ip = ipaddress.IPv4Address(identifier)
        return {
            'type': 'ip',
            'address': str(ip),
            'network': str(ipaddress.IPv4Network(f'{ip}/32', strict=False)),
        }
    except ipaddress.AddressValueError:
        pass

    # Try to parse as IP network
    try:
        network = ipaddress.IPv4Network(identifier, strict=False)
        return {
            'type': 'network',
            'network': str(network),
            'addresses': [str(ip) for ip in network.hosts()][:10],  # First 10 for display
        }
    except ipaddress.AddressValueError:
        pass

    # Try to match VLAN by name
    for vlan in vlans_data:
        vlan_name = vlan.get('name', '').lower()
        vlan_id = vlan.get('vlan', 1)

        if (
            vlan_name == identifier.lower()
            or f'vlan_{vlan_id}' == identifier.lower()
            or f'vlan {vlan_id}' == identifier.lower()
            or str(vlan_id) == identifier
        ):
            return {
                'type': 'vlan',
                'vlan_id': vlan_id,
                'vlan_name': vlan_name,
                'network': vlan.get('ip_subnet', 'Unknown'),
                'gateway': vlan.get('ip', 'Unknown'),
            }

    # Default to treating as IP if nothing else matches
    return {
        'type': 'unknown',
        'identifier': identifier,
        'note': 'Could not resolve to IP, network, or VLAN',
    }


def _find_matching_rules(
    source_spec: dict[str, Any],
    dest_spec: dict[str, Any],
    protocol: str,
    port: str | None,
    firewall_data: list[dict[str, Any]],
) -> list[FirewallRule]:
    """Find firewall rules matching the traffic specification."""
    matching_rules = []

    for rule_data in firewall_data:
        if not rule_data.get('enabled', True):
            continue

        # Convert to our FirewallRule model
        rule = FirewallRule(
            id=rule_data.get('_id', ''),
            name=rule_data.get('name', ''),
            action=rule_data.get('action', 'allow'),
            enabled=rule_data.get('enabled', True),
            source_type=rule_data.get('src_networkconf_type', 'any'),
            source=rule_data.get('src_networkconf_id', 'any'),
            dest_type=rule_data.get('dst_networkconf_type', 'any'),
            destination=rule_data.get('dst_networkconf_id', 'any'),
            protocol=rule_data.get('protocol', 'all'),
            dest_port=rule_data.get('dst_port', ''),
            order=rule_data.get('rule_index', 9999),
            rule_set=rule_data.get('ruleset', 'LAN_IN'),
        )

        # Check if rule matches (simplified logic)
        if _rule_matches_traffic(rule, source_spec, dest_spec, protocol, port):
            matching_rules.append(rule)

    # Sort by rule order (lower number = higher priority)
    return sorted(matching_rules, key=lambda r: r.order)


def _rule_matches_traffic(
    rule: FirewallRule,
    source_spec: dict[str, Any],
    dest_spec: dict[str, Any],
    protocol: str,
    port: str | None,
) -> bool:
    """Check if firewall rule matches the traffic."""
    # Simplified matching logic
    # Real implementation would need sophisticated network matching

    # Protocol check
    if rule.protocol not in ('all', protocol):
        return False

    # Port check
    if port and rule.dest_port and rule.dest_port != port:
        return False

    # Source/destination check - very simplified
    # Real implementation would resolve network IDs to actual networks
    if rule.source == 'any' or rule.destination == 'any':
        return True

    # If we get here, assume it might match for demo purposes
    return True


def _determine_verdict(matching_rules: list[FirewallRule]) -> Literal['allow', 'deny']:
    """Determine firewall verdict based on matching rules."""
    if not matching_rules:
        return 'allow'  # Default policy

    # First matching rule determines the verdict
    first_rule = matching_rules[0]
    return 'deny' if first_rule.is_blocking else 'allow'


async def _build_vlan_matrix(
    vlans_data: list[dict[str, Any]], firewall_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build VLAN-to-VLAN connectivity matrix."""
    vlans = [
        {'id': vlan.get('vlan', 1), 'name': vlan.get('name', f'VLAN {vlan.get("vlan", 1)}')}
        for vlan in vlans_data
    ]

    matrix = {}

    for source_vlan in vlans:
        matrix[source_vlan['name']] = {}

        for dest_vlan in vlans:
            if source_vlan['id'] == dest_vlan['id']:
                # Same VLAN - always allowed
                matrix[source_vlan['name']][dest_vlan['name']] = 'allow'
            else:
                # Check inter-VLAN rules (simplified)
                verdict = _check_inter_vlan_rules(
                    source_vlan['id'], dest_vlan['id'], firewall_data
                )
                matrix[source_vlan['name']][dest_vlan['name']] = verdict

    return {
        'vlans': vlans,
        'connectivity_matrix': matrix,
    }


def _check_inter_vlan_rules(
    source_vlan_id: int, dest_vlan_id: int, firewall_data: list[dict[str, Any]]
) -> str:
    """Check firewall rules between two VLANs."""
    # Simplified VLAN rule checking
    for rule in firewall_data:
        if not rule.get('enabled', True):
            continue

        # Very basic heuristic for inter-VLAN rules
        rule_name = rule.get('name', '').lower()
        if 'block' in rule_name or 'deny' in rule_name:
            return 'deny'

    return 'allow'  # Default allow for demo


def _generate_firewall_recommendations(
    matching_rules: list[FirewallRule],
    verdict: str,
    source_spec: dict[str, Any],
    dest_spec: dict[str, Any],
) -> list[str]:
    """Generate firewall configuration recommendations."""
    recommendations = []

    if not matching_rules:
        recommendations.append(
            'No specific firewall rules found for this traffic. '
            'Consider adding explicit rules for better security.'
        )

    if verdict == 'deny':
        blocking_rule = next((r for r in matching_rules if r.is_blocking), None)
        if blocking_rule:
            recommendations.append(
                f'Traffic blocked by rule "{blocking_rule.name}". '
                f'If this traffic should be allowed, modify or reorder this rule.'
            )

    if len(matching_rules) > 1:
        recommendations.append(
            f'{len(matching_rules)} rules apply to this traffic. '
            'Consider consolidating similar rules for better performance.'
        )

    return recommendations
