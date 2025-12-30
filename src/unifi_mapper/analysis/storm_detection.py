"""Broadcast/multicast storm detection tool for UniFi networks."""

from datetime import datetime
from typing import Any
from unifi_mcp.models import (
    PortTrafficMetrics,
    StormDetectionReport,
    StormEvent,
    StormSeverity,
    StormType,
)
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


# Default thresholds for storm detection
DEFAULT_THRESHOLDS = {
    'broadcast_percent_warning': 10.0,  # % of traffic that is broadcast
    'broadcast_percent_high': 25.0,
    'broadcast_percent_critical': 50.0,
    'multicast_percent_warning': 15.0,
    'multicast_percent_high': 30.0,
    'multicast_percent_critical': 50.0,
    'non_unicast_percent_warning': 20.0,  # Combined broadcast + multicast
    'non_unicast_percent_critical': 60.0,
}


async def detect_storms(
    device_id: str | None = None,
    thresholds: dict[str, float] | None = None,
) -> StormDetectionReport:
    """Detect broadcast and multicast storms in the network.

    When to use this tool:
    - When network performance suddenly degrades
    - When switches show high CPU utilization
    - When clients experience intermittent connectivity
    - During routine network health monitoring
    - After connecting new devices that might be misconfigured

    How storm detection works:
    - Analyzes traffic statistics from all switch ports
    - Calculates broadcast/multicast traffic percentages
    - Compares against configurable thresholds
    - Identifies ports that are sources or victims of storms

    Common causes of storms:
    - Spanning tree loops (most common)
    - Misconfigured network devices
    - Malfunctioning NICs
    - Malware or network attacks
    - Excessive multicast from streaming devices

    Common workflow:
    1. detect_storms() - identify storm conditions
    2. If storms found, check discover_lldp_topology() for loops
    3. Identify source port/device from the report
    4. Isolate problematic port or device
    5. Investigate root cause (STP, device config, hardware)

    What to do next:
    - If CRITICAL severity: Immediately isolate affected ports
    - If loops detected: Review STP configuration
    - If single device: Check device for issues
    - Monitor after fixes to confirm resolution

    Args:
        device_id: Optional device ID to check. If None, checks all switches.
        thresholds: Optional custom thresholds dict. Keys include:
            - broadcast_percent_warning/high/critical
            - multicast_percent_warning/high/critical
            - non_unicast_percent_warning/critical

    Returns:
        StormDetectionReport with detected storms and high-risk ports

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            # Merge custom thresholds with defaults
            active_thresholds = {**DEFAULT_THRESHOLDS}
            if thresholds:
                active_thresholds.update(thresholds)

            active_storms: list[StormEvent] = []
            high_risk_ports: list[PortTrafficMetrics] = []
            devices_analyzed = 0
            ports_analyzed = 0

            for device in devices:
                # Filter to switches only (or specific device)
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch'):
                    if not device_id:
                        continue
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                devices_analyzed += 1
                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))

                # Get port statistics
                port_table = device.get('port_table', [])

                for port in port_table:
                    port_idx = port.get('port_idx', 0)
                    if port_idx == 0:
                        continue

                    ports_analyzed += 1

                    # Extract traffic metrics
                    metrics = _extract_port_metrics(port, port_idx)

                    # Analyze for storm conditions
                    storm_event, severity = _analyze_port_for_storm(
                        metrics, dev_id, dev_name, active_thresholds
                    )

                    if storm_event:
                        active_storms.append(storm_event)

                    # Track high-risk ports (elevated but not storm-level)
                    if severity in (StormSeverity.WARNING, StormSeverity.HIGH):
                        if not storm_event:  # Not already in storms list
                            high_risk_ports.append(metrics)

                # Check if specific device was requested and found
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

            return StormDetectionReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=devices_analyzed,
                ports_analyzed=ports_analyzed,
                storms_detected=len(active_storms),
                active_storms=active_storms,
                high_risk_ports=high_risk_ports,
                network_healthy=len(active_storms) == 0,
                thresholds=active_thresholds,
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
                message=f'Error detecting storms: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _extract_port_metrics(port: dict[str, Any], port_idx: int) -> PortTrafficMetrics:
    """Extract traffic metrics from port data."""
    # Get packet counts
    rx_packets = port.get('rx_packets', 0) or 0
    tx_packets = port.get('tx_packets', 0) or 0
    rx_broadcast = port.get('rx_broadcast', 0) or 0
    tx_broadcast = port.get('tx_broadcast', 0) or 0
    rx_multicast = port.get('rx_multicast', 0) or 0
    tx_multicast = port.get('tx_multicast', 0) or 0

    total_packets = rx_packets + tx_packets
    total_broadcast = rx_broadcast + tx_broadcast
    total_multicast = rx_multicast + tx_multicast

    # Calculate percentages
    broadcast_percent = 0.0
    multicast_percent = 0.0
    if total_packets > 0:
        broadcast_percent = (total_broadcast / total_packets) * 100
        multicast_percent = (total_multicast / total_packets) * 100

    return PortTrafficMetrics(
        port_idx=port_idx,
        port_name=port.get('name', '') or f'Port {port_idx}',
        rx_packets=rx_packets,
        tx_packets=tx_packets,
        rx_broadcast=rx_broadcast,
        tx_broadcast=tx_broadcast,
        rx_multicast=rx_multicast,
        tx_multicast=tx_multicast,
        broadcast_percent=round(broadcast_percent, 2),
        multicast_percent=round(multicast_percent, 2),
    )


def _analyze_port_for_storm(
    metrics: PortTrafficMetrics,
    device_id: str,
    device_name: str,
    thresholds: dict[str, float],
) -> tuple[StormEvent | None, StormSeverity]:
    """Analyze port metrics for storm conditions."""
    # Determine severity based on thresholds
    severity = StormSeverity.INFO
    storm_type: StormType | None = None
    recommendation = ''

    # Check broadcast levels
    if metrics.broadcast_percent >= thresholds['broadcast_percent_critical']:
        severity = StormSeverity.CRITICAL
        storm_type = StormType.BROADCAST
        recommendation = (
            'CRITICAL: Isolate port immediately. Check for STP loops or malfunctioning device.'
        )
    elif metrics.broadcast_percent >= thresholds['broadcast_percent_high']:
        severity = max(severity, StormSeverity.HIGH, key=lambda x: list(StormSeverity).index(x))
        storm_type = StormType.BROADCAST
        recommendation = (
            'HIGH: Monitor closely. Investigate connected device and STP configuration.'
        )
    elif metrics.broadcast_percent >= thresholds['broadcast_percent_warning']:
        severity = max(severity, StormSeverity.WARNING, key=lambda x: list(StormSeverity).index(x))
        recommendation = 'Elevated broadcast traffic. Monitor for increases.'

    # Check multicast levels
    if metrics.multicast_percent >= thresholds['multicast_percent_critical']:
        severity = StormSeverity.CRITICAL
        storm_type = StormType.MULTICAST if not storm_type else StormType.MIXED
        recommendation = 'CRITICAL: High multicast traffic. Check for streaming loops or multicast misconfiguration.'
    elif metrics.multicast_percent >= thresholds['multicast_percent_high']:
        if severity != StormSeverity.CRITICAL:
            severity = StormSeverity.HIGH
        if storm_type == StormType.BROADCAST:
            storm_type = StormType.MIXED
        elif not storm_type:
            storm_type = StormType.MULTICAST
        recommendation = (
            recommendation
            or 'HIGH: Elevated multicast. Check multicast routing and IGMP snooping.'
        )
    elif metrics.multicast_percent >= thresholds['multicast_percent_warning']:
        severity = max(severity, StormSeverity.WARNING, key=lambda x: list(StormSeverity).index(x))

    # Check combined non-unicast
    non_unicast = metrics.broadcast_percent + metrics.multicast_percent
    if non_unicast >= thresholds['non_unicast_percent_critical']:
        severity = StormSeverity.CRITICAL
        storm_type = storm_type or StormType.MIXED
        recommendation = (
            'CRITICAL: Extremely high non-unicast traffic. Network likely severely impacted.'
        )

    # Only return storm event for HIGH or CRITICAL
    if severity in (StormSeverity.HIGH, StormSeverity.CRITICAL) and storm_type:
        return StormEvent(
            device_id=device_id,
            device_name=device_name,
            port_idx=metrics.port_idx,
            storm_type=storm_type,
            severity=severity,
            broadcast_percent=metrics.broadcast_percent,
            multicast_percent=metrics.multicast_percent,
            affected_ports=[metrics.port_idx],
            is_active=True,
            recommendation=recommendation,
        ), severity

    return None, severity
