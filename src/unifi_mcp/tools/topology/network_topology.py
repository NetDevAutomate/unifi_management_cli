"""Network topology tool for understanding network structure."""

from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mcp.models import Device
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def get_network_topology(
    include_clients: Annotated[
        bool, Field(description='Include client devices in topology')
    ] = False,
    format: Annotated[
        Literal['json', 'mermaid', 'table'],
        Field(description='Output format'),
    ] = 'json',
) -> dict[str, Any] | str:
    """Get complete network topology showing device relationships and connections.

    When to use this tool:
    - Getting an overview of the entire network structure
    - Understanding device hierarchy and relationships
    - Identifying potential network design issues
    - Before troubleshooting to understand network layout
    - Generating network documentation

    Common workflow:
    1. Use get_network_topology() for overall network overview
    2. Use get_device_tree() to drill down into specific device relationships
    3. Use get_port_map() for detailed port-level information
    4. Use find_device() to locate specific devices within the topology

    What to do next:
    - For device details: Use find_device() on specific devices
    - For port details: Use get_port_map() for switch configurations
    - For connectivity: Use traceroute() between any two devices
    - For issues: Look for devices without uplinks or unusual configurations

    Args:
        include_clients: Whether to include client devices (may be many)
        format: Output format:
                - 'json': Structured data for further processing
                - 'mermaid': Mermaid diagram code for visualization
                - 'table': Human-readable table format

    Returns:
        Network topology data in requested format:
        - JSON: Dictionary with devices, connections, VLANs, statistics
        - Mermaid: String with Mermaid diagram syntax
        - Table: Formatted table string

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to controller
        ToolError: API_ERROR for API-related issues
    """
    async with UniFiClient() as client:
        # Get all network data
        devices_data = await client.get(client.build_path('stat/device'))
        vlans_data = await client.get(client.build_path('rest/networkconf'))

        clients_data = []
        if include_clients:
            clients_data = await client.get(client.build_path('stat/sta'))

        # Build topology structure
        topology = _build_topology_structure(devices_data, vlans_data, clients_data)

        # Format output based on requested format
        if format == 'json':
            return topology
        elif format == 'mermaid':
            return _generate_mermaid_topology(topology)
        elif format == 'table':
            return _generate_table_topology(topology)
        else:
            raise ToolError(
                message=f'Unknown format: {format}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Use format: json, mermaid, or table',
            )


