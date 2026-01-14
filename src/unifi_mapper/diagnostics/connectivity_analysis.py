"""Advanced connectivity analysis diagnostic tool."""

from collections import defaultdict
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Tuple
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


class ConnectivityPath(BaseModel):
    """Represents a connectivity path between devices."""

    source_device: str = Field(description='Source device name')
    source_mac: str = Field(description='Source MAC address')
    destination_device: str = Field(description='Destination device name')
    destination_mac: str = Field(description='Destination MAC address')
    path_hops: List[str] = Field(description='Network hops in the path')
    path_quality: str = Field(description='Path quality: excellent, good, fair, poor')
    bandwidth_usage: Optional[float] = Field(description='Bandwidth usage percentage')
    latency_ms: Optional[float] = Field(description='Path latency in milliseconds')
    issues: List[str] = Field(description='Connectivity issues detected')


class NetworkSegment(BaseModel):
    """Network segment analysis."""

    segment_id: str = Field(description='Segment identifier')
    segment_type: str = Field(description='Segment type: switch, ap, vlan, site')
    device_count: int = Field(description='Number of devices in segment')
    uplink_quality: str = Field(description='Uplink quality: excellent, good, fair, poor')
    congestion_level: str = Field(description='Congestion level: low, medium, high, critical')
    redundancy: bool = Field(description='Whether segment has redundant paths')
    single_points_of_failure: List[str] = Field(description='Single points of failure')


class ConnectivityIssue(BaseModel):
    """Connectivity issue identification."""

    issue_type: str = Field(description='Type of issue')
    severity: str = Field(description='Issue severity: low, medium, high, critical')
    affected_devices: List[str] = Field(description='List of affected device names')
    description: str = Field(description='Detailed issue description')
    root_cause: Optional[str] = Field(description='Identified root cause')
    resolution_steps: List[str] = Field(description='Steps to resolve the issue')


class ConnectivityAnalysisReport(BaseModel):
    """Comprehensive connectivity analysis report."""

    timestamp: str = Field(description='When the analysis was performed')

    # Overall connectivity health
    network_connectivity_score: int = Field(
        description='Overall connectivity score (0-100)', ge=0, le=100
    )
    total_paths_analyzed: int = Field(description='Number of connectivity paths analyzed')
    healthy_paths: int = Field(description='Number of healthy connectivity paths')
    degraded_paths: int = Field(description='Number of degraded connectivity paths')
    broken_paths: int = Field(description='Number of broken connectivity paths')

    # Network topology insights
    network_segments: List[NetworkSegment] = Field(description='Network segment analysis')
    critical_paths: List[ConnectivityPath] = Field(description='Critical connectivity paths')
    redundant_paths: List[ConnectivityPath] = Field(description='Available redundant paths')

    # Issues and bottlenecks
    connectivity_issues: List[ConnectivityIssue] = Field(
        description='Identified connectivity issues'
    )
    bandwidth_bottlenecks: List[str] = Field(description='Bandwidth bottleneck locations')
    latency_issues: List[str] = Field(description='High latency path segments')

    # Recommendations
    optimization_opportunities: List[str] = Field(description='Network optimization opportunities')
    reliability_improvements: List[str] = Field(description='Reliability improvement suggestions')
    capacity_planning: List[str] = Field(description='Capacity planning recommendations')


