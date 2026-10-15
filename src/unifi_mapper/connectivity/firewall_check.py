"""Firewall check tool: which rules match a pair's protocol and port, honestly labelled.

The verdict is ``not assessed`` (issue 093). The check lists the enabled rules whose protocol
and destination port match the traffic, in evaluation order, but it does not resolve each
rule's source and destination networks (or zones, on a zone-based firewall) against the pair,
and it does not read the site's default inter-network policy, so it cannot say whether the
traffic is allowed or denied. Until that evaluation exists (planned for 0.5.0 after a live
capture of classic and zone-based rule shapes), every verdict says so and ``basis`` names
exactly what was checked.
"""

from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.models import FirewallRule
from unifi_mapper.core.utils.client import UniFiClient


NOT_ASSESSED = 'not assessed'
BASIS = (
    'Rules were matched on protocol and destination port only; their source and destination '
    'networks were not evaluated against this pair and the default policy was not read, so '
    'whether the traffic is allowed or denied is not assessed.'
)


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
    3. Use diagnose_vlans() to understand VLAN network segmentation
    4. Review security_audit() for firewall configuration recommendations

    What to do next:
    - If traffic DENIED: Review blocking rule and determine if intentional
    - If traffic ALLOWED: Verify the path with traceroute()
    - If rules conflict: Use security_audit() to check rule consistency
    - For VLAN issues: Use diagnose_vlans() to verify network configuration

    Args:
        source: Source specification - can be:
                - IP address (192.0.2.10)
                - IP network (192.0.2.0/24)
                - VLAN name (Corporate, IoT, Guest)
                - VLAN ID (VLAN_10)
        destination: Destination specification (same formats as source)
        protocol: Network protocol to check (tcp, udp, icmp, all)
        port: Specific port or range (e.g., "80", "443", "1000-2000")

    Returns:
        Dictionary containing:
        - verdict: always ``'not assessed'`` (issue 093); ``basis`` says what was checked
        - matching_rules: All firewall rules that apply to this traffic
        - rule_order: Order in which rules are evaluated
        - recommendations: Suggestions for rule improvements
        - vlan_matrix: When both endpoints are VLANs, ``{'vlans': [{'id', 'name'}, ...],
          'connectivity_matrix': [{'source', 'destination', 'verdict'}, ...]}``, one record
          per ordered pair of networks (a list, so a network name is never a mapping key);
          ``None`` otherwise

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

        verdict = NOT_ASSESSED  # issue 093: no rule engine evaluates the pair yet

        # Build VLAN connectivity matrix if both endpoints are VLANs
        vlan_matrix = None
        if source_spec.get('type') == 'vlan' and dest_spec.get('type') == 'vlan':
            vlan_matrix = await _build_vlan_matrix(vlans_data)

        # Generate recommendations
        recommendations = _generate_firewall_recommendations(
            matching_rules, verdict, source_spec, dest_spec
        )

        return {
            'verdict': verdict,
            'basis': BASIS,
            'source_resolved': source_spec,
            'destination_resolved': dest_spec,
            'matching_rules': [rule.model_dump() for rule in matching_rules],
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
    # Protocol and destination port only (issue 093): the rule's source and destination
    # networks are NOT evaluated against the pair, which is why the verdict is 'not assessed'.

    # Protocol check
    if rule.protocol not in ('all', protocol):
        return False

    # Port check
    if port and rule.dest_port and rule.dest_port != port:
        return False

    # Every rule that matches on protocol and port is listed; which of them applies to this
    # pair's networks is the per-pair evaluation that does not exist yet (0.5.0).
    return True


async def _build_vlan_matrix(
    vlans_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the VLAN-to-VLAN connectivity matrix as one record per (source, destination).

    The matrix is a list of ``{'source', 'destination', 'verdict'}`` records, never a map
    keyed by network name: the output redactors drop or mask a mapping entry whose KEY looks
    like a secret, so a network the operator named ``IoT-PSK`` would lose its verdicts
    (issue 091). Names are values here, which neither redactor touches.
    """
    vlans = [
        {'id': vlan.get('vlan', 1), 'name': vlan.get('name', f'VLAN {vlan.get("vlan", 1)}')}
        for vlan in vlans_data
    ]

    matrix: list[dict[str, str]] = []

    for source_vlan in vlans:
        for dest_vlan in vlans:
            # Issue 093: no cell is judged until the rules are evaluated per pair; even the
            # same-VLAN cell depends on the switch's isolation settings this check does not read.
            matrix.append(
                {
                    'source': source_vlan['name'],
                    'destination': dest_vlan['name'],
                    'verdict': NOT_ASSESSED,
                }
            )

    return {
        'vlans': vlans,
        'connectivity_matrix': matrix,
    }


def _generate_firewall_recommendations(
    matching_rules: list[FirewallRule],
    verdict: str,
    source_spec: dict[str, Any],
    dest_spec: dict[str, Any],
) -> list[str]:
    """Say what the listed rules are and are not evidence of (issue 093)."""
    recommendations = [
        "The verdict is not assessed: this check does not evaluate each rule's source and "
        'destination against the pair or read the default policy. Confirm reachability in the '
        "controller's firewall view or with a live probe from the gateway."
    ]
    if not matching_rules:
        recommendations.append(
            "No enabled rule matches this protocol and port, so the site's default policy "
            'decides; this check does not read it.'
        )
    else:
        blocking = [r.name for r in matching_rules if r.is_blocking]
        if blocking:
            recommendations.append(
                f'{len(blocking)} of the {len(matching_rules)} matching rules block: '
                + ', '.join(f'"{name}"' for name in blocking)
                + '. Whether one applies to this pair depends on its source and destination '
                'networks, which were not evaluated.'
            )
    return recommendations
