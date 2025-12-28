#!/usr/bin/env python3
"""
Capacity Planner for UniFi Networks.

Provides proactive capacity planning and resource monitoring:
- Port utilization trending (daily/weekly/monthly)
- Predict port exhaustion dates
- PoE budget utilization trends
- Switch port density recommendations
- Uplink saturation analysis
- Growth projections and planning
"""

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CapacityStatus(Enum):
    """Capacity status levels."""

    HEALTHY = "healthy"  # <60% utilization
    MONITOR = "monitor"  # 60-75% utilization
    WARNING = "warning"  # 75-85% utilization
    CRITICAL = "critical"  # 85-95% utilization
    EXHAUSTED = "exhausted"  # >95% utilization


class ResourceType(Enum):
    """Types of network resources."""

    SWITCH_PORTS = "switch_ports"
    POE_BUDGET = "poe_budget"
    UPLINK_BANDWIDTH = "uplink_bandwidth"
    MAC_TABLE = "mac_table"
    CPU = "cpu"
    MEMORY = "memory"


@dataclass
class UtilizationSample:
    """A single utilization measurement."""

    timestamp: datetime
    value: float  # Percentage 0-100
    absolute_used: int = 0
    absolute_total: int = 0


@dataclass
class UtilizationTrend:
    """Utilization trend analysis for a resource."""

    resource_type: ResourceType
    device_id: str
    device_name: str

    # Current state
    current_utilization: float = 0.0
    current_used: int = 0
    current_total: int = 0

    # Historical data
    samples: List[UtilizationSample] = field(default_factory=list)

    # Trend analysis
    trend_direction: str = "stable"  # increasing, decreasing, stable
    trend_rate_per_day: float = 0.0  # Change in percentage points per day
    avg_utilization_7d: float = 0.0
    avg_utilization_30d: float = 0.0
    peak_utilization_7d: float = 0.0
    peak_utilization_30d: float = 0.0

    # Projections
    days_to_warning: Optional[int] = None  # Days until 75%
    days_to_critical: Optional[int] = None  # Days until 85%
    days_to_exhaustion: Optional[int] = None  # Days until 95%
    projected_date_warning: Optional[datetime] = None
    projected_date_critical: Optional[datetime] = None
    projected_date_exhaustion: Optional[datetime] = None

    @property
    def status(self) -> CapacityStatus:
        """Get current capacity status."""
        if self.current_utilization >= 95:
            return CapacityStatus.EXHAUSTED
        elif self.current_utilization >= 85:
            return CapacityStatus.CRITICAL
        elif self.current_utilization >= 75:
            return CapacityStatus.WARNING
        elif self.current_utilization >= 60:
            return CapacityStatus.MONITOR
        return CapacityStatus.HEALTHY

    def add_sample(self, utilization: float, used: int, total: int) -> None:
        """Add a utilization sample."""
        self.samples.append(UtilizationSample(
            timestamp=datetime.now(),
            value=utilization,
            absolute_used=used,
            absolute_total=total,
        ))

        # Keep only 90 days of history
        cutoff = datetime.now() - timedelta(days=90)
        self.samples = [s for s in self.samples if s.timestamp > cutoff]

    def calculate_trends(self) -> None:
        """Calculate trend analysis from samples."""
        if len(self.samples) < 2:
            return

        now = datetime.now()

        # Get samples for different periods
        samples_7d = [s for s in self.samples if s.timestamp > now - timedelta(days=7)]
        samples_30d = [s for s in self.samples if s.timestamp > now - timedelta(days=30)]

        # Calculate averages and peaks
        if samples_7d:
            values_7d = [s.value for s in samples_7d]
            self.avg_utilization_7d = statistics.mean(values_7d)
            self.peak_utilization_7d = max(values_7d)

        if samples_30d:
            values_30d = [s.value for s in samples_30d]
            self.avg_utilization_30d = statistics.mean(values_30d)
            self.peak_utilization_30d = max(values_30d)

        # Calculate trend (linear regression simplified)
        if len(samples_7d) >= 2:
            # Get oldest and newest in period
            sorted_samples = sorted(samples_7d, key=lambda s: s.timestamp)
            oldest = sorted_samples[0]
            newest = sorted_samples[-1]

            time_diff_days = (newest.timestamp - oldest.timestamp).total_seconds() / 86400
            if time_diff_days > 0:
                value_diff = newest.value - oldest.value
                self.trend_rate_per_day = value_diff / time_diff_days

                if self.trend_rate_per_day > 0.5:
                    self.trend_direction = "increasing"
                elif self.trend_rate_per_day < -0.5:
                    self.trend_direction = "decreasing"
                else:
                    self.trend_direction = "stable"

        # Calculate projections if trending up
        if self.trend_rate_per_day > 0:
            remaining_to_warning = max(0, 75 - self.current_utilization)
            remaining_to_critical = max(0, 85 - self.current_utilization)
            remaining_to_exhaustion = max(0, 95 - self.current_utilization)

            if remaining_to_warning > 0:
                self.days_to_warning = int(remaining_to_warning / self.trend_rate_per_day)
                self.projected_date_warning = now + timedelta(days=self.days_to_warning)

            if remaining_to_critical > 0:
                self.days_to_critical = int(remaining_to_critical / self.trend_rate_per_day)
                self.projected_date_critical = now + timedelta(days=self.days_to_critical)

            if remaining_to_exhaustion > 0:
                self.days_to_exhaustion = int(remaining_to_exhaustion / self.trend_rate_per_day)
                self.projected_date_exhaustion = now + timedelta(days=self.days_to_exhaustion)


