"""Network health check diagnostic tool."""

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict, List
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


class NetworkHealthReport(BaseModel):
    """Network health assessment report."""

    timestamp: str = Field(description='When the health check was performed')
    overall_score: int = Field(description='Overall health score (0-100)', ge=0, le=100)
    status: str = Field(description='Overall network status: healthy, warning, critical')

    # Device health metrics
    total_devices: int = Field(description='Total infrastructure devices')
    devices_online: int = Field(description='Number of devices online')
    devices_offline: int = Field(description='Number of devices offline')
    devices_adopted: int = Field(description='Number of adopted devices')

    # Performance indicators
    high_cpu_devices: List[str] = Field(description='Devices with CPU > 80%')
    high_memory_devices: List[str] = Field(description='Devices with memory > 85%')
    high_load_devices: List[str] = Field(description='Devices with high load average')

    # Connectivity health
    clients_connected: int = Field(description='Total connected clients')
    uplink_issues: List[str] = Field(description='Devices with uplink problems')
    firmware_outdated: List[str] = Field(description='Devices with outdated firmware')

    # Critical issues
    critical_issues: List[str] = Field(description='Critical issues requiring attention')
    warnings: List[str] = Field(description='Warning conditions to monitor')
    recommendations: List[str] = Field(description='Recommended actions')


async def network_health_check() -> NetworkHealthReport:
    """Perform comprehensive network health assessment.

    When to use this tool:
    - Regular network maintenance and monitoring
    - Before major network changes or updates
    - When investigating network performance issues
    - As part of automated health monitoring workflows

    Common workflow:
    1. Run network_health_check() to get overall status
    2. If issues found, use specific diagnostic tools:
       - performance_analysis() for performance issues
       - security_audit() for security concerns
       - connectivity_analysis() for connectivity problems
    3. Use find_device() to investigate specific problematic devices

    What to do next:
    - If overall_score < 70: Investigate critical_issues immediately
    - If warnings present: Schedule maintenance to address them
    - If devices offline: Check physical connections and power
    - If performance issues: Run performance_analysis() for detailed metrics

    Returns:
        NetworkHealthReport with comprehensive health metrics and recommendations

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        try:
            # Get all network data
            devices_data = await client.get(client.build_path('stat/device'))
            clients_data = await client.get(client.build_path('stat/sta'))
            health_data = await client.get(client.build_path('stat/health'))

            # Analyze the data
            return _analyze_network_health(devices_data, clients_data, health_data)

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller for health check',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                    related_tools=['find_device', 'get_network_topology'],
                )
            raise ToolError(
                message=f'Error performing health check: {str(e)}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
                related_tools=['performance_analysis', 'connectivity_analysis'],
            )


def _analyze_network_health(
    devices_data: List[Dict[str, Any]],
    clients_data: List[Dict[str, Any]],
    health_data: List[Dict[str, Any]],
) -> NetworkHealthReport:
    """Analyze network data and generate health report."""
    # Initialize counters and lists
    total_devices = len(devices_data)
    devices_online = 0
    devices_offline = 0
    devices_adopted = 0

    high_cpu_devices = []
    high_memory_devices = []
    high_load_devices = []
    uplink_issues = []
    firmware_outdated = []

    critical_issues = []
    warnings = []
    recommendations = []

    # Analyze device health
    for device in devices_data:
        device_name = device.get('name', device.get('mac', 'Unknown'))

        # Connection status
        if device.get('state') == 1:  # Online
            devices_online += 1
        else:
            devices_offline += 1
            critical_issues.append(f'Device {device_name} is offline')

        # Adoption status
        if device.get('adopted', False):
            devices_adopted += 1
        else:
            warnings.append(f'Device {device_name} is not adopted')

        # Performance metrics
        system_stats = device.get('system-stats', {})
        if system_stats:
            cpu_percent = system_stats.get('cpu')
            memory_percent = system_stats.get('mem')
            load_avg = system_stats.get('loadavg_1')

            if cpu_percent and cpu_percent > 80:
                high_cpu_devices.append(f'{device_name} ({cpu_percent}%)')
                if cpu_percent > 95:
                    critical_issues.append(
                        f'Device {device_name} has critical CPU usage: {cpu_percent}%'
                    )

            if memory_percent and memory_percent > 85:
                high_memory_devices.append(f'{device_name} ({memory_percent}%)')
                if memory_percent > 95:
                    critical_issues.append(
                        f'Device {device_name} has critical memory usage: {memory_percent}%'
                    )

            if load_avg and load_avg > 2.0:
                high_load_devices.append(f'{device_name} ({load_avg})')

        # Uplink status
        uplink = device.get('uplink', {})
        if uplink and not uplink.get('up', False):
            uplink_issues.append(f'{device_name} has uplink problems')
            critical_issues.append(f'Device {device_name} uplink is down')

        # Firmware version check (simplified - in real implementation, compare with latest)
        if device.get('version', '').startswith('3.') or device.get('version', '').startswith(
            '4.'
        ):
            firmware_outdated.append(f'{device_name} (v{device.get("version", "unknown")})')
            warnings.append(f'Device {device_name} firmware may be outdated')

    # Client analysis
    clients_connected = len(clients_data)

    # Calculate overall score
    score = _calculate_health_score(
        total_devices,
        devices_online,
        devices_offline,
        len(critical_issues),
        len(warnings),
        len(high_cpu_devices),
        len(high_memory_devices),
        len(uplink_issues),
    )

    # Determine status
    if score >= 90:
        status = 'healthy'
    elif score >= 70:
        status = 'warning'
    else:
        status = 'critical'

    # Generate recommendations
    if devices_offline > 0:
        recommendations.append('Check power and network connections for offline devices')
    if len(high_cpu_devices) > 0:
        recommendations.append('Monitor high CPU devices and consider load balancing')
    if len(high_memory_devices) > 0:
        recommendations.append('Investigate memory usage on affected devices')
    if len(firmware_outdated) > 0:
        recommendations.append('Schedule firmware updates for outdated devices')
    if len(uplink_issues) > 0:
        recommendations.append('Check uplink cables and switch ports')

    return NetworkHealthReport(
        timestamp=datetime.now().isoformat(),
        overall_score=score,
        status=status,
        total_devices=total_devices,
        devices_online=devices_online,
        devices_offline=devices_offline,
        devices_adopted=devices_adopted,
        high_cpu_devices=high_cpu_devices,
        high_memory_devices=high_memory_devices,
        high_load_devices=high_load_devices,
        clients_connected=clients_connected,
        uplink_issues=uplink_issues,
        firmware_outdated=firmware_outdated,
        critical_issues=critical_issues,
        warnings=warnings,
        recommendations=recommendations,
    )


def _calculate_health_score(
    total_devices: int,
    online: int,
    offline: int,
    critical_issues: int,
    warnings: int,
    high_cpu: int,
    high_memory: int,
    uplink_issues: int,
) -> int:
    """Calculate overall network health score (0-100)."""
    if total_devices == 0:
        return 0

    # Base score from device connectivity
    connectivity_score = (online / total_devices) * 70

    # Deduct points for issues
    critical_penalty = critical_issues * 15  # 15 points per critical issue
    warning_penalty = warnings * 5  # 5 points per warning
    performance_penalty = (high_cpu + high_memory) * 3  # 3 points per performance issue
    uplink_penalty = uplink_issues * 10  # 10 points per uplink issue

    final_score = (
        connectivity_score
        - critical_penalty
        - warning_penalty
        - performance_penalty
        - uplink_penalty
    )

    # Ensure score is between 0 and 100
    return max(0, min(100, int(final_score)))