async def connectivity_analysis() -> ConnectivityAnalysisReport:
    """Perform advanced connectivity analysis to identify patterns, bottlenecks, and optimization opportunities.

    When to use this tool:
    - When network performance issues are suspected but not clearly identified
    - For proactive network optimization and capacity planning
    - To understand network topology and traffic patterns
    - When planning network changes or expansions
    - During incident investigation to understand connectivity impact

    Common workflow:
    1. Run connectivity_analysis() to understand overall connectivity health
    2. Focus on critical connectivity_issues first
    3. Use find_device() to investigate devices in bandwidth_bottlenecks
    4. Use port_map() to understand physical connections of critical paths
    5. Use network_topology() to visualize problematic network segments

    What to do next:
    - If connectivity_score < 70: Address critical connectivity issues immediately
    - If bandwidth_bottlenecks found: Plan capacity upgrades for affected segments
    - If single points of failure: Implement redundancy where critical
    - If latency_issues: Investigate and optimize affected network paths
    - Use optimization_opportunities for proactive network improvements

    Returns:
        ConnectivityAnalysisReport with detailed connectivity analysis and recommendations

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        try:
            # Get comprehensive network data
            devices_data = await client.get(client.build_path('stat/device'))
            clients_data = await client.get(client.build_path('stat/sta'))

            # Get port statistics for bandwidth analysis
            try:
                port_stats = []
                for device in devices_data:
                    device_id = device.get('_id')
                    if device_id:
                        try:
                            stats = await client.get(client.build_path(f'stat/device/{device_id}'))
                            if stats and 'port_table' in stats[0]:
                                port_stats.append(stats[0])
                        except Exception:
                            continue  # Skip if can't get port stats for this device
            except Exception:
                port_stats = []

            # Perform connectivity analysis
            return _analyze_network_connectivity(devices_data, clients_data, port_stats)

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller for connectivity analysis',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                    related_tools=['network_health_check', 'find_device'],
                )
            raise ToolError(
                message=f'Error performing connectivity analysis: {str(e)}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
                related_tools=['network_health_check', 'performance_analysis'],
            )


def _analyze_network_connectivity(
    devices_data: List[Dict[str, Any]],
    clients_data: List[Dict[str, Any]],
    port_stats: List[Dict[str, Any]],
) -> ConnectivityAnalysisReport:
    """Perform comprehensive connectivity analysis."""
    # Build network topology map
    topology_map = _build_topology_map(devices_data, clients_data)

    # Analyze connectivity paths
    connectivity_paths = _analyze_connectivity_paths(topology_map, devices_data, clients_data)

    # Analyze network segments
    network_segments = _analyze_network_segments(devices_data, port_stats)

    # Detect connectivity issues
    connectivity_issues = _detect_connectivity_issues(devices_data, clients_data, port_stats)

    # Identify bottlenecks
    bandwidth_bottlenecks, latency_issues = _identify_bottlenecks(devices_data, port_stats)

    # Calculate overall connectivity score
    connectivity_score = _calculate_connectivity_score(
        connectivity_paths, connectivity_issues, bandwidth_bottlenecks
    )

    # Generate recommendations
    optimization_opportunities, reliability_improvements, capacity_planning = (
        _generate_connectivity_recommendations(
            connectivity_issues, bandwidth_bottlenecks, network_segments
        )
    )

    # Categorize paths
    healthy_paths = len([p for p in connectivity_paths if p.path_quality in ['excellent', 'good']])
    degraded_paths = len([p for p in connectivity_paths if p.path_quality == 'fair'])
    broken_paths = len([p for p in connectivity_paths if p.path_quality == 'poor'])

    # Identify critical and redundant paths
    critical_paths = [p for p in connectivity_paths if 'critical' in ' '.join(p.issues).lower()]
    redundant_paths = [p for p in connectivity_paths if len(p.path_hops) > 2]

    return ConnectivityAnalysisReport(
        timestamp=datetime.now().isoformat(),
        network_connectivity_score=connectivity_score,
        total_paths_analyzed=len(connectivity_paths),
        healthy_paths=healthy_paths,
        degraded_paths=degraded_paths,
        broken_paths=broken_paths,
        network_segments=network_segments,
        critical_paths=critical_paths,
        redundant_paths=redundant_paths,
        connectivity_issues=connectivity_issues,
        bandwidth_bottlenecks=bandwidth_bottlenecks,
        latency_issues=latency_issues,
        optimization_opportunities=optimization_opportunities,
        reliability_improvements=reliability_improvements,
        capacity_planning=capacity_planning,
    )


def _build_topology_map(
    devices_data: List[Dict[str, Any]], clients_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Build network topology map from device and client data."""
    topology = {'devices': {}, 'clients': {}, 'connections': [], 'uplinks': {}}

    # Map devices
    for device in devices_data:
        mac = device.get('mac', '')
        topology['devices'][mac] = {
            'name': device.get('name', mac),
            'type': device.get('type', 'unknown'),
            'model': device.get('model', ''),
            'ip': device.get('ip'),
            'state': device.get('state', 0),
            'adopted': device.get('adopted', False),
        }

        # Track uplinks
        uplink = device.get('uplink', {})
        if uplink and uplink.get('uplink_mac'):
            topology['uplinks'][mac] = {
                'parent': uplink.get('uplink_mac'),
                'port': uplink.get('uplink_remote_port'),
                'up': uplink.get('up', False),
            }

    # Map clients
    for client in clients_data:
        mac = client.get('mac', '')
        topology['clients'][mac] = {
            'name': client.get('name', client.get('hostname', mac)),
            'ip': client.get('ip'),
            'ap_mac': client.get('ap_mac'),
            'sw_mac': client.get('sw_mac'),
            'sw_port': client.get('sw_port'),
            'uptime': client.get('uptime', 0),
        }

    return topology