@dataclass
class DeviceCapacity:
    """Capacity information for a single device."""

    device_id: str
    device_name: str
    device_model: str
    device_type: str

    # Port capacity
    total_ports: int = 0
    used_ports: int = 0
    available_ports: int = 0
    port_utilization: float = 0.0

    # PoE capacity (if applicable)
    poe_budget_watts: float = 0.0
    poe_consumption_watts: float = 0.0
    poe_utilization: float = 0.0
    poe_available_watts: float = 0.0

    # Uplink capacity
    uplink_count: int = 0
    uplink_speed_mbps: int = 0
    uplink_utilization: float = 0.0

    # System resources
    cpu_utilization: float = 0.0
    memory_utilization: float = 0.0

    # Trends
    port_trend: Optional[UtilizationTrend] = None
    poe_trend: Optional[UtilizationTrend] = None
    uplink_trend: Optional[UtilizationTrend] = None

    @property
    def port_status(self) -> CapacityStatus:
        """Get port capacity status."""
        if self.port_utilization >= 95:
            return CapacityStatus.EXHAUSTED
        elif self.port_utilization >= 85:
            return CapacityStatus.CRITICAL
        elif self.port_utilization >= 75:
            return CapacityStatus.WARNING
        elif self.port_utilization >= 60:
            return CapacityStatus.MONITOR
        return CapacityStatus.HEALTHY

    @property
    def poe_status(self) -> CapacityStatus:
        """Get PoE capacity status."""
        if self.poe_budget_watts == 0:
            return CapacityStatus.HEALTHY
        if self.poe_utilization >= 95:
            return CapacityStatus.EXHAUSTED
        elif self.poe_utilization >= 85:
            return CapacityStatus.CRITICAL
        elif self.poe_utilization >= 75:
            return CapacityStatus.WARNING
        elif self.poe_utilization >= 60:
            return CapacityStatus.MONITOR
        return CapacityStatus.HEALTHY


