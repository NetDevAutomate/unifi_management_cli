"""Pydantic models for network analysis tools."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any


# =============================================================================
# IP Conflict Detection Models
# =============================================================================


class ConflictingClient(BaseModel):
    """A client device involved in an IP conflict."""

    mac_address: str = Field(description='MAC address of the client')
    hostname: str | None = Field(description='Hostname of the client')
    name: str | None = Field(description='Friendly name of the client')
    is_wired: bool = Field(description='Whether client is connected via wire')
    is_guest: bool = Field(default=False, description='Whether client is a guest')
    connected_device: str | None = Field(description='Switch/AP the client is connected to')
    connected_port: str | None = Field(description='Port or wireless interface')
    last_seen: datetime | None = Field(description='When client was last seen')
    vlan: int | None = Field(description='VLAN the client is on')


class IPConflict(BaseModel):
    """An IP address conflict between multiple devices."""

    ip_address: str = Field(description='The conflicting IP address')
    clients: list[ConflictingClient] = Field(description='Clients claiming this IP')
    conflict_count: int = Field(description='Number of devices with this IP')
    severity: str = Field(description='Severity: low, medium, high, critical')
    vlan_mismatch: bool = Field(default=False, description='If clients are on different VLANs')


class IPConflictReport(BaseModel):
    """Report of all IP conflicts in the network."""

    timestamp: str = Field(description='When the scan was performed')
    total_clients_scanned: int = Field(description='Total clients analyzed')
    conflicts_found: int = Field(description='Number of IP conflicts detected')
    conflicts: list[IPConflict] = Field(description='List of all IP conflicts')
    healthy: bool = Field(description='True if no conflicts found')
    recommendations: list[str] = Field(default_factory=list, description='Suggested actions')


# =============================================================================
# Storm Detection Models
# =============================================================================


class StormSeverity(str, Enum):
    """Storm severity levels."""

    INFO = 'info'
    WARNING = 'warning'
    HIGH = 'high'
    CRITICAL = 'critical'


class StormType(str, Enum):
    """Types of network storms."""

    BROADCAST = 'broadcast'
    MULTICAST = 'multicast'
    UNKNOWN_UNICAST = 'unknown_unicast'
    MIXED = 'mixed'


class PortTrafficMetrics(BaseModel):
    """Traffic metrics for a port."""

    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    rx_packets: int = Field(default=0, description='Received packets')
    tx_packets: int = Field(default=0, description='Transmitted packets')
    rx_broadcast: int = Field(default=0, description='Received broadcast packets')
    tx_broadcast: int = Field(default=0, description='Transmitted broadcast packets')
    rx_multicast: int = Field(default=0, description='Received multicast packets')
    tx_multicast: int = Field(default=0, description='Transmitted multicast packets')
    broadcast_percent: float = Field(default=0.0, description='Broadcast traffic percentage')
    multicast_percent: float = Field(default=0.0, description='Multicast traffic percentage')


class StormEvent(BaseModel):
    """A detected storm event."""

    device_id: str = Field(description='Device ID where storm detected')
    device_name: str = Field(description='Device name')
    port_idx: int | None = Field(description='Port index if port-specific')
    storm_type: StormType = Field(description='Type of storm')
    severity: StormSeverity = Field(description='Severity level')
    broadcast_percent: float = Field(description='Broadcast traffic percentage')
    multicast_percent: float = Field(description='Multicast traffic percentage')
    affected_ports: list[int] = Field(default_factory=list, description='Ports affected')
    is_active: bool = Field(default=True, description='Whether storm is ongoing')
    recommendation: str = Field(description='Recommended action')


class StormDetectionReport(BaseModel):
    """Storm detection analysis report."""

    timestamp: str = Field(description='When analysis was performed')
    devices_analyzed: int = Field(description='Number of devices checked')
    ports_analyzed: int = Field(description='Number of ports checked')
    storms_detected: int = Field(description='Number of storm events')
    active_storms: list[StormEvent] = Field(description='Currently active storms')
    high_risk_ports: list[PortTrafficMetrics] = Field(description='Ports with elevated traffic')
    network_healthy: bool = Field(description='True if no storms detected')
    thresholds: dict[str, float] = Field(description='Detection thresholds used')


# =============================================================================
# VLAN Diagnostics Models
# =============================================================================


class VLANInfo(BaseModel):
    """Information about a VLAN."""

    vlan_id: int = Field(description='VLAN ID')
    name: str = Field(description='VLAN name')
    subnet: str | None = Field(description='IP subnet')
    gateway: str | None = Field(description='Gateway IP')
    enabled: bool = Field(default=True, description='Whether VLAN is enabled')
    dhcp_enabled: bool = Field(default=False, description='Whether DHCP is enabled')
    client_count: int = Field(default=0, description='Clients on this VLAN')


class PortVLANConfig(BaseModel):
    """VLAN configuration for a switch port."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    native_vlan: int = Field(description='Native/untagged VLAN')
    tagged_vlans: list[int] = Field(default_factory=list, description='Tagged VLANs')
    profile_name: str = Field(description='Port profile name')
    is_trunk: bool = Field(description='Whether port is a trunk')


