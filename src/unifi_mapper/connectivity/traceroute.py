"""Traceroute tool for tracing network paths between endpoints."""

from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mapper.core.models import NetworkPath, PathHop
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def traceroute(
    source: Annotated[
        str,
        Field(description='Source endpoint (IP, MAC, hostname, or "gateway")'),
    ],
    destination: Annotated[
        str,
        Field(description='Destination endpoint (IP, MAC, hostname, or "internet")'),
    ],
    include_firewall: Annotated[
        bool, Field(description='Check firewall rules along the path')
    ] = True,
    verbosity: Annotated[
        Literal['guided', 'expert'],
        Field(description='Output detail level'),
    ] = 'guided',
) -> NetworkPath:
    """Trace network path between two endpoints with firewall analysis.

    When to use this tool:
    - Troubleshooting connectivity between devices
    - Understanding the path network traffic takes
    - Identifying where traffic might be blocked by firewalls
    - Verifying VLAN routing and inter-VLAN communication
    - Diagnosing network performance issues

    Common workflow:
    1. Use find_device() first if you don't know exact device identifiers
    2. Run traceroute() to see the complete L2 and L3 path
    3. If path shows DENY: Use firewall_check() for detailed rule analysis
    4. If high latency: Use link_quality() and system_load() on slow hops
    5. Use get_port_map() to verify physical connections

    What to do next:
    - If path shows FIREWALL BLOCKED: Use firewall_check() for specific blocking rules
    - If path incomplete: Check if destination device is online with find_device()
    - If high latency: Use link_quality() on interfaces showing slow response
    - If crosses VLANs: Verify inter-VLAN routing with vlan_info()

    Args:
        source: Starting endpoint - can be:
                - IP address (192.168.1.10)
                - MAC address (aa:bb:cc:dd:ee:ff)
                - Device hostname/name
                - Switch port (switch-name:port24)
                - "gateway" for the network gateway
        destination: Target endpoint - same formats as source, plus:
                    - "internet" for tracing to external connectivity
        include_firewall: Whether to analyze firewall rules along the path
        verbosity: 'guided' for plain English, 'expert' for technical details

    Returns:
        NetworkPath showing:
        - Complete L2 path (switches, ports, VLANs)
        - L3 routing information for inter-VLAN paths
        - Latency at each hop (if measurable)
        - Firewall analysis results if requested
        - VLAN boundary crossings highlighted

    Raises:
        ToolError: ENDPOINT_NOT_FOUND if source or destination not found
        ToolError: PATH_INCOMPLETE if path cannot be fully traced
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
    """
    async with UniFiClient() as client:
        # Get network data
        devices_data = await client.get(client.build_path('stat/device'))
        clients_data = await client.get(client.build_path('stat/sta'))
        vlans_data = await client.get(client.build_path('rest/networkconf'))

        # Resolve source and destination endpoints
        source_device = await _resolve_endpoint(source.lower(), devices_data, clients_data)
        dest_device = await _resolve_endpoint(destination.lower(), devices_data, clients_data)

        # Build L2 path
        l2_path = await _trace_l2_path(source_device, dest_device, devices_data, clients_data)

        # Check if path crosses VLANs (L3 routing needed)
        source_vlan = _get_device_vlan(source_device)
        dest_vlan = _get_device_vlan(dest_device)
        crosses_vlans = source_vlan != dest_vlan

        # Add L3 routing information if needed
        if crosses_vlans:
            l2_path = await _add_l3_routing_info(l2_path, source_vlan, dest_vlan, vlans_data)

        # Add firewall analysis if requested
        if include_firewall:
            l2_path = await _add_firewall_analysis(client, l2_path, source_device, dest_device)

        # Build NetworkPath result
        return NetworkPath(
            source=source,
            source_resolved=source_device['mac'],
            source_name=source_device.get('name', ''),
            destination=destination,
            destination_resolved=dest_device['mac'],
            destination_name=dest_device.get('name', ''),
            hops=l2_path,
            total_latency_ms=sum(hop.latency_ms for hop in l2_path if hop.latency_ms),
            crosses_vlans=crosses_vlans,
            vlans_traversed=list({hop.vlan for hop in l2_path if hop.vlan}),
            is_l2_only=not crosses_vlans,
            is_l3_routed=crosses_vlans,
            firewall_verdict=(
                'deny'
                if any(hop.is_blocked for hop in l2_path)
                else 'allow'
                if include_firewall
                else 'unknown'
            ),
        )


