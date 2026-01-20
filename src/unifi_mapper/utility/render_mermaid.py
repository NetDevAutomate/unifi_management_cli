"""Mermaid diagram rendering tool."""

from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mapper.core.models import NetworkPath
from unifi_mapper.core.utils.errors import ToolError


async def render_mermaid(
    diagram_type: Annotated[
        Literal['path', 'topology', 'firewall_matrix', 'stp'],
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

    STP diagram features:
    - Hierarchical layout with Core/Distribution/Access subgraphs
    - Root bridge highlighted with crown icon
    - Bridge priorities displayed on each switch
    - Blocked links shown as dashed red lines
    - Forwarding links shown as solid green lines

    What to do next:
    - Include generated diagram in reports or documentation
    - Use format_table() for tabular data alongside diagrams
    - Share diagram with team members for collaborative troubleshooting

    Args:
        diagram_type: Type of diagram to generate:
                     - 'path': Network path from traceroute
                     - 'topology': Network topology overview
                     - 'firewall_matrix': Firewall rules matrix
                     - 'stp': STP topology with hierarchy tiers
        data: Data to render (NetworkPath, topology dict, firewall data, or STPTopology)

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
        elif diagram_type == 'stp':
            return _render_stp_diagram(data)
        else:
            raise ToolError(
                message=f'Unknown diagram type: {diagram_type}',
                error_code='INVALID_DATA',
                suggestion='Use: path, topology, firewall_matrix, or stp',
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
    """Render network topology as Mermaid diagram with hierarchical layout.

    Uses subgraphs organized by device type for better readability:
    - Gateways at top (Internet edge)
    - Core switches in middle
    - Access layer (APs) below switches
    - Clients at bottom (if included)

    Layout is vertical (TB) with horizontal device groupings to prevent
    the extremely wide diagrams that occur with flat layouts.
    """
    devices = topology_data.get('devices', [])
    if not devices:
        return '```mermaid\ngraph TB\n    A[No devices found]\n```'

    # Group devices by type
    gateways = [d for d in devices if d.get('type') == 'gateway']
    switches = [d for d in devices if d.get('type') == 'switch']
    aps = [d for d in devices if d.get('type') == 'ap']
    clients = [d for d in devices if d.get('type') == 'client']

    lines = ['```mermaid', 'graph TB']

    # Internet node at top
    if gateways:
        lines.append('    Internet((🌐 Internet))')
        lines.append('')

    # Gateway layer subgraph
    if gateways:
        lines.append('    subgraph GW[" 🔒 Gateways "]')
        lines.append('    direction LR')
        for device in gateways:
            node_id = device['mac'].replace(':', '')
            device_name = device.get('name', 'Unnamed')
            device_model = device.get('model', '')
            lines.append(f'        {node_id}["{device_name}<br/><small>{device_model}</small>"]')
        lines.append('    end')
        lines.append('')
        # Connect Internet to gateways
        for device in gateways:
            node_id = device['mac'].replace(':', '')
            lines.append(f'    Internet --> {node_id}')
        lines.append('')

    # Switch layer - separate core from access switches
    if switches:
        gateway_macs = [g['mac'] for g in gateways]
        core_switches = [s for s in switches if s.get('connected_to') in gateway_macs]
        access_switches = [s for s in switches if s not in core_switches]

        if core_switches:
            lines.append('    subgraph CORE[" 🔀 Core Switches "]')
            lines.append('    direction LR')
            for device in core_switches:
                node_id = device['mac'].replace(':', '')
                device_name = device.get('name', 'Unnamed')
                device_model = device.get('model', '')
                lines.append(f'        {node_id}["{device_name}<br/><small>{device_model}</small>"]')
            lines.append('    end')
            lines.append('')

        if access_switches:
            lines.append('    subgraph ACCESS[" 🔌 Access Switches "]')
            lines.append('    direction LR')
            for device in access_switches:
                node_id = device['mac'].replace(':', '')
                device_name = device.get('name', 'Unnamed')
                device_model = device.get('model', '')
                lines.append(f'        {node_id}["{device_name}<br/><small>{device_model}</small>"]')
            lines.append('    end')
            lines.append('')

    # Access Point layer
    if aps:
        lines.append('    subgraph APS[" 📡 Access Points "]')
        lines.append('    direction LR')
        for device in aps:
            node_id = device['mac'].replace(':', '')
            device_name = device.get('name', 'Unnamed')
            device_model = device.get('model', '')
            lines.append(f'        {node_id}(("{device_name}<br/><small>{device_model}</small>"))')
        lines.append('    end')
        lines.append('')

    # Client layer (if present)
    if clients:
        lines.append('    subgraph CLIENTS[" 💻 Clients "]')
        lines.append('    direction LR')
        for device in clients:
            node_id = device['mac'].replace(':', '')
            device_name = device.get('name', 'Unnamed')
            device_model = device.get('model', '')
            lines.append(f'        {node_id}{{"{device_name}<br/><small>{device_model}</small>"}}')
        lines.append('    end')
        lines.append('')

    # Add all connections between devices
    lines.append('    %% Connections')
    for device in devices:
        if device.get('connected_to'):
            device_id = device['mac'].replace(':', '')
            parent_id = device['connected_to'].replace(':', '')
            port_info = device.get('port_idx')
            if port_info:
                lines.append(f'    {parent_id} -->|P{port_info}| {device_id}')
            else:
                lines.append(f'    {parent_id} --> {device_id}')

    lines.append('')

    # Styling with distinct colors per device type
    lines.extend([
        '    %% Styling',
        '    classDef gateway fill:#4CAF50,stroke:#2E7D32,color:#fff',
        '    classDef switch fill:#2196F3,stroke:#1565C0,color:#fff',
        '    classDef ap fill:#9C27B0,stroke:#6A1B9A,color:#fff',
        '    classDef client fill:#FF9800,stroke:#E65100,color:#fff',
        '    classDef internet fill:#607D8B,stroke:#37474F,color:#fff',
        '',
        '    class Internet internet',
    ])

    # Apply class to each device
    for device in gateways:
        node_id = device['mac'].replace(':', '')
        lines.append(f'    class {node_id} gateway')
    for device in switches:
        node_id = device['mac'].replace(':', '')
        lines.append(f'    class {node_id} switch')
    for device in aps:
        node_id = device['mac'].replace(':', '')
        lines.append(f'    class {node_id} ap')
    for device in clients:
        node_id = device['mac'].replace(':', '')
        lines.append(f'    class {node_id} client')

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


def _render_stp_diagram(stp_data: Any) -> str:
    """Render STP topology as Mermaid diagram with hierarchy tiers.

    Shows switches organized by hierarchy tier (Core, Distribution, Access)
    with root bridge highlighted and blocked ports indicated.

    Args:
        stp_data: STPTopology object or dict with topology data

    Returns:
        Mermaid diagram string
    """
    # Handle both STPTopology objects and dictionaries
    if hasattr(stp_data, 'switches'):
        switches = stp_data.switches
        connections = stp_data.connections
        gateway_name = stp_data.gateway_name
    else:
        switches = stp_data.get('switches', [])
        connections = stp_data.get('connections', [])
        gateway_name = stp_data.get('gateway_name')

    if not switches:
        return '```mermaid\ngraph TB\n    A[No STP data available]\n```'

    lines = ['```mermaid', 'graph TB']

    # Group switches by tier
    tier_switches: dict[int, list[Any]] = {}
    for switch in switches:
        tier = switch.hierarchy_tier if hasattr(switch, 'hierarchy_tier') else switch.get('hierarchy_tier', 2)
        if tier not in tier_switches:
            tier_switches[tier] = []
        tier_switches[tier].append(switch)

    # Render gateway at top if known
    if gateway_name:
        lines.append('    GW((🌐 Gateway))')
        lines.append('')

    # Tier names mapping
    tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}

    # Render each tier as subgraph
    for tier in sorted(tier_switches.keys()):
        tier_name = tier_names.get(tier, f'Tier {tier}')
        lines.append(f'    subgraph {tier_name.upper()}[" {tier_name} "]')
        lines.append('    direction LR')

        for switch in tier_switches[tier]:
            # Get switch attributes
            if hasattr(switch, 'device_id'):
                device_id = switch.device_id
                name = switch.name
                priority = switch.current_priority
                is_root = switch.is_root_bridge
            else:
                device_id = switch.get('device_id', '')
                name = switch.get('name', 'Unknown')
                priority = switch.get('current_priority', 32768)
                is_root = switch.get('is_root_bridge', False)

            node_id = device_id.replace('-', '_')

            # Crown for root bridge
            root_marker = ' 👑' if is_root else ''

            label = f'"{name}<br/>Priority: {priority}{root_marker}"'
            lines.append(f'        {node_id}[{label}]')

        lines.append('    end')
        lines.append('')

    # Add gateway connections
    if gateway_name:
        for switch in tier_switches.get(0, []):
            connected = switch.connected_to_gateway if hasattr(switch, 'connected_to_gateway') else switch.get('connected_to_gateway', False)
            if connected:
                device_id = switch.device_id if hasattr(switch, 'device_id') else switch.get('device_id', '')
                node_id = device_id.replace('-', '_')
                lines.append(f'    GW --> {node_id}')
        lines.append('')

    # Add inter-switch connections
    rendered_connections: set[tuple[str, str]] = set()
    for conn in connections:
        if hasattr(conn, 'from_device_id'):
            from_id = conn.from_device_id.replace('-', '_')
            to_id = conn.to_device_id.replace('-', '_')
            is_blocked = conn.is_blocked
        else:
            from_id = conn.get('from_device_id', '').replace('-', '_')
            to_id = conn.get('to_device_id', '').replace('-', '_')
            is_blocked = conn.get('is_blocked', False)

        # Avoid duplicate connections
        conn_pair = sorted([from_id, to_id])
        conn_key: tuple[str, str] = (conn_pair[0], conn_pair[1])
        if conn_key in rendered_connections:
            continue
        rendered_connections.add(conn_key)

        if is_blocked:
            lines.append(f'    {from_id} -.-x|blocked| {to_id}')
        else:
            lines.append(f'    {from_id} --> {to_id}')

    lines.append('')

    # Styling
    lines.extend([
        '    %% Styling',
        '    classDef core fill:#4CAF50,stroke:#2E7D32,color:#fff',
        '    classDef dist fill:#2196F3,stroke:#1565C0,color:#fff',
        '    classDef access fill:#FF9800,stroke:#E65100,color:#fff',
        '    classDef root fill:#9C27B0,stroke:#6A1B9A,color:#fff',
        '    classDef gateway fill:#607D8B,stroke:#37474F,color:#fff',
        '',
        '    class GW gateway',
    ])

    # Apply classes based on tier and root status
    for tier, switches_in_tier in tier_switches.items():
        class_name = 'core' if tier == 0 else 'dist' if tier == 1 else 'access'
        for switch in switches_in_tier:
            if hasattr(switch, 'device_id'):
                device_id = switch.device_id
                is_root = switch.is_root_bridge
            else:
                device_id = switch.get('device_id', '')
                is_root = switch.get('is_root_bridge', False)

            node_id = device_id.replace('-', '_')
            if is_root:
                lines.append(f'    class {node_id} root')
            else:
                lines.append(f'    class {node_id} {class_name}')

    lines.append('```')
    return '\n'.join(lines)