class VLANDiagnosticCheck(BaseModel):
    """Result of a single VLAN diagnostic check."""

    check_name: str = Field(description='Name of the check')
    status: str = Field(description='PASS, FAIL, or WARNING')
    message: str = Field(description='Human-readable result')
    details: dict[str, Any] = Field(default_factory=dict, description='Additional details')
    recommendations: list[str] = Field(default_factory=list, description='Suggested fixes')


class VLANDiagnosticReport(BaseModel):
    """Comprehensive VLAN diagnostic report."""

    timestamp: str = Field(description='When diagnostics ran')
    vlans_configured: int = Field(description='Number of VLANs configured')
    vlans: list[VLANInfo] = Field(description='All configured VLANs')
    port_configs: list[PortVLANConfig] = Field(description='Port VLAN configurations')
    diagnostic_checks: list[VLANDiagnosticCheck] = Field(description='Diagnostic results')
    issues_found: int = Field(description='Number of issues detected')
    warnings_found: int = Field(description='Number of warnings')
    overall_health: str = Field(description='HEALTHY, DEGRADED, or CRITICAL')


# =============================================================================
# Link Quality Models (P2)
# =============================================================================


class PortLinkQuality(BaseModel):
    """Link quality metrics for a port."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    link_speed: str = Field(description='Current link speed')
    full_duplex: bool = Field(description='Full duplex enabled')
    stp_state: str | None = Field(description='STP port state')
    poe_enabled: bool = Field(default=False, description='PoE enabled')
    poe_power: float | None = Field(description='PoE power in watts')
    rx_errors: int = Field(default=0, description='Receive errors')
    tx_errors: int = Field(default=0, description='Transmit errors')
    rx_dropped: int = Field(default=0, description='Receive dropped')
    tx_dropped: int = Field(default=0, description='Transmit dropped')
    crc_errors: int = Field(default=0, description='CRC errors')
    collisions: int = Field(default=0, description='Collisions')
    utilization_percent: float = Field(default=0.0, description='Port utilization')
    health_score: int = Field(description='Health score 0-100')
    issues: list[str] = Field(default_factory=list, description='Detected issues')


class LinkQualityReport(BaseModel):
    """Link quality analysis report."""

    timestamp: str = Field(description='When analysis was performed')
    devices_analyzed: int = Field(description='Number of devices checked')
    ports_analyzed: int = Field(description='Number of ports checked')
    healthy_ports: int = Field(description='Ports with good health')
    degraded_ports: int = Field(description='Ports with issues')
    critical_ports: int = Field(description='Ports with critical issues')
    port_metrics: list[PortLinkQuality] = Field(description='All port metrics')
    overall_health: str = Field(description='HEALTHY, DEGRADED, or CRITICAL')
    top_issues: list[str] = Field(description='Most common issues found')


# =============================================================================
# Capacity Planning Models (P2)
# =============================================================================


class DeviceCapacity(BaseModel):
    """Capacity metrics for a device."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    model: str = Field(description='Device model')
    total_ports: int = Field(description='Total port count')
    used_ports: int = Field(description='Ports in use')
    available_ports: int = Field(description='Available ports')
    utilization_percent: float = Field(description='Port utilization %')
    poe_budget_watts: float | None = Field(description='Total PoE budget')
    poe_used_watts: float | None = Field(description='PoE power used')
    poe_available_watts: float | None = Field(description='Available PoE power')
    poe_utilization_percent: float | None = Field(description='PoE utilization %')
    uplink_capacity_gbps: float = Field(description='Total uplink capacity')
    recommendation: str | None = Field(description='Capacity recommendation')