def _build_topology_structure(
    devices_data: list[dict[str, Any]],
    vlans_data: list[dict[str, Any]],
    clients_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build structured topology from API data."""
    # Convert devices to our models
    devices = []
    for device_info in devices_data:
        device = Device(
            mac=device_info.get('mac', ''),
            name=device_info.get('name', '') or device_info.get('hostname', ''),
            model=device_info.get('model', ''),
            ip=device_info.get('ip'),
            type=_map_device_type(device_info.get('type', '')),
            uptime=device_info.get('uptime', 0),
            connected_to=device_info.get('uplink', {}).get('uplink_mac'),
            port_idx=device_info.get('uplink', {}).get('uplink_remote_port'),
            cpu_percent=device_info.get('system-stats', {}).get('cpu'),
            memory_percent=device_info.get('system-stats', {}).get('mem'),
        )
        devices.append(device)

    # Add clients if requested
    if clients_data:
        for client_info in clients_data:
            client = Device(
                mac=client_info.get('mac', ''),
                name=(
                    client_info.get('display_name')
                    or client_info.get('hostname')
                    or client_info.get('name', 'Unknown Client')
                ),
                model=client_info.get('oui', 'Client Device'),
                ip=client_info.get('ip'),
                type='client',
                uptime=0,  # Clients don't report uptime
                connected_to=client_info.get('ap_mac') or client_info.get('sw_mac'),
                port_idx=client_info.get('sw_port'),
            )
            devices.append(client)

    # Build hierarchy
    device_hierarchy = _build_device_hierarchy(devices)

    # Get VLAN summary
    vlan_summary = _build_vlan_summary(vlans_data, devices)

    # Calculate statistics
    stats = _calculate_network_stats(devices, clients_data)

    return {
        'devices': [device.dict() for device in devices],
        'hierarchy': device_hierarchy,
        'vlans': vlan_summary,
        'statistics': stats,
        'connection_matrix': _build_connection_matrix(devices),
    }


def _map_device_type(unifi_type: str) -> Literal['switch', 'ap', 'gateway', 'client']:
    """Map UniFi device type to our standardized types."""
    type_mapping = {
        'usw': 'switch',
        'uap': 'ap',
        'ugw': 'gateway',
        'udm': 'gateway',
        'uxg': 'gateway',
    }
    mapped = type_mapping.get(unifi_type.lower(), 'switch')
    return mapped  # type: ignore


def _build_device_hierarchy(devices: list[Device]) -> dict[str, Any]:
    """Build hierarchical device structure."""
    # Find root devices (gateways with no uplink)
    roots = [d for d in devices if d.type == 'gateway' or not d.connected_to]

    hierarchy = {}
    for root in roots:
        hierarchy[root.mac] = _build_device_subtree(root, devices)

    return hierarchy


def _build_device_subtree(parent: Device, all_devices: list[Device]) -> dict[str, Any]:
    """Build device subtree recursively."""
    children = [d for d in all_devices if d.connected_to == parent.mac]

    subtree = {
        'device': parent.dict(),
        'children': {},
    }

    for child in children:
        subtree['children'][child.mac] = _build_device_subtree(child, all_devices)

    return subtree


def _build_vlan_summary(
    vlans_data: list[dict[str, Any]], devices: list[Device]
) -> list[dict[str, Any]]:
    """Build VLAN summary with device counts."""
    vlan_summary = []

    for vlan_info in vlans_data:
        vlan_id = vlan_info.get('vlan', 1)

        # Count devices in this VLAN (simplified - would need port data for accuracy)
        device_count = len([d for d in devices if d.type != 'client'])  # Placeholder

        vlan_summary.append(
            {
                'id': vlan_id,
                'name': vlan_info.get('name', f'VLAN {vlan_id}'),
                'subnet': vlan_info.get('ip_subnet', 'Unknown'),
                'gateway': vlan_info.get('ip', 'Unknown'),
                'dhcp_enabled': vlan_info.get('dhcpd_enabled', False),
                'device_count': device_count,
            }
        )

    return vlan_summary


def _calculate_network_stats(
    devices: list[Device], clients_data: list[dict[str, Any]]
) -> dict[str, Any]:
    """Calculate network statistics."""
    device_counts = {
        'switches': len([d for d in devices if d.type == 'switch']),
        'access_points': len([d for d in devices if d.type == 'ap']),
        'gateways': len([d for d in devices if d.type == 'gateway']),
        'clients': len(clients_data),
        'total_infrastructure': len([d for d in devices if d.type != 'client']),
    }

    return {
        'device_counts': device_counts,
        'total_devices': len(devices) + len(clients_data),
        'infrastructure_devices': device_counts['total_infrastructure'],
        'uptime_stats': {
            'average_uptime': sum(d.uptime for d in devices if d.uptime > 0)
            // max(1, len([d for d in devices if d.uptime > 0])),
            'max_uptime': max((d.uptime for d in devices), default=0),
        },
    }


def _build_connection_matrix(devices: list[Device]) -> dict[str, list[str]]:
    """Build device connection matrix."""
    matrix = {}

    for device in devices:
        connections = []
        if device.connected_to:
            # Find parent device name
            parent = next((d for d in devices if d.mac == device.connected_to), None)
            if parent:
                connections.append(f'{parent.display_name} (parent)')

        # Find children
        children = [d for d in devices if d.connected_to == device.mac]
        for child in children:
            connections.append(f'{child.display_name} (child)')

        matrix[device.display_name] = connections

    return matrix


def _generate_mermaid_topology(topology: dict[str, Any]) -> str:
    """Generate Mermaid diagram from topology data."""
    lines = ['```mermaid', 'graph TD']

    # Add devices as nodes
    devices = topology['devices']
    for device in devices:
        node_id = device['mac'].replace(':', '')  # Remove colons for valid node ID
        device_label = f'{device["name"]}\\n({device["model"]})'

        # Style by device type
        if device['type'] == 'gateway':
            lines.append(f'    {node_id}["{device_label}"]')
            lines.append(f'    {node_id} --> Internet[Internet]')
        elif device['type'] == 'switch':
            lines.append(f'    {node_id}["{device_label}"]')
        elif device['type'] == 'ap':
            lines.append(f'    {node_id}(("{device_label}"))')
        else:  # client
            lines.append(f'    {node_id}{{"{device_label}"}}')

    # Add connections
    for device in devices:
        if device.get('connected_to'):
            device_id = device['mac'].replace(':', '')
            parent_id = device['connected_to'].replace(':', '')
            port_info = f'|Port {device.get("port_idx")}|' if device.get('port_idx') else ''
            lines.append(f'    {parent_id} -->{port_info} {device_id}')

    lines.append('```')
    return '\n'.join(lines)


def _generate_table_topology(topology: dict[str, Any]) -> str:
    """Generate table format topology."""
    devices = topology['devices']
    stats = topology['statistics']

    lines = ['# Network Topology\n']

    # Summary statistics
    lines.append('## Summary')
    lines.append(f'- **Total Devices**: {stats["total_devices"]}')
    lines.append(f'- **Switches**: {stats["device_counts"]["switches"]}')
    lines.append(f'- **Access Points**: {stats["device_counts"]["access_points"]}')
    lines.append(f'- **Gateways**: {stats["device_counts"]["gateways"]}')
    lines.append(f'- **Clients**: {stats["device_counts"]["clients"]}\n')

    # Device table
    lines.append('## Devices\n')
    lines.append('| Name | Type | Model | IP | Uptime | Connected To |')
    lines.append('|------|------|-------|----|---------|--------------|\n')

    for device in devices:
        uptime_hours = device.get('uptime', 0) // 3600
        connected_to = (
            'Root' if not device.get('connected_to') else f'via {device.get("port_idx", "?")}'
        )
        lines.append(
            f'| {device.get("name", "Unnamed")} | {device["type"]} | '
            f'{device.get("model", "Unknown")} | {device.get("ip", "None")} | '
            f'{uptime_hours}h | {connected_to} |'
        )

    # VLAN summary
    if topology.get('vlans'):
        lines.append('\n## VLANs\n')
        lines.append('| ID | Name | Subnet | Gateway | DHCP |')
        lines.append('|----|------|--------|---------|------|')

        for vlan in topology['vlans']:
            dhcp_status = '✅' if vlan['dhcp_enabled'] else '❌'
            lines.append(
                f'| {vlan["id"]} | {vlan["name"]} | {vlan["subnet"]} | '
                f'{vlan["gateway"]} | {dhcp_status} |'
            )

    return '\n'.join(lines)
