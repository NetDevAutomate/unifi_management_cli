#!/usr/bin/env python3
"""
Link Quality Monitor for UniFi Networks.

Provides physical layer diagnostics and link quality analysis:
- CRC error rate tracking and trending
- Frame error analysis (runts, giants, jabbers, collisions)
- SFP/SFP+ module diagnostics (DOM - Digital Optical Monitoring)
- Duplex mismatch detection
- Speed/auto-negotiation issue identification
- Cable quality estimation
- Historical link quality trending
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class LinkHealthStatus(Enum):
    """Link health status levels."""

    EXCELLENT = "excellent"  # No issues, optimal performance
    GOOD = "good"  # Minor issues, acceptable performance
    DEGRADED = "degraded"  # Noticeable issues, investigate
    POOR = "poor"  # Significant issues, action needed
    CRITICAL = "critical"  # Severe issues, immediate action


class LinkAlertType(Enum):
    """Types of link quality alerts."""

    CRC_ERRORS = "crc_errors"
    FRAME_ERRORS = "frame_errors"
    COLLISIONS = "collisions"
    DUPLEX_MISMATCH = "duplex_mismatch"
    SPEED_MISMATCH = "speed_mismatch"
    LINK_FLAPPING = "link_flapping"
    SFP_WARNING = "sfp_warning"
    SFP_CRITICAL = "sfp_critical"
    RUNT_FRAMES = "runt_frames"
    GIANT_FRAMES = "giant_frames"
    LATE_COLLISIONS = "late_collisions"
    AUTONEG_FAILURE = "autoneg_failure"


@dataclass
class SFPModuleInfo:
    """SFP/SFP+ module diagnostic information (DOM)."""

    port_idx: int
    device_id: str
    device_name: str
    vendor: str = ""
    part_number: str = ""
    serial_number: str = ""
    connector_type: str = ""  # LC, SC, etc.
    wavelength_nm: int = 0

    # Digital Optical Monitoring values
    temperature_celsius: float = 0.0
    voltage_v: float = 0.0
    tx_power_dbm: float = 0.0
    rx_power_dbm: float = 0.0
    bias_current_ma: float = 0.0

    # Thresholds (from SFP EEPROM)
    temp_high_alarm: float = 75.0
    temp_low_alarm: float = -5.0
    voltage_high_alarm: float = 3.6
    voltage_low_alarm: float = 3.0
    tx_power_high_alarm: float = 3.0
    tx_power_low_alarm: float = -11.0
    rx_power_high_alarm: float = 0.0
    rx_power_low_alarm: float = -20.0

    # Status
    is_present: bool = True
    has_dom: bool = False
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def temperature_status(self) -> LinkHealthStatus:
        """Check temperature status."""
        if self.temperature_celsius >= self.temp_high_alarm:
            return LinkHealthStatus.CRITICAL
        elif self.temperature_celsius >= self.temp_high_alarm - 10:
            return LinkHealthStatus.DEGRADED
        elif self.temperature_celsius <= self.temp_low_alarm:
            return LinkHealthStatus.CRITICAL
        return LinkHealthStatus.EXCELLENT

    @property
    def rx_power_status(self) -> LinkHealthStatus:
        """Check receive power status (signal strength)."""
        if self.rx_power_dbm <= self.rx_power_low_alarm:
            return LinkHealthStatus.CRITICAL
        elif self.rx_power_dbm <= self.rx_power_low_alarm + 3:
            return LinkHealthStatus.DEGRADED
        elif self.rx_power_dbm >= self.rx_power_high_alarm:
            return LinkHealthStatus.DEGRADED
        return LinkHealthStatus.EXCELLENT

    @property
    def overall_status(self) -> LinkHealthStatus:
        """Get overall SFP health status."""
        statuses = [self.temperature_status, self.rx_power_status]
        if LinkHealthStatus.CRITICAL in statuses:
            return LinkHealthStatus.CRITICAL
        elif LinkHealthStatus.DEGRADED in statuses:
            return LinkHealthStatus.DEGRADED
        return LinkHealthStatus.EXCELLENT


@dataclass
class LinkQualityMetrics:
    """Comprehensive link quality metrics for a single port."""

    port_idx: int
    device_id: str
    device_name: str
    port_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    # Link state
    is_up: bool = True
    speed_mbps: int = 0
    full_duplex: bool = True
    autoneg_enabled: bool = True
    autoneg_complete: bool = True

    # Error counters (cumulative)
    rx_errors: int = 0
    tx_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0
    crc_errors: int = 0
    alignment_errors: int = 0
    collisions: int = 0
    late_collisions: int = 0

    # Frame errors
    runts: int = 0  # Undersized frames
    giants: int = 0  # Oversized frames
    jabbers: int = 0  # Oversized with CRC errors
    fragments: int = 0  # Undersized with CRC errors

    # Traffic counters (for rate calculation)
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_packets: int = 0
    tx_packets: int = 0
    rx_broadcast: int = 0
    rx_multicast: int = 0

    # Link stability
    uptime_seconds: int = 0
    link_changes_24h: int = 0
    last_link_down: Optional[datetime] = None

    # SFP info (if applicable)
    sfp_info: Optional[SFPModuleInfo] = None

    # Historical data for trending
    error_history: List[Tuple[datetime, int]] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        """Get total error count."""
        return (
            self.rx_errors + self.tx_errors + self.crc_errors +
            self.alignment_errors + self.collisions + self.late_collisions +
            self.runts + self.giants + self.jabbers + self.fragments
        )

    @property
    def error_rate_ppm(self) -> float:
        """Calculate error rate in parts per million."""
        total_packets = self.rx_packets + self.tx_packets
        if total_packets == 0:
            return 0.0
        return (self.total_errors / total_packets) * 1_000_000

    @property
    def has_duplex_issue(self) -> bool:
        """Detect potential duplex mismatch (high late collisions)."""
        if self.late_collisions > 0 and self.tx_packets > 0:
            late_collision_rate = self.late_collisions / self.tx_packets
            return late_collision_rate > 0.001  # >0.1% late collisions
        return False

    @property
    def health_status(self) -> LinkHealthStatus:
        """Calculate overall link health status."""
        if not self.is_up:
            return LinkHealthStatus.CRITICAL

        issues = []

        # Error rate thresholds (PPM)
        error_ppm = self.error_rate_ppm
        if error_ppm > 1000:  # >0.1% errors
            issues.append(LinkHealthStatus.CRITICAL)
        elif error_ppm > 100:  # >0.01% errors
            issues.append(LinkHealthStatus.POOR)
        elif error_ppm > 10:  # >0.001% errors
            issues.append(LinkHealthStatus.DEGRADED)

        # Duplex issues
        if self.has_duplex_issue:
            issues.append(LinkHealthStatus.POOR)

        # Link stability
        if self.link_changes_24h > 10:
            issues.append(LinkHealthStatus.POOR)
        elif self.link_changes_24h > 3:
            issues.append(LinkHealthStatus.DEGRADED)

        # SFP status
        if self.sfp_info:
            issues.append(self.sfp_info.overall_status)

        # Return worst status
        if LinkHealthStatus.CRITICAL in issues:
            return LinkHealthStatus.CRITICAL
        elif LinkHealthStatus.POOR in issues:
            return LinkHealthStatus.POOR
        elif LinkHealthStatus.DEGRADED in issues:
            return LinkHealthStatus.DEGRADED
        elif issues:
            return LinkHealthStatus.GOOD
        return LinkHealthStatus.EXCELLENT

    def calculate_health_score(self) -> float:
        """Calculate health score from 0-100."""
        if not self.is_up:
            return 0.0

        score = 100.0

        # Error rate penalty
        error_ppm = self.error_rate_ppm
        if error_ppm > 0:
            score -= min(40, error_ppm / 25)  # Max 40 point penalty

        # Duplex mismatch penalty
        if self.has_duplex_issue:
            score -= 20

        # Link stability penalty
        score -= min(20, self.link_changes_24h * 2)

        # SFP issues penalty
        if self.sfp_info:
            if self.sfp_info.overall_status == LinkHealthStatus.CRITICAL:
                score -= 30
            elif self.sfp_info.overall_status == LinkHealthStatus.DEGRADED:
                score -= 15

        return max(0.0, score)


@dataclass
class LinkQualityReport:
    """Complete link quality analysis results."""

    timestamp: datetime = field(default_factory=datetime.now)
    devices_analyzed: int = 0
    ports_analyzed: int = 0

    # Aggregated metrics
    total_errors: int = 0
    ports_with_errors: int = 0
    ports_with_sfp: int = 0

    # Status counts
    excellent_ports: int = 0
    good_ports: int = 0
    degraded_ports: int = 0
    poor_ports: int = 0
    critical_ports: int = 0

    # Detailed results
    port_metrics: List[LinkQualityMetrics] = field(default_factory=list)
    sfp_modules: List[SFPModuleInfo] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)

    def add_alert(
        self,
        alert_type: LinkAlertType,
        severity: LinkHealthStatus,
        message: str,
        device_name: str,
        port_idx: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an alert."""
        self.alerts.append({
            "type": alert_type.value,
            "severity": severity.value,
            "message": message,
            "device_name": device_name,
            "port_idx": port_idx,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })

    @property
    def overall_health_score(self) -> float:
        """Calculate network-wide link quality score."""
        if not self.port_metrics:
            return 100.0
        return sum(m.calculate_health_score() for m in self.port_metrics) / len(self.port_metrics)

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "devices_analyzed": self.devices_analyzed,
            "ports_analyzed": self.ports_analyzed,
            "overall_health_score": round(self.overall_health_score, 1),
            "total_errors": self.total_errors,
            "ports_with_errors": self.ports_with_errors,
            "status_distribution": {
                "excellent": self.excellent_ports,
                "good": self.good_ports,
                "degraded": self.degraded_ports,
                "poor": self.poor_ports,
                "critical": self.critical_ports,
            },
            "total_alerts": len(self.alerts),
            "sfp_modules": self.ports_with_sfp,
        }


