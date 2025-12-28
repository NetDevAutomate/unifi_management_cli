#!/usr/bin/env python3
"""
MAC Table Analyzer for UniFi Networks.

Provides comprehensive MAC address table analysis including:
- MAC flapping detection (indicates loops or misconfigurations)
- Rogue/unauthorized device detection
- Port capacity analysis (too many MACs on access port)
- MAC table utilization monitoring
- Historical MAC movement tracking
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class MACAlertSeverity(Enum):
    """Severity levels for MAC-related alerts."""

    CRITICAL = "critical"  # Active loop or security breach
    HIGH = "high"  # MAC flapping or unauthorized device
    MEDIUM = "medium"  # Unusual MAC count or minor issues
    LOW = "low"  # Informational
    INFO = "info"


class MACAlertType(Enum):
    """Types of MAC-related alerts."""

    FLAPPING = "mac_flapping"
    UNAUTHORIZED = "unauthorized_mac"
    EXCESSIVE_MACS = "excessive_macs_on_port"
    TABLE_FULL = "mac_table_near_capacity"
    DUPLICATE_MAC = "duplicate_mac_address"
    VENDOR_MISMATCH = "vendor_mismatch"  # MAC doesn't match expected vendor


@dataclass
class MACTableEntry:
    """Represents a single MAC table entry."""

    mac_address: str
    vlan_id: int
    port_idx: int
    device_id: str
    device_name: str
    entry_type: str  # 'dynamic', 'static', 'secure'
    age_seconds: int
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    vendor: Optional[str] = None
    hostname: Optional[str] = None
    ip_address: Optional[str] = None

    @property
    def is_multicast(self) -> bool:
        """Check if MAC is multicast (first octet LSB is 1)."""
        try:
            first_octet = int(self.mac_address.replace(":", "")[:2], 16)
            return bool(first_octet & 0x01)
        except (ValueError, IndexError):
            return False

    @property
    def is_broadcast(self) -> bool:
        """Check if MAC is broadcast."""
        return self.mac_address.upper().replace(":", "") == "FFFFFFFFFFFF"

    @property
    def oui(self) -> str:
        """Get the OUI (first 3 octets) of the MAC address."""
        return self.mac_address.upper().replace(":", "")[:6]


@dataclass
class MACFlappingEvent:
    """Records a MAC flapping event."""

    mac_address: str
    vlan_id: int
    from_port: int
    to_port: int
    from_device: str
    to_device: str
    timestamp: datetime = field(default_factory=datetime.now)
    flap_count: int = 1

    @property
    def is_cross_device(self) -> bool:
        """Check if flapping is between different devices (more severe)."""
        return self.from_device != self.to_device


@dataclass
class MACAnalysisResult:
    """Complete MAC table analysis results."""

    timestamp: datetime = field(default_factory=datetime.now)
    total_mac_entries: int = 0
    unique_mac_addresses: int = 0
    dynamic_entries: int = 0
    static_entries: int = 0
    multicast_entries: int = 0

    # Per-device stats
    device_mac_counts: Dict[str, int] = field(default_factory=dict)

    # Per-port stats
    port_mac_counts: Dict[str, Dict[int, int]] = field(default_factory=dict)

    # Alerts and issues
    flapping_events: List[MACFlappingEvent] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)

    # Detailed entries (optional, can be large)
    entries: List[MACTableEntry] = field(default_factory=list)

    # Authorized MAC tracking
    unauthorized_macs: List[MACTableEntry] = field(default_factory=list)

    def add_alert(
        self,
        alert_type: MACAlertType,
        severity: MACAlertSeverity,
        message: str,
        device_id: str = "",
        port_idx: Optional[int] = None,
        mac_address: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an alert to the results."""
        self.alerts.append(
            {
                "type": alert_type.value,
                "severity": severity.value,
                "message": message,
                "device_id": device_id,
                "port_idx": port_idx,
                "mac_address": mac_address,
                "details": details or {},
                "timestamp": datetime.now().isoformat(),
            }
        )

    def get_alerts_by_severity(self, severity: MACAlertSeverity) -> List[Dict[str, Any]]:
        """Get alerts filtered by severity."""
        return [a for a in self.alerts if a["severity"] == severity.value]

    @property
    def has_critical_alerts(self) -> bool:
        """Check if there are any critical alerts."""
        return any(a["severity"] == MACAlertSeverity.CRITICAL.value for a in self.alerts)

    def summary(self) -> Dict[str, Any]:
        """Get summary of analysis results."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_entries": self.total_mac_entries,
            "unique_macs": self.unique_mac_addresses,
            "dynamic": self.dynamic_entries,
            "static": self.static_entries,
            "multicast": self.multicast_entries,
            "devices_analyzed": len(self.device_mac_counts),
            "flapping_events": len(self.flapping_events),
            "total_alerts": len(self.alerts),
            "critical_alerts": len(self.get_alerts_by_severity(MACAlertSeverity.CRITICAL)),
            "high_alerts": len(self.get_alerts_by_severity(MACAlertSeverity.HIGH)),
            "unauthorized_macs": len(self.unauthorized_macs),
        }


class MACTableAnalyzer:
    """
    Comprehensive MAC table analyzer for UniFi networks.

    Detects:
    - MAC flapping (potential loops or attacks)
    - Unauthorized/rogue devices
    - Ports with excessive MAC addresses
    - MAC table capacity issues
    - Duplicate MAC addresses across VLANs
    """

    # Thresholds (configurable)
    DEFAULT_MAX_MACS_PER_ACCESS_PORT = 5  # Expect few MACs on access ports
    DEFAULT_MAX_MACS_PER_TRUNK_PORT = 500  # Trunk ports can have many
    DEFAULT_FLAP_WINDOW_SECONDS = 60  # Time window for flap detection
    DEFAULT_FLAP_THRESHOLD = 3  # Number of moves to consider flapping
    DEFAULT_MAC_TABLE_WARNING_PERCENT = 80  # Warn at 80% capacity

    def __init__(
        self,
        api_client,
        site: str = "default",
        authorized_macs: Optional[Set[str]] = None,
        authorized_ouis: Optional[Set[str]] = None,
    ):
        """
        Initialize MAC Table Analyzer.

        Args:
            api_client: UniFi API client instance
            site: UniFi site name
            authorized_macs: Set of authorized MAC addresses (for rogue detection)
            authorized_ouis: Set of authorized OUI prefixes (vendor filtering)
        """
        self.api_client = api_client
        self.site = site
        self.authorized_macs = authorized_macs or set()
        self.authorized_ouis = authorized_ouis or set()

        # Historical tracking for flap detection
        self._mac_history: Dict[str, List[Tuple[datetime, str, int]]] = defaultdict(list)
        self._last_analysis: Optional[MACAnalysisResult] = None

        # Cache for device info
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._port_profile_cache: Dict[str, str] = {}  # port_key -> profile type

    def _get_devices(self) -> List[Dict[str, Any]]:
        """Get all network devices."""
        try:
            result = self.api_client.get_devices(self.site)
            if result and "data" in result:
                # Cache device info
                for device in result["data"]:
                    self._device_cache[device["_id"]] = device
                return result["data"]
            return []
        except Exception as e:
            logger.error(f"Failed to get devices: {e}")
            return []

    def _get_mac_table(self, device_id: str) -> List[Dict[str, Any]]:
        """Get MAC table for a specific device."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/stat/device/{device_id}"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/stat/device/{device_id}"

            def _fetch():
                return self.api_client.session.get(
                    endpoint, timeout=self.api_client.timeout
                )

            response = self.api_client._retry_request(_fetch)

            if response and response.status_code == 200:
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    device_data = data["data"][0]
                    # MAC table is typically in 'mac_table' or can be derived from port_table
                    return device_data.get("mac_table", [])
            return []

        except Exception as e:
            logger.debug(f"Failed to get MAC table for device {device_id}: {e}")
            return []

    def _get_clients(self) -> Dict[str, Dict[str, Any]]:
        """Get all known clients (for hostname/IP enrichment)."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/stat/sta"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/stat/sta"

            def _fetch():
                return self.api_client.session.get(
                    endpoint, timeout=self.api_client.timeout
                )

            response = self.api_client._retry_request(_fetch)

            clients = {}
            if response and response.status_code == 200:
                data = response.json()
                for client in data.get("data", []):
                    mac = client.get("mac", "").upper()
                    if mac:
                        clients[mac] = client
            return clients

        except Exception as e:
            logger.debug(f"Failed to get clients: {e}")
            return {}

    def _is_access_port(self, device_id: str, port_idx: int) -> bool:
        """Determine if a port is an access port (vs trunk)."""
        device = self._device_cache.get(device_id, {})
        port_overrides = device.get("port_overrides", [])

        for po in port_overrides:
            if po.get("port_idx") == port_idx:
                # Check for trunk indicators
                forward = po.get("forward", "")
                profile = po.get("portconf_id", "").lower()
                tagged_vlans = po.get("tagged_networkconf_ids", [])

                if forward == "all" or "trunk" in profile or len(tagged_vlans) > 1:
                    return False
                return True

        # Default assumption based on port table
        port_table = device.get("port_table", [])
        for pt in port_table:
            if pt.get("port_idx") == port_idx:
                # High-speed ports are often trunks
                if pt.get("speed", 0) >= 10000:
                    return False
                if pt.get("is_uplink", False):
                    return False
        return True

    def _detect_flapping(
        self,
        mac: str,
        device_id: str,
        port_idx: int,
        timestamp: datetime,
    ) -> Optional[MACFlappingEvent]:
        """
        Detect if a MAC address is flapping between ports.

        Returns a flapping event if detected, None otherwise.
        """
        history = self._mac_history[mac]
        window_start = timestamp - timedelta(seconds=self.DEFAULT_FLAP_WINDOW_SECONDS)

        # Add current observation
        history.append((timestamp, device_id, port_idx))

        # Clean old entries
        self._mac_history[mac] = [
            (ts, dev, port) for ts, dev, port in history if ts > window_start
        ]

        # Check for flapping (same MAC seen on different ports recently)
        recent_locations = set()
        for ts, dev, port in self._mac_history[mac]:
            recent_locations.add((dev, port))

        if len(recent_locations) >= self.DEFAULT_FLAP_THRESHOLD:
            # MAC is flapping
            locations = list(recent_locations)
            if len(locations) >= 2:
                from_dev, from_port = locations[-2]
                to_dev, to_port = locations[-1]

                from_name = self._device_cache.get(from_dev, {}).get(
                    "name", self._device_cache.get(from_dev, {}).get("model", from_dev)
                )
                to_name = self._device_cache.get(to_dev, {}).get(
                    "name", self._device_cache.get(to_dev, {}).get("model", to_dev)
                )

                return MACFlappingEvent(
                    mac_address=mac,
                    vlan_id=0,  # Would need VLAN context
                    from_port=from_port,
                    to_port=to_port,
                    from_device=from_name,
                    to_device=to_name,
                    timestamp=timestamp,
                    flap_count=len(self._mac_history[mac]),
                )
        return None

    def analyze(self, include_entries: bool = False) -> MACAnalysisResult:
        """
        Perform comprehensive MAC table analysis.

        Args:
            include_entries: Include full MAC entry details in results

        Returns:
            MACAnalysisResult with analysis findings
        """
        logger.info("Starting MAC table analysis...")
        result = MACAnalysisResult()
        now = datetime.now()

        # Get client info for enrichment
        clients = self._get_clients()

        # Get all devices
        devices = self._get_devices()
        switches = [d for d in devices if d.get("type") == "usw"]

        all_macs: Set[str] = set()
        mac_to_locations: Dict[str, List[Tuple[str, int, int]]] = defaultdict(
            list
        )  # mac -> [(device, port, vlan)]

        for switch in switches:
            device_id = switch["_id"]
            device_name = switch.get("name", switch.get("model", "Unknown"))

            # Get MAC table
            mac_table = self._get_mac_table(device_id)

            # Also check port table for connected MACs
            port_table = switch.get("port_table", [])

            device_mac_count = 0
            port_mac_counts: Dict[int, int] = defaultdict(int)

            # Process MAC table entries
            for entry in mac_table:
                mac = entry.get("mac", "").upper().replace("-", ":")
                if not mac:
                    continue

                port_idx = entry.get("port_idx", entry.get("port", 0))
                vlan_id = entry.get("vlan", entry.get("vlan_id", 1))
                entry_type = entry.get("type", "dynamic")
                age = entry.get("age", 0)

                all_macs.add(mac)
                mac_to_locations[mac].append((device_id, port_idx, vlan_id))
                device_mac_count += 1
                port_mac_counts[port_idx] += 1

                # Create entry object
                mac_entry = MACTableEntry(
                    mac_address=mac,
                    vlan_id=vlan_id,
                    port_idx=port_idx,
                    device_id=device_id,
                    device_name=device_name,
                    entry_type=entry_type,
                    age_seconds=age,
                )

                # Enrich with client info
                if mac in clients:
                    client = clients[mac]
                    mac_entry.hostname = client.get("hostname", client.get("name"))
                    mac_entry.ip_address = client.get("ip")

                # Track entry types
                if mac_entry.is_multicast:
                    result.multicast_entries += 1
                elif entry_type == "static":
                    result.static_entries += 1
                else:
                    result.dynamic_entries += 1

                # Check for flapping
                flap_event = self._detect_flapping(mac, device_id, port_idx, now)
                if flap_event:
                    result.flapping_events.append(flap_event)
                    severity = (
                        MACAlertSeverity.CRITICAL
                        if flap_event.is_cross_device
                        else MACAlertSeverity.HIGH
                    )
                    result.add_alert(
                        MACAlertType.FLAPPING,
                        severity,
                        f"MAC {mac} flapping between {flap_event.from_device}:{flap_event.from_port} "
                        f"and {flap_event.to_device}:{flap_event.to_port}",
                        device_id=device_id,
                        port_idx=port_idx,
                        mac_address=mac,
                        details={
                            "flap_count": flap_event.flap_count,
                            "is_cross_device": flap_event.is_cross_device,
                        },
                    )

                # Check for unauthorized MACs
                if self.authorized_macs or self.authorized_ouis:
                    is_authorized = (
                        mac in self.authorized_macs
                        or mac_entry.oui in self.authorized_ouis
                    )
                    if not is_authorized and not mac_entry.is_multicast:
                        result.unauthorized_macs.append(mac_entry)

                if include_entries:
                    result.entries.append(mac_entry)

            # Check for excessive MACs per port
            for port_idx, mac_count in port_mac_counts.items():
                is_access = self._is_access_port(device_id, port_idx)
                threshold = (
                    self.DEFAULT_MAX_MACS_PER_ACCESS_PORT
                    if is_access
                    else self.DEFAULT_MAX_MACS_PER_TRUNK_PORT
                )

                if mac_count > threshold:
                    severity = (
                        MACAlertSeverity.HIGH if is_access else MACAlertSeverity.MEDIUM
                    )
                    result.add_alert(
                        MACAlertType.EXCESSIVE_MACS,
                        severity,
                        f"Port {port_idx} on {device_name} has {mac_count} MACs "
                        f"(threshold: {threshold})",
                        device_id=device_id,
                        port_idx=port_idx,
                        details={
                            "mac_count": mac_count,
                            "threshold": threshold,
                            "is_access_port": is_access,
                        },
                    )

            result.device_mac_counts[device_name] = device_mac_count
            result.port_mac_counts[device_name] = dict(port_mac_counts)

        # Check for duplicate MACs across VLANs (can indicate misconfiguration)
        for mac, locations in mac_to_locations.items():
            if len(locations) > 1:
                # Check if same MAC on different VLANs on same device
                device_vlans = defaultdict(set)
                for dev, port, vlan in locations:
                    device_vlans[dev].add(vlan)

                for dev, vlans in device_vlans.items():
                    if len(vlans) > 1:
                        result.add_alert(
                            MACAlertType.DUPLICATE_MAC,
                            MACAlertSeverity.MEDIUM,
                            f"MAC {mac} appears on multiple VLANs: {vlans}",
                            device_id=dev,
                            mac_address=mac,
                            details={"vlans": list(vlans)},
                        )

        # Add unauthorized MAC alerts
        if result.unauthorized_macs:
            for entry in result.unauthorized_macs[:10]:  # Limit alerts
                result.add_alert(
                    MACAlertType.UNAUTHORIZED,
                    MACAlertSeverity.HIGH,
                    f"Unauthorized MAC {entry.mac_address} on {entry.device_name} port {entry.port_idx}",
                    device_id=entry.device_id,
                    port_idx=entry.port_idx,
                    mac_address=entry.mac_address,
                    details={
                        "hostname": entry.hostname,
                        "ip": entry.ip_address,
                        "oui": entry.oui,
                    },
                )

        # Set totals
        result.total_mac_entries = sum(result.device_mac_counts.values())
        result.unique_mac_addresses = len(all_macs)

        self._last_analysis = result
        logger.info(
            f"MAC analysis complete: {result.total_mac_entries} entries, "
            f"{len(result.alerts)} alerts, {len(result.flapping_events)} flapping events"
        )

        return result

    def generate_report(self, result: Optional[MACAnalysisResult] = None) -> str:
        """Generate a human-readable MAC analysis report."""
        if result is None:
            result = self._last_analysis
        if result is None:
            return "No analysis results available. Run analyze() first."

        report = [
            "# MAC Table Analysis Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total MAC Entries | {result.total_mac_entries} |",
            f"| Unique MAC Addresses | {result.unique_mac_addresses} |",
            f"| Dynamic Entries | {result.dynamic_entries} |",
            f"| Static Entries | {result.static_entries} |",
            f"| Multicast Entries | {result.multicast_entries} |",
            f"| Devices Analyzed | {len(result.device_mac_counts)} |",
            "",
        ]

        # Alerts section
        if result.alerts:
            report.extend(
                [
                    "## Alerts",
                    "",
                ]
            )

            severity_order = ["critical", "high", "medium", "low", "info"]
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
                "info": "⚪",
            }

            for severity in severity_order:
                alerts = [a for a in result.alerts if a["severity"] == severity]
                if alerts:
                    report.append(
                        f"### {severity_emoji[severity]} {severity.upper()} ({len(alerts)})"
                    )
                    report.append("")
                    for alert in alerts:
                        report.append(f"- **{alert['type']}**: {alert['message']}")
                    report.append("")

        # Flapping events
        if result.flapping_events:
            report.extend(
                [
                    "## MAC Flapping Events",
                    "",
                    "| MAC Address | From | To | Flap Count | Cross-Device |",
                    "|-------------|------|-----|------------|--------------|",
                ]
            )
            for event in result.flapping_events:
                cross = "⚠️ Yes" if event.is_cross_device else "No"
                report.append(
                    f"| {event.mac_address} | {event.from_device}:{event.from_port} | "
                    f"{event.to_device}:{event.to_port} | {event.flap_count} | {cross} |"
                )
            report.append("")

        # Per-device breakdown
        if result.device_mac_counts:
            report.extend(
                [
                    "## MAC Count by Device",
                    "",
                    "| Device | MAC Count |",
                    "|--------|-----------|",
                ]
            )
            for device, count in sorted(
                result.device_mac_counts.items(), key=lambda x: x[1], reverse=True
            ):
                report.append(f"| {device} | {count} |")
            report.append("")

        # Unauthorized MACs
        if result.unauthorized_macs:
            report.extend(
                [
                    "## Unauthorized MAC Addresses",
                    "",
                    "| MAC | Device | Port | Hostname | IP |",
                    "|-----|--------|------|----------|-----|",
                ]
            )
            for entry in result.unauthorized_macs[:20]:
                report.append(
                    f"| {entry.mac_address} | {entry.device_name} | {entry.port_idx} | "
                    f"{entry.hostname or 'N/A'} | {entry.ip_address or 'N/A'} |"
                )
            if len(result.unauthorized_macs) > 20:
                report.append(
                    f"| ... | *{len(result.unauthorized_macs) - 20} more entries* | | | |"
                )
            report.append("")

        return "\n".join(report)
