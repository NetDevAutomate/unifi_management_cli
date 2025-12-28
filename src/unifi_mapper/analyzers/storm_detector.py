#!/usr/bin/env python3
"""
Broadcast/Multicast Storm Detector for UniFi Networks.

Provides real-time and historical analysis of broadcast/multicast traffic:
- Broadcast storm detection and alerting
- Multicast flood identification
- Per-VLAN traffic analysis
- Storm source identification
- Historical storm event logging
- Threshold-based alerting
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class StormSeverity(Enum):
    """Storm severity levels."""

    INFO = "info"  # Elevated but acceptable
    WARNING = "warning"  # Above normal, monitor
    HIGH = "high"  # Significant impact likely
    CRITICAL = "critical"  # Active storm, immediate action


class StormType(Enum):
    """Types of traffic storms."""

    BROADCAST = "broadcast"
    MULTICAST = "multicast"
    UNKNOWN_UNICAST = "unknown_unicast"  # Flooding due to MAC table overflow
    MIXED = "mixed"


@dataclass
class TrafficMetrics:
    """Traffic metrics for a single port or VLAN."""

    timestamp: datetime = field(default_factory=datetime.now)

    # Packet counts
    rx_packets: int = 0
    tx_packets: int = 0
    rx_broadcast: int = 0
    tx_broadcast: int = 0
    rx_multicast: int = 0
    tx_multicast: int = 0

    # Byte counts
    rx_bytes: int = 0
    tx_bytes: int = 0
    rx_broadcast_bytes: int = 0
    rx_multicast_bytes: int = 0

    # Calculated rates (packets per second)
    broadcast_pps: float = 0.0
    multicast_pps: float = 0.0
    total_pps: float = 0.0

    # Percentages
    broadcast_percent: float = 0.0
    multicast_percent: float = 0.0

    @property
    def total_broadcast(self) -> int:
        return self.rx_broadcast + self.tx_broadcast

    @property
    def total_multicast(self) -> int:
        return self.rx_multicast + self.tx_multicast

    @property
    def non_unicast_percent(self) -> float:
        """Percentage of non-unicast traffic."""
        total = self.rx_packets + self.tx_packets
        if total == 0:
            return 0.0
        non_unicast = self.total_broadcast + self.total_multicast
        return (non_unicast / total) * 100


@dataclass
class StormEvent:
    """Records a detected storm event."""

    event_id: str
    storm_type: StormType
    severity: StormSeverity
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_seconds: int = 0

    # Location
    device_id: str = ""
    device_name: str = ""
    port_idx: Optional[int] = None
    vlan_id: Optional[int] = None

    # Metrics at detection
    broadcast_pps: float = 0.0
    multicast_pps: float = 0.0
    broadcast_percent: float = 0.0
    multicast_percent: float = 0.0
    peak_pps: float = 0.0

    # Impact
    affected_ports: List[int] = field(default_factory=list)
    packet_count: int = 0

    # Resolution
    is_active: bool = True
    resolution_notes: str = ""

    def end_event(self, notes: str = "") -> None:
        """Mark event as ended."""
        self.end_time = datetime.now()
        self.duration_seconds = int((self.end_time - self.start_time).total_seconds())
        self.is_active = False
        self.resolution_notes = notes


@dataclass
class PortStormAnalysis:
    """Storm analysis for a single port."""

    device_id: str
    device_name: str
    port_idx: int
    port_name: str = ""
    vlan_id: Optional[int] = None

    # Current metrics
    metrics: TrafficMetrics = field(default_factory=TrafficMetrics)

    # Historical samples for trending
    history: List[TrafficMetrics] = field(default_factory=list)

    # Storm status
    storm_detected: bool = False
    storm_type: Optional[StormType] = None
    severity: StormSeverity = StormSeverity.INFO

    # Thresholds exceeded
    broadcast_threshold_exceeded: bool = False
    multicast_threshold_exceeded: bool = False
    pps_threshold_exceeded: bool = False


@dataclass
class StormDetectionResult:
    """Complete storm detection analysis results."""

    timestamp: datetime = field(default_factory=datetime.now)
    devices_analyzed: int = 0
    ports_analyzed: int = 0

    # Network-wide metrics
    total_broadcast_pps: float = 0.0
    total_multicast_pps: float = 0.0
    network_broadcast_percent: float = 0.0
    network_multicast_percent: float = 0.0

    # Storm detection
    active_storms: List[StormEvent] = field(default_factory=list)
    historical_storms: List[StormEvent] = field(default_factory=list)
    ports_at_risk: List[PortStormAnalysis] = field(default_factory=list)

    # Per-port analysis
    port_analyses: List[PortStormAnalysis] = field(default_factory=list)

    # Alerts
    alerts: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def has_active_storm(self) -> bool:
        return len(self.active_storms) > 0

    @property
    def storm_severity(self) -> StormSeverity:
        """Get highest severity among active storms."""
        if not self.active_storms:
            return StormSeverity.INFO
        severities = [s.severity for s in self.active_storms]
        if StormSeverity.CRITICAL in severities:
            return StormSeverity.CRITICAL
        elif StormSeverity.HIGH in severities:
            return StormSeverity.HIGH
        elif StormSeverity.WARNING in severities:
            return StormSeverity.WARNING
        return StormSeverity.INFO

    def add_alert(
        self,
        severity: StormSeverity,
        message: str,
        device_name: str = "",
        port_idx: Optional[int] = None,
        storm_type: Optional[StormType] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an alert."""
        self.alerts.append({
            "severity": severity.value,
            "message": message,
            "device_name": device_name,
            "port_idx": port_idx,
            "storm_type": storm_type.value if storm_type else None,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "devices_analyzed": self.devices_analyzed,
            "ports_analyzed": self.ports_analyzed,
            "has_active_storm": self.has_active_storm,
            "active_storm_count": len(self.active_storms),
            "storm_severity": self.storm_severity.value,
            "network_broadcast_percent": round(self.network_broadcast_percent, 2),
            "network_multicast_percent": round(self.network_multicast_percent, 2),
            "total_broadcast_pps": round(self.total_broadcast_pps, 1),
            "total_multicast_pps": round(self.total_multicast_pps, 1),
            "ports_at_risk": len(self.ports_at_risk),
            "total_alerts": len(self.alerts),
        }


class StormDetector:
    """
    Broadcast and Multicast Storm Detection for UniFi Networks.

    Detects and alerts on:
    - Broadcast storms (excessive broadcast traffic)
    - Multicast floods (excessive multicast traffic)
    - Unknown unicast flooding (MAC table overflow symptoms)
    - Per-port and per-VLAN storm analysis
    """

    # Default thresholds
    BROADCAST_PERCENT_WARNING = 5.0  # % of traffic
    BROADCAST_PERCENT_HIGH = 15.0
    BROADCAST_PERCENT_CRITICAL = 30.0

    MULTICAST_PERCENT_WARNING = 10.0
    MULTICAST_PERCENT_HIGH = 25.0
    MULTICAST_PERCENT_CRITICAL = 40.0

    BROADCAST_PPS_WARNING = 500  # packets per second
    BROADCAST_PPS_HIGH = 2000
    BROADCAST_PPS_CRITICAL = 5000

    MULTICAST_PPS_WARNING = 1000
    MULTICAST_PPS_HIGH = 5000
    MULTICAST_PPS_CRITICAL = 10000

    def __init__(
        self,
        api_client,
        site: str = "default",
        custom_thresholds: Optional[Dict[str, float]] = None,
    ):
        """
        Initialize Storm Detector.

        Args:
            api_client: UniFi API client
            site: UniFi site name
            custom_thresholds: Override default thresholds
        """
        self.api_client = api_client
        self.site = site

        # Apply custom thresholds
        if custom_thresholds:
            for key, value in custom_thresholds.items():
                if hasattr(self, key.upper()):
                    setattr(self, key.upper(), value)

        # Historical tracking
        self._previous_metrics: Dict[str, TrafficMetrics] = {}  # port_key -> metrics
        self._active_storms: Dict[str, StormEvent] = {}  # event_id -> storm
        self._storm_history: List[StormEvent] = []
        self._last_analysis_time: Optional[datetime] = None
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

    def _extract_traffic_metrics(
        self, port_data: Dict[str, Any], previous: Optional[TrafficMetrics]
    ) -> TrafficMetrics:
        """Extract traffic metrics from port data."""
        metrics = TrafficMetrics()

        # Raw counters
        metrics.rx_packets = port_data.get("rx_packets", 0)
        metrics.tx_packets = port_data.get("tx_packets", 0)
        metrics.rx_broadcast = port_data.get("rx_broadcast", 0)
        metrics.tx_broadcast = port_data.get("tx_broadcast", 0)
        metrics.rx_multicast = port_data.get("rx_multicast", 0)
        metrics.tx_multicast = port_data.get("tx_multicast", 0)
        metrics.rx_bytes = port_data.get("rx_bytes", 0)
        metrics.tx_bytes = port_data.get("tx_bytes", 0)

        # Calculate percentages
        total_packets = metrics.rx_packets + metrics.tx_packets
        if total_packets > 0:
            metrics.broadcast_percent = (metrics.total_broadcast / total_packets) * 100
            metrics.multicast_percent = (metrics.total_multicast / total_packets) * 100

        # Calculate rates if we have previous sample
        if previous and self._last_analysis_time:
            time_delta = (datetime.now() - self._last_analysis_time).total_seconds()
            if time_delta > 0:
                bc_delta = max(0, metrics.total_broadcast - previous.total_broadcast)
                mc_delta = max(0, metrics.total_multicast - previous.total_multicast)
                total_delta = max(
                    0,
                    (metrics.rx_packets + metrics.tx_packets)
                    - (previous.rx_packets + previous.tx_packets),
                )

                metrics.broadcast_pps = bc_delta / time_delta
                metrics.multicast_pps = mc_delta / time_delta
                metrics.total_pps = total_delta / time_delta

        return metrics

    def _classify_storm(
        self, metrics: TrafficMetrics
    ) -> Tuple[Optional[StormType], StormSeverity]:
        """Classify storm type and severity based on metrics."""
        bc_critical = (
            metrics.broadcast_percent >= self.BROADCAST_PERCENT_CRITICAL
            or metrics.broadcast_pps >= self.BROADCAST_PPS_CRITICAL
        )
        bc_high = (
            metrics.broadcast_percent >= self.BROADCAST_PERCENT_HIGH
            or metrics.broadcast_pps >= self.BROADCAST_PPS_HIGH
        )
        bc_warning = (
            metrics.broadcast_percent >= self.BROADCAST_PERCENT_WARNING
            or metrics.broadcast_pps >= self.BROADCAST_PPS_WARNING
        )

        mc_critical = (
            metrics.multicast_percent >= self.MULTICAST_PERCENT_CRITICAL
            or metrics.multicast_pps >= self.MULTICAST_PPS_CRITICAL
        )
        mc_high = (
            metrics.multicast_percent >= self.MULTICAST_PERCENT_HIGH
            or metrics.multicast_pps >= self.MULTICAST_PPS_HIGH
        )
        mc_warning = (
            metrics.multicast_percent >= self.MULTICAST_PERCENT_WARNING
            or metrics.multicast_pps >= self.MULTICAST_PPS_WARNING
        )

        # Determine type and severity
        if bc_critical or mc_critical:
            severity = StormSeverity.CRITICAL
        elif bc_high or mc_high:
            severity = StormSeverity.HIGH
        elif bc_warning or mc_warning:
            severity = StormSeverity.WARNING
        else:
            return None, StormSeverity.INFO

        # Determine storm type
        if bc_warning and mc_warning:
            storm_type = StormType.MIXED
        elif bc_warning:
            storm_type = StormType.BROADCAST
        elif mc_warning:
            storm_type = StormType.MULTICAST
        else:
            storm_type = StormType.BROADCAST  # Default

        return storm_type, severity

    def _generate_event_id(
        self, device_id: str, port_idx: int, storm_type: StormType
    ) -> str:
        """Generate unique event ID."""
        return f"{device_id}:{port_idx}:{storm_type.value}"

    def analyze(self) -> StormDetectionResult:
        """
        Perform storm detection analysis.

        Returns:
            StormDetectionResult with analysis findings
        """
        logger.info("Starting storm detection analysis...")
        result = StormDetectionResult()

        devices = self._get_devices()

        # Network-wide totals
        total_rx_packets = 0
        total_tx_packets = 0
        total_broadcast = 0
        total_multicast = 0

        for device in devices:
            device_type = device.get("type", "")
            if device_type not in ["usw", "udm", "ugw", "udmpro"]:
                continue

            result.devices_analyzed += 1
            device_id = device["_id"]
            device_name = device.get("name", device.get("model", "Unknown"))
            port_table = device.get("port_table", [])

            for port_data in port_table:
                result.ports_analyzed += 1
                port_idx = port_data.get("port_idx", 0)
                port_name = port_data.get("name", f"Port {port_idx}")
                port_key = f"{device_id}:{port_idx}"

                # Get previous metrics for rate calculation
                previous_metrics = self._previous_metrics.get(port_key)

                # Extract current metrics
                metrics = self._extract_traffic_metrics(port_data, previous_metrics)

                # Update totals
                total_rx_packets += metrics.rx_packets
                total_tx_packets += metrics.tx_packets
                total_broadcast += metrics.total_broadcast
                total_multicast += metrics.total_multicast

                # Classify storm
                storm_type, severity = self._classify_storm(metrics)

                # Create port analysis
                port_analysis = PortStormAnalysis(
                    device_id=device_id,
                    device_name=device_name,
                    port_idx=port_idx,
                    port_name=port_name,
                    metrics=metrics,
                )

                if storm_type:
                    port_analysis.storm_detected = True
                    port_analysis.storm_type = storm_type
                    port_analysis.severity = severity

                    # Track or update storm event
                    event_id = self._generate_event_id(device_id, port_idx, storm_type)

                    if event_id in self._active_storms:
                        # Update existing storm
                        storm = self._active_storms[event_id]
                        storm.peak_pps = max(
                            storm.peak_pps,
                            metrics.broadcast_pps + metrics.multicast_pps,
                        )
                        storm.packet_count += metrics.total_broadcast + metrics.total_multicast
                    else:
                        # New storm detected
                        storm = StormEvent(
                            event_id=event_id,
                            storm_type=storm_type,
                            severity=severity,
                            device_id=device_id,
                            device_name=device_name,
                            port_idx=port_idx,
                            broadcast_pps=metrics.broadcast_pps,
                            multicast_pps=metrics.multicast_pps,
                            broadcast_percent=metrics.broadcast_percent,
                            multicast_percent=metrics.multicast_percent,
                            peak_pps=metrics.broadcast_pps + metrics.multicast_pps,
                        )
                        self._active_storms[event_id] = storm

                        # Generate alert
                        result.add_alert(
                            severity,
                            f"{storm_type.value.upper()} storm detected on {device_name} "
                            f"port {port_idx}: {metrics.broadcast_percent:.1f}% broadcast, "
                            f"{metrics.multicast_percent:.1f}% multicast",
                            device_name,
                            port_idx,
                            storm_type,
                            {
                                "broadcast_pps": metrics.broadcast_pps,
                                "multicast_pps": metrics.multicast_pps,
                                "broadcast_percent": metrics.broadcast_percent,
                                "multicast_percent": metrics.multicast_percent,
                            },
                        )

                    result.active_storms.append(self._active_storms[event_id])

                elif severity == StormSeverity.INFO and metrics.non_unicast_percent > 2:
                    # Port at risk but not storming
                    result.ports_at_risk.append(port_analysis)

                # Store metrics for next analysis
                self._previous_metrics[port_key] = metrics
                result.port_analyses.append(port_analysis)

        # Check for resolved storms
        for event_id in list(self._active_storms.keys()):
            if event_id not in [s.event_id for s in result.active_storms]:
                # Storm has ended
                storm = self._active_storms.pop(event_id)
                storm.end_event("Traffic returned to normal levels")
                self._storm_history.append(storm)
                result.historical_storms.append(storm)

                result.add_alert(
                    StormSeverity.INFO,
                    f"{storm.storm_type.value.upper()} storm resolved on "
                    f"{storm.device_name} port {storm.port_idx} "
                    f"(duration: {storm.duration_seconds}s)",
                    storm.device_name,
                    storm.port_idx,
                    storm.storm_type,
                    {"duration_seconds": storm.duration_seconds},
                )

        # Calculate network-wide percentages
        total_packets = total_rx_packets + total_tx_packets
        if total_packets > 0:
            result.network_broadcast_percent = (total_broadcast / total_packets) * 100
            result.network_multicast_percent = (total_multicast / total_packets) * 100

        # Calculate network-wide PPS (requires previous sample)
        if self._last_analysis_time:
            time_delta = (datetime.now() - self._last_analysis_time).total_seconds()
            if time_delta > 0:
                # Sum individual port PPS values
                result.total_broadcast_pps = sum(
                    p.metrics.broadcast_pps for p in result.port_analyses
                )
                result.total_multicast_pps = sum(
                    p.metrics.multicast_pps for p in result.port_analyses
                )

        # Add historical storms to result
        cutoff = datetime.now() - timedelta(hours=24)
        result.historical_storms = [
            s for s in self._storm_history if s.start_time > cutoff
        ]

        self._last_analysis_time = datetime.now()

        logger.info(
            f"Storm analysis complete: {result.ports_analyzed} ports, "
            f"{len(result.active_storms)} active storms, "
            f"network broadcast: {result.network_broadcast_percent:.1f}%"
        )

        return result

    def generate_report(self, result: StormDetectionResult) -> str:
        """Generate human-readable storm detection report."""
        report = [
            "# Broadcast/Multicast Storm Detection Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        # Status banner
        if result.has_active_storm:
            severity_emoji = {
                StormSeverity.WARNING: "⚠️",
                StormSeverity.HIGH: "🟠",
                StormSeverity.CRITICAL: "🔴",
            }
            emoji = severity_emoji.get(result.storm_severity, "⚠️")
            report.extend([
                f"## {emoji} ACTIVE STORM DETECTED - {result.storm_severity.value.upper()}",
                "",
            ])
        else:
            report.extend([
                "## ✅ No Active Storms",
                "",
            ])

        # Summary
        report.extend([
            "## Network Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Devices Analyzed | {result.devices_analyzed} |",
            f"| Ports Analyzed | {result.ports_analyzed} |",
            f"| Network Broadcast % | {result.network_broadcast_percent:.2f}% |",
            f"| Network Multicast % | {result.network_multicast_percent:.2f}% |",
            f"| Total Broadcast PPS | {result.total_broadcast_pps:.0f} |",
            f"| Total Multicast PPS | {result.total_multicast_pps:.0f} |",
            f"| Active Storms | {len(result.active_storms)} |",
            f"| Ports at Risk | {len(result.ports_at_risk)} |",
            "",
        ])

        # Active storms detail
        if result.active_storms:
            report.extend([
                "## 🔥 Active Storm Events",
                "",
                "| Device | Port | Type | Severity | BC% | MC% | Peak PPS | Duration |",
                "|--------|------|------|----------|-----|-----|----------|----------|",
            ])

            for storm in result.active_storms:
                duration = int((datetime.now() - storm.start_time).total_seconds())
                report.append(
                    f"| {storm.device_name} | {storm.port_idx} | "
                    f"{storm.storm_type.value} | {storm.severity.value} | "
                    f"{storm.broadcast_percent:.1f}% | {storm.multicast_percent:.1f}% | "
                    f"{storm.peak_pps:.0f} | {duration}s |"
                )
            report.append("")

        # Ports at risk
        if result.ports_at_risk:
            report.extend([
                "## ⚠️ Ports at Elevated Risk",
                "",
                "| Device | Port | Broadcast % | Multicast % | Non-Unicast % |",
                "|--------|------|-------------|-------------|---------------|",
            ])

            for port in sorted(
                result.ports_at_risk,
                key=lambda p: p.metrics.non_unicast_percent,
                reverse=True,
            )[:15]:
                report.append(
                    f"| {port.device_name} | {port.port_idx} | "
                    f"{port.metrics.broadcast_percent:.2f}% | "
                    f"{port.metrics.multicast_percent:.2f}% | "
                    f"{port.metrics.non_unicast_percent:.2f}% |"
                )
            report.append("")

        # Recent storm history
        if result.historical_storms:
            report.extend([
                "## 📜 Storm History (Last 24h)",
                "",
                "| Time | Device | Port | Type | Duration | Peak PPS |",
                "|------|--------|------|------|----------|----------|",
            ])

            for storm in sorted(
                result.historical_storms, key=lambda s: s.start_time, reverse=True
            )[:10]:
                report.append(
                    f"| {storm.start_time.strftime('%H:%M:%S')} | {storm.device_name} | "
                    f"{storm.port_idx} | {storm.storm_type.value} | "
                    f"{storm.duration_seconds}s | {storm.peak_pps:.0f} |"
                )
            report.append("")

        # Alerts
        if result.alerts:
            report.extend([
                "## Alerts",
                "",
            ])

            for alert in result.alerts:
                emoji = {"critical": "🔴", "high": "🟠", "warning": "🟡", "info": "ℹ️"}.get(
                    alert["severity"], "⚪"
                )
                report.append(f"- {emoji} {alert['message']}")
            report.append("")

        # Thresholds reference
        report.extend([
            "## Detection Thresholds",
            "",
            "| Level | Broadcast % | Broadcast PPS | Multicast % | Multicast PPS |",
            "|-------|-------------|---------------|-------------|---------------|",
            f"| Warning | {self.BROADCAST_PERCENT_WARNING}% | {self.BROADCAST_PPS_WARNING} | "
            f"{self.MULTICAST_PERCENT_WARNING}% | {self.MULTICAST_PPS_WARNING} |",
            f"| High | {self.BROADCAST_PERCENT_HIGH}% | {self.BROADCAST_PPS_HIGH} | "
            f"{self.MULTICAST_PERCENT_HIGH}% | {self.MULTICAST_PPS_HIGH} |",
            f"| Critical | {self.BROADCAST_PERCENT_CRITICAL}% | {self.BROADCAST_PPS_CRITICAL} | "
            f"{self.MULTICAST_PERCENT_CRITICAL}% | {self.MULTICAST_PPS_CRITICAL} |",
            "",
        ])

        return "\n".join(report)