@dataclass
class CapacityReport:
    """Complete capacity planning report."""

    timestamp: datetime = field(default_factory=datetime.now)

    # Device capacities
    devices: List[DeviceCapacity] = field(default_factory=list)

    # Network-wide summaries
    total_ports: int = 0
    used_ports: int = 0
    available_ports: int = 0
    network_port_utilization: float = 0.0

    total_poe_budget_watts: float = 0.0
    total_poe_consumption_watts: float = 0.0
    network_poe_utilization: float = 0.0

    # Alerts and recommendations
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    # Devices needing attention
    devices_critical: List[str] = field(default_factory=list)
    devices_warning: List[str] = field(default_factory=list)

    def add_alert(
        self,
        severity: str,
        resource_type: ResourceType,
        message: str,
        device_name: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a capacity alert."""
        self.alerts.append({
            "severity": severity,
            "resource_type": resource_type.value,
            "message": message,
            "device_name": device_name,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })

    def add_recommendation(
        self,
        priority: str,
        category: str,
        message: str,
        device_name: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a capacity recommendation."""
        self.recommendations.append({
            "priority": priority,
            "category": category,
            "message": message,
            "device_name": device_name,
            "details": details or {},
        })

    def summary(self) -> Dict[str, Any]:
        """Get report summary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "devices_analyzed": len(self.devices),
            "network_port_utilization": round(self.network_port_utilization, 1),
            "total_ports": self.total_ports,
            "available_ports": self.available_ports,
            "network_poe_utilization": round(self.network_poe_utilization, 1),
            "devices_critical": len(self.devices_critical),
            "devices_warning": len(self.devices_warning),
            "total_alerts": len(self.alerts),
            "total_recommendations": len(self.recommendations),
        }


class CapacityPlanner:
    """
    Network capacity planning and forecasting for UniFi networks.

    Provides:
    - Current capacity assessment
    - Trend analysis and forecasting
    - Proactive alerting before exhaustion
    - Capacity planning recommendations
    """

    # Thresholds
    PORT_UTIL_WARNING = 75
    PORT_UTIL_CRITICAL = 85
    POE_UTIL_WARNING = 75
    POE_UTIL_CRITICAL = 85
    UPLINK_UTIL_WARNING = 70
    UPLINK_UTIL_CRITICAL = 85

    def __init__(self, api_client, site: str = "default"):
        """Initialize Capacity Planner."""
        self.api_client = api_client
        self.site = site

        # Historical data storage
        self._historical_data: Dict[str, UtilizationTrend] = {}
        self._device_cache: Dict[str, Dict[str, Any]] = {}

    def _get_devices(self) -> List[Dict[str, Any]]:
        """Get all network devices."""
        try:
            result = self.api_client.get_devices(self.site)
            if result and "data" in result:
                for device in result["data"]:
                    self._device_cache[device["_id"]] = device
                return result["data"]
            return []
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []

    def _analyze_device_capacity(self, device: Dict[str, Any]) -> DeviceCapacity:
        """Analyze capacity for a single device."""
        device_id = device["_id"]
        device_name = device.get("name", device.get("model", "Unknown"))
        device_model = device.get("model", "")
        device_type = device.get("type", "")

        capacity = DeviceCapacity(
            device_id=device_id,
            device_name=device_name,
            device_model=device_model,
            device_type=device_type,
        )

        # Port analysis
        port_table = device.get("port_table", [])
        capacity.total_ports = len(port_table)
        capacity.used_ports = sum(1 for p in port_table if p.get("up", False))
        capacity.available_ports = capacity.total_ports - capacity.used_ports

        if capacity.total_ports > 0:
            capacity.port_utilization = (capacity.used_ports / capacity.total_ports) * 100

        # PoE analysis
        sys_stats = device.get("sys_stats", {})
        capacity.poe_consumption_watts = sys_stats.get("poe_consumption", 0)

        # Get PoE budget from device capabilities
        poe_budget = device.get("poe_budget", 0)
        if poe_budget == 0:
            # Try to get from sys_stats
            poe_budget = sys_stats.get("poe_power_budget", 0)

        capacity.poe_budget_watts = poe_budget
        capacity.poe_available_watts = poe_budget - capacity.poe_consumption_watts

        if capacity.poe_budget_watts > 0:
            capacity.poe_utilization = (
                capacity.poe_consumption_watts / capacity.poe_budget_watts
            ) * 100

        # Uplink analysis
        uplink_ports = [p for p in port_table if p.get("is_uplink", False)]
        capacity.uplink_count = len(uplink_ports)

        if uplink_ports:
            # Get max uplink speed
            capacity.uplink_speed_mbps = max(
                p.get("speed", 0) for p in uplink_ports
            )

            # Calculate uplink utilization (simplified)
            total_uplink_bytes = sum(
                p.get("rx_bytes", 0) + p.get("tx_bytes", 0) for p in uplink_ports
            )
            # This is cumulative, so we'd need delta for accurate rate
            # For now, estimate from recent traffic

        # System resources
        system_stats = device.get("system-stats", {})
        capacity.cpu_utilization = system_stats.get("cpu", 0)
        capacity.memory_utilization = system_stats.get("mem", 0)

        # Update historical trends
        self._update_trends(capacity)

        return capacity

    def _update_trends(self, capacity: DeviceCapacity) -> None:
        """Update historical trends for a device."""
        device_key = capacity.device_id

        # Port utilization trend
        port_trend_key = f"{device_key}:ports"
        if port_trend_key not in self._historical_data:
            self._historical_data[port_trend_key] = UtilizationTrend(
                resource_type=ResourceType.SWITCH_PORTS,
                device_id=capacity.device_id,
                device_name=capacity.device_name,
            )

        port_trend = self._historical_data[port_trend_key]
        port_trend.current_utilization = capacity.port_utilization
        port_trend.current_used = capacity.used_ports
        port_trend.current_total = capacity.total_ports
        port_trend.add_sample(
            capacity.port_utilization,
            capacity.used_ports,
            capacity.total_ports,
        )
        port_trend.calculate_trends()
        capacity.port_trend = port_trend

        # PoE utilization trend (if applicable)
        if capacity.poe_budget_watts > 0:
            poe_trend_key = f"{device_key}:poe"
            if poe_trend_key not in self._historical_data:
                self._historical_data[poe_trend_key] = UtilizationTrend(
                    resource_type=ResourceType.POE_BUDGET,
                    device_id=capacity.device_id,
                    device_name=capacity.device_name,
                )

            poe_trend = self._historical_data[poe_trend_key]
            poe_trend.current_utilization = capacity.poe_utilization
            poe_trend.current_used = int(capacity.poe_consumption_watts)
            poe_trend.current_total = int(capacity.poe_budget_watts)
            poe_trend.add_sample(
                capacity.poe_utilization,
                int(capacity.poe_consumption_watts),
                int(capacity.poe_budget_watts),
            )
            poe_trend.calculate_trends()
            capacity.poe_trend = poe_trend

    def analyze(self) -> CapacityReport:
        """
        Perform comprehensive capacity analysis.

        Returns:
            CapacityReport with analysis results
        """
        logger.info("Starting capacity analysis...")
        report = CapacityReport()

        devices = self._get_devices()

        for device in devices:
            device_type = device.get("type", "")
            if device_type not in ["usw", "udm", "ugw", "udmpro"]:
                continue

            capacity = self._analyze_device_capacity(device)
            report.devices.append(capacity)

            # Aggregate totals
            report.total_ports += capacity.total_ports
            report.used_ports += capacity.used_ports
            report.available_ports += capacity.available_ports
            report.total_poe_budget_watts += capacity.poe_budget_watts
            report.total_poe_consumption_watts += capacity.poe_consumption_watts

            # Track devices needing attention
            if capacity.port_status == CapacityStatus.CRITICAL:
                report.devices_critical.append(capacity.device_name)
            elif capacity.port_status == CapacityStatus.WARNING:
                report.devices_warning.append(capacity.device_name)

            if capacity.poe_status == CapacityStatus.CRITICAL:
                if capacity.device_name not in report.devices_critical:
                    report.devices_critical.append(capacity.device_name)
            elif capacity.poe_status == CapacityStatus.WARNING:
                if capacity.device_name not in report.devices_warning:
                    report.devices_warning.append(capacity.device_name)

            # Generate alerts
            self._generate_alerts(report, capacity)

        # Calculate network-wide utilization
        if report.total_ports > 0:
            report.network_port_utilization = (
                report.used_ports / report.total_ports
            ) * 100

        if report.total_poe_budget_watts > 0:
            report.network_poe_utilization = (
                report.total_poe_consumption_watts / report.total_poe_budget_watts
            ) * 100

        # Generate recommendations
        self._generate_recommendations(report)

        logger.info(
            f"Capacity analysis complete: {len(report.devices)} devices, "
            f"port utilization: {report.network_port_utilization:.1f}%, "
            f"PoE utilization: {report.network_poe_utilization:.1f}%"
        )

        return report

    def _generate_alerts(self, report: CapacityReport, capacity: DeviceCapacity) -> None:
        """Generate alerts for capacity issues."""

        # Port capacity alerts
        if capacity.port_status == CapacityStatus.EXHAUSTED:
            report.add_alert(
                "critical",
                ResourceType.SWITCH_PORTS,
                f"Switch ports exhausted on {capacity.device_name} "
                f"({capacity.used_ports}/{capacity.total_ports})",
                capacity.device_name,
                {"used": capacity.used_ports, "total": capacity.total_ports},
            )
        elif capacity.port_status == CapacityStatus.CRITICAL:
            report.add_alert(
                "high",
                ResourceType.SWITCH_PORTS,
                f"Switch ports critical on {capacity.device_name}: "
                f"{capacity.port_utilization:.0f}% "
                f"({capacity.available_ports} available)",
                capacity.device_name,
                {
                    "utilization": capacity.port_utilization,
                    "available": capacity.available_ports,
                },
            )
        elif capacity.port_status == CapacityStatus.WARNING:
            report.add_alert(
                "warning",
                ResourceType.SWITCH_PORTS,
                f"Switch ports warning on {capacity.device_name}: "
                f"{capacity.port_utilization:.0f}% utilization",
                capacity.device_name,
                {"utilization": capacity.port_utilization},
            )

        # PoE capacity alerts
        if capacity.poe_status == CapacityStatus.CRITICAL:
            report.add_alert(
                "high",
                ResourceType.POE_BUDGET,
                f"PoE budget critical on {capacity.device_name}: "
                f"{capacity.poe_utilization:.0f}% "
                f"({capacity.poe_available_watts:.0f}W available)",
                capacity.device_name,
                {
                    "utilization": capacity.poe_utilization,
                    "available_watts": capacity.poe_available_watts,
                },
            )
        elif capacity.poe_status == CapacityStatus.WARNING:
            report.add_alert(
                "warning",
                ResourceType.POE_BUDGET,
                f"PoE budget warning on {capacity.device_name}: "
                f"{capacity.poe_utilization:.0f}% utilization",
                capacity.device_name,
                {"utilization": capacity.poe_utilization},
            )

        # Trend-based alerts (proactive)
        if capacity.port_trend and capacity.port_trend.days_to_critical:
            if capacity.port_trend.days_to_critical <= 30:
                report.add_alert(
                    "warning",
                    ResourceType.SWITCH_PORTS,
                    f"Port capacity on {capacity.device_name} projected to reach "
                    f"critical level in {capacity.port_trend.days_to_critical} days",
                    capacity.device_name,
                    {
                        "days_to_critical": capacity.port_trend.days_to_critical,
                        "trend_rate": capacity.port_trend.trend_rate_per_day,
                    },
                )

    def _generate_recommendations(self, report: CapacityReport) -> None:
        """Generate capacity planning recommendations."""

        # Devices at critical capacity
        for device in report.devices:
            if device.port_status in [CapacityStatus.CRITICAL, CapacityStatus.EXHAUSTED]:
                report.add_recommendation(
                    "high",
                    "expansion",
                    f"Consider adding switch capacity near {device.device_name} "
                    f"({device.available_ports} ports available)",
                    device.device_name,
                    {"available_ports": device.available_ports},
                )

            if device.poe_status in [CapacityStatus.CRITICAL, CapacityStatus.EXHAUSTED]:
                report.add_recommendation(
                    "high",
                    "expansion",
                    f"PoE budget insufficient on {device.device_name}. "
                    f"Consider adding PoE switch or redistributing devices "
                    f"({device.poe_available_watts:.0f}W available)",
                    device.device_name,
                    {"available_watts": device.poe_available_watts},
                )

        # Network-wide recommendations
        if report.network_port_utilization > 70:
            report.add_recommendation(
                "medium",
                "planning",
                f"Network-wide port utilization at {report.network_port_utilization:.0f}%. "
                f"Plan for expansion ({report.available_ports} ports available across network)",
                "",
                {
                    "utilization": report.network_port_utilization,
                    "available": report.available_ports,
                },
            )

        # Look for optimization opportunities
        low_util_devices = [
            d for d in report.devices if d.port_utilization < 30 and d.total_ports > 8
        ]
        if low_util_devices:
            report.add_recommendation(
                "low",
                "optimization",
                f"{len(low_util_devices)} switches have <30% port utilization. "
                "Consider consolidation opportunities",
                "",
                {"devices": [d.device_name for d in low_util_devices]},
            )

    def generate_report(self, result: CapacityReport) -> str:
        """Generate human-readable capacity report."""
        report = [
            "# Network Capacity Planning Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Executive Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Devices Analyzed | {len(result.devices)} |",
            f"| Network Port Utilization | {result.network_port_utilization:.1f}% |",
            f"| Total Ports | {result.total_ports} |",
            f"| Available Ports | {result.available_ports} |",
            f"| Network PoE Utilization | {result.network_poe_utilization:.1f}% |",
            f"| Devices Critical | {len(result.devices_critical)} |",
            f"| Devices Warning | {len(result.devices_warning)} |",
            "",
        ]

        # Status summary
        status_emoji = {
            CapacityStatus.HEALTHY: "🟢",
            CapacityStatus.MONITOR: "🔵",
            CapacityStatus.WARNING: "🟡",
            CapacityStatus.CRITICAL: "🟠",
            CapacityStatus.EXHAUSTED: "🔴",
        }

        # Overall status
        if result.devices_critical:
            report.append(f"## 🔴 CRITICAL: {len(result.devices_critical)} devices need immediate attention")
            report.append("")
        elif result.devices_warning:
            report.append(f"## 🟡 WARNING: {len(result.devices_warning)} devices approaching capacity limits")
            report.append("")
        else:
            report.append("## 🟢 All devices within healthy capacity limits")
            report.append("")

        # Device capacity table
        report.extend([
            "## Device Capacity Status",
            "",
            "| Device | Model | Ports | Port % | PoE | PoE % | Status |",
            "|--------|-------|-------|--------|-----|-------|--------|",
        ])

        for device in sorted(result.devices, key=lambda d: d.port_utilization, reverse=True):
            port_status = status_emoji.get(device.port_status, "⚪")
            poe_info = f"{device.poe_consumption_watts:.0f}W/{device.poe_budget_watts:.0f}W" if device.poe_budget_watts else "N/A"
            poe_pct = f"{device.poe_utilization:.0f}%" if device.poe_budget_watts else "N/A"

            report.append(
                f"| {device.device_name} | {device.device_model} | "
                f"{device.used_ports}/{device.total_ports} | {device.port_utilization:.0f}% | "
                f"{poe_info} | {poe_pct} | {port_status} |"
            )
        report.append("")

        # Trend projections
        devices_with_projections = [
            d for d in result.devices
            if d.port_trend and d.port_trend.days_to_critical and d.port_trend.days_to_critical <= 90
        ]

        if devices_with_projections:
            report.extend([
                "## Capacity Projections (Next 90 Days)",
                "",
                "| Device | Current | Trend | Days to Critical | Projected Date |",
                "|--------|---------|-------|------------------|----------------|",
            ])

            for device in devices_with_projections:
                trend = device.port_trend
                trend_arrow = "📈" if trend.trend_direction == "increasing" else "📉" if trend.trend_direction == "decreasing" else "➡️"
                proj_date = trend.projected_date_critical.strftime("%Y-%m-%d") if trend.projected_date_critical else "N/A"

                report.append(
                    f"| {device.device_name} | {trend.current_utilization:.0f}% | "
                    f"{trend_arrow} {trend.trend_rate_per_day:+.1f}%/day | "
                    f"{trend.days_to_critical} | {proj_date} |"
                )
            report.append("")

        # Alerts
        if result.alerts:
            report.extend(["## Alerts", ""])

            for alert in sorted(result.alerts, key=lambda a: {"critical": 0, "high": 1, "warning": 2, "info": 3}.get(a["severity"], 4)):
                severity_emoji = {"critical": "🔴", "high": "🟠", "warning": "🟡", "info": "ℹ️"}.get(
                    alert["severity"], "⚪"
                )
                report.append(f"- {severity_emoji} **{alert['severity'].upper()}**: {alert['message']}")
            report.append("")

        # Recommendations
        if result.recommendations:
            report.extend(["## Recommendations", ""])

            for rec in sorted(result.recommendations, key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r["priority"], 3)):
                priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(rec["priority"], "⚪")
                report.append(f"- {priority_emoji} **{rec['category'].upper()}**: {rec['message']}")
            report.append("")

        return "\n".join(report)
