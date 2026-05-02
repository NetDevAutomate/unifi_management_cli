"""LAG (Link Aggregation) monitoring tool for UniFi networks."""

import re
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.models import (
    LACPState,
    LAGGroup,
    LAGHealthReport,
    LAGMember,
    LAGStatus,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# Thresholds for LAG health assessment
LOAD_IMBALANCE_WARNING = 30  # % difference from average considered imbalanced
MIN_ACTIVE_MEMBERS_PERCENT = 50  # Minimum % of members that should be active


def _empty_int_list() -> list[int]:
    return []


def _empty_lag_candidates() -> list['LAGCandidate']:
    return []


class LAGCandidate(BaseModel):
    """A candidate parallel-link group that could become a LAG."""

    device_a: str
    device_b: str
    device_a_ports: list[int] = Field(default_factory=_empty_int_list)
    device_b_ports: list[int] = Field(default_factory=_empty_int_list)
    link_count: int
    min_speed_mbps: int
    total_capacity_mbps: int
    recommendation: str


class LAGCandidateReport(BaseModel):
    """Report of LAG candidates discovered from LLDP links."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    candidate_count: int = 0
    candidates: list[LAGCandidate] = Field(default_factory=_empty_lag_candidates)


async def monitor_lags(
    device_id: str | None = None,
) -> LAGHealthReport:
    """Monitor Link Aggregation Group health and performance.

    When to use this tool:
    - When experiencing intermittent connectivity on aggregated links
    - When monitoring high-availability switch interconnects
    - During routine infrastructure health assessments
    - After physical changes to LAG member cables
    - When troubleshooting bandwidth issues between switches

    How LAG monitoring works:
    - Discovers all port aggregation groups on switches
    - Analyzes member port status and traffic distribution
    - Calculates load balance scores across LAG members
    - Identifies failed, degraded, or misconfigured LAGs
    - Provides recommendations for optimization

    Types of issues detected:
    - Failed LAG members (link down)
    - Load imbalance (uneven traffic distribution)
    - LACP state issues (suspended, defaulted, expired)
    - High error counts on LAG members
    - Bandwidth capacity degradation

    Common workflow:
    1. monitor_lags() - get overview of LAG health
    2. Review any DEGRADED or CRITICAL LAGs
    3. Check physical connections for failed members
    4. Analyze load balance scores for uneven distribution
    5. Verify LACP settings match on both ends

    What to do next:
    - If members down: Check cables and SFPs, verify port config
    - If load imbalanced: Review hash algorithm (try src-dst-ip)
    - If LACP issues: Verify mode (active/passive) matches partner
    - If high errors: Check cable quality, port stats with link_quality

    Args:
        device_id: Optional device ID to check. If None, checks all switches.

    Returns:
        LAGHealthReport with all LAGs, member status, and recommendations

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            devices_analyzed = 0
            lag_groups: list[LAGGroup] = []
            all_issues: list[dict[str, Any]] = []
            recommendations: list[str] = []

            healthy_count = 0
            degraded_count = 0
            critical_count = 0
            total_bandwidth_gbps = 0.0
            active_bandwidth_gbps = 0.0

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

                # Extract LAG groups from device
                device_lags = _extract_lag_groups(device, dev_id, dev_name)

                for lag in device_lags:
                    lag_groups.append(lag)
                    total_bandwidth_gbps += lag.total_bandwidth_mbps / 1000
                    active_bandwidth_gbps += lag.active_bandwidth_mbps / 1000

                    # Count by status
                    if lag.status == LAGStatus.HEALTHY:
                        healthy_count += 1
                    elif lag.status == LAGStatus.DEGRADED:
                        degraded_count += 1
                        for issue in lag.issues:
                            all_issues.append(
                                {
                                    'severity': 'warning',
                                    'message': issue,
                                    'lag_id': lag.lag_id,
                                    'device_name': lag.device_name,
                                    'timestamp': datetime.now().isoformat(),
                                }
                            )
                    elif lag.status in (LAGStatus.CRITICAL, LAGStatus.MISCONFIGURED):
                        critical_count += 1
                        for issue in lag.issues:
                            all_issues.append(
                                {
                                    'severity': 'critical',
                                    'message': issue,
                                    'lag_id': lag.lag_id,
                                    'device_name': lag.device_name,
                                    'timestamp': datetime.now().isoformat(),
                                }
                            )

                # Check if specific device was found
                if device_id and devices_analyzed > 0:
                    break

            # Handle device not found
            if device_id and devices_analyzed == 0:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_network_topology'],
                )

            # Generate recommendations
            recommendations = _generate_recommendations(lag_groups)

            return LAGHealthReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=devices_analyzed,
                total_lags=len(lag_groups),
                healthy_lags=healthy_count,
                degraded_lags=degraded_count,
                critical_lags=critical_count,
                lag_groups=lag_groups,
                total_lag_bandwidth_gbps=round(total_bandwidth_gbps, 2),
                active_lag_bandwidth_gbps=round(active_bandwidth_gbps, 2),
                issues=all_issues,
                recommendations=recommendations,
                network_healthy=critical_count == 0 and degraded_count == 0,
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
                message=f'Error monitoring LAGs: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


