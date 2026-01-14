"""Performance analysis diagnostic tool."""

import statistics
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


class DevicePerformance(BaseModel):
    """Performance metrics for a single device."""

    name: str = Field(description='Device name')
    mac: str = Field(description='Device MAC address')
    model: str = Field(description='Device model')
    type: str = Field(description='Device type')

    # System metrics
    cpu_percent: Optional[float] = Field(description='CPU usage percentage', ge=0, le=100)
    memory_percent: Optional[float] = Field(description='Memory usage percentage', ge=0, le=100)
    load_average: Optional[float] = Field(description='1-minute load average')
    uptime_days: Optional[float] = Field(description='Device uptime in days')

    # Network metrics
    tx_bytes: Optional[int] = Field(description='Total bytes transmitted')
    rx_bytes: Optional[int] = Field(description='Total bytes received')
    tx_packets: Optional[int] = Field(description='Total packets transmitted')
    rx_packets: Optional[int] = Field(description='Total packets received')
    tx_dropped: Optional[int] = Field(description='Dropped transmitted packets')
    rx_dropped: Optional[int] = Field(description='Dropped received packets')

    # Performance indicators
    performance_score: int = Field(description='Performance score (0-100)', ge=0, le=100)
    bottleneck_indicators: List[str] = Field(description='Performance bottleneck indicators')
    recommendations: List[str] = Field(description='Performance improvement recommendations')


class NetworkPerformanceReport(BaseModel):
    """Comprehensive network performance analysis report."""

    timestamp: str = Field(description='When the analysis was performed')

    # Overall metrics
    total_devices_analyzed: int = Field(description='Number of devices analyzed')
    average_cpu: Optional[float] = Field(description='Average CPU usage across all devices')
    average_memory: Optional[float] = Field(description='Average memory usage across all devices')
    average_load: Optional[float] = Field(description='Average load across all devices')

    # Performance categorization
    high_performers: List[DevicePerformance] = Field(
        description='Well-performing devices (score > 80)'
    )
    average_performers: List[DevicePerformance] = Field(
        description='Average performing devices (score 60-80)'
    )
    poor_performers: List[DevicePerformance] = Field(
        description='Poor performing devices (score < 60)'
    )

    # Network-wide bottlenecks
    network_bottlenecks: List[str] = Field(description='Network-wide performance bottlenecks')
    capacity_warnings: List[str] = Field(description='Devices approaching capacity limits')
    critical_alerts: List[str] = Field(description='Critical performance alerts')

    # Recommendations
    optimization_recommendations: List[str] = Field(
        description='Network optimization recommendations'
    )