class CapacityReport(BaseModel):
    """Network capacity planning report."""

    timestamp: str = Field(description='When analysis was performed')
    total_devices: int = Field(description='Total devices analyzed')
    total_ports: int = Field(description='Total ports in network')
    used_ports: int = Field(description='Total ports in use')
    available_ports: int = Field(description='Total available ports')
    overall_utilization: float = Field(description='Overall port utilization %')
    total_poe_budget: float = Field(description='Total PoE budget watts')
    total_poe_used: float = Field(description='Total PoE used watts')
    devices: list[DeviceCapacity] = Field(description='Per-device capacity')
    bottlenecks: list[str] = Field(description='Identified bottlenecks')
    expansion_needed: bool = Field(description='Whether expansion is recommended')
    recommendations: list[str] = Field(description='Capacity recommendations')


# =============================================================================
# LAG Monitoring Models (P2)
# =============================================================================


class LAGStatus(str, Enum):
    """LAG health status."""

    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    CRITICAL = 'critical'
    INACTIVE = 'inactive'
    MISCONFIGURED = 'misconfigured'


class LACPState(str, Enum):
    """LACP port states."""

    ACTIVE = 'active'
    PASSIVE = 'passive'
    SUSPENDED = 'suspended'
    DEFAULTED = 'defaulted'
    EXPIRED = 'expired'
    COLLECTING = 'collecting'
    DISTRIBUTING = 'distributing'


class LAGMember(BaseModel):
    """A single LAG member port."""

    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    is_active: bool = Field(default=True, description='Whether member is active')
    link_up: bool = Field(default=True, description='Whether link is up')
    speed_mbps: int = Field(default=0, description='Port speed in Mbps')
    lacp_state: LACPState = Field(default=LACPState.ACTIVE, description='LACP state')
    rx_bytes: int = Field(default=0, description='Bytes received')
    tx_bytes: int = Field(default=0, description='Bytes transmitted')
    rx_packets: int = Field(default=0, description='Packets received')
    tx_packets: int = Field(default=0, description='Packets transmitted')
    rx_errors: int = Field(default=0, description='Receive errors')
    tx_errors: int = Field(default=0, description='Transmit errors')
    load_percent: float = Field(default=0.0, description='Traffic load percentage')


class LAGGroup(BaseModel):
    """A Link Aggregation Group."""

    lag_id: str = Field(description='LAG identifier')
    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    lag_name: str = Field(default='', description='LAG name')
    members: list[LAGMember] = Field(default_factory=list, description='LAG members')
    expected_members: int = Field(default=0, description='Expected member count')
    active_members: int = Field(default=0, description='Active member count')
    total_bandwidth_mbps: int = Field(default=0, description='Total bandwidth')
    active_bandwidth_mbps: int = Field(default=0, description='Active bandwidth')
    total_rx_bytes: int = Field(default=0, description='Total received bytes')
    total_tx_bytes: int = Field(default=0, description='Total transmitted bytes')
    partner_system_id: str = Field(default='', description='LACP partner system ID')
    partner_device_name: str = Field(default='', description='Partner device name')
    status: LAGStatus = Field(default=LAGStatus.HEALTHY, description='LAG health status')
    efficiency_percent: float = Field(default=0.0, description='Bandwidth efficiency')
    load_balance_score: float = Field(default=100.0, description='Load balance score 0-100')
    issues: list[str] = Field(default_factory=list, description='Detected issues')