def _analyze_connectivity_paths(
    topology_map: Dict[str, Any],
    devices_data: List[Dict[str, Any]],
    clients_data: List[Dict[str, Any]],
) -> List[ConnectivityPath]:
    """Analyze connectivity paths between devices."""
    paths = []

    # Analyze device-to-device paths (infrastructure connectivity)
    for device_mac, device_info in topology_map['devices'].items():
        if device_mac in topology_map['uplinks']:
            uplink_info = topology_map['uplinks'][device_mac]
            parent_mac = uplink_info['parent']

            if parent_mac in topology_map['devices']:
                path_quality = _assess_path_quality(
                    device_info, topology_map['devices'][parent_mac], uplink_info
                )
                issues = _identify_path_issues(device_info, uplink_info)

                path = ConnectivityPath(
                    source_device=device_info['name'],
                    source_mac=device_mac,
                    destination_device=topology_map['devices'][parent_mac]['name'],
                    destination_mac=parent_mac,
                    path_hops=[device_info['name'], topology_map['devices'][parent_mac]['name']],
                    path_quality=path_quality,
                    bandwidth_usage=None,  # Would need detailed port stats
                    latency_ms=None,  # Would need ping/monitoring data
                    issues=issues,
                )
                paths.append(path)

    # Analyze client connectivity paths
    for client_mac, client_info in topology_map['clients'].items():
        # Client to AP/Switch path
        connection_point = client_info.get('ap_mac') or client_info.get('sw_mac')
        if connection_point and connection_point in topology_map['devices']:
            device_info = topology_map['devices'][connection_point]
            path_quality = _assess_client_path_quality(client_info, device_info)
            issues = _identify_client_path_issues(client_info)

            path = ConnectivityPath(
                source_device=client_info['name'],
                source_mac=client_mac,
                destination_device=device_info['name'],
                destination_mac=connection_point,
                path_hops=[client_info['name'], device_info['name']],
                path_quality=path_quality,
                bandwidth_usage=None,
                latency_ms=None,
                issues=issues,
            )
            paths.append(path)

    return paths


def _analyze_network_segments(
    devices_data: List[Dict[str, Any]], port_stats: List[Dict[str, Any]]
) -> List[NetworkSegment]:
    """Analyze network segments for health and redundancy."""
    segments = []

    # Group devices by type and analyze as segments
    device_types = defaultdict(list)
    for device in devices_data:
        device_type = device.get('type', 'unknown')
        device_types[device_type].append(device)

    for segment_type, devices in device_types.items():
        if not devices:
            continue

        # Analyze segment health (count reserved for future metrics)
        _online_devices = len([d for d in devices if d.get('state') == 1])  # noqa: F841
        uplink_quality = _assess_segment_uplink_quality(devices)
        congestion_level = _assess_segment_congestion(devices, port_stats)
        redundancy = _check_segment_redundancy(devices)
        spofs = _identify_single_points_of_failure(devices)

        segment = NetworkSegment(
            segment_id=f'{segment_type}_segment',
            segment_type=segment_type,
            device_count=len(devices),
            uplink_quality=uplink_quality,
            congestion_level=congestion_level,
            redundancy=redundancy,
            single_points_of_failure=spofs,
        )
        segments.append(segment)

    return segments


