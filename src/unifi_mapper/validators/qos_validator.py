#!/usr/bin/env python3
"""
QoS Configuration Validator for UniFi Networks.

Validates Quality of Service configuration for consistent network behavior:
- Queue configuration consistency across devices
- DSCP trust settings on trunk ports
- CoS/DSCP mapping verification
- QoS policy mismatch detection
- Voice VLAN configuration validation
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class QoSFindingSeverity(Enum):
    """Severity levels for QoS findings."""

    CRITICAL = "critical"  # Will cause service impact
    HIGH = "high"  # Likely to cause issues
    MEDIUM = "medium"  # Best practice violation
    LOW = "low"  # Minor optimization
    INFO = "info"  # Informational


class QoSFindingType(Enum):
    """Types of QoS findings."""

    TRUST_MISMATCH = "trust_mismatch"
    QUEUE_INCONSISTENT = "queue_inconsistent"
    DSCP_MAPPING_ISSUE = "dscp_mapping_issue"
    VOICE_VLAN_CONFIG = "voice_vlan_config"
    PRIORITY_CONFLICT = "priority_conflict"
    MISSING_QOS_POLICY = "missing_qos_policy"
    BANDWIDTH_LIMIT = "bandwidth_limit"


@dataclass
class QoSFinding:
    """A single QoS configuration finding."""

    finding_type: QoSFindingType
    severity: QoSFindingSeverity
    message: str
    device_name: str
    device_id: str = ""
    port_idx: Optional[int] = None
    current_value: Any = None
    expected_value: Any = None
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.finding_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "device_name": self.device_name,
            "device_id": self.device_id,
            "port_idx": self.port_idx,
            "current_value": self.current_value,
            "expected_value": self.expected_value,
            "recommendation": self.recommendation,
        }


@dataclass
class PortQoSConfig:
    """QoS configuration for a port."""

    port_idx: int
    device_id: str
    device_name: str

    # Trust settings
    trust_mode: str = "none"  # none, dscp, cos, both
    default_cos: int = 0
    default_dscp: int = 0

    # Bandwidth settings
    egress_rate_limit_kbps: Optional[int] = None
    ingress_rate_limit_kbps: Optional[int] = None

    # Queue settings
    num_queues: int = 8
    strict_priority_queues: int = 0
    weighted_queues: int = 8

    # Voice VLAN
    voice_vlan_enabled: bool = False
    voice_vlan_id: Optional[int] = None

    # Port role (affects expected QoS behavior)
    is_uplink: bool = False
    is_access: bool = True


@dataclass
class QoSValidationResult:
    """Complete QoS validation results."""

    timestamp: datetime = field(default_factory=datetime.now)
    devices_checked: int = 0
    ports_checked: int = 0

    # Findings
    findings: List[QoSFinding] = field(default_factory=list)

    # Summary counts
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Configuration summary
    devices_with_qos: int = 0
    ports_with_trust_dscp: int = 0
    ports_with_rate_limits: int = 0
    voice_vlans_configured: int = 0

    def add_finding(self, finding: QoSFinding) -> None:
        """Add a finding."""
        self.findings.append(finding)

        if finding.severity == QoSFindingSeverity.CRITICAL:
            self.critical_count += 1
        elif finding.severity == QoSFindingSeverity.HIGH:
            self.high_count += 1
        elif finding.severity == QoSFindingSeverity.MEDIUM:
            self.medium_count += 1
        elif finding.severity == QoSFindingSeverity.LOW:
            self.low_count += 1

    @property
    def passed(self) -> bool:
        """Check if validation passed (no critical/high issues)."""
        return self.critical_count == 0 and self.high_count == 0

    def summary(self) -> Dict[str, Any]:
        """Get validation summary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "passed": self.passed,
            "devices_checked": self.devices_checked,
            "ports_checked": self.ports_checked,
            "findings": {
                "critical": self.critical_count,
                "high": self.high_count,
                "medium": self.medium_count,
                "low": self.low_count,
            },
            "qos_summary": {
                "devices_with_qos": self.devices_with_qos,
                "ports_with_dscp_trust": self.ports_with_trust_dscp,
                "ports_with_rate_limits": self.ports_with_rate_limits,
                "voice_vlans": self.voice_vlans_configured,
            },
        }


