"""STP (Spanning Tree Protocol) optimization tool for UniFi networks.

This module discovers the current STP topology, calculates optimal bridge
priorities based on network hierarchy, and generates reports with visual
diagrams showing current vs optimal configuration.
"""

from datetime import datetime
from typing import Any, cast
from unifi_mapper.analysis.model_capabilities import (
    SwitchCapabilityClass,
    classify_model,
    is_access_class,
    is_root_eligible,
)
from unifi_mapper.analysis.stp_guard import audit_stp_guard_recommendations
from unifi_mapper.core.models.stp import (
    STP_PRIORITY_ACCESS_BASE,
    STP_PRIORITY_CORE,
    STP_PRIORITY_DEFAULT,
    STP_PRIORITY_DISTRIBUTION,
    STP_PRIORITY_INCREMENT,
    STPChange,
    STPConnection,
    STPNetworkValidationReport,
    STPOptimizationReport,
    STPPathCostFinding,
    STPPortConfig,
    STPPortState,
    STPRole,
    STPTopology,
    STPValidationFinding,
    SwitchSTPConfig,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.overrides import STPOverrides, load_stp_overrides


def _as_int(value: Any, default: int = 0) -> int:
    """Convert UniFi API scalar values to int with a safe fallback."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    """Convert common UniFi API boolean encodings to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ('', '0', 'false', 'no', 'off')
    return bool(value)


def _as_dict(value: Any) -> dict[str, Any]:
    """Return dict values from nested API fields, otherwise an empty dict."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _switch_capability(switch: SwitchSTPConfig) -> SwitchCapabilityClass:
    """Classify a switch while preserving explicit non-unknown capability overrides."""
    classified = classify_model(switch.model)
    if classified.value == 'unknown' and switch.capability.value != 'unknown':
        return switch.capability
    return classified


async def discover_stp_topology(
    device_id: str | None = None,
    overrides: STPOverrides | None = None,
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
        overrides: Optional STP overrides controlling root eligibility.

    Returns:
        STPTopology with complete spanning tree state

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    resolved_overrides = overrides if overrides is not None else load_stp_overrides()

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
                capability = classify_model(dev_model)

                capability = classify_model(dev_model)
                force_access = resolved_overrides.is_force_access(dev_mac)
                override_root = resolved_overrides.is_root_eligible_override(dev_mac)

                if force_access:
                    eligible = False
                elif override_root and is_root_eligible(capability):
                    eligible = True
                else:
                    eligible = is_root_eligible(capability)

                switch_config = SwitchSTPConfig(
                    device_id=dev_id,
                    name=dev_name,
                    mac=dev_mac,
                    model=dev_model,
                    current_priority=stp_priority,
                    is_root_bridge=(dev_id == root_bridge_id),
                    port_states=port_states,
                    connected_to_gateway=connected_to_gateway,
                    capability=capability,
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
            _calculate_hierarchy_tiers(switches, overrides=resolved_overrides)
            _apply_root_eligibility(switches, overrides=resolved_overrides)

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

        port_stats = _as_dict(port_data.get('port_stats'))
        port_config = STPPortConfig(
            port_idx=port_idx,
            port_name=port_name,
            stp_state=stp_state,
            stp_role=stp_role,
            path_cost=path_cost,
            connected_device=connected_device,
            connected_device_id=connected_device_id,
            is_uplink=is_uplink,
            is_up=_as_bool(port_data.get('up'), default=False),
            enabled=_as_bool(port_data.get('enabled'), default=True),
            link_speed_mbps=_as_int(port_data.get('speed')),
            full_duplex=_as_bool(port_data.get('full_duplex'), default=True),
            rx_errors=_as_int(port_data.get('rx_errors')),
            tx_errors=_as_int(port_data.get('tx_errors')),
            rx_dropped=_as_int(port_data.get('rx_dropped')),
            tx_dropped=_as_int(port_data.get('tx_dropped')),
            crc_errors=_as_int(port_data.get('rx_crc_errors') or port_stats.get('rx_crc_errors')),
            stp_tc_count=_as_int(
                port_data.get('stp_tc_count')
                or port_data.get('stp_state_change_count')
                or port_data.get('stp_topology_change_count')
            ),
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
    overrides: STPOverrides | None = None,
) -> None:
    """Calculate network hierarchy tiers using capability + topology.

    Rules:
    - Tier 0 (Core): gateway-connected AND root-eligible capability
      (AGGREGATION or CORE_DISTRIBUTION) AND not force_access_macs.
    - A gateway-connected access-class switch becomes Tier 1 so it is
      below Tier 0 but still close to the gateway hierarchically.
    - BFS from the resolved Tier 0 set populates remaining tiers. A
      switch only reached via access-class neighbours still gets the
      hop-count tier (BFS distance from Tier 0).

    The old algorithm treated any gateway-connected switch as Tier 0,
    which promoted small access switches (e.g. USW-Lite) to Core and
    triggered incorrect priority 4096 recommendations.
    """
    resolved = overrides or STPOverrides()

    adjacency: dict[str, set[str]] = {s.device_id: set() for s in switches}
    for switch in switches:
        for port in switch.port_states:
            if port.connected_device_id:
                adjacency[switch.device_id].add(port.connected_device_id)

    resolved_overrides = overrides if overrides is not None else STPOverrides()

    # Find core switches (root-capable and connected to gateway).
    # Gateway-adjacent access switches are still BFS roots, but they are not
    # marked as Tier 0 because they should not become the STP root.
    core_switch_ids: set[str] = set()
    bfs_roots: set[str] = set()
    for switch in switches:
        if switch.connected_to_gateway:
            switch.capability = _switch_capability(switch)

            force_access = resolved_overrides.is_force_access(switch.mac)
            root_capable = is_root_eligible(switch.capability) or (
                switch.capability.value == 'unknown'
            )
            override_root = resolved_overrides.is_root_eligible_override(switch.mac)
            if not force_access and (root_capable or (override_root and not is_access_class(switch.capability))):
                switch.hierarchy_tier = 0
                switch.tier_reason = 'Gateway-connected root-capable switch'
                core_switch_ids.add(switch.device_id)
            else:
                switch.hierarchy_tier = 1
                switch.tier_reason = 'Gateway-connected access-class switch'
            bfs_roots.add(switch.device_id)

    # BFS to find distances from core
    if bfs_roots:
        visited = set(bfs_roots)
        current_tier = bfs_roots
        tier_level = 1 if core_switch_ids else 2

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
                                s.tier_reason = f'{tier_level} hop(s) from gateway-adjacent switch'
            current_tier = next_tier
            tier_level += 1


def _apply_root_eligibility(
    switches: list[SwitchSTPConfig],
    overrides: STPOverrides | None = None,
) -> None:
    """Mark preferred STP root candidates based on topology and model capability."""
    resolved_overrides = overrides if overrides is not None else STPOverrides()

    for switch in switches:
        switch.capability = _switch_capability(switch)
        force_access = resolved_overrides.is_force_access(switch.mac)
        override_root = resolved_overrides.is_root_eligible_override(switch.mac)

        if not switch.connected_to_gateway:
            switch.root_eligible = False
            switch.root_preference = 900
            switch.root_eligibility_reason = 'Not directly connected to gateway'
        elif force_access or is_access_class(switch.capability):
            switch.root_eligible = False
            switch.root_preference = 500
            switch.root_eligibility_reason = (
                f'Gateway-connected {switch.capability.value} switch is access-class'
            )
        elif is_root_eligible(switch.capability):
            switch.root_eligible = True
            switch.root_preference = 10 if switch.capability.value == 'aggregation' else 100
            switch.root_eligibility_reason = f'Gateway-connected {switch.capability.value} switch'
        elif override_root:
            switch.root_eligible = True
            switch.root_preference = 50
            switch.root_eligibility_reason = 'Gateway-connected root-eligible override'
        else:
            switch.root_eligible = False
            switch.root_preference = 700
            switch.root_eligibility_reason = (
                f'Gateway-connected {switch.capability.value} switch is not root-capable'
            )


def expected_long_path_cost(speed_mbps: int) -> int:
    """Return IEEE 802.1t long path cost for common Ethernet speeds."""
    if speed_mbps >= 100000:
        return 200
    if speed_mbps >= 40000:
        return 500
    if speed_mbps >= 10000:
        return 2000
    if speed_mbps >= 5000:
        return 4000
    if speed_mbps >= 2500:
        return 8000
    if speed_mbps >= 1000:
        return 20000
    if speed_mbps >= 100:
        return 200000
    return 2000000


def audit_stp_path_costs(topology: STPTopology) -> list[STPPathCostFinding]:
    """Audit inter-switch ports for STP path-cost values that distort 10G selection."""
    switch_ids = {switch.device_id for switch in topology.switches}
    findings: list[STPPathCostFinding] = []

    for switch in topology.switches:
        for port in switch.port_states:
            if (
                port.connected_device_id not in switch_ids
                or port.link_speed_mbps <= 0
                or port.path_cost <= 0
            ):
                continue

            expected = expected_long_path_cost(port.link_speed_mbps)
            if port.link_speed_mbps >= 10000 and port.path_cost < 100:
                findings.append(
                    STPPathCostFinding(
                        severity='CRITICAL',
                        device_name=switch.name,
                        port_idx=port.port_idx,
                        link_speed_mbps=port.link_speed_mbps,
                        path_cost=port.path_cost,
                        expected_long_cost=expected,
                        message=(
                            f'{switch.name} port {port.port_idx} has legacy-style STP path '
                            f'cost {port.path_cost} on a {port.link_speed_mbps // 1000}G link.'
                        ),
                        recommendation=(
                            'Confirm all switches use IEEE long path cost mode so 10G links '
                            'are preferred predictably over slower paths.'
                        ),
                    )
                )
            elif abs(port.path_cost - expected) > expected * 0.5:
                findings.append(
                    STPPathCostFinding(
                        severity='WARNING',
                        device_name=switch.name,
                        port_idx=port.port_idx,
                        link_speed_mbps=port.link_speed_mbps,
                        path_cost=port.path_cost,
                        expected_long_cost=expected,
                        message=(
                            f'{switch.name} port {port.port_idx} path cost {port.path_cost} '
                            f'differs from expected long cost {expected}.'
                        ),
                        recommendation='Review STP path cost mode and any manual path-cost overrides.',
                    )
                )

    return findings


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
    _apply_root_eligibility(topology.switches)

    # Sort switches by tier to assign priorities
    switches_by_tier: dict[int, list[SwitchSTPConfig]] = {}
    for switch in topology.switches:
        tier = switch.hierarchy_tier
        if tier not in switches_by_tier:
            switches_by_tier[tier] = []
        switches_by_tier[tier].append(switch)

    tier_zero_switches = switches_by_tier.get(0, [])
    eligible_root_candidates = [switch for switch in tier_zero_switches if switch.root_eligible]
    root_candidates = eligible_root_candidates or tier_zero_switches
    has_non_root_tier_zero = False
    preferred_root_id = None
    if root_candidates:
        preferred_root = sorted(
            root_candidates,
            key=lambda switch: (not switch.root_eligible, switch.root_preference, switch.name),
        )[0]
        preferred_root_id = preferred_root.device_id
        has_non_root_tier_zero = any(
            switch.device_id != preferred_root_id for switch in tier_zero_switches
        ) or any(
            switch.connected_to_gateway and switch.device_id != preferred_root_id
            for switch in topology.switches
        )

    # Assign optimal priorities based on tier and root eligibility
    for tier, tier_switches in switches_by_tier.items():
        if tier == 0:
            base_priority = STP_PRIORITY_CORE
            tier_name = 'Core'
        elif tier == 1:
            base_priority = (
                STP_PRIORITY_DISTRIBUTION + STP_PRIORITY_INCREMENT
                if has_non_root_tier_zero
                else STP_PRIORITY_DISTRIBUTION
            )
            tier_name = 'Distribution'
        else:
            base_priority = STP_PRIORITY_ACCESS_BASE + ((tier - 2) * STP_PRIORITY_INCREMENT)
            tier_name = f'Access (Tier {tier})'

        for switch in tier_switches:
            # UniFi API only accepts multiples of 4096
            if tier == 0 and preferred_root_id:
                optimal_priority = (
                    STP_PRIORITY_CORE
                    if switch.device_id == preferred_root_id
                    else STP_PRIORITY_DISTRIBUTION
                )
            elif tier == 1 and switch.connected_to_gateway and not switch.root_eligible:
                optimal_priority = STP_PRIORITY_DISTRIBUTION
            else:
                optimal_priority = base_priority
            switch.optimal_priority = optimal_priority

            if switch.current_priority != optimal_priority:
                reason = (
                    f'{tier_name} switch should have priority {optimal_priority}{guard_reason}'
                )
                if switch.connected_to_gateway and tier == 0 and not guard_reason:
                    reason = (
                        f'Core switch (gateway-connected, {switch.capability.value}) '
                        f'should have priority {optimal_priority}'
                    )
                if tier == 0 and switch.device_id == preferred_root_id:
                    reason = (
                        f'Preferred root ({switch.root_eligibility_reason}) should have '
                        f'priority {optimal_priority}'
                    )
                elif tier == 0 and not switch.root_eligible:
                    reason = (
                        f'Gateway-connected switch should not be preferred root: '
                        f'{switch.root_eligibility_reason}'
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
    _apply_root_eligibility(topology.switches)
    root_candidates = [
        switch for switch in topology.switches if switch.hierarchy_tier == 0 and switch.root_eligible
    ]
    if not root_candidates:
        root_candidates = [
            switch for switch in topology.switches if switch.hierarchy_tier == 0 and switch.connected_to_gateway
        ]
    if root_candidates:
        optimal_switch = sorted(
            root_candidates,
            key=lambda switch: (not switch.root_eligible, switch.root_preference, switch.name),
        )[0]
        optimal_root = optimal_switch.name
        optimal_root_reason = optimal_switch.root_eligibility_reason or (
            'Core switch directly connected to gateway'
        )

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


async def validate_10g_expansion_readiness(
    planned_flex_xg_switches: int = 2,
    target_speed_mbps: int = 10000,
    drops_threshold: int = 100000,
) -> STPNetworkValidationReport:
    """Validate local UniFi STP health before adding USW Flex XG switches.

    The validation combines current STP topology, bridge priority optimization,
    switch-to-switch link speed, duplex, and error counters. It is intentionally
    read-only and suitable to run before installing additional 10G switches.
    """
    topology = await discover_stp_topology()
    changes = await calculate_optimal_priorities(topology)
    return build_10g_expansion_validation_report(
        topology=topology,
        stp_changes=changes,
        planned_flex_xg_switches=planned_flex_xg_switches,
        target_speed_mbps=target_speed_mbps,
        drops_threshold=drops_threshold,
    )


def build_10g_expansion_validation_report(
    topology: STPTopology,
    stp_changes: list[STPChange],
    planned_flex_xg_switches: int = 2,
    target_speed_mbps: int = 10000,
    drops_threshold: int = 100000,
) -> STPNetworkValidationReport:
    """Build a validation report from already-discovered STP topology data."""
    findings: list[STPValidationFinding] = []
    _apply_root_eligibility(topology.switches)
    switch_ids = {switch.device_id for switch in topology.switches}
    inter_switch_ports = [
        (switch, port)
        for switch in topology.switches
        for port in switch.port_states
        if port.connected_device_id in switch_ids
    ]
    ten_gig_ports = [
        (switch, port) for switch, port in inter_switch_ports if port.link_speed_mbps >= target_speed_mbps
    ]

    if planned_flex_xg_switches < 1:
        findings.append(
            STPValidationFinding(
                severity='CRITICAL',
                category='Plan',
                message='No USW Flex XG switches are included in the expansion plan.',
                recommendation='Set planned_flex_xg_switches to the number of switches being added.',
            )
        )

    root_switch = next((switch for switch in topology.switches if switch.is_root_bridge), None)
    if topology.root_bridge_priority == STP_PRIORITY_DEFAULT:
        findings.append(
            STPValidationFinding(
                severity='WARNING',
                category='STP',
                message='Current root bridge is still using the default STP priority 32768.',
                recommendation='Apply explicit bridge priorities before adding redundant 10G paths.',
                device_name=topology.root_bridge_name,
            )
        )

    if root_switch and not root_switch.connected_to_gateway:
        findings.append(
            STPValidationFinding(
                severity='CRITICAL',
                category='STP',
                message=f'Current root bridge "{root_switch.name}" is not directly connected to the gateway.',
                recommendation='Make a gateway-connected core switch the STP root before adding the Flex XG switches.',
                device_name=root_switch.name,
            )
        )

    if root_switch and not root_switch.root_eligible and root_switch.capability.value != 'unknown':
        findings.append(
            STPValidationFinding(
                severity='CRITICAL',
                category='STP',
                message=(
                    f'Current root bridge "{root_switch.name}" is not an eligible STP root '
                    f'for capability class {root_switch.capability.value}.'
                ),
                recommendation='Move the root bridge to an aggregation or core/distribution switch.',
                device_name=root_switch.name,
            )
        )

    if stp_changes:
        findings.append(
            STPValidationFinding(
                severity='WARNING',
                category='STP',
                message=f'{len(stp_changes)} STP bridge priority change(s) are recommended.',
                recommendation='Run stp optimize --dry-run, review the changes, then apply them in a maintenance window.',
            )
        )

    if topology.blocked_ports_count > 0:
        findings.append(
            STPValidationFinding(
                severity='WARNING',
                category='STP',
                message=f'{topology.blocked_ports_count} port(s) are currently blocking or discarding.',
                recommendation='Confirm these are intentional redundant paths, not an accidental loop.',
            )
        )

    for cost_finding in audit_stp_path_costs(topology):
        findings.append(
            STPValidationFinding(
                severity=cost_finding.severity,
                category='Path Cost',
                message=cost_finding.message,
                recommendation=cost_finding.recommendation,
                device_name=cost_finding.device_name,
                port_idx=cost_finding.port_idx,
            )
        )

    for guard_finding in audit_stp_guard_recommendations(topology).findings:
        if guard_finding.severity == 'INFO':
            continue
        findings.append(
            STPValidationFinding(
                severity=guard_finding.severity,
                category=guard_finding.category,
                message=guard_finding.message,
                recommendation=guard_finding.recommendation,
                device_name=guard_finding.device_name,
                port_idx=guard_finding.port_idx,
            )
        )

    if not inter_switch_ports:
        findings.append(
            STPValidationFinding(
                severity='CRITICAL',
                category='Topology',
                message='No LLDP switch-to-switch links were discovered.',
                recommendation='Enable LLDP on infrastructure switches and re-run validation.',
            )
        )

    if planned_flex_xg_switches and len(ten_gig_ports) < planned_flex_xg_switches:
        findings.append(
            STPValidationFinding(
                severity='WARNING',
                category='10G',
                message=(
                    f'Only {len(ten_gig_ports)} discovered switch-to-switch port(s) are currently '
                    f'negotiating at {target_speed_mbps // 1000}G or better.'
                ),
                recommendation=(
                    f'After adding {planned_flex_xg_switches} USW Flex XG switch(es), verify each uplink '
                    f'negotiates at {target_speed_mbps // 1000}G full-duplex.'
                ),
            )
        )

    for switch, port in inter_switch_ports:
        port_errors = port.rx_errors + port.tx_errors + port.crc_errors
        port_drops = port.rx_dropped + port.tx_dropped

        if port.is_up and not port.full_duplex and port.link_speed_mbps >= 1000:
            findings.append(
                STPValidationFinding(
                    severity='CRITICAL',
                    category='Link',
                    message=f'{switch.name} port {port.port_idx} is not full-duplex.',
                    recommendation='Fix speed/duplex negotiation before using this path for 10G uplink traffic.',
                    device_name=switch.name,
                    port_idx=port.port_idx,
                )
            )

        if port_errors > 0:
            severity = 'CRITICAL' if port.crc_errors > 100 or port_errors > 1000 else 'WARNING'
            findings.append(
                STPValidationFinding(
                    severity=severity,
                    category='Errors',
                    message=(
                        f'{switch.name} port {port.port_idx} has errors/drops '
                        f'(errors={port_errors}, drops={port_drops}).'
                    ),
                    recommendation='Inspect transceivers, cables, patching, and port counters before expansion.',
                    device_name=switch.name,
                    port_idx=port.port_idx,
                )
            )
        elif port_drops > 0:
            severity = 'WARNING' if port_drops > drops_threshold else 'INFO'
            findings.append(
                STPValidationFinding(
                    severity=severity,
                    category='Drops',
                    message=f'{switch.name} port {port.port_idx} has drops={port_drops}.',
                    recommendation=(
                        'Treat drops-only counters as informational unless they are increasing '
                        'or exceed the configured threshold.'
                    ),
                    device_name=switch.name,
                    port_idx=port.port_idx,
                )
            )

    critical_count = sum(1 for finding in findings if finding.severity == 'CRITICAL')
    warning_count = sum(1 for finding in findings if finding.severity == 'WARNING')
    if critical_count:
        readiness = 'NOT_READY'
    elif warning_count:
        readiness = 'READY_WITH_WARNINGS'
    else:
        readiness = 'READY'

    return STPNetworkValidationReport(
        planned_flex_xg_switches=planned_flex_xg_switches,
        target_speed_mbps=target_speed_mbps,
        switches_analyzed=len(topology.switches),
        inter_switch_links=len(topology.connections),
        ten_gig_links=len(ten_gig_ports),
        blocked_ports_count=topology.blocked_ports_count,
        stp_changes_required=len(stp_changes),
        validation_passed=critical_count == 0,
        readiness=readiness,
        findings=findings,
        stp_changes=stp_changes,
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


def format_10g_validation_report_markdown(report: STPNetworkValidationReport) -> str:
    """Format 10G expansion validation report as markdown."""
    lines = [
        '# UniFi 10G Expansion Validation Report',
        f'*Generated: {report.timestamp}*',
        '',
        '## Summary',
        f'- **Readiness**: {report.readiness}',
        f'- **Validation Passed**: {"Yes" if report.validation_passed else "No"}',
        f'- **Planned USW Flex XG Switches**: {report.planned_flex_xg_switches}',
        f'- **Switches Analyzed**: {report.switches_analyzed}',
        f'- **Inter-switch Links**: {report.inter_switch_links}',
        f'- **10G Inter-switch Ports**: {report.ten_gig_links}',
        f'- **Blocked STP Ports**: {report.blocked_ports_count}',
        f'- **STP Priority Changes Required**: {report.stp_changes_required}',
        '',
    ]

    if report.findings:
        lines.append('## Findings')
        lines.append('')
        lines.append('| Severity | Category | Device | Port | Finding | Recommendation |')
        lines.append('|----------|----------|--------|------|---------|----------------|')
        for finding in report.findings:
            device = finding.device_name or ''
            port = str(finding.port_idx) if finding.port_idx is not None else ''
            lines.append(
                f'| {finding.severity} | {finding.category} | {device} | {port} | '
                f'{finding.message} | {finding.recommendation} |'
            )
        lines.append('')
    else:
        lines.extend(
            [
                '## Findings',
                '',
                'No critical or warning findings detected.',
                '',
            ]
        )

    if report.stp_changes:
        lines.append('## Recommended STP Priority Changes')
        lines.append('')
        lines.append('| Switch | Current | Recommended | Reason |')
        lines.append('|--------|---------|-------------|--------|')
        for change in report.stp_changes:
            lines.append(
                f'| {change.device_name} | {change.current_priority} | '
                f'{change.new_priority} | {change.reason} |'
            )
        lines.append('')
        lines.append('## Configuration Diff')
        lines.append('```diff')
        for change in report.stp_changes:
            lines.append(f'- {change.device_name}: priority {change.current_priority}')
            lines.append(f'+ {change.device_name}: priority {change.new_priority}')
        lines.append('```')
        lines.append('')

    lines.extend(
        [
            '## Post-install Checks',
            '',
            f'- Verify each USW Flex XG uplink negotiates at {report.target_speed_mbps // 1000}G full-duplex.',
            '- Re-run `unifi-mapper stp analyze` and confirm the root bridge is still the intended core switch.',
            '- Re-run this validation after cabling the new switches and investigate any new port errors.',
        ]
    )

    return '\n'.join(lines)
