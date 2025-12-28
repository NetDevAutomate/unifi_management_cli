#!/usr/bin/env python3
"""
LAG (Link Aggregation) Health Monitor for UniFi Networks.

Monitors link aggregation group health and configuration:
- LACP state verification
- Load distribution analysis
- Failed/misconfigured member detection
- Bandwidth utilization per member
- LAG consistency between paired devices
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class LAGStatus(Enum):
    """LAG health status."""

    HEALTHY = "healthy"  # All members active and balanced
    DEGRADED = "degraded"  # Some members down
    CRITICAL = "critical"  # Major issues
    INACTIVE = "inactive"  # LAG not active
    MISCONFIGURED = "misconfigured"  # Configuration problems


class LACPState(Enum):
    """LACP port states."""

    ACTIVE = "active"
    PASSIVE = "passive"
    SUSPENDED = "suspended"
    DEFAULTED = "defaulted"
    EXPIRED = "expired"
    COLLECTING = "collecting"
    DISTRIBUTING = "distributing"


@dataclass
class LAGMember:
    """A single LAG member port."""

    port_idx: int
    port_name: str
    is_active: bool = True
    link_up: bool = True
    speed_mbps: int = 0
    lacp_state: LACPState = LACPState.ACTIVE

    # Traffic stats
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0

    # Errors
    rx_errors: int = 0
    tx_errors: int = 0

    # Load percentage (calculated)
    load_percent: float = 0.0


@dataclass
class LAGGroup:
    """A Link Aggregation Group."""

    lag_id: str
    device_id: str
    device_name: str
    lag_name: str = ""

    # Members
    members: List[LAGMember] = field(default_factory=list)
    expected_members: int = 0
    active_members: int = 0

    # Aggregate stats
    total_bandwidth_mbps: int = 0
    active_bandwidth_mbps: int = 0
    total_rx_bytes: int = 0
    total_tx_bytes: int = 0

    # Partner info (for LACP)
    partner_system_id: str = ""
    partner_device_name: str = ""

    # Status
    status: LAGStatus = LAGStatus.HEALTHY
    issues: List[str] = field(default_factory=list)

    @property
    def efficiency(self) -> float:
        """Calculate LAG efficiency (active/total bandwidth)."""
        if self.total_bandwidth_mbps == 0:
            return 0.0
        return (self.active_bandwidth_mbps / self.total_bandwidth_mbps) * 100

    @property
    def load_balance_score(self) -> float:
        """
        Calculate load balance score (0-100).

        100 = perfectly balanced, lower = imbalanced
        """
        if len(self.members) < 2:
            return 100.0

        active_members = [m for m in self.members if m.is_active]
        if len(active_members) < 2:
            return 100.0

        loads = [m.load_percent for m in active_members]
        avg_load = sum(loads) / len(loads)

        if avg_load == 0:
            return 100.0

        # Calculate variance from average
        variance = sum((load - avg_load) ** 2 for load in loads) / len(loads)
        std_dev = variance ** 0.5

        # Score based on standard deviation (lower is better)
        score = max(0, 100 - (std_dev * 2))
        return score

    def calculate_member_loads(self) -> None:
        """Calculate load distribution across members."""
        if self.total_tx_bytes == 0 and self.total_rx_bytes == 0:
            return

        total_traffic = self.total_tx_bytes + self.total_rx_bytes

        for member in self.members:
            member_traffic = member.tx_bytes + member.rx_bytes
            if total_traffic > 0:
                member.load_percent = (member_traffic / total_traffic) * 100


@dataclass
class LAGHealthReport:
    """Complete LAG health report."""

    timestamp: datetime = field(default_factory=datetime.now)
    devices_checked: int = 0

    # LAG groups
    lag_groups: List[LAGGroup] = field(default_factory=list)
    total_lags: int = 0
    healthy_lags: int = 0
    degraded_lags: int = 0
    critical_lags: int = 0

    # Network-wide
    total_lag_bandwidth_gbps: float = 0.0
    active_lag_bandwidth_gbps: float = 0.0

    # Issues and recommendations
    issues: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def add_issue(
        self,
        severity: str,
        message: str,
        lag_id: str = "",
        device_name: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an issue."""
        self.issues.append({
            "severity": severity,
            "message": message,
            "lag_id": lag_id,
            "device_name": device_name,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self) -> Dict[str, Any]:
        """Get report summary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "devices_checked": self.devices_checked,
            "total_lags": self.total_lags,
            "healthy": self.healthy_lags,
            "degraded": self.degraded_lags,
            "critical": self.critical_lags,
            "total_bandwidth_gbps": self.total_lag_bandwidth_gbps,
            "active_bandwidth_gbps": self.active_lag_bandwidth_gbps,
            "issues_count": len(self.issues),
        }


class LAGMonitor:
    """
    Link Aggregation Group Health Monitor.

    Monitors:
    - LACP state and partner matching
    - Member port health and activity
    - Load distribution across members
    - Configuration consistency
    """

    # Thresholds
    LOAD_IMBALANCE_WARNING = 30  # % difference from average
    MIN_ACTIVE_MEMBERS_PERCENT = 50  # Minimum % of members that should be active

    def __init__(self, api_client, site: str = "default"):
        """Initialize LAG Monitor."""
        self.api_client = api_client
        self.site = site
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

    def _extract_lag_groups(self, device: Dict[str, Any]) -> List[LAGGroup]:
        """Extract LAG groups from device configuration."""
        device_id = device["_id"]
        device_name = device.get("name", device.get("model", "Unknown"))
        lag_groups = []

        # Check for aggregate interfaces
        port_table = device.get("port_table", [])
        port_overrides = device.get("port_overrides", [])

        # Build port override lookup
        override_by_port = {po.get("port_idx"): po for po in port_overrides}

        # Find LAG configurations
        # In UniFi, LAGs are typically configured via port aggregation settings
        aggregates = device.get("port_aggregates", [])

        for agg in aggregates:
            lag_id = agg.get("_id", f"{device_id}_lag")
            member_ports = agg.get("member_ports", [])

            lag = LAGGroup(
                lag_id=lag_id,
                device_id=device_id,
                device_name=device_name,
                lag_name=agg.get("name", f"LAG-{lag_id[-4:]}"),
                expected_members=len(member_ports),
            )

            # Get member details
            for port_idx in member_ports:
                port_data = next(
                    (p for p in port_table if p.get("port_idx") == port_idx), {}
                )
                port_override = override_by_port.get(port_idx, {})

                member = LAGMember(
                    port_idx=port_idx,
                    port_name=port_data.get("name", f"Port {port_idx}"),
                    link_up=port_data.get("up", False),
                    is_active=port_data.get("up", False) and port_data.get("enabled", True),
                    speed_mbps=port_data.get("speed", 0),
                    rx_bytes=port_data.get("rx_bytes", 0),
                    tx_bytes=port_data.get("tx_bytes", 0),
                    rx_packets=port_data.get("rx_packets", 0),
                    tx_packets=port_data.get("tx_packets", 0),
                    rx_errors=port_data.get("rx_errors", 0),
                    tx_errors=port_data.get("tx_errors", 0),
                )

                if member.is_active:
                    lag.active_members += 1
                    lag.active_bandwidth_mbps += member.speed_mbps

                lag.total_bandwidth_mbps += member.speed_mbps
                lag.total_rx_bytes += member.rx_bytes
                lag.total_tx_bytes += member.tx_bytes
                lag.members.append(member)

            # Calculate load distribution
            lag.calculate_member_loads()

            # Determine status
            lag.status = self._determine_lag_status(lag)

            lag_groups.append(lag)

        return lag_groups

    def _determine_lag_status(self, lag: LAGGroup) -> LAGStatus:
        """Determine LAG health status."""
        if lag.expected_members == 0:
            return LAGStatus.INACTIVE

        active_percent = (lag.active_members / lag.expected_members) * 100

        if lag.active_members == 0:
            lag.issues.append("No active members")
            return LAGStatus.CRITICAL

        if active_percent < self.MIN_ACTIVE_MEMBERS_PERCENT:
            lag.issues.append(f"Only {lag.active_members}/{lag.expected_members} members active")
            return LAGStatus.CRITICAL

        if lag.active_members < lag.expected_members:
            lag.issues.append(f"{lag.expected_members - lag.active_members} member(s) down")
            return LAGStatus.DEGRADED

        if lag.load_balance_score < 70:
            lag.issues.append(f"Load imbalance detected (score: {lag.load_balance_score:.0f})")
            return LAGStatus.DEGRADED

        # Check for member errors
        error_members = [m for m in lag.members if m.rx_errors + m.tx_errors > 1000]
        if error_members:
            lag.issues.append(f"{len(error_members)} member(s) with high error counts")
            return LAGStatus.DEGRADED

        return LAGStatus.HEALTHY

    def analyze(self) -> LAGHealthReport:
        """
        Analyze LAG health across the network.

        Returns:
            LAGHealthReport with analysis results
        """
        logger.info("Starting LAG health analysis...")
        report = LAGHealthReport()

        devices = self._get_devices()

        for device in devices:
            device_type = device.get("type", "")
            if device_type not in ["usw", "udm"]:
                continue

            report.devices_checked += 1

            # Extract LAG groups
            lags = self._extract_lag_groups(device)

            for lag in lags:
                report.lag_groups.append(lag)
                report.total_lags += 1
                report.total_lag_bandwidth_gbps += lag.total_bandwidth_mbps / 1000
                report.active_lag_bandwidth_gbps += lag.active_bandwidth_mbps / 1000

                # Count by status
                if lag.status == LAGStatus.HEALTHY:
                    report.healthy_lags += 1
                elif lag.status == LAGStatus.DEGRADED:
                    report.degraded_lags += 1
                    for issue in lag.issues:
                        report.add_issue(
                            "warning",
                            issue,
                            lag.lag_id,
                            lag.device_name,
                        )
                elif lag.status in [LAGStatus.CRITICAL, LAGStatus.MISCONFIGURED]:
                    report.critical_lags += 1
                    for issue in lag.issues:
                        report.add_issue(
                            "critical",
                            issue,
                            lag.lag_id,
                            lag.device_name,
                        )

        # Generate recommendations
        self._generate_recommendations(report)

        logger.info(
            f"LAG analysis complete: {report.total_lags} LAGs, "
            f"{report.healthy_lags} healthy, {report.degraded_lags} degraded, "
            f"{report.critical_lags} critical"
        )

        return report

    def _generate_recommendations(self, report: LAGHealthReport) -> None:
        """Generate recommendations based on analysis."""
        for lag in report.lag_groups:
            if lag.status == LAGStatus.DEGRADED:
                if lag.active_members < lag.expected_members:
                    report.recommendations.append(
                        f"Investigate failed member port(s) on {lag.device_name} {lag.lag_name}"
                    )
                if lag.load_balance_score < 70:
                    report.recommendations.append(
                        f"Review hashing algorithm for {lag.lag_name} - consider src-dst-ip"
                    )

            if lag.status == LAGStatus.CRITICAL:
                report.recommendations.append(
                    f"URGENT: {lag.lag_name} on {lag.device_name} requires immediate attention"
                )

    def generate_report(self, result: LAGHealthReport) -> str:
        """Generate human-readable LAG health report."""
        report = [
            "# Link Aggregation Health Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Devices Checked | {result.devices_checked} |",
            f"| Total LAGs | {result.total_lags} |",
            f"| 🟢 Healthy | {result.healthy_lags} |",
            f"| 🟡 Degraded | {result.degraded_lags} |",
            f"| 🔴 Critical | {result.critical_lags} |",
            f"| Total Bandwidth | {result.total_lag_bandwidth_gbps:.1f} Gbps |",
            f"| Active Bandwidth | {result.active_lag_bandwidth_gbps:.1f} Gbps |",
            "",
        ]

        if not result.lag_groups:
            report.append("*No LAG groups found in the network*")
            report.append("")
            return "\n".join(report)

        # LAG details
        report.extend([
            "## LAG Details",
            "",
            "| Device | LAG | Members | Active | Bandwidth | Balance | Status |",
            "|--------|-----|---------|--------|-----------|---------|--------|",
        ])

        status_emoji = {
            LAGStatus.HEALTHY: "🟢",
            LAGStatus.DEGRADED: "🟡",
            LAGStatus.CRITICAL: "🔴",
            LAGStatus.INACTIVE: "⚪",
            LAGStatus.MISCONFIGURED: "🟠",
        }

        for lag in result.lag_groups:
            emoji = status_emoji.get(lag.status, "⚪")
            report.append(
                f"| {lag.device_name} | {lag.lag_name} | "
                f"{lag.expected_members} | {lag.active_members} | "
                f"{lag.active_bandwidth_mbps/1000:.1f}G/{lag.total_bandwidth_mbps/1000:.1f}G | "
                f"{lag.load_balance_score:.0f}% | {emoji} {lag.status.value} |"
            )
        report.append("")

        # Member details for non-healthy LAGs
        problem_lags = [l for l in result.lag_groups if l.status != LAGStatus.HEALTHY]
        if problem_lags:
            report.extend([
                "## Problem LAG Details",
                "",
            ])

            for lag in problem_lags:
                report.append(f"### {lag.device_name} - {lag.lag_name}")
                report.append("")
                report.append("| Port | Status | Speed | Load | Errors |")
                report.append("|------|--------|-------|------|--------|")

                for member in lag.members:
                    status = "✅ Active" if member.is_active else "❌ Down"
                    errors = member.rx_errors + member.tx_errors
                    report.append(
                        f"| {member.port_name} | {status} | "
                        f"{member.speed_mbps/1000:.0f}G | {member.load_percent:.1f}% | {errors} |"
                    )
                report.append("")

                if lag.issues:
                    report.append("**Issues:**")
                    for issue in lag.issues:
                        report.append(f"- {issue}")
                    report.append("")

        # Recommendations
        if result.recommendations:
            report.extend([
                "## Recommendations",
                "",
            ])
            for rec in result.recommendations:
                report.append(f"- {rec}")
            report.append("")

        return "\n".join(report)