class LAGHealthReport(BaseModel):
    """LAG health monitoring report."""

    timestamp: str = Field(description='When analysis was performed')
    devices_analyzed: int = Field(default=0, description='Devices checked')
    total_lags: int = Field(default=0, description='Total LAGs found')
    healthy_lags: int = Field(default=0, description='Healthy LAGs')
    degraded_lags: int = Field(default=0, description='Degraded LAGs')
    critical_lags: int = Field(default=0, description='Critical LAGs')
    lag_groups: list[LAGGroup] = Field(default_factory=list, description='LAG details')
    total_lag_bandwidth_gbps: float = Field(default=0.0, description='Total LAG bandwidth')
    active_lag_bandwidth_gbps: float = Field(default=0.0, description='Active LAG bandwidth')
    issues: list[dict[str, Any]] = Field(default_factory=list, description='All issues')
    recommendations: list[str] = Field(default_factory=list, description='Recommendations')
    network_healthy: bool = Field(default=True, description='True if all LAGs healthy')


# =============================================================================
# QoS Validation Models (P2)
# =============================================================================


class QoSSeverity(str, Enum):
    """QoS issue severity levels."""

    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'


class QoSFinding(BaseModel):
    """A QoS configuration finding."""

    severity: QoSSeverity = Field(description='Finding severity')
    category: str = Field(description='Finding category')
    message: str = Field(description='Human-readable message')
    device_id: str | None = Field(default=None, description='Affected device')
    device_name: str | None = Field(default=None, description='Device name')
    port_idx: int | None = Field(default=None, description='Affected port')
    current_value: str | None = Field(default=None, description='Current setting')
    expected_value: str | None = Field(default=None, description='Expected setting')
    recommendation: str = Field(description='Recommended action')