def _detect_connectivity_issues(
    devices_data: List[Dict[str, Any]],
    clients_data: List[Dict[str, Any]],
    port_stats: List[Dict[str, Any]],
) -> List[ConnectivityIssue]:
    """Detect specific connectivity issues."""
    issues = []

    # Check for offline devices
    offline_devices = [d for d in devices_data if d.get('state') != 1]
    if offline_devices:
        device_names = [d.get('name', d.get('mac', 'Unknown')) for d in offline_devices]
        issues.append(
            ConnectivityIssue(
                issue_type='Device Offline',
                severity='high' if len(offline_devices) > 1 else 'medium',
                affected_devices=device_names,
                description=f'{len(offline_devices)} devices are currently offline',
                root_cause='Power, cable, or device failure',
                resolution_steps=[
                    'Check power connections and status LEDs',
                    'Verify cable connections and cable integrity',
                    'Check switch port status',
                    'Consider device replacement if hardware failure',
                ],
            )
        )

    # Check for uplink issues
    uplink_issues = []
    for device in devices_data:
        uplink = device.get('uplink', {})
        if uplink and not uplink.get('up', False):
            device_name = device.get('name', device.get('mac', 'Unknown'))
            uplink_issues.append(device_name)

    if uplink_issues:
        issues.append(
            ConnectivityIssue(
                issue_type='Uplink Failure',
                severity='critical',
                affected_devices=uplink_issues,
                description=f'{len(uplink_issues)} devices have uplink connectivity issues',
                root_cause='Cable failure, switch port failure, or network misconfiguration',
                resolution_steps=[
                    'Check uplink cable connections',
                    'Verify switch port configuration and status',
                    'Test cable integrity with cable tester',
                    'Check for VLAN or network configuration issues',
                ],
            )
        )

    # Check for high error rates (would need detailed port stats)
    # This is simplified - real implementation would analyze error counters

    return issues


def _identify_bottlenecks(
    devices_data: List[Dict[str, Any]], port_stats: List[Dict[str, Any]]
) -> Tuple[List[str], List[str]]:
    """Identify bandwidth and latency bottlenecks."""
    bandwidth_bottlenecks = []
    latency_issues = []

    # Analyze port statistics for bandwidth utilization
    for port_stat in port_stats:
        device_name = port_stat.get('name', 'Unknown Device')
        port_table = port_stat.get('port_table', [])

        for port in port_table:
            port_idx = port.get('port_idx', 0)
            speed = port.get('speed', 0)
            tx_bytes = port.get('tx_bytes', 0)
            rx_bytes = port.get('rx_bytes', 0)

            # Simplified bandwidth analysis
            # In real implementation, would track over time intervals
            if speed > 0:
                # This is very simplified - real analysis needs time-series data
                utilization_estimate = (tx_bytes + rx_bytes) / (
                    speed * 1000000
                )  # Very rough estimate
                if utilization_estimate > 0.8:  # 80% utilization
                    bandwidth_bottlenecks.append(f'{device_name} port {port_idx}')

    # Latency analysis would require active monitoring/ping data
    # For now, identify potential latency issues from topology
    for device in devices_data:
        device_name = device.get('name', 'Unknown')

        # High CPU can cause latency
        system_stats = device.get('system-stats', {})
        cpu = system_stats.get('cpu', 0)
        if cpu > 90:
            latency_issues.append(f'{device_name} - high CPU usage may cause latency')

        # Multiple uplink hops can increase latency
        uplink_chain_length = _calculate_uplink_chain_length(device, devices_data)
        if uplink_chain_length > 3:
            latency_issues.append(f'{device_name} - long uplink chain may increase latency')

    return bandwidth_bottlenecks, latency_issues