async def performance_analysis() -> NetworkPerformanceReport:
    """Perform detailed network performance analysis and bottleneck detection.

    When to use this tool:
    - When network_health_check() indicates performance issues
    - During network capacity planning
    - To identify performance bottlenecks before they become critical
    - For regular performance monitoring and trending

    Common workflow:
    1. Run performance_analysis() to get detailed performance metrics
    2. Focus on poor_performers and critical_alerts first
    3. Use find_device() to get detailed information about problematic devices
    4. Use port_map() to understand physical connections of bottleneck devices
    5. Consider connectivity_analysis() if network congestion is suspected

    What to do next:
    - If poor_performers found: Investigate load balancing or hardware upgrades
    - If critical_alerts present: Take immediate action to prevent failures
    - If capacity_warnings: Plan for network expansion or optimization
    - Use network topology tools to understand traffic patterns

    Returns:
        NetworkPerformanceReport with detailed performance analysis and recommendations

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        try:
            # Get device data with detailed stats
            devices_data = await client.get(client.build_path('stat/device'))

            # Analyze performance for each device
            device_performances = []
            for device_data in devices_data:
                perf = _analyze_device_performance(device_data)
                if perf:  # Only include devices with performance data
                    device_performances.append(perf)

            # Generate comprehensive report
            return _generate_performance_report(device_performances)

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller for performance analysis',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                    related_tools=['network_health_check', 'find_device'],
                )
            raise ToolError(
                message=f'Error performing performance analysis: {str(e)}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
                related_tools=['network_health_check', 'connectivity_analysis'],
            )


def _analyze_device_performance(device_data: Dict[str, Any]) -> Optional[DevicePerformance]:
    """Analyze performance metrics for a single device."""
    # Skip if device doesn't have system stats
    system_stats = device_data.get('system-stats', {})
    if not system_stats:
        return None

    name = device_data.get('name', device_data.get('mac', 'Unknown'))
    mac = device_data.get('mac', '')
    model = device_data.get('model', '')
    device_type = device_data.get('type', 'unknown')

    # Extract system metrics
    cpu_percent = system_stats.get('cpu')
    memory_percent = system_stats.get('mem')
    load_average = system_stats.get('loadavg_1')
    uptime_seconds = device_data.get('uptime', 0)
    uptime_days = uptime_seconds / 86400 if uptime_seconds else None

    # Extract network stats
    stat = device_data.get('stat', {})
    sw_stat = stat.get('sw', {}) if stat else {}

    tx_bytes = sw_stat.get('tx_bytes')
    rx_bytes = sw_stat.get('rx_bytes')
    tx_packets = sw_stat.get('tx_packets')
    rx_packets = sw_stat.get('rx_packets')
    tx_dropped = sw_stat.get('tx_dropped')
    rx_dropped = sw_stat.get('rx_dropped')

    # Analyze performance and identify bottlenecks
    bottlenecks = []
    recommendations = []

    # CPU analysis
    if cpu_percent:
        if cpu_percent > 90:
            bottlenecks.append(f'Critical CPU usage: {cpu_percent}%')
            recommendations.append('Immediate CPU load reduction needed')
        elif cpu_percent > 80:
            bottlenecks.append(f'High CPU usage: {cpu_percent}%')
            recommendations.append('Monitor CPU usage and consider load balancing')

    # Memory analysis
    if memory_percent:
        if memory_percent > 95:
            bottlenecks.append(f'Critical memory usage: {memory_percent}%')
            recommendations.append('Memory usage critical - restart may be needed')
        elif memory_percent > 85:
            bottlenecks.append(f'High memory usage: {memory_percent}%')
            recommendations.append('Monitor memory usage patterns')

    # Load average analysis (for Unix-like systems, >1.0 per core indicates load)
    if load_average:
        if load_average > 4.0:
            bottlenecks.append(f'Very high load average: {load_average}')
            recommendations.append('System under heavy load - investigate processes')
        elif load_average > 2.0:
            bottlenecks.append(f'High load average: {load_average}')
            recommendations.append('Monitor system load trends')

    # Network error analysis
    if tx_dropped and tx_dropped > 0:
        bottlenecks.append(f'TX packet drops: {tx_dropped}')
        recommendations.append('Check for network congestion or interface issues')

    if rx_dropped and rx_dropped > 0:
        bottlenecks.append(f'RX packet drops: {rx_dropped}')
        recommendations.append('Check for buffer overruns or processing delays')

    # Calculate performance score
    score = _calculate_performance_score(
        cpu_percent, memory_percent, load_average, tx_dropped, rx_dropped
    )

    # Add general recommendations based on score
    if score < 60:
        recommendations.append('Device performance is poor - consider maintenance or replacement')
    elif score < 80:
        recommendations.append('Device performance could be improved with optimization')
    elif not recommendations:
        recommendations.append('Device is performing well')

    return DevicePerformance(
        name=name,
        mac=mac,
        model=model,
        type=device_type,
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        load_average=load_average,
        uptime_days=uptime_days,
        tx_bytes=tx_bytes,
        rx_bytes=rx_bytes,
        tx_packets=tx_packets,
        rx_packets=rx_packets,
        tx_dropped=tx_dropped,
        rx_dropped=rx_dropped,
        performance_score=score,
        bottleneck_indicators=bottlenecks,
        recommendations=recommendations,
    )


def _calculate_performance_score(
    cpu: Optional[float],
    memory: Optional[float],
    load: Optional[float],
    tx_dropped: Optional[int],
    rx_dropped: Optional[int],
) -> int:
    """Calculate device performance score (0-100)."""
    score = 100  # Start with perfect score

    # CPU penalty
    if cpu:
        if cpu > 95:
            score -= 40
        elif cpu > 80:
            score -= 25
        elif cpu > 60:
            score -= 10

    # Memory penalty
    if memory:
        if memory > 95:
            score -= 30
        elif memory > 85:
            score -= 20
        elif memory > 70:
            score -= 10

    # Load average penalty
    if load:
        if load > 4.0:
            score -= 20
        elif load > 2.0:
            score -= 10
        elif load > 1.0:
            score -= 5

    # Network drops penalty
    drops_total = (tx_dropped or 0) + (rx_dropped or 0)
    if drops_total > 1000:
        score -= 20
    elif drops_total > 100:
        score -= 10
    elif drops_total > 10:
        score -= 5

    return max(0, min(100, score))


def _generate_performance_report(
    performances: List[DevicePerformance],
) -> NetworkPerformanceReport:
    """Generate comprehensive network performance report."""
    if not performances:
        return NetworkPerformanceReport(
            timestamp=datetime.now().isoformat(),
            total_devices_analyzed=0,
            high_performers=[],
            average_performers=[],
            poor_performers=[],
            network_bottlenecks=['No devices with performance data found'],
            capacity_warnings=[],
            critical_alerts=[],
            optimization_recommendations=['Ensure devices have performance monitoring enabled'],
        )

    # Calculate averages
    cpu_values = [p.cpu_percent for p in performances if p.cpu_percent is not None]
    memory_values = [p.memory_percent for p in performances if p.memory_percent is not None]
    load_values = [p.load_average for p in performances if p.load_average is not None]

    avg_cpu = statistics.mean(cpu_values) if cpu_values else None
    avg_memory = statistics.mean(memory_values) if memory_values else None
    avg_load = statistics.mean(load_values) if load_values else None

    # Categorize by performance
    high_performers = [p for p in performances if p.performance_score > 80]
    average_performers = [p for p in performances if 60 <= p.performance_score <= 80]
    poor_performers = [p for p in performances if p.performance_score < 60]

    # Identify network-wide issues
    network_bottlenecks = []
    capacity_warnings = []
    critical_alerts = []

    if avg_cpu and avg_cpu > 70:
        network_bottlenecks.append(f'Network-wide high CPU usage: {avg_cpu:.1f}% average')

    if avg_memory and avg_memory > 80:
        network_bottlenecks.append(f'Network-wide high memory usage: {avg_memory:.1f}% average')

    # Check for devices approaching limits
    for perf in performances:
        if perf.cpu_percent and perf.cpu_percent > 85:
            capacity_warnings.append(f'{perf.name} CPU approaching limit: {perf.cpu_percent}%')

        if perf.memory_percent and perf.memory_percent > 90:
            capacity_warnings.append(
                f'{perf.name} memory approaching limit: {perf.memory_percent}%'
            )

        if perf.performance_score < 40:
            critical_alerts.append(
                f'{perf.name} performance critical (score: {perf.performance_score})'
            )

    # Generate optimization recommendations
    recommendations = []

    if len(poor_performers) > len(performances) * 0.3:  # More than 30% poor performers
        recommendations.append(
            'Consider network-wide performance optimization or hardware upgrades'
        )

    if avg_cpu and avg_cpu > 60:
        recommendations.append('Investigate CPU-intensive processes and consider load balancing')

    if avg_memory and avg_memory > 75:
        recommendations.append('Monitor memory usage trends and plan for capacity expansion')

    if len(critical_alerts) > 0:
        recommendations.append(
            'Address critical performance alerts immediately to prevent failures'
        )

    if not recommendations:
        recommendations.append('Network performance is healthy - continue regular monitoring')

    return NetworkPerformanceReport(
        timestamp=datetime.now().isoformat(),
        total_devices_analyzed=len(performances),
        average_cpu=avg_cpu,
        average_memory=avg_memory,
        average_load=avg_load,
        high_performers=high_performers,
        average_performers=average_performers,
        poor_performers=poor_performers,
        network_bottlenecks=network_bottlenecks,
        capacity_warnings=capacity_warnings,
        critical_alerts=critical_alerts,
        optimization_recommendations=recommendations,
    )