class PortQoSConfig(BaseModel):
    """QoS configuration for a port."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    dscp_trust: bool = Field(default=False, description='DSCP trust enabled')
    cos_trust: bool = Field(default=False, description='CoS trust enabled')
    storm_control_enabled: bool = Field(default=False, description='Storm control')
    rate_limit_in: int | None = Field(default=None, description='Ingress rate limit')
    rate_limit_out: int | None = Field(default=None, description='Egress rate limit')
    voice_vlan: int | None = Field(default=None, description='Voice VLAN ID')
    qos_profile: str | None = Field(default=None, description='QoS profile name')


class QoSValidationReport(BaseModel):
    """QoS validation report."""

    timestamp: str = Field(description='When validation was performed')
    devices_analyzed: int = Field(description='Devices checked')
    ports_analyzed: int = Field(description='Ports checked')
    findings: list[QoSFinding] = Field(default_factory=list, description='All findings')
    critical_count: int = Field(default=0, description='Critical issues')
    error_count: int = Field(default=0, description='Error issues')
    warning_count: int = Field(default=0, description='Warnings')
    info_count: int = Field(default=0, description='Info items')
    port_configs: list[PortQoSConfig] = Field(description='Port QoS configs')
    voice_vlan_configured: bool = Field(default=False, description='Voice VLAN exists')
    dscp_trust_enabled_count: int = Field(default=0, description='Ports with DSCP trust')
    overall_health: str = Field(description='HEALTHY, DEGRADED, or CRITICAL')
    recommendations: list[str] = Field(default_factory=list, description='Recommendations')


# =============================================================================
# MAC Analyzer Models (P3)
# =============================================================================


class MACAlertSeverity(str, Enum):
    """Severity levels for MAC table alerts."""

    INFO = 'info'
    WARNING = 'warning'
    HIGH = 'high'
    CRITICAL = 'critical'


class MACAlertType(str, Enum):
    """Types of MAC table alerts."""

    FLAPPING = 'flapping'
    UNAUTHORIZED = 'unauthorized'
    EXCESSIVE_MACS = 'excessive_macs'
    AGING_ISSUE = 'aging_issue'


class MACTableEntry(BaseModel):
    """A single MAC address table entry."""

    mac_address: str = Field(description='MAC address')
    device_id: str = Field(description='Device ID where MAC is learned')
    device_name: str = Field(description='Device name')
    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    vlan_id: int = Field(default=1, description='VLAN ID')
    is_static: bool = Field(default=False, description='Static MAC entry')
    age_seconds: int | None = Field(default=None, description='Entry age in seconds')
    last_seen: str | None = Field(default=None, description='When MAC was last seen')


class MACFlappingEvent(BaseModel):
    """A detected MAC address flapping event."""

    mac_address: str = Field(description='Flapping MAC address')
    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    ports_involved: list[int] = Field(description='Ports where MAC was seen')
    flap_count: int = Field(description='Number of flaps detected')
    window_seconds: int = Field(description='Detection window')
    first_seen: str = Field(description='First flap timestamp')
    last_seen: str = Field(description='Last flap timestamp')
    severity: MACAlertSeverity = Field(description='Alert severity')
    recommendation: str = Field(description='Recommended action')


class MACAlert(BaseModel):
    """A MAC table alert."""

    alert_type: MACAlertType = Field(description='Type of alert')
    severity: MACAlertSeverity = Field(description='Alert severity')
    message: str = Field(description='Human-readable message')
    device_id: str = Field(description='Affected device')
    device_name: str = Field(description='Device name')
    port_idx: int | None = Field(default=None, description='Affected port')
    mac_address: str | None = Field(default=None, description='Related MAC')
    details: dict[str, Any] = Field(default_factory=dict, description='Additional details')
    recommendation: str = Field(description='Recommended action')


class PortMACCount(BaseModel):
    """MAC count statistics for a port."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    port_idx: int = Field(description='Port index')
    port_name: str = Field(description='Port name')
    mac_count: int = Field(description='Number of MACs on port')
    is_trunk: bool = Field(default=False, description='Whether port is trunk')
    is_uplink: bool = Field(default=False, description='Whether port is uplink')
    exceeds_threshold: bool = Field(default=False, description='Exceeds access port limit')


class MACAnalysisReport(BaseModel):
    """MAC table analysis report."""

    timestamp: str = Field(description='When analysis was performed')
    devices_analyzed: int = Field(description='Number of devices checked')
    total_mac_entries: int = Field(description='Total MAC entries found')
    unique_mac_addresses: int = Field(description='Unique MACs in network')
    static_mac_count: int = Field(description='Number of static MAC entries')
    flapping_events: list[MACFlappingEvent] = Field(
        default_factory=list, description='Detected flapping events'
    )
    alerts: list[MACAlert] = Field(default_factory=list, description='All alerts')
    port_mac_counts: list[PortMACCount] = Field(
        default_factory=list, description='Per-port MAC counts'
    )
    ports_exceeding_threshold: int = Field(default=0, description='Ports with excessive MACs')
    critical_alerts: int = Field(default=0, description='Critical alert count')
    warning_alerts: int = Field(default=0, description='Warning alert count')
    network_healthy: bool = Field(default=True, description='True if no critical issues')
    recommendations: list[str] = Field(default_factory=list, description='Recommendations')


# =============================================================================
# Firmware Advisor Models (P3)
# =============================================================================