def _assess_path_quality(
    device_info: Dict[str, Any], parent_info: Dict[str, Any], uplink_info: Dict[str, Any]
) -> str:
    """Assess quality of connectivity path between devices."""
    # Start with excellent and degrade based on issues
    quality = 'excellent'

    if not uplink_info.get('up', False):
        return 'poor'

    if device_info.get('state') != 1 or parent_info.get('state') != 1:
        return 'poor'

    # Check for adoption issues
    if not device_info.get('adopted', False) or not parent_info.get('adopted', False):
        quality = 'fair'

    return quality


def _assess_client_path_quality(client_info: Dict[str, Any], device_info: Dict[str, Any]) -> str:
    """Assess quality of client connectivity path."""
    # Check device health
    if device_info.get('state') != 1:
        return 'poor'

    # Check client uptime (very short uptime might indicate connection issues)
    uptime = client_info.get('uptime', 0)
    if uptime < 300:  # Less than 5 minutes
        return 'fair'

    return 'good'


def _identify_path_issues(device_info: Dict[str, Any], uplink_info: Dict[str, Any]) -> List[str]:
    """Identify specific issues with a connectivity path."""
    issues = []

    if not uplink_info.get('up', False):
        issues.append('Uplink is down')

    if device_info.get('state') != 1:
        issues.append('Source device is offline')

    if not device_info.get('adopted', False):
        issues.append('Device is not adopted')

    return issues


def _identify_client_path_issues(client_info: Dict[str, Any]) -> List[str]:
    """Identify issues with client connectivity."""
    issues = []

    uptime = client_info.get('uptime', 0)
    if uptime < 300:
        issues.append('Recent connection - may be unstable')

    if not client_info.get('ip'):
        issues.append('No IP address assigned')

    return issues


def _assess_segment_uplink_quality(devices: List[Dict[str, Any]]) -> str:
    """Assess overall uplink quality for a network segment."""
    total_devices = len(devices)
    devices_with_good_uplinks = 0

    for device in devices:
        uplink = device.get('uplink', {})
        if uplink and uplink.get('up', False):
            devices_with_good_uplinks += 1

    if total_devices == 0:
        return 'unknown'

    uplink_ratio = devices_with_good_uplinks / total_devices

    if uplink_ratio >= 0.95:
        return 'excellent'
    elif uplink_ratio >= 0.85:
        return 'good'
    elif uplink_ratio >= 0.70:
        return 'fair'
    else:
        return 'poor'


def _assess_segment_congestion(
    devices: List[Dict[str, Any]], port_stats: List[Dict[str, Any]]
) -> str:
    """Assess congestion level for a network segment."""
    # Simplified congestion assessment
    # Real implementation would analyze traffic patterns and utilization

    high_cpu_devices = 0
    for device in devices:
        system_stats = device.get('system-stats', {})
        cpu = system_stats.get('cpu', 0)
        if cpu > 80:
            high_cpu_devices += 1

    if high_cpu_devices == 0:
        return 'low'
    elif high_cpu_devices <= len(devices) * 0.2:  # 20%
        return 'medium'
    elif high_cpu_devices <= len(devices) * 0.5:  # 50%
        return 'high'
    else:
        return 'critical'


def _check_segment_redundancy(devices: List[Dict[str, Any]]) -> bool:
    """Check if network segment has redundancy."""
    # Simple check: if there are multiple devices of the same type,
    # there might be some redundancy
    return len(devices) > 1


def _identify_single_points_of_failure(devices: List[Dict[str, Any]]) -> List[str]:
    """Identify single points of failure in network segment."""
    spofs = []

    # If only one device of a critical type
    if len(devices) == 1:
        device_name = devices[0].get('name', 'Unknown Device')
        device_type = devices[0].get('type', 'unknown')
        if device_type in ['ugw', 'udm', 'uxg']:  # Gateway devices
            spofs.append(f'Single gateway device: {device_name}')

    return spofs


