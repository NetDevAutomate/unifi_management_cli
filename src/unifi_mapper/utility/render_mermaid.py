"""Mermaid diagram rendering tool."""

from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mcp.models import NetworkPath
from unifi_mcp.utils.errors import ToolError


async def render_mermaid(
    diagram_type: Annotated[
        Literal['path', 'topology', 'firewall_matrix'],
        Field(description='Type of diagram to render'),
    ],
    data: Annotated[Any, Field(description='Data to render as Mermaid diagram')],
) -> str:
    """Render data as Mermaid diagram for visualization.

    When to use this tool:
    - Converting network topology data into visual diagrams
    - Creating path visualizations from traceroute results
    - Generating firewall rule matrices for easy understanding
    - Documenting network layouts

    Common workflow:
    1. Get data from topology, connectivity, or config tools
    2. Use render_mermaid() to create visual representation
    3. Include diagram in documentation or troubleshooting reports
    4. Use export_markdown() to save diagrams with analysis

    What to do next:
    - Include generated diagram in reports or documentation
    - Use format_table() for tabular data alongside diagrams
    - Share diagram with team members for collaborative troubleshooting

    Args:
        diagram_type: Type of diagram to generate:
                     - 'path': Network path from traceroute
                     - 'topology': Network topology overview
                     - 'firewall_matrix': Firewall rules matrix
        data: Data to render (NetworkPath, topology dict, or firewall data)

    Returns:
        Mermaid diagram as markdown code block string

    Raises:
        ToolError: INVALID_DATA if data cannot be rendered as requested diagram type
    """
    try:
        if diagram_type == 'path':
            return _render_path_diagram(data)
        elif diagram_type == 'topology':
            return _render_topology_diagram(data)
        elif diagram_type == 'firewall_matrix':
            return _render_firewall_matrix(data)
        else:
            raise ToolError(
                message=f'Unknown diagram type: {diagram_type}',
                error_code='INVALID_DATA',
                suggestion='Use: path, topology, or firewall_matrix',
            )
    except Exception as e:
        raise ToolError(
            message=f'Failed to render diagram: {e}',
            error_code='INVALID_DATA',
            suggestion='Check that data format matches the diagram type',
        )


def _render_path_diagram(path_data: Any) -> str:
    """Render network path as Mermaid diagram."""
    if not isinstance(path_data, (NetworkPath, dict)):
        raise ValueError('Path data must be NetworkPath object or dict')

    # Handle both NetworkPath objects and dictionaries
    if hasattr(path_data, 'hops'):
        hops = path_data.hops
        source = path_data.source
        destination = path_data.destination
        firewall_verdict = path_data.firewall_verdict
    else:
        hops = path_data.get('hops', [])
        source = path_data.get('source', 'Source')
        destination = path_data.get('destination', 'Destination')
        firewall_verdict = path_data.get('firewall_verdict', 'unknown')

    lines = ['```mermaid', 'graph LR']

    # Add title
    verdict_icon = (
        '✅' if firewall_verdict == 'allow' else '❌' if firewall_verdict == 'deny' else '❓'
    )
    lines.append(f'    subgraph "Path: {source} → {destination} {verdict_icon}"')

    prev_node = None
    for hop in hops:
        node_id = f'H{hop.hop_number}' if hasattr(hop, 'hop_number') else f'H{len(lines)}'

        # Get hop attributes (handle both object and dict)
        device_name = (
            hop.device_name if hasattr(hop, 'device_name') else hop.get('device_name', 'Unknown')
        )
        device_type = (
            hop.device_type if hasattr(hop, 'device_type') else hop.get('device_type', 'unknown')
        )
        interface = hop.interface if hasattr(hop, 'interface') else hop.get('interface', 'unknown')
        vlan = hop.vlan if hasattr(hop, 'vlan') else hop.get('vlan')
        latency_ms = hop.latency_ms if hasattr(hop, 'latency_ms') else hop.get('latency_ms')
        is_blocked = (
            hop.is_blocked if hasattr(hop, 'is_blocked') else hop.get('firewall_result') == 'deny'
        )

        # Node label with device info
        vlan_info = f'<br/>VLAN {vlan}' if vlan else ''
        latency_info = f'<br/>{latency_ms}ms' if latency_ms else ''
        node_label = f'"{device_name}<br/>{interface}{vlan_info}{latency_info}"'

        # Node shape based on device type
        if device_type == 'gateway':
            lines.append(f'        {node_id}[{node_label}]')
        elif device_type == 'switch':
            lines.append(f'        {node_id}[{node_label}]')
        elif device_type == 'ap':
            lines.append(f'        {node_id}(({node_label}))')
        else:  # client
            lines.append(f'        {node_id}{{{node_label}}}')

        # Edge to previous node
        if prev_node:
            edge_style = '-.->|BLOCKED|' if is_blocked else '-->|OK|'
            lines.append(f'        {prev_node} {edge_style} {node_id}')

        prev_node = node_id

    lines.append('    end')

    # Add styling
    lines.extend(
        [
            '    classDef gateway fill:#e1f5fe',
            '    classDef switch fill:#f3e5f5',
            '    classDef ap fill:#e8f5e8',
            '    classDef client fill:#fff3e0',
            '    classDef blocked stroke:#f44336,stroke-width:3px',
        ]
    )

    lines.append('```')
    return '\n'.join(lines)