class FirmwareStatus(str, Enum):
    """Firmware security status."""

    CURRENT = 'current'
    UPDATE_AVAILABLE = 'update_available'
    SECURITY_UPDATE = 'security_update'
    CRITICAL = 'critical'
    EOL = 'end_of_life'
    UNKNOWN = 'unknown'


class UpdatePriority(str, Enum):
    """Firmware update priority levels."""

    CRITICAL = 'critical'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    NONE = 'none'


class KnownVulnerability(BaseModel):
    """A known firmware vulnerability."""

    cve_id: str = Field(description='CVE identifier')
    severity: str = Field(description='Severity: critical, high, medium, low')
    description: str = Field(description='Vulnerability description')
    affected_versions: list[str] = Field(description='Version patterns affected')
    fixed_version: str = Field(description='Version where fix was applied')
    disclosure_date: str = Field(description='When vulnerability was disclosed')
    references: list[str] = Field(default_factory=list, description='Reference URLs')


class DeviceFirmwareInfo(BaseModel):
    """Firmware information for a single device."""

    device_id: str = Field(description='Device ID')
    device_name: str = Field(description='Device name')
    model: str = Field(description='Device model')
    device_type: str = Field(description='Device type')
    current_version: str = Field(description='Currently installed firmware')
    latest_version: str = Field(default='', description='Latest available firmware')
    status: FirmwareStatus = Field(default=FirmwareStatus.UNKNOWN, description='Firmware status')
    update_priority: UpdatePriority = Field(
        default=UpdatePriority.NONE, description='Update priority'
    )
    vulnerabilities: list[KnownVulnerability] = Field(
        default_factory=list, description='Known vulnerabilities'
    )
    uptime_days: int = Field(default=0, description='Device uptime in days')
    auto_upgrade_enabled: bool = Field(default=False, description='Auto-upgrade enabled')
    family: str = Field(default='', description='Device family for consistency')
    family_version_mismatch: bool = Field(default=False, description='Version differs from family')
    needs_update: bool = Field(default=False, description='Whether update is needed')
    has_critical_vulns: bool = Field(default=False, description='Has critical vulnerabilities')


class FirmwareRecommendation(BaseModel):
    """A firmware update recommendation."""

    priority: str = Field(description='Priority: critical, high, medium, low, info')
    message: str = Field(description='Recommendation message')
    device_name: str = Field(default='', description='Affected device')
    action: str = Field(default='', description='Recommended action')


class FirmwareSecurityReport(BaseModel):
    """Complete firmware security assessment report."""

    timestamp: str = Field(description='When analysis was performed')
    devices_checked: int = Field(description='Number of devices analyzed')
    security_score: int = Field(description='Security score 0-100')

    # Status counts
    current_count: int = Field(default=0, description='Devices on current firmware')
    update_available_count: int = Field(default=0, description='Devices with updates available')
    security_update_count: int = Field(default=0, description='Devices needing security updates')
    critical_count: int = Field(default=0, description='Devices with critical vulnerabilities')
    eol_count: int = Field(default=0, description='End-of-life devices')

    # Priority counts
    critical_priority: int = Field(default=0, description='Critical priority updates')
    high_priority: int = Field(default=0, description='High priority updates')
    medium_priority: int = Field(default=0, description='Medium priority updates')

    # Vulnerability summary
    total_vulnerabilities: int = Field(default=0, description='Total vulnerabilities')
    critical_vulnerabilities: int = Field(default=0, description='Critical vulnerabilities')

    # Device details
    devices: list[DeviceFirmwareInfo] = Field(description='Per-device firmware info')

    # Consistency
    inconsistent_families: list[str] = Field(
        default_factory=list, description='Families with version mismatches'
    )

    # Recommendations
    recommendations: list[FirmwareRecommendation] = Field(
        default_factory=list, description='Prioritized recommendations'
    )

    # Overall health
    network_healthy: bool = Field(default=True, description='True if no critical issues')