class LinkQualityMonitor:
    """
    Comprehensive link quality monitoring for UniFi networks.

    Monitors physical layer health including:
    - Error rates and types
    - SFP module diagnostics
    - Link stability
    - Duplex/speed issues
    """

    # Error rate thresholds (errors per million packets)
    ERROR_THRESHOLD_WARNING = 10  # 0.001%
    ERROR_THRESHOLD_HIGH = 100  # 0.01%
    ERROR_THRESHOLD_CRITICAL = 1000  # 0.1%

    # Link stability thresholds
    LINK_FLAP_WARNING = 3  # flaps in 24h
    LINK_FLAP_HIGH = 10

    def __init__(self, api_client, site: str = "default"):
        """Initialize Link Quality Monitor."""
        self.api_client = api_client
        self.site = site
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._historical_metrics: Dict[str, List[LinkQualityMetrics]] = {}

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

    def _extract_port_metrics(
        self, device: Dict[str, Any], port_data: Dict[str, Any]
    ) -> LinkQualityMetrics:
        """Extract link quality metrics from port data."""
        device_id = device["_id"]
        device_name = device.get("name", device.get("model", "Unknown"))
        port_idx = port_data.get("port_idx", 0)

        metrics = LinkQualityMetrics(
            port_idx=port_idx,
            device_id=device_id,
            device_name=device_name,
            port_name=port_data.get("name", f"Port {port_idx}"),
        )

        # Link state
        metrics.is_up = port_data.get("up", False)
        metrics.speed_mbps = port_data.get("speed", 0)
        metrics.full_duplex = port_data.get("full_duplex", True)
        metrics.autoneg_enabled = port_data.get("autoneg", True)

        # Error counters
        metrics.rx_errors = port_data.get("rx_errors", 0)
        metrics.tx_errors = port_data.get("tx_errors", 0)
        metrics.rx_dropped = port_data.get("rx_dropped", 0)
        metrics.tx_dropped = port_data.get("tx_dropped", 0)

        # Get detailed error breakdown if available
        port_stats = port_data.get("port_stats", {})
        metrics.crc_errors = port_stats.get("rx_crc_errors", port_data.get("rx_crc_errors", 0))
        metrics.alignment_errors = port_stats.get("rx_align_errors", 0)
        metrics.collisions = port_stats.get("collisions", port_data.get("collisions", 0))
        metrics.late_collisions = port_stats.get("late_collisions", 0)

        # Frame errors
        metrics.runts = port_stats.get("rx_runts", 0)
        metrics.giants = port_stats.get("rx_giants", 0)
        metrics.jabbers = port_stats.get("rx_jabbers", 0)
        metrics.fragments = port_stats.get("rx_fragments", 0)

        # Traffic counters
        metrics.rx_bytes = port_data.get("rx_bytes", 0)
        metrics.tx_bytes = port_data.get("tx_bytes", 0)
        metrics.rx_packets = port_data.get("rx_packets", 0)
        metrics.tx_packets = port_data.get("tx_packets", 0)
        metrics.rx_broadcast = port_data.get("rx_broadcast", 0)
        metrics.rx_multicast = port_data.get("rx_multicast", 0)

        # Link stability
        metrics.uptime_seconds = port_data.get("port_uptime", port_data.get("uptime", 0))

        # SFP information (if present)
        if port_data.get("sfp_found", False) or port_data.get("media", "") in ["SFP", "SFP+"]:
            metrics.sfp_info = self._extract_sfp_info(device, port_data)

        return metrics

    def _extract_sfp_info(
        self, device: Dict[str, Any], port_data: Dict[str, Any]
    ) -> Optional[SFPModuleInfo]:
        """Extract SFP module diagnostic information."""
        device_id = device["_id"]
        device_name = device.get("name", device.get("model", "Unknown"))
        port_idx = port_data.get("port_idx", 0)

        sfp = SFPModuleInfo(
            port_idx=port_idx,
            device_id=device_id,
            device_name=device_name,
        )

        # Basic SFP info
        sfp.vendor = port_data.get("sfp_vendor", "")
        sfp.part_number = port_data.get("sfp_part", "")
        sfp.serial_number = port_data.get("sfp_serial", "")
        sfp.is_present = port_data.get("sfp_found", True)

        # DOM (Digital Optical Monitoring) values
        dom = port_data.get("sfp_dom", {})
        if dom:
            sfp.has_dom = True
            sfp.temperature_celsius = dom.get("temperature", 0.0)
            sfp.voltage_v = dom.get("voltage", 0.0)
            sfp.tx_power_dbm = dom.get("tx_power", 0.0)
            sfp.rx_power_dbm = dom.get("rx_power", 0.0)
            sfp.bias_current_ma = dom.get("bias_current", 0.0)

        return sfp

    def analyze(self, include_all_ports: bool = False) -> LinkQualityReport:
        """
        Perform comprehensive link quality analysis.

        Args:
            include_all_ports: Include ports with no issues (default: only problematic)

        Returns:
            LinkQualityReport with analysis results
        """
        logger.info("Starting link quality analysis...")
        report = LinkQualityReport()

        devices = self._get_devices()

        for device in devices:
            device_type = device.get("type", "")
            if device_type not in ["usw", "udm", "ugw", "udmpro"]:
                continue

            report.devices_analyzed += 1
            device_name = device.get("name", device.get("model", "Unknown"))
            port_table = device.get("port_table", [])

            for port_data in port_table:
                report.ports_analyzed += 1
                metrics = self._extract_port_metrics(device, port_data)

                # Categorize by health status
                status = metrics.health_status
                if status == LinkHealthStatus.EXCELLENT:
                    report.excellent_ports += 1
                elif status == LinkHealthStatus.GOOD:
                    report.good_ports += 1
                elif status == LinkHealthStatus.DEGRADED:
                    report.degraded_ports += 1
                elif status == LinkHealthStatus.POOR:
                    report.poor_ports += 1
                elif status == LinkHealthStatus.CRITICAL:
                    report.critical_ports += 1

                # Track totals
                if metrics.total_errors > 0:
                    report.ports_with_errors += 1
                    report.total_errors += metrics.total_errors

                if metrics.sfp_info:
                    report.ports_with_sfp += 1
                    report.sfp_modules.append(metrics.sfp_info)

                # Generate alerts for issues
                self._generate_alerts(report, metrics)

                # Include in detailed results
                if include_all_ports or metrics.health_status not in [
                    LinkHealthStatus.EXCELLENT,
                    LinkHealthStatus.GOOD,
                ]:
                    report.port_metrics.append(metrics)

        # Sort metrics by health score (worst first)
        report.port_metrics.sort(key=lambda m: m.calculate_health_score())

        logger.info(
            f"Link quality analysis complete: {report.ports_analyzed} ports, "
            f"health score: {report.overall_health_score:.1f}%, "
            f"{len(report.alerts)} alerts"
        )

        return report

    def _generate_alerts(
        self, report: LinkQualityReport, metrics: LinkQualityMetrics
    ) -> None:
        """Generate alerts based on link metrics."""

        # CRC errors
        if metrics.crc_errors > 0:
            severity = self._get_error_severity(metrics.error_rate_ppm)
            report.add_alert(
                LinkAlertType.CRC_ERRORS,
                severity,
                f"CRC errors detected: {metrics.crc_errors} "
                f"({metrics.error_rate_ppm:.1f} PPM)",
                metrics.device_name,
                metrics.port_idx,
                {"crc_errors": metrics.crc_errors, "error_rate_ppm": metrics.error_rate_ppm},
            )

        # Late collisions (duplex mismatch indicator)
        if metrics.late_collisions > 0:
            report.add_alert(
                LinkAlertType.LATE_COLLISIONS,
                LinkHealthStatus.POOR,
                f"Late collisions detected: {metrics.late_collisions} - "
                "possible duplex mismatch",
                metrics.device_name,
                metrics.port_idx,
                {"late_collisions": metrics.late_collisions},
            )

        # Duplex mismatch
        if metrics.has_duplex_issue:
            report.add_alert(
                LinkAlertType.DUPLEX_MISMATCH,
                LinkHealthStatus.POOR,
                f"Suspected duplex mismatch on port {metrics.port_idx}",
                metrics.device_name,
                metrics.port_idx,
                {
                    "late_collisions": metrics.late_collisions,
                    "full_duplex": metrics.full_duplex,
                },
            )

        # Runt frames (undersized)
        if metrics.runts > 100:
            report.add_alert(
                LinkAlertType.RUNT_FRAMES,
                LinkHealthStatus.DEGRADED,
                f"Excessive runt frames: {metrics.runts}",
                metrics.device_name,
                metrics.port_idx,
                {"runts": metrics.runts},
            )

        # Giant frames (oversized)
        if metrics.giants > 100:
            report.add_alert(
                LinkAlertType.GIANT_FRAMES,
                LinkHealthStatus.DEGRADED,
                f"Excessive giant frames: {metrics.giants}",
                metrics.device_name,
                metrics.port_idx,
                {"giants": metrics.giants},
            )

        # Link flapping
        if metrics.link_changes_24h >= self.LINK_FLAP_HIGH:
            report.add_alert(
                LinkAlertType.LINK_FLAPPING,
                LinkHealthStatus.POOR,
                f"Link flapping: {metrics.link_changes_24h} changes in 24h",
                metrics.device_name,
                metrics.port_idx,
                {"link_changes": metrics.link_changes_24h},
            )
        elif metrics.link_changes_24h >= self.LINK_FLAP_WARNING:
            report.add_alert(
                LinkAlertType.LINK_FLAPPING,
                LinkHealthStatus.DEGRADED,
                f"Link unstable: {metrics.link_changes_24h} changes in 24h",
                metrics.device_name,
                metrics.port_idx,
                {"link_changes": metrics.link_changes_24h},
            )

        # SFP alerts
        if metrics.sfp_info and metrics.sfp_info.has_dom:
            sfp = metrics.sfp_info

            if sfp.temperature_status == LinkHealthStatus.CRITICAL:
                report.add_alert(
                    LinkAlertType.SFP_CRITICAL,
                    LinkHealthStatus.CRITICAL,
                    f"SFP temperature critical: {sfp.temperature_celsius}°C",
                    metrics.device_name,
                    metrics.port_idx,
                    {"temperature": sfp.temperature_celsius},
                )

            if sfp.rx_power_status == LinkHealthStatus.CRITICAL:
                report.add_alert(
                    LinkAlertType.SFP_CRITICAL,
                    LinkHealthStatus.CRITICAL,
                    f"SFP RX power low: {sfp.rx_power_dbm} dBm",
                    metrics.device_name,
                    metrics.port_idx,
                    {"rx_power": sfp.rx_power_dbm},
                )
            elif sfp.rx_power_status == LinkHealthStatus.DEGRADED:
                report.add_alert(
                    LinkAlertType.SFP_WARNING,
                    LinkHealthStatus.DEGRADED,
                    f"SFP RX power marginal: {sfp.rx_power_dbm} dBm",
                    metrics.device_name,
                    metrics.port_idx,
                    {"rx_power": sfp.rx_power_dbm},
                )

    def _get_error_severity(self, error_ppm: float) -> LinkHealthStatus:
        """Get severity level based on error rate."""
        if error_ppm >= self.ERROR_THRESHOLD_CRITICAL:
            return LinkHealthStatus.CRITICAL
        elif error_ppm >= self.ERROR_THRESHOLD_HIGH:
            return LinkHealthStatus.POOR
        elif error_ppm >= self.ERROR_THRESHOLD_WARNING:
            return LinkHealthStatus.DEGRADED
        return LinkHealthStatus.GOOD

    def generate_report(self, result: LinkQualityReport) -> str:
        """Generate human-readable link quality report."""
        report = [
            "# Link Quality Analysis Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Overall Health Score | {result.overall_health_score:.1f}% |",
            f"| Devices Analyzed | {result.devices_analyzed} |",
            f"| Ports Analyzed | {result.ports_analyzed} |",
            f"| Ports with Errors | {result.ports_with_errors} |",
            f"| Total Errors | {result.total_errors:,} |",
            f"| SFP Modules | {result.ports_with_sfp} |",
            "",
            "## Port Health Distribution",
            "",
            f"| Status | Count |",
            f"|--------|-------|",
            f"| 🟢 Excellent | {result.excellent_ports} |",
            f"| 🟢 Good | {result.good_ports} |",
            f"| 🟡 Degraded | {result.degraded_ports} |",
            f"| 🟠 Poor | {result.poor_ports} |",
            f"| 🔴 Critical | {result.critical_ports} |",
            "",
        ]

        # Alerts section
        if result.alerts:
            report.extend(["## Alerts", ""])

            severity_order = ["critical", "poor", "degraded", "good"]
            severity_emoji = {
                "critical": "🔴",
                "poor": "🟠",
                "degraded": "🟡",
                "good": "🟢",
            }

            for severity in severity_order:
                alerts = [a for a in result.alerts if a["severity"] == severity]
                if alerts:
                    report.append(f"### {severity_emoji.get(severity, '⚪')} {severity.upper()}")
                    report.append("")
                    for alert in alerts:
                        report.append(
                            f"- **{alert['device_name']} Port {alert['port_idx']}**: "
                            f"{alert['message']}"
                        )
                    report.append("")

        # Problem ports detail
        problem_ports = [
            m for m in result.port_metrics
            if m.health_status not in [LinkHealthStatus.EXCELLENT, LinkHealthStatus.GOOD]
        ]

        if problem_ports:
            report.extend([
                "## Problem Ports Detail",
                "",
                "| Device | Port | Status | Score | Errors | Issues |",
                "|--------|------|--------|-------|--------|--------|",
            ])

            status_emoji = {
                LinkHealthStatus.DEGRADED: "🟡",
                LinkHealthStatus.POOR: "🟠",
                LinkHealthStatus.CRITICAL: "🔴",
            }

            for m in problem_ports[:20]:
                issues = []
                if m.crc_errors > 0:
                    issues.append(f"CRC:{m.crc_errors}")
                if m.late_collisions > 0:
                    issues.append(f"Late-Col:{m.late_collisions}")
                if m.has_duplex_issue:
                    issues.append("Duplex?")
                if m.link_changes_24h > 3:
                    issues.append(f"Flaps:{m.link_changes_24h}")

                emoji = status_emoji.get(m.health_status, "⚪")
                report.append(
                    f"| {m.device_name} | {m.port_idx} | {emoji} {m.health_status.value} | "
                    f"{m.calculate_health_score():.0f}% | {m.total_errors:,} | {', '.join(issues) or 'N/A'} |"
                )
            report.append("")

        # SFP module details
        problem_sfps = [s for s in result.sfp_modules if s.overall_status != LinkHealthStatus.EXCELLENT]
        if problem_sfps:
            report.extend([
                "## SFP Module Issues",
                "",
                "| Device | Port | Vendor | Temp | RX Power | Status |",
                "|--------|------|--------|------|----------|--------|",
            ])

            for sfp in problem_sfps:
                status_emoji = {
                    LinkHealthStatus.DEGRADED: "🟡",
                    LinkHealthStatus.POOR: "🟠",
                    LinkHealthStatus.CRITICAL: "🔴",
                }.get(sfp.overall_status, "⚪")

                report.append(
                    f"| {sfp.device_name} | {sfp.port_idx} | {sfp.vendor or 'Unknown'} | "
                    f"{sfp.temperature_celsius:.1f}°C | {sfp.rx_power_dbm:.1f} dBm | "
                    f"{status_emoji} {sfp.overall_status.value} |"
                )
            report.append("")

        return "\n".join(report)