def _render_topology_diagram(topology_data: dict[str, Any]) -> str:
    """Render network topology as Mermaid diagram."""
    lines = ['```mermaid', 'graph TD']

    devices = topology_data.get('devices', [])
    if not devices:
        return '```mermaid\ngraph TD\n    A[No devices found]\n```'

    # Add title
    total_devices = len(devices)
    lines.append(f'    subgraph "Network Topology ({total_devices} devices)"')

    # Group devices by type (used for Internet connection logic and future subgraph grouping)
    gateways = [d for d in devices if d.get('type') == 'gateway']
    _switches = [d for d in devices if d.get('type') == 'switch']  # noqa: F841
    _aps = [d for d in devices if d.get('type') == 'ap']  # noqa: F841
    _clients = [d for d in devices if d.get('type') == 'client']  # noqa: F841

    # Add Internet connection
    if gateways:
        lines.append('        Internet[Internet]')

    # Add devices as nodes
    for device in devices:
        node_id = device['mac'].replace(':', '')
        device_name = device.get('name', 'Unnamed')
        device_model = device.get('model', '')
        device_label = f'"{device_name}\\n({device_model})"'

        if device['type'] == 'gateway':
            lines.append(f'        {node_id}[{device_label}]')
            lines.append(f'        Internet --> {node_id}')
        elif device['type'] == 'switch':
            lines.append(f'        {node_id}[{device_label}]')
        elif device['type'] == 'ap':
            lines.append(f'        {node_id}(({device_label}))')
        else:  # client
            lines.append(f'        {node_id}{{{device_label}}}')

    # Add connections
    for device in devices:
        if device.get('connected_to'):
            device_id = device['mac'].replace(':', '')
            parent_id = device['connected_to'].replace(':', '')
            port_info = f'Port {device.get("port_idx", "?")}' if device.get('port_idx') else ''
            lines.append(f'        {parent_id} -->|{port_info}| {device_id}')

    lines.append('    end')

    # Add styling
    lines.extend(
        [
            '    classDef gateway fill:#e1f5fe',
            '    classDef switch fill:#f3e5f5',
            '    classDef ap fill:#e8f5e8',
            '    classDef client fill:#fff3e0',
        ]
    )

    lines.append('```')
    return '\n'.join(lines)


def _render_firewall_matrix(firewall_data: dict[str, Any]) -> str:
    """Render firewall rules as Mermaid diagram."""
    lines = ['```mermaid', 'graph LR']

    vlan_matrix = firewall_data.get('vlan_matrix', {})
    if not vlan_matrix:
        return '```mermaid\ngraph LR\n    A[No firewall matrix data]\n```'

    vlans = vlan_matrix.get('vlans', [])
    connectivity = vlan_matrix.get('connectivity_matrix', {})

    lines.append('    subgraph "Inter-VLAN Firewall Rules"')

    # Add VLAN nodes
    for vlan in vlans:
        node_id = f'V{vlan["id"]}'
        vlan_label = f'"{vlan["name"]}\\n(VLAN {vlan["id"]})"'
        lines.append(f'        {node_id}[{vlan_label}]')

    # Add connections based on firewall rules
    for source_vlan, destinations in connectivity.items():
        source_id = f'V{_get_vlan_id_from_name(source_vlan, vlans)}'

        for dest_vlan, verdict in destinations.items():
            if source_vlan == dest_vlan:
                continue  # Skip self-connections

            dest_id = f'V{_get_vlan_id_from_name(dest_vlan, vlans)}'

            if verdict == 'allow':
                lines.append(f'        {source_id} -->|✅ ALLOW| {dest_id}')
            else:
                lines.append(f'        {source_id} -.->|❌ DENY| {dest_id}')

    lines.append('    end')

    # Add styling
    lines.extend(
        [
            '    classDef vlan fill:#e3f2fd',
            '    linkStyle default stroke:#4caf50,stroke-width:2px',
        ]
    )

    lines.append('```')
    return '\n'.join(lines)


def _get_vlan_id_from_name(vlan_name: str, vlans: list[dict[str, str]]) -> int:
    """Get VLAN ID from name."""
    for vlan in vlans:
        if vlan.get('name') == vlan_name:
            return vlan.get('id', 1)
    return 1  # Default VLAN
