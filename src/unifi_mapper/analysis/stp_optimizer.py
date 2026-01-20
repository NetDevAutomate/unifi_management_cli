"""STP (Spanning Tree Protocol) optimization tool for UniFi networks.

This module discovers the current STP topology, calculates optimal bridge
priorities based on network hierarchy, and generates reports with visual
diagrams showing current vs optimal configuration.
"""

from datetime import datetime
from typing import Any
from unifi_mapper.core.models.stp import (
    STP_PRIORITY_ACCESS_BASE,
    STP_PRIORITY_CORE,
    STP_PRIORITY_DEFAULT,
    STP_PRIORITY_DISTRIBUTION,
    STP_PRIORITY_INCREMENT,
    STPChange,
    STPConnection,
    STPOptimizationReport,
    STPPortConfig,
    STPPortState,
    STPRole,
    STPTopology,
    SwitchSTPConfig,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def discover_stp_topology(
    device_id: str | None = None,
) -> STPTopology:
    """Discover current STP topology from all switches via LLDP and port_table.

    When to use this tool:
    - When troubleshooting STP convergence issues
    - When planning STP priority changes
    - To understand current spanning tree state
    - After physical network changes

    How STP discovery works:
    - Queries all switches for their STP configuration
    - Extracts bridge priority, port states, and roles
    - Builds topology graph from LLDP neighbor data
    - Identifies current root bridge and blocked ports
    - Determines network hierarchy tiers

    Args:
        device_id: Optional device ID to analyze specific switch.
                  If None, discovers entire network topology.

    Returns:
        STPTopology with complete spanning tree state

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            # Find gateway first for hierarchy determination
            gateway_id = None
            gateway_name = None
            gateway_mac = None
            for device in devices:
                device_type = device.get('type', '')
                if device_type in ('ugw', 'usg', 'udm', 'udmpro', 'gateway'):
                    gateway_id = device.get('_id')
                    gateway_name = device.get('name', 'Gateway')
                    gateway_mac = device.get('mac', '').lower()
                    break

            # Build MAC to device lookup
            mac_to_device: dict[str, dict[str, Any]] = {}
            for device in devices:
                mac = device.get('mac', '').lower()
                if mac:
                    mac_to_device[mac] = device
                    # Also store normalized (no colons) version
                    mac_to_device[mac.replace(':', '')] = device

            switches: list[SwitchSTPConfig] = []
            connections: list[STPConnection] = []
            devices_analyzed = 0
            root_bridge_id: str | None = None
            root_bridge_name: str | None = None
            root_bridge_priority = 65535  # Higher than any valid STP priority
            blocked_ports_count = 0

            for device in devices:
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch', 'udm', 'udmpro'):
                    continue

                # Filter to specific device if requested
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                devices_analyzed += 1
                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))
                dev_mac = device.get('mac', '').lower()
                dev_model = device.get('model', '')

                # Extract STP configuration (API may return string or int)
                raw_priority = device.get('stp_priority', STP_PRIORITY_DEFAULT)
                if raw_priority is None:
                    stp_priority = STP_PRIORITY_DEFAULT
                else:
                    try:
                        stp_priority = int(raw_priority)
                    except (ValueError, TypeError):
                        stp_priority = STP_PRIORITY_DEFAULT

                # Check if this is the root bridge (lowest priority wins)
                if stp_priority < root_bridge_priority:
                    root_bridge_priority = stp_priority
                    root_bridge_id = dev_id
                    root_bridge_name = dev_name

                # Extract port STP states
                port_states, device_connections, device_blocked = _extract_port_stp_states(
                    device, dev_id, dev_name, mac_to_device, gateway_mac
                )
                blocked_ports_count += device_blocked

                connections.extend(device_connections)

                # Determine if connected to gateway
                connected_to_gateway = _is_connected_to_gateway(device, gateway_mac, mac_to_device)

                switch_config = SwitchSTPConfig(
                    device_id=dev_id,
                    name=dev_name,
                    mac=dev_mac,
                    model=dev_model,
                    current_priority=stp_priority,
                    is_root_bridge=(dev_id == root_bridge_id),
                    port_states=port_states,
                    connected_to_gateway=connected_to_gateway,
                )

                switches.append(switch_config)

                if device_id and devices_analyzed > 0:
                    break

            if device_id and devices_analyzed == 0:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_network_topology'],
                )

            # Calculate hierarchy tiers based on gateway connectivity
            _calculate_hierarchy_tiers(switches)

            # Update root bridge status
            for switch in switches:
                switch.is_root_bridge = switch.device_id == root_bridge_id

            return STPTopology(
                timestamp=datetime.now().isoformat(),
                root_bridge_id=root_bridge_id,
                root_bridge_name=root_bridge_name,
                root_bridge_priority=root_bridge_priority,
                gateway_id=gateway_id,
                gateway_name=gateway_name,
                switches=switches,
                connections=connections,
                loops_detected=blocked_ports_count > 0,
                blocked_ports_count=blocked_ports_count,
            )

        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error discovering STP topology: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _extract_port_stp_states(
    device: dict[str, Any],
    device_id: str,
    device_name: str,
    mac_to_device: dict[str, dict[str, Any]],
    gateway_mac: str | None,
) -> tuple[list[STPPortConfig], list[STPConnection], int]:
    """Extract STP states from port table and LLDP data."""
    port_states: list[STPPortConfig] = []
    connections: list[STPConnection] = []
    blocked_count = 0

    port_table = device.get('port_table', [])
    lldp_table = device.get('lldp_table', [])

    # Build LLDP lookup by port index
    lldp_by_port: dict[int, dict[str, Any]] = {}
    for lldp_entry in lldp_table:
        port_idx = lldp_entry.get('local_port_idx')
        if port_idx is not None:
            lldp_by_port[port_idx] = lldp_entry

    for port_data in port_table:
        port_idx = port_data.get('port_idx', 0)
        port_name = port_data.get('name', '') or f'Port {port_idx}'

        # Get STP state from port data
        stp_state_str = port_data.get('stp_state', 'forwarding')
        stp_state = _parse_stp_state(stp_state_str)

        # Get STP role
        stp_role_str = port_data.get('stp_role', 'designated')
        stp_role = _parse_stp_role(stp_role_str)

        # Get path cost
        path_cost = port_data.get('stp_pathcost', 0)
        if path_cost is None:
            path_cost = 0

        # Check for connected device via LLDP
        connected_device = None
        connected_device_id = None
        is_uplink = False

        lldp_info = lldp_by_port.get(port_idx, {})
        chassis_id = lldp_info.get('chassis_id', '')
        if chassis_id:
            normalized_mac = chassis_id.lower().replace(':', '').replace('-', '')
            if normalized_mac in mac_to_device:
                connected_dev = mac_to_device[normalized_mac]
                connected_device = connected_dev.get('name', chassis_id)
                connected_device_id = connected_dev.get('_id')
                # Check if this is an uplink to gateway
                if gateway_mac and normalized_mac == gateway_mac.replace(':', ''):
                    is_uplink = True

        if stp_state in (STPPortState.BLOCKING, STPPortState.DISCARDING):
            blocked_count += 1

        port_config = STPPortConfig(
            port_idx=port_idx,
            port_name=port_name,
            stp_state=stp_state,
            stp_role=stp_role,
            path_cost=path_cost,
            connected_device=connected_device,
            connected_device_id=connected_device_id,
            is_uplink=is_uplink,
        )
        port_states.append(port_config)

        # Create connection if we found a connected device
        if connected_device_id:
            connection = STPConnection(
                from_device_id=device_id,
                from_device_name=device_name,
                from_port_idx=port_idx,
                to_device_id=connected_device_id,
                to_device_name=connected_device or 'Unknown',
                stp_state=stp_state,
                path_cost=path_cost,
                is_blocked=stp_state in (STPPortState.BLOCKING, STPPortState.DISCARDING),
            )
            connections.append(connection)

    return port_states, connections, blocked_count


def _parse_stp_state(state_str: str) -> STPPortState:
    """Parse STP state string to enum."""
    state_map = {
        'forwarding': STPPortState.FORWARDING,
        'blocking': STPPortState.BLOCKING,
        'discarding': STPPortState.DISCARDING,
        'learning': STPPortState.LEARNING,
        'listening': STPPortState.LISTENING,
        'disabled': STPPortState.DISABLED,
    }
    return state_map.get(state_str.lower(), STPPortState.FORWARDING)


def _parse_stp_role(role_str: str) -> STPRole:
    """Parse STP role string to enum."""
    role_map = {
        'root': STPRole.ROOT,
        'designated': STPRole.DESIGNATED,
        'alternate': STPRole.ALTERNATE,
        'backup': STPRole.BACKUP,
        'disabled': STPRole.DISABLED,
    }
    return role_map.get(role_str.lower(), STPRole.DESIGNATED)


def _is_connected_to_gateway(
    device: dict[str, Any],
    gateway_mac: str | None,
    mac_to_device: dict[str, dict[str, Any]],
) -> bool:
    """Check if device is directly connected to gateway."""
    if not gateway_mac:
        return False

    lldp_table = device.get('lldp_table', [])
    gateway_mac_normalized = gateway_mac.replace(':', '').lower()

    for lldp_entry in lldp_table:
        chassis_id = lldp_entry.get('chassis_id', '')
        if chassis_id:
            normalized = chassis_id.lower().replace(':', '').replace('-', '')
            if normalized == gateway_mac_normalized:
                return True

    return False


def _calculate_hierarchy_tiers(
    switches: list[SwitchSTPConfig],
) -> None:
    """Calculate network hierarchy tiers for each switch.

    Tier 0 (Core): Directly connected to gateway
    Tier 1 (Distribution): One hop from core
    Tier 2+ (Access): Two or more hops from core
    """
    # Build adjacency from port connections
    adjacency: dict[str, set[str]] = {s.device_id: set() for s in switches}

    for switch in switches:
        for port in switch.port_states:
            if port.connected_device_id:
                adjacency[switch.device_id].add(port.connected_device_id)

    # Find core switches (connected to gateway)
    core_switch_ids: set[str] = set()
    for switch in switches:
        if switch.connected_to_gateway:
            switch.hierarchy_tier = 0
            core_switch_ids.add(switch.device_id)

    # BFS to find distances from core
    if core_switch_ids:
        visited = set(core_switch_ids)
        current_tier = core_switch_ids
        tier_level = 1

        while current_tier:
            next_tier: set[str] = set()
            for switch_id in current_tier:
                for neighbor_id in adjacency.get(switch_id, set()):
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_tier.add(neighbor_id)
                        # Update tier for neighbor
                        for s in switches:
                            if s.device_id == neighbor_id:
                                s.hierarchy_tier = tier_level
            current_tier = next_tier
            tier_level += 1


async def calculate_optimal_priorities(
    topology: STPTopology,
) -> list[STPChange]:
    """Calculate optimal bridge priorities based on network hierarchy.

    Algorithm:
    1. Find gateway/router as reference point
    2. Tier 0 (Core): Switches directly connected to gateway -> Priority 4096
    3. Tier 1 (Distribution): One hop from core -> Priority 8192
    4. Tier 2 (Access): Two+ hops from core -> Priority 16384+

    The goal is to ensure the root bridge is the core switch closest to
    the gateway, providing deterministic STP topology.

    Args:
        topology: Current STP topology from discover_stp_topology()

    Returns:
        List of STPChange objects describing recommended changes
    """
    changes: list[STPChange] = []

    # Sort switches by tier to assign priorities
    switches_by_tier: dict[int, list[SwitchSTPConfig]] = {}
    for switch in topology.switches:
        tier = switch.hierarchy_tier
        if tier not in switches_by_tier:
            switches_by_tier[tier] = []
        switches_by_tier[tier].append(switch)

    # Assign optimal priorities based on tier
    for tier, tier_switches in switches_by_tier.items():
        if tier == 0:
            base_priority = STP_PRIORITY_CORE
            tier_name = 'Core'
        elif tier == 1:
            base_priority = STP_PRIORITY_DISTRIBUTION
            tier_name = 'Distribution'
        else:
            base_priority = STP_PRIORITY_ACCESS_BASE + ((tier - 2) * STP_PRIORITY_INCREMENT)
            tier_name = f'Access (Tier {tier})'

        for switch in tier_switches:
            # All switches in same tier get same priority
            # STP uses MAC address as tiebreaker (lower MAC wins)
            # UniFi API only accepts multiples of 4096
            optimal_priority = base_priority
            switch.optimal_priority = optimal_priority

            if switch.current_priority != optimal_priority:
                reason = f'{tier_name} switch should have priority {optimal_priority}'
                if switch.connected_to_gateway and tier == 0:
                    reason = (
                        f'Core switch (gateway-connected) should have priority {optimal_priority}'
                    )

                change = STPChange(
                    device_id=switch.device_id,
                    device_name=switch.name,
                    current_priority=switch.current_priority,
                    new_priority=optimal_priority,
                    hierarchy_tier=tier,
                    reason=reason,
                )
                changes.append(change)

    return changes


async def generate_stp_report(
    topology: STPTopology,
    changes: list[STPChange],
) -> STPOptimizationReport:
    """Generate comprehensive STP optimization report.

    Creates a report with:
    - Current vs optimal topology comparison
    - Mermaid diagrams for visualization
    - List of recommended changes
    - Issues and recommendations

    Args:
        topology: Current STP topology
        changes: Calculated optimal priority changes

    Returns:
        Complete STPOptimizationReport
    """
    issues: list[str] = []
    recommendations: list[str] = []

    # Check for issues
    if topology.blocked_ports_count > 0:
        issues.append(
            f'Found {topology.blocked_ports_count} blocked port(s) - indicates redundant paths'
        )

    if topology.root_bridge_priority == STP_PRIORITY_DEFAULT:
        issues.append('Root bridge using default priority (32768) - not explicitly configured')

    # Find misplaced root bridge
    root_switch = None
    for switch in topology.switches:
        if switch.is_root_bridge:
            root_switch = switch
            break

    if root_switch and not root_switch.connected_to_gateway:
        issues.append(f'Root bridge "{root_switch.name}" is not directly connected to gateway')
        recommendations.append(
            'Consider setting root bridge to a core switch connected to the gateway'
        )

    # General recommendations
    if changes:
        recommendations.append(f'Apply {len(changes)} priority change(s) to optimize STP topology')

    # Find optimal root candidate
    optimal_root = None
    optimal_root_reason = ''
    for switch in topology.switches:
        if switch.hierarchy_tier == 0 and switch.connected_to_gateway:
            optimal_root = switch.name
            optimal_root_reason = 'Core switch directly connected to gateway'
            break

    if not optimal_root and topology.switches:
        # Fall back to switch with lowest tier
        sorted_switches = sorted(topology.switches, key=lambda s: s.hierarchy_tier)
        if sorted_switches:
            optimal_root = sorted_switches[0].name
            optimal_root_reason = f'Tier {sorted_switches[0].hierarchy_tier} switch'

    # Generate diagrams
    current_diagram = _render_stp_diagram(topology, changes, show_optimal=False)
    optimal_diagram = _render_stp_diagram(topology, changes, show_optimal=True)

    return STPOptimizationReport(
        timestamp=datetime.now().isoformat(),
        switches_analyzed=len(topology.switches),
        current_root=topology.root_bridge_name,
        current_root_priority=topology.root_bridge_priority,
        optimal_root=optimal_root,
        optimal_root_reason=optimal_root_reason,
        changes_required=len(changes),
        changes=changes,
        topology=topology,
        issues=issues,
        recommendations=recommendations,
        current_diagram=current_diagram,
        optimal_diagram=optimal_diagram,
    )


def _render_stp_diagram(
    topology: STPTopology,
    changes: list[STPChange],
    show_optimal: bool = False,
) -> str:
    """Render STP topology as Mermaid diagram.

    Args:
        topology: STP topology data
        changes: Priority changes
        show_optimal: If True, show optimal priorities; else current

    Returns:
        Mermaid diagram string
    """
    lines = ['```mermaid', 'graph TB']

    # Group switches by tier
    tier_switches: dict[int, list[SwitchSTPConfig]] = {}
    for switch in topology.switches:
        tier = switch.hierarchy_tier
        if tier not in tier_switches:
            tier_switches[tier] = []
        tier_switches[tier].append(switch)

    # Render gateway at top if known
    if topology.gateway_name:
        lines.append('    GW((🌐 Gateway))')
        lines.append('')

    # Render each tier as subgraph
    tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}

    for tier in sorted(tier_switches.keys()):
        tier_name = tier_names.get(tier, f'Tier {tier}')
        lines.append(f'    subgraph {tier_name.upper()}[" {tier_name} "]')
        lines.append('    direction LR')

        for switch in tier_switches[tier]:
            node_id = switch.device_id.replace('-', '_')

            if show_optimal:
                priority = switch.optimal_priority or switch.current_priority
            else:
                priority = switch.current_priority

            # Crown for root bridge
            root_marker = ' 👑' if switch.is_root_bridge and not show_optimal else ''
            if show_optimal and switch.hierarchy_tier == 0:
                root_marker = ' 👑'

            label = f'"{switch.name}<br/>{priority}{root_marker}"'
            lines.append(f'        {node_id}[{label}]')

        lines.append('    end')
        lines.append('')

    # Add gateway connections
    if topology.gateway_name:
        for switch in tier_switches.get(0, []):
            if switch.connected_to_gateway:
                node_id = switch.device_id.replace('-', '_')
                lines.append(f'    GW --> {node_id}')

    # Add inter-switch connections
    rendered_connections: set[tuple[str, str]] = set()
    for conn in topology.connections:
        from_id = conn.from_device_id.replace('-', '_')
        to_id = conn.to_device_id.replace('-', '_')

        # Avoid duplicate connections
        conn_pair = sorted([from_id, to_id])
        conn_key: tuple[str, str] = (conn_pair[0], conn_pair[1])
        if conn_key in rendered_connections:
            continue
        rendered_connections.add(conn_key)

        if conn.is_blocked:
            lines.append(f'    {from_id} -.-x|blocked| {to_id}')
        else:
            lines.append(f'    {from_id} --> {to_id}')

    lines.append('')

    # Styling
    lines.extend(
        [
            '    %% Styling',
            '    classDef core fill:#4CAF50,stroke:#2E7D32,color:#fff',
            '    classDef dist fill:#2196F3,stroke:#1565C0,color:#fff',
            '    classDef access fill:#FF9800,stroke:#E65100,color:#fff',
            '    classDef root fill:#9C27B0,stroke:#6A1B9A,color:#fff',
            '    classDef gateway fill:#607D8B,stroke:#37474F,color:#fff',
            '',
            '    class GW gateway',
        ]
    )

    # Apply classes based on tier
    for tier, switches in tier_switches.items():
        class_name = 'core' if tier == 0 else 'dist' if tier == 1 else 'access'
        for switch in switches:
            node_id = switch.device_id.replace('-', '_')
            if switch.is_root_bridge and not show_optimal:
                lines.append(f'    class {node_id} root')
            else:
                lines.append(f'    class {node_id} {class_name}')

    lines.append('```')
    return '\n'.join(lines)


async def apply_stp_changes(
    changes: list[STPChange],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply STP priority changes to switches.

    CAUTION: Changing STP priorities can cause network disruption during
    convergence. Always use dry_run=True first to review changes.

    Args:
        changes: List of STPChange objects to apply
        dry_run: If True, only simulate changes without applying

    Returns:
        Dictionary with results:
        - applied: List of successfully applied changes
        - failed: List of failed changes with error messages
        - dry_run: Whether this was a dry run
    """
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    if dry_run:
        for change in changes:
            applied.append(
                {
                    'device_id': change.device_id,
                    'device_name': change.device_name,
                    'current_priority': change.current_priority,
                    'new_priority': change.new_priority,
                    'status': 'would_apply',
                }
            )
        return {
            'applied': applied,
            'failed': failed,
            'dry_run': True,
            'message': f'Dry run: {len(changes)} change(s) would be applied',
        }

    async with UniFiClient() as client:
        for change in changes:
            try:
                # Get current device data for proper update
                device = await client.get_device(change.device_id)
                if not device:
                    failed.append(
                        {
                            'device_id': change.device_id,
                            'device_name': change.device_name,
                            'error': 'Device not found',
                        }
                    )
                    continue

                # Build update payload with STP priority
                update_payload = {
                    '_id': device['_id'],
                    'mac': device['mac'],
                    'stp_priority': change.new_priority,
                }

                # Include config version fields for proper persistence
                for field in ['config_version', 'cfgversion', 'config_revision']:
                    if field in device:
                        update_payload[field] = device[field]

                # Send update via PUT
                path = client.build_path(f'rest/device/{change.device_id}')
                await client.put(path, update_payload)

                # Force provision to apply changes
                await client.force_provision(device['mac'])

                applied.append(
                    {
                        'device_id': change.device_id,
                        'device_name': change.device_name,
                        'current_priority': change.current_priority,
                        'new_priority': change.new_priority,
                        'status': 'applied',
                    }
                )

            except Exception as e:
                failed.append(
                    {
                        'device_id': change.device_id,
                        'device_name': change.device_name,
                        'error': str(e),
                    }
                )

    return {
        'applied': applied,
        'failed': failed,
        'dry_run': False,
        'message': f'Applied {len(applied)} change(s), {len(failed)} failed',
    }


def format_stp_report_markdown(report: STPOptimizationReport) -> str:
    """Format STP optimization report as markdown.

    Args:
        report: Complete STP optimization report

    Returns:
        Formatted markdown string
    """
    lines = [
        '# STP Optimization Report',
        f'*Generated: {report.timestamp}*',
        '',
        '## Summary',
        f'- **Switches Analyzed**: {report.switches_analyzed}',
        f'- **Current Root**: {report.current_root or "Unknown"} '
        f'(Priority: {report.current_root_priority})',
        f'- **Optimal Root**: {report.optimal_root or "Unknown"}',
        f'- **Changes Required**: {report.changes_required}',
        '',
    ]

    # Issues section
    if report.issues:
        lines.append('## Issues Detected')
        for issue in report.issues:
            lines.append(f'- ⚠️ {issue}')
        lines.append('')

    # Current topology table
    lines.append('## Current Topology')
    lines.append('')
    lines.append('| Switch | Priority | Tier | Root | Gateway Connected |')
    lines.append('|--------|----------|------|------|-------------------|')
    for switch in report.topology.switches:
        tier_name = ['Core', 'Distribution', 'Access'][min(switch.hierarchy_tier, 2)]
        root_marker = '✅' if switch.is_root_bridge else ''
        gw_marker = '✅' if switch.connected_to_gateway else ''
        lines.append(
            f'| {switch.name} | {switch.current_priority} | '
            f'{tier_name} | {root_marker} | {gw_marker} |'
        )
    lines.append('')

    # Current diagram
    lines.append('### Current Topology Diagram')
    lines.append('')
    lines.append(report.current_diagram)
    lines.append('')

    # Optimal configuration section
    if report.changes:
        lines.append('## Recommended Changes')
        lines.append('')
        lines.append('| Switch | Current | Optimal | Tier | Reason |')
        lines.append('|--------|---------|---------|------|--------|')
        for change in report.changes:
            tier_name = ['Core', 'Distribution', 'Access'][min(change.hierarchy_tier, 2)]
            lines.append(
                f'| {change.device_name} | {change.current_priority} | '
                f'{change.new_priority} | {tier_name} | {change.reason} |'
            )
        lines.append('')

        # Optimal diagram
        lines.append('### Optimal Topology Diagram')
        lines.append('')
        lines.append(report.optimal_diagram)
        lines.append('')

        # Diff section
        lines.append('## Configuration Diff')
        lines.append('```diff')
        for change in report.changes:
            lines.append(f'- {change.device_name}: priority {change.current_priority}')
            lines.append(f'+ {change.device_name}: priority {change.new_priority}')
        lines.append('```')
        lines.append('')

    # Recommendations
    if report.recommendations:
        lines.append('## Recommendations')
        for rec in report.recommendations:
            lines.append(f'- {rec}')
        lines.append('')

    # Priority reference
    lines.append('## STP Priority Standards')
    lines.append('')
    lines.append('| Tier | Priority Range | Description |')
    lines.append('|------|----------------|-------------|')
    lines.append('| Core | 4096 | Directly connected to gateway |')
    lines.append('| Distribution | 8192-12288 | One hop from core |')
    lines.append('| Access | 16384-28672 | Two+ hops from core |')
    lines.append('| Default | 32768 | UniFi default (not recommended) |')

    return '\n'.join(lines)