async def find_lag_candidates(min_links: int = 2) -> LAGCandidateReport:
    """Find parallel healthy inter-switch links that may be LACP candidates."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return find_lag_candidates_from_data(devices, min_links=min_links)


def find_lag_candidates_from_data(
    devices: list[dict[str, Any]],
    min_links: int = 2,
) -> LAGCandidateReport:
    """Find LAG candidates from UniFi device dictionaries."""
    devices_by_mac = {
        _normalize_mac(device.get('mac')): device
        for device in devices
        if _normalize_mac(device.get('mac'))
    }
    grouped_links: dict[
        tuple[str, str],
        dict[
            tuple[tuple[str, int], tuple[str, int]],
            tuple[str, str, int, int, int],
        ],
    ] = {}
    devices_analyzed = 0

    for device in devices:
        if device.get('type') not in ('usw', 'switch', 'udm', 'udmpro'):
            continue
        devices_analyzed += 1
        local_device_id = str(device.get('_id'))
        existing_lag_ports = _existing_lag_ports(device)
        ports_by_idx = _ports_by_idx(device)
        for lldp in _dict_list(device.get('lldp_table')):
            local_port = _as_int(lldp.get('local_port_idx'))
            if local_port in existing_lag_ports:
                continue
            remote_mac = _normalize_mac(lldp.get('chassis_id'))
            remote_device = devices_by_mac.get(remote_mac)
            if remote_device is None:
                continue
            remote_device_id = str(remote_device.get('_id'))
            remote_port = _lldp_remote_port_idx(lldp)
            if remote_port and remote_port in _existing_lag_ports(remote_device):
                continue
            port = ports_by_idx.get(local_port)
            if port is None or not _port_is_candidate_member(port):
                continue
            sorted_pair = sorted([local_device_id, remote_device_id])
            pair = (sorted_pair[0], sorted_pair[1])
            if remote_port <= 0:
                remote_port = -local_port
            sorted_endpoints = sorted(
                ((local_device_id, local_port), (remote_device_id, remote_port))
            )
            canonical_link = (sorted_endpoints[0], sorted_endpoints[1])
            grouped_links.setdefault(pair, {})[canonical_link] = (
                local_device_id,
                remote_device_id,
                local_port,
                remote_port,
                _as_int(port.get('speed')),
            )

    candidates: list[LAGCandidate] = []
    devices_by_id = {str(device.get('_id')): device for device in devices}
    for pair, links_by_endpoint in grouped_links.items():
        links = list(links_by_endpoint.values())
        if len(links) < min_links:
            continue
        speeds = [speed for _, _, _, _, speed in links]
        if not speeds or len(set(speeds)) != 1:
            continue
        device_a_id, device_b_id = pair
        device_a = devices_by_id.get(device_a_id, {})
        device_b = devices_by_id.get(device_b_id, {})
        ports_by_device: dict[str, set[int]] = {device_a_id: set(), device_b_id: set()}
        for local_id, remote_id, local_port, remote_port, _ in links:
            ports_by_device.setdefault(local_id, set()).add(local_port)
            if remote_port > 0:
                ports_by_device.setdefault(remote_id, set()).add(remote_port)
        if (
            len(ports_by_device.get(device_a_id, set())) < min_links
            or len(ports_by_device.get(device_b_id, set())) < min_links
        ):
            continue
        min_speed = min(speeds)
        candidates.append(
            LAGCandidate(
                device_a=str(device_a.get('name') or device_a.get('mac')),
                device_b=str(device_b.get('name') or device_b.get('mac')),
                device_a_ports=sorted(ports_by_device.get(device_a_id, set())),
                device_b_ports=sorted(ports_by_device.get(device_b_id, set())),
                link_count=len(links),
                min_speed_mbps=min_speed,
                total_capacity_mbps=min_speed * len(links),
                recommendation='Review both ends for LACP compatibility before configuring a LAG.',
            )
        )

    return LAGCandidateReport(
        devices_analyzed=devices_analyzed,
        candidate_count=len(candidates),
        candidates=candidates,
    )


def _extract_lag_groups(
    device: dict[str, Any],
    device_id: str,
    device_name: str,
) -> list[LAGGroup]:
    """Extract LAG groups from device configuration."""
    lag_groups: list[LAGGroup] = []

    port_table = device.get('port_table', [])
    port_overrides = device.get('port_overrides', [])

    # Build port override lookup (reserved for future enhancement)
    _override_by_port = {po.get('port_idx'): po for po in port_overrides}  # noqa: F841

    # Find LAG configurations in UniFi
    aggregates = device.get('port_aggregates', [])

    for agg in aggregates:
        lag_id = agg.get('_id', f'{device_id}_lag_{len(lag_groups)}')
        member_ports = agg.get('member_ports', [])

        if not member_ports:
            continue

        members: list[LAGMember] = []
        active_members = 0
        total_bandwidth = 0
        active_bandwidth = 0
        total_rx_bytes = 0
        total_tx_bytes = 0

        for port_idx in member_ports:
            empty_port: dict[str, Any] = {}
            port_data = cast(
                dict[str, Any],
                next((p for p in port_table if p.get('port_idx') == port_idx), empty_port),
            )

            link_up = bool(port_data.get('up', False))
            enabled = bool(port_data.get('enable', True))
            is_active = link_up and enabled
            speed = _as_int(port_data.get('speed'))

            member = LAGMember(
                port_idx=port_idx,
                port_name=port_data.get('name', '') or f'Port {port_idx}',
                link_up=link_up,
                is_active=is_active,
                speed_mbps=speed,
                lacp_state=LACPState.ACTIVE if is_active else LACPState.SUSPENDED,
                rx_bytes=port_data.get('rx_bytes', 0) or 0,
                tx_bytes=port_data.get('tx_bytes', 0) or 0,
                rx_packets=port_data.get('rx_packets', 0) or 0,
                tx_packets=port_data.get('tx_packets', 0) or 0,
                rx_errors=port_data.get('rx_errors', 0) or 0,
                tx_errors=port_data.get('tx_errors', 0) or 0,
            )

            if is_active:
                active_members += 1
                active_bandwidth += speed

            total_bandwidth += speed
            total_rx_bytes += member.rx_bytes
            total_tx_bytes += member.tx_bytes
            members.append(member)

        # Calculate load distribution
        total_traffic = total_rx_bytes + total_tx_bytes
        if total_traffic > 0:
            for member in members:
                member_traffic = member.rx_bytes + member.tx_bytes
                member.load_percent = (member_traffic / total_traffic) * 100

        # Calculate efficiency and load balance score
        efficiency = 0.0
        if total_bandwidth > 0:
            efficiency = (active_bandwidth / total_bandwidth) * 100

        load_balance_score = _calculate_load_balance_score(members)

        # Determine status and issues
        status, issues = _determine_lag_status(
            expected_members=len(member_ports),
            active_members=active_members,
            members=members,
            load_balance_score=load_balance_score,
        )

        lag = LAGGroup(
            lag_id=lag_id,
            device_id=device_id,
            device_name=device_name,
            lag_name=agg.get('name', f'LAG-{lag_id[-4:]}'),
            members=members,
            expected_members=len(member_ports),
            active_members=active_members,
            total_bandwidth_mbps=total_bandwidth,
            active_bandwidth_mbps=active_bandwidth,
            total_rx_bytes=total_rx_bytes,
            total_tx_bytes=total_tx_bytes,
            status=status,
            efficiency_percent=round(efficiency, 1),
            load_balance_score=round(load_balance_score, 1),
            issues=issues,
        )

        lag_groups.append(lag)

    return lag_groups


def _existing_lag_ports(device: dict[str, Any]) -> set[int]:
    ports: set[int] = set()
    for aggregate in _dict_list(device.get('port_aggregates')):
        members = aggregate.get('member_ports')
        if isinstance(members, list):
            member_values = cast(list[Any], members)
            ports.update(_as_int(member) for member in member_values)
    return ports


def _ports_by_idx(device: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _as_int(port.get('port_idx')): port
        for port in _dict_list(device.get('port_table'))
    }


def _port_is_candidate_member(port: dict[str, Any]) -> bool:
    enabled = port.get('enabled', port.get('enable', True))
    return bool(port.get('up')) and bool(enabled) and _as_int(port.get('speed')) > 0


def _lldp_remote_port_idx(lldp: dict[str, Any]) -> int:
    for key in ('remote_port_idx', 'uplink_remote_port', 'port_idx', 'port_id'):
        port_idx = _parse_port_idx(lldp.get(key))
        if port_idx:
            return port_idx
    return 0


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    values = cast(list[Any], value)
    return [cast(dict[str, Any], item) for item in values if isinstance(item, dict)]


def _normalize_mac(value: Any) -> str:
    return str(value or '').lower().replace(':', '').replace('-', '')


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_port_idx(value: Any) -> int:
    port_idx = _as_int(value)
    if port_idx:
        return port_idx
    text = str(value or '')
    match = re.search(r'(\d+)\s*$', text)
    if match:
        return _as_int(match.group(1))
    return 0


def _calculate_load_balance_score(members: list[LAGMember]) -> float:
    """Calculate load balance score (0-100). 100 = perfectly balanced."""
    active_members = [m for m in members if m.is_active]

    if len(active_members) < 2:
        return 100.0

    loads = [m.load_percent for m in active_members]
    avg_load = sum(loads) / len(loads)

    if avg_load == 0:
        return 100.0

    # Calculate variance from average
    variance = sum((load - avg_load) ** 2 for load in loads) / len(loads)
    std_dev = variance**0.5

    # Score based on standard deviation (lower is better)
    score = max(0, 100 - (std_dev * 2))
    return score


def _determine_lag_status(
    expected_members: int,
    active_members: int,
    members: list[LAGMember],
    load_balance_score: float,
) -> tuple[LAGStatus, list[str]]:
    """Determine LAG health status and issues."""
    issues: list[str] = []

    if expected_members == 0:
        return LAGStatus.INACTIVE, issues

    active_percent = (active_members / expected_members) * 100

    if active_members == 0:
        issues.append('No active members')
        return LAGStatus.CRITICAL, issues

    if active_percent < MIN_ACTIVE_MEMBERS_PERCENT:
        issues.append(f'Only {active_members}/{expected_members} members active')
        return LAGStatus.CRITICAL, issues

    if active_members < expected_members:
        issues.append(f'{expected_members - active_members} member(s) down')
        return LAGStatus.DEGRADED, issues

    if load_balance_score < 70:
        issues.append(f'Load imbalance detected (score: {load_balance_score:.0f})')
        return LAGStatus.DEGRADED, issues

    # Check for member errors
    error_members = [m for m in members if m.rx_errors + m.tx_errors > 1000]
    if error_members:
        issues.append(f'{len(error_members)} member(s) with high error counts')
        return LAGStatus.DEGRADED, issues

    return LAGStatus.HEALTHY, issues


def _generate_recommendations(lag_groups: list[LAGGroup]) -> list[str]:
    """Generate recommendations based on LAG analysis."""
    recommendations: list[str] = []

    for lag in lag_groups:
        if lag.status == LAGStatus.DEGRADED:
            if lag.active_members < lag.expected_members:
                recommendations.append(
                    f'Investigate failed member port(s) on {lag.device_name} {lag.lag_name}'
                )
            if lag.load_balance_score < 70:
                recommendations.append(
                    f'Review hashing algorithm for {lag.lag_name} - consider src-dst-ip'
                )

        if lag.status == LAGStatus.CRITICAL:
            recommendations.append(
                f'URGENT: {lag.lag_name} on {lag.device_name} requires immediate attention'
            )

    if not lag_groups:
        recommendations.append(
            'No LAGs found - consider aggregation for critical inter-switch links'
        )

    return recommendations
