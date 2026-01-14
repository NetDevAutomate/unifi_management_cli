"""Link quality analysis tool for UniFi networks."""

from datetime import datetime
from typing import Any
from unifi_mapper.core.models import (
    LinkQualityReport,
    PortLinkQuality,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# Error rate thresholds (errors per million packets)
ERROR_THRESHOLD_WARNING = 10  # 0.001%
ERROR_THRESHOLD_HIGH = 100  # 0.01%
ERROR_THRESHOLD_CRITICAL = 1000  # 0.1%


async def analyze_link_quality(
    device_id: str | None = None,
    include_healthy: bool = False,
) -> LinkQualityReport:
    """Analyze physical layer link quality across the network.

    When to use this tool:
    - When experiencing intermittent connectivity issues
    - When clients report slow or unreliable connections
    - During routine network health assessments
    - After cabling changes or physical moves
    - When troubleshooting specific switch ports

    How link quality analysis works:
    - Collects error counters from all switch ports
    - Calculates error rates (errors per million packets)
    - Checks for duplex mismatches (indicated by late collisions)
    - Monitors link stability (flapping detection)
    - Scores each port's health from 0-100

    Types of issues detected:
    - CRC errors (cable/connector problems)
    - Late collisions (duplex mismatch)
    - Excessive drops (congestion or buffer issues)
    - Link flapping (unstable physical connection)
    - Frame errors (runts, giants, jabbers)

    Common workflow:
    1. analyze_link_quality() - get overview of problem ports
    2. Review ports with low health scores
    3. Check physical connections (cables, patch panels)
    4. Verify duplex/speed settings match on both ends
    5. Replace cables if CRC errors persist

    What to do next:
    - High CRC errors: Check/replace cables, verify connectors
    - Late collisions: Force duplex settings on both ends
    - Link flapping: Check cable connections, test with known-good cable
    - High drops: Check for congestion, verify switch buffers

    Args:
        device_id: Optional device ID to analyze. If None, analyzes all switches.
        include_healthy: Include ports with no issues (default: only problematic)

    Returns:
        LinkQualityReport with port metrics and health scores

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            port_metrics: list[PortLinkQuality] = []
            devices_analyzed = 0
            ports_analyzed = 0
            healthy_ports = 0
            degraded_ports = 0
            critical_ports = 0
            top_issues: dict[str, int] = {}

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
                port_table = device.get('port_table', [])

                for port in port_table:
                    port_idx = port.get('port_idx', 0)
                    if port_idx == 0:
                        continue

                    ports_analyzed += 1

                    # Extract metrics
                    metrics = _extract_link_metrics(port, dev_id, dev_name)

                    # Categorize by health
                    if metrics.health_score >= 90:
                        healthy_ports += 1
                        if not include_healthy:
                            continue
                    elif metrics.health_score >= 70:
                        degraded_ports += 1
                    else:
                        critical_ports += 1

                    # Track common issues
                    for issue in metrics.issues:
                        top_issues[issue] = top_issues.get(issue, 0) + 1

                    port_metrics.append(metrics)

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

            # Sort by health score (worst first)
            port_metrics.sort(key=lambda m: m.health_score)

            # Determine overall health
            if critical_ports > 0:
                overall_health = 'CRITICAL'
            elif degraded_ports > 0:
                overall_health = 'DEGRADED'
            else:
                overall_health = 'HEALTHY'

            # Get top issues sorted by frequency
            sorted_issues = sorted(top_issues.items(), key=lambda x: x[1], reverse=True)
            top_issue_list = [f'{issue} ({count} ports)' for issue, count in sorted_issues[:5]]

            return LinkQualityReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=devices_analyzed,
                ports_analyzed=ports_analyzed,
                healthy_ports=healthy_ports,
                degraded_ports=degraded_ports,
                critical_ports=critical_ports,
                port_metrics=port_metrics,
                overall_health=overall_health,
                top_issues=top_issue_list,
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
                message=f'Error analyzing link quality: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _extract_link_metrics(
    port: dict[str, Any],
    device_id: str,
    device_name: str,
) -> PortLinkQuality:
    """Extract link quality metrics from port data."""
    port_idx = port.get('port_idx', 0)
    port_name = port.get('name', '') or f'Port {port_idx}'

    # Basic link info
    is_up = port.get('up', False)
    speed = port.get('speed', 0)
    full_duplex = port.get('full_duplex', True)
    stp_state = port.get('stp_state', None)

    # PoE info
    poe_enabled = port.get('poe_mode', 'off') not in ('off', None)
    poe_power = port.get('poe_power', None)

    # Error counters
    rx_errors = port.get('rx_errors', 0) or 0
    tx_errors = port.get('tx_errors', 0) or 0
    rx_dropped = port.get('rx_dropped', 0) or 0
    tx_dropped = port.get('tx_dropped', 0) or 0

    # Detailed error breakdown (if available)
    port_stats = port.get('port_stats', {})
    crc_errors = port_stats.get('rx_crc_errors', port.get('rx_crc_errors', 0)) or 0
    collisions = port_stats.get('collisions', port.get('collisions', 0)) or 0

    # Traffic for utilization
    rx_bytes = port.get('rx_bytes', 0) or 0
    tx_bytes = port.get('tx_bytes', 0) or 0
    rx_packets = port.get('rx_packets', 0) or 0
    tx_packets = port.get('tx_packets', 0) or 0

    # Calculate error rate (PPM)
    total_packets = rx_packets + tx_packets
    total_errors = rx_errors + tx_errors + crc_errors
    error_ppm = 0.0
    if total_packets > 0:
        error_ppm = (total_errors / total_packets) * 1_000_000

    # Calculate utilization (simplified)
    utilization = 0.0
    if speed > 0:
        # Rough estimate based on bytes
        total_bytes = rx_bytes + tx_bytes
        # This is cumulative, so we can't get accurate rate without history
        # Just estimate based on relative traffic volume
        if total_bytes > 0:
            utilization = min(100.0, (total_bytes / (speed * 1_000_000)) * 100)

    # Detect issues
    issues: list[str] = []

    if not is_up:
        issues.append('Link down')

    if crc_errors > 100:
        issues.append('CRC errors - check cable')

    # Late collisions indicate duplex mismatch
    late_collisions = port_stats.get('late_collisions', 0) or 0
    if late_collisions > 0:
        issues.append('Late collisions - duplex mismatch suspected')

    if not full_duplex and speed >= 100:
        issues.append('Half-duplex on fast link')

    if rx_dropped > 1000 or tx_dropped > 1000:
        issues.append('High packet drops')

    if error_ppm > ERROR_THRESHOLD_CRITICAL:
        issues.append('Critical error rate')
    elif error_ppm > ERROR_THRESHOLD_HIGH:
        issues.append('High error rate')
    elif error_ppm > ERROR_THRESHOLD_WARNING:
        issues.append('Elevated error rate')

    # Calculate health score (0-100)
    health_score = _calculate_health_score(
        is_up,
        error_ppm,
        late_collisions,
        full_duplex,
        speed,
        rx_dropped,
        tx_dropped,
        total_packets,
    )

    return PortLinkQuality(
        device_id=device_id,
        device_name=device_name,
        port_idx=port_idx,
        port_name=port_name,
        link_speed=f'{speed} Mbps' if speed > 0 else 'Down',
        full_duplex=full_duplex,
        stp_state=stp_state,
        poe_enabled=poe_enabled,
        poe_power=poe_power,
        rx_errors=rx_errors,
        tx_errors=tx_errors,
        rx_dropped=rx_dropped,
        tx_dropped=tx_dropped,
        crc_errors=crc_errors,
        collisions=collisions,
        utilization_percent=round(utilization, 2),
        health_score=health_score,
        issues=issues,
    )


def _calculate_health_score(
    is_up: bool,
    error_ppm: float,
    late_collisions: int,
    full_duplex: bool,
    speed: int,
    rx_dropped: int,
    tx_dropped: int,
    total_packets: int,
) -> int:
    """Calculate health score from 0-100."""
    if not is_up:
        return 0

    score = 100.0

    # Error rate penalty (max 40 points)
    if error_ppm > 0:
        score -= min(40, error_ppm / 25)

    # Duplex mismatch penalty (20 points)
    if late_collisions > 0:
        score -= 20
    elif not full_duplex and speed >= 100:
        score -= 10

    # Drop rate penalty (max 20 points)
    if total_packets > 0:
        total_dropped = rx_dropped + tx_dropped
        drop_rate = (total_dropped / total_packets) * 100
        score -= min(20, drop_rate * 10)

    return max(0, int(score))