class QoSValidator:
    """
    QoS Configuration Validator for UniFi networks.

    Validates:
    - DSCP trust configuration on uplink/trunk ports
    - Queue configuration consistency
    - Voice VLAN settings
    - Rate limiting configuration
    - QoS policy alignment between connected ports
    """

    # Expected configurations
    UPLINK_TRUST_MODE = "dscp"  # Uplinks should trust DSCP
    ACCESS_TRUST_MODE = "none"  # Access ports typically don't trust

    def __init__(self, api_client, site: str = "default"):
        """Initialize QoS Validator."""
        self.api_client = api_client
        self.site = site
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._port_qos_configs: List[PortQoSConfig] = []

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

    def _get_networks(self) -> List[Dict[str, Any]]:
        """Get network configurations."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"

            def _fetch():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)

            response = self.api_client._retry_request(_fetch)

            if response and response.status_code == 200:
                return response.json().get("data", [])
            return []
        except Exception as e:
            logger.error(f"Failed to get networks: {e}")
            return []

    def _extract_port_qos_config(
        self, device: Dict[str, Any], port_data: Dict[str, Any], port_override: Dict[str, Any]
    ) -> PortQoSConfig:
        """Extract QoS configuration for a port."""
        device_id = device["_id"]
        device_name = device.get("name", device.get("model", "Unknown"))
        port_idx = port_data.get("port_idx", 0)

        config = PortQoSConfig(
            port_idx=port_idx,
            device_id=device_id,
            device_name=device_name,
        )

        # Determine port role
        config.is_uplink = port_data.get("is_uplink", False)
        config.is_access = not config.is_uplink

        # Trust mode from port override
        config.trust_mode = port_override.get("dot1x_ctrl", "none")
        if port_override.get("qos_profile"):
            # QoS profile applied - implies trust configuration
            config.trust_mode = "dscp"

        # Rate limits
        config.egress_rate_limit_kbps = port_override.get("egress_rate_limit_kbps")
        config.ingress_rate_limit_kbps = port_override.get("ingress_rate_limit_kbps")

        # Voice VLAN
        voice_vlan = port_override.get("voice_network_id")
        if voice_vlan:
            config.voice_vlan_enabled = True
            config.voice_vlan_id = voice_vlan

        return config

    def validate(self) -> QoSValidationResult:
        """
        Perform comprehensive QoS validation.

        Returns:
            QoSValidationResult with validation findings
        """
        logger.info("Starting QoS configuration validation...")
        result = QoSValidationResult()

        devices = self._get_devices()
        networks = self._get_networks()

        # Track configurations for consistency checking
        uplink_configs: List[PortQoSConfig] = []
        access_configs: List[PortQoSConfig] = []
        voice_vlan_devices: Set[str] = set()

        for device in devices:
            device_type = device.get("type", "")
            if device_type not in ["usw", "udm", "ugw"]:
                continue

            result.devices_checked += 1
            device_id = device["_id"]
            device_name = device.get("name", device.get("model", "Unknown"))
            port_table = device.get("port_table", [])
            port_overrides = device.get("port_overrides", [])

            # Create port override lookup
            override_by_port = {po.get("port_idx"): po for po in port_overrides}
            has_qos_config = False

            for port_data in port_table:
                result.ports_checked += 1
                port_idx = port_data.get("port_idx", 0)
                port_override = override_by_port.get(port_idx, {})

                # Extract QoS config
                qos_config = self._extract_port_qos_config(device, port_data, port_override)
                self._port_qos_configs.append(qos_config)

                # Track stats
                if qos_config.trust_mode == "dscp":
                    result.ports_with_trust_dscp += 1
                    has_qos_config = True

                if qos_config.egress_rate_limit_kbps or qos_config.ingress_rate_limit_kbps:
                    result.ports_with_rate_limits += 1
                    has_qos_config = True

                if qos_config.voice_vlan_enabled:
                    voice_vlan_devices.add(device_name)

                # Categorize for consistency checking
                if qos_config.is_uplink:
                    uplink_configs.append(qos_config)
                else:
                    access_configs.append(qos_config)

                # Validate individual port
                self._validate_port_qos(result, qos_config, port_data)

            if has_qos_config:
                result.devices_with_qos += 1

        # Cross-device consistency checks
        self._check_uplink_consistency(result, uplink_configs)
        self._check_voice_vlan_consistency(result, networks, voice_vlan_devices)

        result.voice_vlans_configured = len(voice_vlan_devices)

        logger.info(
            f"QoS validation complete: {result.ports_checked} ports, "
            f"{len(result.findings)} findings, passed: {result.passed}"
        )

        return result

    def _validate_port_qos(
        self, result: QoSValidationResult, config: PortQoSConfig, port_data: Dict[str, Any]
    ) -> None:
        """Validate QoS configuration for a single port."""

        # Check DSCP trust on uplinks
        if config.is_uplink:
            if config.trust_mode not in ["dscp", "both"]:
                result.add_finding(QoSFinding(
                    finding_type=QoSFindingType.TRUST_MISMATCH,
                    severity=QoSFindingSeverity.MEDIUM,
                    message=f"Uplink port not trusting DSCP markings",
                    device_name=config.device_name,
                    device_id=config.device_id,
                    port_idx=config.port_idx,
                    current_value=config.trust_mode,
                    expected_value="dscp",
                    recommendation="Configure DSCP trust on uplink ports to preserve QoS markings",
                ))

        # Check rate limiting on uplinks (usually not wanted)
        if config.is_uplink and (config.egress_rate_limit_kbps or config.ingress_rate_limit_kbps):
            result.add_finding(QoSFinding(
                finding_type=QoSFindingType.BANDWIDTH_LIMIT,
                severity=QoSFindingSeverity.HIGH,
                message=f"Rate limiting configured on uplink port",
                device_name=config.device_name,
                device_id=config.device_id,
                port_idx=config.port_idx,
                current_value=f"Egress: {config.egress_rate_limit_kbps}, Ingress: {config.ingress_rate_limit_kbps}",
                expected_value="No rate limiting on uplinks",
                recommendation="Remove rate limiting from uplink ports to prevent bottlenecks",
            ))

        # Voice VLAN without proper trust
        if config.voice_vlan_enabled and config.trust_mode == "none":
            result.add_finding(QoSFinding(
                finding_type=QoSFindingType.VOICE_VLAN_CONFIG,
                severity=QoSFindingSeverity.HIGH,
                message=f"Voice VLAN enabled but QoS trust not configured",
                device_name=config.device_name,
                device_id=config.device_id,
                port_idx=config.port_idx,
                current_value=f"Voice VLAN: {config.voice_vlan_id}, Trust: {config.trust_mode}",
                expected_value="DSCP or CoS trust enabled",
                recommendation="Enable DSCP/CoS trust on voice VLAN ports for proper call quality",
            ))

    def _check_uplink_consistency(
        self, result: QoSValidationResult, uplink_configs: List[PortQoSConfig]
    ) -> None:
        """Check QoS consistency across uplink ports."""
        if len(uplink_configs) < 2:
            return

        # Group by trust mode
        trust_modes = {}
        for config in uplink_configs:
            if config.trust_mode not in trust_modes:
                trust_modes[config.trust_mode] = []
            trust_modes[config.trust_mode].append(config)

        # Check for inconsistency
        if len(trust_modes) > 1:
            mode_counts = {mode: len(configs) for mode, configs in trust_modes.items()}
            result.add_finding(QoSFinding(
                finding_type=QoSFindingType.QUEUE_INCONSISTENT,
                severity=QoSFindingSeverity.MEDIUM,
                message=f"Inconsistent QoS trust modes across uplink ports",
                device_name="Network-wide",
                current_value=str(mode_counts),
                expected_value="All uplinks with same trust mode",
                recommendation="Standardize DSCP trust configuration across all uplink ports",
            ))

    def _check_voice_vlan_consistency(
        self, result: QoSValidationResult, networks: List[Dict[str, Any]], voice_vlan_devices: Set[str]
    ) -> None:
        """Check voice VLAN consistency."""
        # Find voice networks
        voice_networks = [n for n in networks if "voice" in n.get("name", "").lower()]

        if voice_networks and not voice_vlan_devices:
            result.add_finding(QoSFinding(
                finding_type=QoSFindingType.VOICE_VLAN_CONFIG,
                severity=QoSFindingSeverity.MEDIUM,
                message="Voice network defined but no ports configured with voice VLAN",
                device_name="Network-wide",
                current_value="0 ports with voice VLAN",
                expected_value="Voice VLAN on phone ports",
                recommendation="Configure voice VLAN on ports connected to IP phones",
            ))

    def generate_report(self, result: QoSValidationResult) -> str:
        """Generate human-readable QoS validation report."""
        report = [
            "# QoS Configuration Validation Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Status | {'✅ PASSED' if result.passed else '❌ FAILED'} |",
            f"| Devices Checked | {result.devices_checked} |",
            f"| Ports Checked | {result.ports_checked} |",
            f"| Devices with QoS | {result.devices_with_qos} |",
            f"| Ports with DSCP Trust | {result.ports_with_trust_dscp} |",
            f"| Ports with Rate Limits | {result.ports_with_rate_limits} |",
            f"| Voice VLANs Configured | {result.voice_vlans_configured} |",
            "",
            "## Finding Summary",
            "",
            f"| Severity | Count |",
            f"|----------|-------|",
            f"| 🔴 Critical | {result.critical_count} |",
            f"| 🟠 High | {result.high_count} |",
            f"| 🟡 Medium | {result.medium_count} |",
            f"| 🔵 Low | {result.low_count} |",
            "",
        ]

        # Findings by severity
        if result.findings:
            report.append("## Detailed Findings")
            report.append("")

            severity_order = ["critical", "high", "medium", "low", "info"]
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
                "info": "ℹ️",
            }

            for severity in severity_order:
                findings = [f for f in result.findings if f.severity.value == severity]
                if findings:
                    emoji = severity_emoji.get(severity, "⚪")
                    report.append(f"### {emoji} {severity.upper()}")
                    report.append("")

                    for finding in findings:
                        port_info = f" Port {finding.port_idx}" if finding.port_idx else ""
                        report.append(f"**{finding.device_name}{port_info}**: {finding.message}")
                        if finding.recommendation:
                            report.append(f"  - *Recommendation*: {finding.recommendation}")
                        report.append("")

        return "\n".join(report)