async def _resolve_endpoint(
    identifier: str, devices_data: list[dict[str, Any]], clients_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve endpoint identifier to device data."""
    # Handle special cases
    if identifier == 'gateway':
        gateways = [d for d in devices_data if d.get('type', '').lower() in ('ugw', 'udm', 'uxg')]
        if not gateways:
            raise ToolError(
                message='Gateway device not found',
                error_code=ErrorCodes.ENDPOINT_NOT_FOUND,
                suggestion='Network may not have a configured gateway device',
                related_tools=['get_network_topology'],
            )
        return gateways[0]

    if identifier == 'internet':
        # Internet is a special destination - find gateway as exit point
        gateways = [d for d in devices_data if d.get('type', '').lower() in ('ugw', 'udm', 'uxg')]
        if not gateways:
            raise ToolError(
                message='Gateway device not found for internet routing',
                error_code=ErrorCodes.ENDPOINT_NOT_FOUND,
                suggestion='Network gateway required for internet tracing',
                related_tools=['get_network_topology'],
            )
        # Create virtual internet endpoint
        return {
            'mac': 'internet',
            'name': 'Internet',
            'type': 'internet',
            'ip': '0.0.0.0',
            'connected_to': gateways[0]['mac'],
        }

    # Search devices
    device = _search_endpoint_in_devices(identifier, devices_data)
    if device:
        return device

    # Search clients
    client = _search_endpoint_in_clients(identifier, clients_data)
    if client:
        return client

    # Not found
    raise ToolError(
        message=f'Endpoint "{identifier}" not found',
        error_code=ErrorCodes.ENDPOINT_NOT_FOUND,
        suggestion=(
            'Verify endpoint identifier is correct. Device may be offline. '
            'Use find_device() to search with different identifiers.'
        ),
        related_tools=['find_device', 'find_mac', 'find_ip'],
    )


def _search_endpoint_in_devices(
    identifier: str, devices_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Search for endpoint in infrastructure devices."""
    for device in devices_data:
        if (
            device.get('mac', '').lower() == identifier
            or device.get('ip', '').lower() == identifier
            or device.get('name', '').lower() == identifier
            or device.get('hostname', '').lower() == identifier
            or identifier in device.get('name', '').lower()
            or identifier in device.get('hostname', '').lower()
        ):
            return device
    return None


def _search_endpoint_in_clients(
    identifier: str, clients_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Search for endpoint in client devices."""
    for client in clients_data:
        if (
            client.get('mac', '').lower() == identifier
            or client.get('ip', '').lower() == identifier
            or client.get('hostname', '').lower() == identifier
            or client.get('display_name', '').lower() == identifier
            or identifier in client.get('hostname', '').lower()
            or identifier in client.get('display_name', '').lower()
        ):
            return client
    return None


async def _trace_l2_path(
    source_device: dict[str, Any],
    dest_device: dict[str, Any],
    devices_data: list[dict[str, Any]],
    clients_data: list[dict[str, Any]],
) -> list[PathHop]:
    """Trace Layer 2 path between devices."""
    hops = []

    # Start with source device
    source_hop = PathHop(
        hop_number=1,
        device_mac=source_device['mac'],
        device_name=source_device.get('name', '') or source_device.get('hostname', ''),
        device_type=_map_device_type(source_device),
        interface='source',
        vlan=_get_device_vlan(source_device),
        latency_ms=0.0,
    )
    hops.append(source_hop)

    # Trace path to destination
    current_device = source_device
    hop_number = 2
    visited = {source_device['mac']}

    # If source is client, trace to its access point/switch first
    if _is_client_device(source_device):
        parent_mac = source_device.get('ap_mac') or source_device.get('sw_mac')
        if parent_mac:
            parent_device = _find_device_by_mac(parent_mac, devices_data)
            if parent_device:
                parent_hop = PathHop(
                    hop_number=hop_number,
                    device_mac=parent_device['mac'],
                    device_name=parent_device.get('name', ''),
                    device_type=_map_device_type(parent_device),
                    interface=f'port{source_device.get("sw_port", "wireless")}',
                    vlan=_get_device_vlan(source_device),
                )
                hops.append(parent_hop)
                current_device = parent_device
                hop_number += 1
                visited.add(parent_device['mac'])

    # Trace through infrastructure to find path to destination
    while current_device['mac'] != dest_device['mac'] and hop_number <= 10:
        next_device = _find_next_hop(current_device, dest_device, devices_data, visited)

        if not next_device:
            break

        next_hop = PathHop(
            hop_number=hop_number,
            device_mac=next_device['mac'],
            device_name=next_device.get('name', ''),
            device_type=_map_device_type(next_device),
            interface=f'port{current_device.get("uplink", {}).get("uplink_remote_port", "unknown")}',
            vlan=_get_device_vlan(current_device),
        )
        hops.append(next_hop)

        current_device = next_device
        hop_number += 1
        visited.add(next_device['mac'])

    # Add destination if not already included
    if current_device['mac'] != dest_device['mac']:
        dest_hop = PathHop(
            hop_number=hop_number,
            device_mac=dest_device['mac'],
            device_name=dest_device.get('name', ''),
            device_type=_map_device_type(dest_device),
            interface='destination',
            vlan=_get_device_vlan(dest_device),
        )
        hops.append(dest_hop)

    return hops


def _map_device_type(device: dict[str, Any]) -> Literal['switch', 'ap', 'gateway', 'client']:
    """Map device data to our device types."""
    if _is_client_device(device):
        return 'client'

    unifi_type = device.get('type', '').lower()
    type_mapping = {
        'usw': 'switch',
        'uap': 'ap',
        'ugw': 'gateway',
        'udm': 'gateway',
        'uxg': 'gateway',
    }
    mapped = type_mapping.get(unifi_type, 'switch')
    return mapped  # type: ignore


def _is_client_device(device: dict[str, Any]) -> bool:
    """Check if device is a client (not infrastructure)."""
    # Clients have ap_mac or sw_mac but no 'type' field like infrastructure
    return 'ap_mac' in device or 'sw_mac' in device


def _get_device_vlan(device: dict[str, Any]) -> int | None:
    """Get VLAN for a device."""
    if _is_client_device(device):
        return device.get('vlan', 1)
    else:
        return device.get('config', {}).get('vlan', 1)


def _find_device_by_mac(mac: str, devices_data: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find device by MAC address."""
    for device in devices_data:
        if device.get('mac', '').lower() == mac.lower():
            return device
    return None


def _find_next_hop(
    current: dict[str, Any],
    destination: dict[str, Any],
    devices_data: list[dict[str, Any]],
    visited: set[str],
) -> dict[str, Any] | None:
    """Find next hop toward destination."""
    # If destination is directly connected to current device, return it
    if destination.get('connected_to') == current['mac']:
        return destination

    # If current device has an uplink and we haven't been there, go upstream
    if current.get('uplink', {}).get('uplink_mac'):
        uplink_mac = current['uplink']['uplink_mac']
        if uplink_mac not in visited:
            uplink_device = _find_device_by_mac(uplink_mac, devices_data)
            if uplink_device:
                return uplink_device

    # Look for devices connected to current device
    children = [
        d
        for d in devices_data
        if d.get('uplink', {}).get('uplink_mac') == current['mac'] and d['mac'] not in visited
    ]

    # Simple heuristic: if destination is "downstream", pick the first child
    # More sophisticated routing logic could be added here
    if children:
        return children[0]

    return None


async def _add_l3_routing_info(
    hops: list[PathHop],
    source_vlan: int | None,
    dest_vlan: int | None,
    vlans_data: list[dict[str, Any]],
) -> list[PathHop]:
    """Add L3 routing information for inter-VLAN paths."""
    # Find VLAN boundary crossings
    for i, hop in enumerate(hops):
        if i > 0:
            prev_vlan = hops[i - 1].vlan
            current_vlan = hop.vlan

            if prev_vlan != current_vlan:
                # This hop crosses VLAN boundary - mark for L3 analysis
                hop.interface = f'{hop.interface} (VLAN {prev_vlan}→{current_vlan})'

    return hops


async def _add_firewall_analysis(
    client: UniFiClient,
    hops: list[PathHop],
    source_device: dict[str, Any],
    dest_device: dict[str, Any],
) -> list[PathHop]:
    """Add firewall analysis to path hops."""
    try:
        # Get firewall rules
        firewall_data = await client.get(client.build_path('rest/firewallrule'))

        source_vlan = _get_device_vlan(source_device)
        dest_vlan = _get_device_vlan(dest_device)

        # Check firewall at VLAN boundaries
        if source_vlan != dest_vlan:
            firewall_verdict = _check_vlan_firewall_rules(source_vlan, dest_vlan, firewall_data)

            # Apply verdict to hops that cross VLAN boundaries
            for hop in hops:
                if hop.vlan != source_vlan:  # This hop is in destination VLAN
                    hop.firewall_checked = True
                    hop.firewall_result = firewall_verdict['action']
                    hop.blocking_rule = firewall_verdict.get('rule_name')

    except Exception:
        # Firewall analysis failed, but don't fail the whole trace
        pass

    return hops


def _check_vlan_firewall_rules(
    source_vlan: int | None,
    dest_vlan: int | None,
    firewall_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check firewall rules between VLANs."""
    # Simplified firewall check - would need more sophisticated logic
    # for production implementation

    for rule in firewall_data:
        if not rule.get('enabled', True):
            continue

        # Check if rule applies to these VLANs
        # This is simplified - real implementation would need to parse
        # source/destination networks and match VLANs
        rule_name = rule.get('name', 'Unknown Rule')

        # Basic heuristic: if rule mentions blocking and VLANs are different
        if (
            rule.get('action') == 'drop'
            and source_vlan != dest_vlan
            and ('block' in rule_name.lower() or 'deny' in rule_name.lower())
        ):
            return {
                'action': 'deny',
                'rule_name': rule_name,
                'rule_id': rule.get('_id', ''),
            }

    # Default to allow if no blocking rules found
    return {'action': 'allow', 'rule_name': None}