def _calculate_uplink_chain_length(
    device: Dict[str, Any], all_devices: List[Dict[str, Any]]
) -> int:
    """Calculate length of uplink chain for a device."""
    # Build device lookup
    device_lookup = {d.get('mac', ''): d for d in all_devices}

    current_device = device
    chain_length = 0
    visited = set()

    while current_device and chain_length < 10:  # Prevent infinite loops
        current_mac = current_device.get('mac', '')
        if current_mac in visited:
            break
        visited.add(current_mac)

        uplink = current_device.get('uplink', {})
        uplink_mac = uplink.get('uplink_mac')

        if not uplink_mac or uplink_mac not in device_lookup:
            break

        current_device = device_lookup[uplink_mac]
        chain_length += 1

    return chain_length


def _calculate_connectivity_score(
    connectivity_paths: List[ConnectivityPath],
    connectivity_issues: List[ConnectivityIssue],
    bandwidth_bottlenecks: List[str],
) -> int:
    """Calculate overall network connectivity score (0-100)."""
    if not connectivity_paths:
        return 0

    # Base score from path quality
    excellent_paths = len([p for p in connectivity_paths if p.path_quality == 'excellent'])
    good_paths = len([p for p in connectivity_paths if p.path_quality == 'good'])
    fair_paths = len([p for p in connectivity_paths if p.path_quality == 'fair'])
    poor_paths = len([p for p in connectivity_paths if p.path_quality == 'poor'])

    total_paths = len(connectivity_paths)
    path_score = (
        excellent_paths * 100 + good_paths * 80 + fair_paths * 60 + poor_paths * 20
    ) / total_paths

    # Penalty for issues
    critical_issues = len([i for i in connectivity_issues if i.severity == 'critical'])
    high_issues = len([i for i in connectivity_issues if i.severity == 'high'])
    medium_issues = len([i for i in connectivity_issues if i.severity == 'medium'])

    issue_penalty = critical_issues * 30 + high_issues * 20 + medium_issues * 10

    # Penalty for bottlenecks
    bottleneck_penalty = len(bandwidth_bottlenecks) * 5

    final_score = path_score - issue_penalty - bottleneck_penalty

    return max(0, min(100, int(final_score)))


def _generate_connectivity_recommendations(
    connectivity_issues: List[ConnectivityIssue],
    bandwidth_bottlenecks: List[str],
    network_segments: List[NetworkSegment],
) -> Tuple[List[str], List[str], List[str]]:
    """Generate connectivity optimization recommendations."""
    optimization_opportunities = []
    reliability_improvements = []
    capacity_planning = []

    # Optimization based on issues
    if bandwidth_bottlenecks:
        optimization_opportunities.append(
            f'Upgrade bandwidth for {len(bandwidth_bottlenecks)} bottleneck locations'
        )

    # Reliability improvements
    critical_issues = [i for i in connectivity_issues if i.severity == 'critical']
    if critical_issues:
        reliability_improvements.append(
            f'Address {len(critical_issues)} critical connectivity issues immediately'
        )

    segments_without_redundancy = [s for s in network_segments if not s.redundancy]
    if segments_without_redundancy:
        reliability_improvements.append(
            f'Add redundancy to {len(segments_without_redundancy)} network segments'
        )

    # Capacity planning
    high_congestion_segments = [
        s for s in network_segments if s.congestion_level in ['high', 'critical']
    ]
    if high_congestion_segments:
        capacity_planning.append(
            f'Plan capacity expansion for {len(high_congestion_segments)} congested segments'
        )

    # General recommendations
    optimization_opportunities.extend(
        [
            'Implement network monitoring for proactive issue detection',
            'Regular cable testing and maintenance schedule',
            'Consider network automation for configuration management',
        ]
    )

    reliability_improvements.extend(
        [
            'Implement redundant uplinks where possible',
            'Regular backup and recovery testing',
            'Document network topology and dependencies',
        ]
    )

    capacity_planning.extend(
        [
            'Monitor bandwidth trends for growth planning',
            'Plan for future device additions and capacity needs',
            'Consider traffic shaping and QoS implementation',
        ]
    )

    return optimization_opportunities, reliability_improvements, capacity_planning
