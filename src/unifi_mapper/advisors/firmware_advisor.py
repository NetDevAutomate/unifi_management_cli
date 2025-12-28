#!/usr/bin/env python3
"""
Firmware Security Advisor for UniFi Networks.

Provides proactive firmware security assessment:
- Compare installed firmware against known latest versions
- Track known security vulnerabilities by version
- Identify devices requiring urgent updates
- Track firmware consistency across device families
- Generate upgrade priority recommendations
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class FirmwareStatus(Enum):
    """Firmware security status."""

    CURRENT = "current"  # Running latest stable
    UPDATE_AVAILABLE = "update_available"  # Newer version exists
    SECURITY_UPDATE = "security_update"  # Security patches available
    CRITICAL = "critical"  # Known critical vulnerabilities
    EOL = "end_of_life"  # No longer supported
    UNKNOWN = "unknown"  # Can't determine status


class UpdatePriority(Enum):
    """Update priority levels."""

    CRITICAL = "critical"  # Update immediately
    HIGH = "high"  # Update within 24 hours
    MEDIUM = "medium"  # Update within 1 week
    LOW = "low"  # Update at convenience
    NONE = "none"  # No update needed


@dataclass
class KnownVulnerability:
    """A known firmware vulnerability."""

    cve_id: str
    severity: str  # critical, high, medium, low
    description: str
    affected_versions: List[str]  # Version patterns affected
    fixed_version: str
    disclosure_date: str
    references: List[str] = field(default_factory=list)


@dataclass
class DeviceFirmwareInfo:
    """Firmware information for a device."""

    device_id: str
    device_name: str
    model: str
    device_type: str
    current_version: str
    latest_version: str = ""

    # Status
    status: FirmwareStatus = FirmwareStatus.UNKNOWN
    update_priority: UpdatePriority = UpdatePriority.NONE

    # Vulnerabilities
    vulnerabilities: List[KnownVulnerability] = field(default_factory=list)

    # Metadata
    last_upgrade: Optional[datetime] = None
    uptime_days: int = 0
    auto_upgrade_enabled: bool = False

    # Family consistency
    family: str = ""
    family_version_mismatch: bool = False

    @property
    def needs_update(self) -> bool:
        """Check if device needs any update."""
        return self.status in [
            FirmwareStatus.UPDATE_AVAILABLE,
            FirmwareStatus.SECURITY_UPDATE,
            FirmwareStatus.CRITICAL,
        ]

    @property
    def has_critical_vulns(self) -> bool:
        """Check for critical vulnerabilities."""
        return any(v.severity == "critical" for v in self.vulnerabilities)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "model": self.model,
            "device_type": self.device_type,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "status": self.status.value,
            "update_priority": self.update_priority.value,
            "vulnerabilities": len(self.vulnerabilities),
            "uptime_days": self.uptime_days,
            "auto_upgrade_enabled": self.auto_upgrade_enabled,
            "family": self.family,
            "family_version_mismatch": self.family_version_mismatch,
        }


@dataclass
class FirmwareSecurityReport:
    """Complete firmware security assessment."""

    timestamp: datetime = field(default_factory=datetime.now)
    devices_checked: int = 0

    # Device info
    devices: List[DeviceFirmwareInfo] = field(default_factory=list)

    # Summary counts
    current_count: int = 0
    update_available_count: int = 0
    security_update_count: int = 0
    critical_count: int = 0
    eol_count: int = 0

    # Priority counts
    critical_priority: int = 0
    high_priority: int = 0
    medium_priority: int = 0

    # Consistency
    family_groups: Dict[str, Set[str]] = field(default_factory=dict)
    inconsistent_families: List[str] = field(default_factory=list)

    # Vulnerabilities
    total_vulnerabilities: int = 0
    critical_vulnerabilities: int = 0

    # Recommendations
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    def add_device(self, device: DeviceFirmwareInfo) -> None:
        """Add a device to the report."""
        self.devices.append(device)
        self.devices_checked += 1

        # Update status counts
        if device.status == FirmwareStatus.CURRENT:
            self.current_count += 1
        elif device.status == FirmwareStatus.UPDATE_AVAILABLE:
            self.update_available_count += 1
        elif device.status == FirmwareStatus.SECURITY_UPDATE:
            self.security_update_count += 1
        elif device.status == FirmwareStatus.CRITICAL:
            self.critical_count += 1
        elif device.status == FirmwareStatus.EOL:
            self.eol_count += 1

        # Update priority counts
        if device.update_priority == UpdatePriority.CRITICAL:
            self.critical_priority += 1
        elif device.update_priority == UpdatePriority.HIGH:
            self.high_priority += 1
        elif device.update_priority == UpdatePriority.MEDIUM:
            self.medium_priority += 1

        # Track vulnerabilities
        self.total_vulnerabilities += len(device.vulnerabilities)
        self.critical_vulnerabilities += sum(
            1 for v in device.vulnerabilities if v.severity == "critical"
        )

        # Track family versions
        if device.family:
            if device.family not in self.family_groups:
                self.family_groups[device.family] = set()
            self.family_groups[device.family].add(device.current_version)

    def add_recommendation(
        self,
        priority: str,
        message: str,
        device_name: str = "",
        action: str = "",
    ) -> None:
        """Add a recommendation."""
        self.recommendations.append({
            "priority": priority,
            "message": message,
            "device_name": device_name,
            "action": action,
            "timestamp": datetime.now().isoformat(),
        })

    @property
    def security_score(self) -> int:
        """Calculate overall security score (0-100)."""
        if self.devices_checked == 0:
            return 100

        score = 100

        # Deduct for critical issues
        score -= self.critical_count * 20
        score -= self.security_update_count * 10
        score -= self.update_available_count * 5
        score -= self.eol_count * 15
        score -= self.critical_vulnerabilities * 15

        # Deduct for inconsistency
        score -= len(self.inconsistent_families) * 5

        return max(0, min(100, score))

    def summary(self) -> Dict[str, Any]:
        """Get report summary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "devices_checked": self.devices_checked,
            "security_score": self.security_score,
            "status": {
                "current": self.current_count,
                "update_available": self.update_available_count,
                "security_update": self.security_update_count,
                "critical": self.critical_count,
                "eol": self.eol_count,
            },
            "priorities": {
                "critical": self.critical_priority,
                "high": self.high_priority,
                "medium": self.medium_priority,
            },
            "vulnerabilities": {
                "total": self.total_vulnerabilities,
                "critical": self.critical_vulnerabilities,
            },
            "inconsistent_families": self.inconsistent_families,
        }


class FirmwareAdvisor:
    """
    Firmware Security Advisor for UniFi networks.

    Provides:
    - Firmware version tracking and comparison
    - Known vulnerability assessment
    - Upgrade priority recommendations
    - Device family consistency checking
    """

    # Known latest firmware versions by device type/model
    # This would ideally be fetched from UniFi's API or a maintained database
    KNOWN_LATEST_VERSIONS = {
        # UniFi switches
        "US-8": "6.6.61",
        "US-8-60W": "6.6.61",
        "US-8-150W": "6.6.61",
        "US-16-150W": "6.6.61",
        "US-24": "6.6.61",
        "US-24-250W": "6.6.61",
        "US-24-500W": "6.6.61",
        "US-48": "6.6.61",
        "US-48-500W": "6.6.61",
        "US-48-750W": "6.6.61",
        "USW-Flex": "6.6.61",
        "USW-Flex-Mini": "2.1.5",
        "USW-Lite-8-PoE": "6.6.61",
        "USW-Lite-16-PoE": "6.6.61",
        "USW-Pro-24": "6.6.61",
        "USW-Pro-24-PoE": "6.6.61",
        "USW-Pro-48": "6.6.61",
        "USW-Pro-48-PoE": "6.6.61",
        "USW-Enterprise-8-PoE": "6.6.61",
        "USW-Enterprise-24-PoE": "6.6.61",
        "USW-Enterprise-48-PoE": "6.6.61",
        "USW-Aggregation": "6.6.61",
        "USW-Pro-Aggregation": "6.6.61",
        # Dream Machines
        "UDM": "3.2.12",
        "UDM-Pro": "3.2.12",
        "UDM-SE": "3.2.12",
        "UDR": "3.2.12",
        "UDW": "3.2.12",
        # Gateways
        "USG": "4.4.57",
        "USG-Pro-4": "4.4.57",
        "USG-XG-8": "4.4.57",
        "UXG-Pro": "3.2.12",
        # Access Points
        "U6-Lite": "6.6.77",
        "U6-LR": "6.6.77",
        "U6-Pro": "6.6.77",
        "U6-Enterprise": "6.6.77",
        "U6-Mesh": "6.6.77",
        "UAP-AC-Pro": "6.6.77",
        "UAP-AC-Lite": "6.6.77",
        "UAP-AC-LR": "6.6.77",
        "UAP-AC-HD": "6.6.77",
        "UAP-nanoHD": "6.6.77",
        "UAP-FlexHD": "6.6.77",
    }

    # Known security vulnerabilities
    # This would ideally be fetched from a vulnerability database
    KNOWN_VULNERABILITIES = [
        KnownVulnerability(
            cve_id="CVE-2024-EXAMPLE-1",
            severity="critical",
            description="Remote code execution vulnerability in web interface",
            affected_versions=["6.5.*", "6.4.*"],
            fixed_version="6.6.0",
            disclosure_date="2024-01-15",
            references=["https://community.ui.com/releases"],
        ),
        KnownVulnerability(
            cve_id="CVE-2023-EXAMPLE-2",
            severity="high",
            description="Authentication bypass in SSH service",
            affected_versions=["6.2.*", "6.3.*"],
            fixed_version="6.4.0",
            disclosure_date="2023-08-20",
            references=["https://community.ui.com/releases"],
        ),
        KnownVulnerability(
            cve_id="CVE-2023-EXAMPLE-3",
            severity="medium",
            description="Information disclosure in SNMP implementation",
            affected_versions=["5.*", "6.0.*", "6.1.*"],
            fixed_version="6.2.0",
            disclosure_date="2023-03-10",
            references=["https://community.ui.com/releases"],
        ),
    ]

    # Device families for consistency checking
    DEVICE_FAMILIES = {
        "switches_gen1": ["US-8", "US-16-150W", "US-24", "US-48"],
        "switches_gen2": ["USW-Lite-8-PoE", "USW-Lite-16-PoE", "USW-Pro-24", "USW-Pro-48"],
        "switches_enterprise": ["USW-Enterprise-8-PoE", "USW-Enterprise-24-PoE", "USW-Enterprise-48-PoE"],
        "dream_machines": ["UDM", "UDM-Pro", "UDM-SE", "UDR"],
        "gateways": ["USG", "USG-Pro-4", "UXG-Pro"],
        "ap_wifi6": ["U6-Lite", "U6-LR", "U6-Pro", "U6-Enterprise"],
        "ap_wifi5": ["UAP-AC-Pro", "UAP-AC-Lite", "UAP-AC-LR", "UAP-AC-HD"],
    }

    # EOL devices that no longer receive updates
    EOL_DEVICES = [
        "UAP",
        "UAP-LR",
        "UAP-Outdoor",
        "US-8-60W-BETA",
    ]

    def __init__(self, api_client, site: str = "default"):
        """Initialize Firmware Advisor."""
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

    def _parse_version(self, version_str: str) -> Tuple[int, ...]:
        """Parse version string into comparable tuple."""
        if not version_str:
            return (0,)

        # Extract version numbers
        match = re.search(r"(\d+(?:\.\d+)*)", version_str)
        if match:
            parts = match.group(1).split(".")
            return tuple(int(p) for p in parts)
        return (0,)

    def _compare_versions(self, current: str, latest: str) -> int:
        """
        Compare two versions.

        Returns:
            -1 if current < latest (needs update)
             0 if current == latest
             1 if current > latest (newer than known)
        """
        current_parts = self._parse_version(current)
        latest_parts = self._parse_version(latest)

        # Pad to same length
        max_len = max(len(current_parts), len(latest_parts))
        current_parts = current_parts + (0,) * (max_len - len(current_parts))
        latest_parts = latest_parts + (0,) * (max_len - len(latest_parts))

        if current_parts < latest_parts:
            return -1
        elif current_parts > latest_parts:
            return 1
        return 0

    def _version_matches_pattern(self, version: str, pattern: str) -> bool:
        """Check if version matches a pattern (e.g., '6.5.*')."""
        pattern_regex = pattern.replace(".", r"\.").replace("*", r".*")
        return bool(re.match(f"^{pattern_regex}$", version))

    def _check_vulnerabilities(
        self, version: str
    ) -> List[KnownVulnerability]:
        """Check version against known vulnerabilities."""
        affected = []
        for vuln in self.KNOWN_VULNERABILITIES:
            for pattern in vuln.affected_versions:
                if self._version_matches_pattern(version, pattern):
                    # Also check if it's been fixed
                    if self._compare_versions(version, vuln.fixed_version) < 0:
                        affected.append(vuln)
                    break
        return affected

    def _get_device_family(self, model: str) -> str:
        """Get the device family for a model."""
        for family, models in self.DEVICE_FAMILIES.items():
            if model in models:
                return family
        return ""

    def _analyze_device(self, device: Dict[str, Any]) -> DeviceFirmwareInfo:
        """Analyze firmware status for a single device."""
        device_id = device["_id"]
        model = device.get("model", "Unknown")
        device_name = device.get("name", model)
        device_type = device.get("type", "unknown")
        current_version = device.get("version", "")

        # Get latest known version
        latest_version = self.KNOWN_LATEST_VERSIONS.get(model, "")

        # Create firmware info
        info = DeviceFirmwareInfo(
            device_id=device_id,
            device_name=device_name,
            model=model,
            device_type=device_type,
            current_version=current_version,
            latest_version=latest_version,
            family=self._get_device_family(model),
            uptime_days=int(device.get("uptime", 0) / 86400),
            auto_upgrade_enabled=device.get("auto_upgrade", False),
        )

        # Parse last upgrade time
        if "upgrade_date" in device:
            try:
                info.last_upgrade = datetime.fromtimestamp(device["upgrade_date"])
            except (ValueError, TypeError):
                pass

        # Check EOL status
        if model in self.EOL_DEVICES:
            info.status = FirmwareStatus.EOL
            info.update_priority = UpdatePriority.HIGH
            return info

        # Check for vulnerabilities
        info.vulnerabilities = self._check_vulnerabilities(current_version)

        # Determine status
        if not latest_version:
            info.status = FirmwareStatus.UNKNOWN
            info.update_priority = UpdatePriority.NONE
        else:
            version_cmp = self._compare_versions(current_version, latest_version)

            if version_cmp >= 0:
                # Current or newer
                info.status = FirmwareStatus.CURRENT
                info.update_priority = UpdatePriority.NONE
            elif info.vulnerabilities:
                # Has known vulnerabilities
                if any(v.severity == "critical" for v in info.vulnerabilities):
                    info.status = FirmwareStatus.CRITICAL
                    info.update_priority = UpdatePriority.CRITICAL
                else:
                    info.status = FirmwareStatus.SECURITY_UPDATE
                    info.update_priority = UpdatePriority.HIGH
            else:
                # Just needs regular update
                info.status = FirmwareStatus.UPDATE_AVAILABLE
                info.update_priority = UpdatePriority.MEDIUM

        return info

    def analyze(self) -> FirmwareSecurityReport:
        """
        Perform comprehensive firmware security analysis.

        Returns:
            FirmwareSecurityReport with analysis results
        """
        logger.info("Starting firmware security analysis...")
        report = FirmwareSecurityReport()

        devices = self._get_devices()

        for device in devices:
            device_info = self._analyze_device(device)
            report.add_device(device_info)

        # Check family consistency
        for family, versions in report.family_groups.items():
            if len(versions) > 1:
                report.inconsistent_families.append(family)
                # Mark devices with mismatched versions
                for device in report.devices:
                    if device.family == family:
                        device.family_version_mismatch = True

        # Generate recommendations
        self._generate_recommendations(report)

        logger.info(
            f"Firmware analysis complete: {report.devices_checked} devices, "
            f"security score: {report.security_score}/100"
        )

        return report

    def _generate_recommendations(self, report: FirmwareSecurityReport) -> None:
        """Generate prioritized recommendations."""
        # Critical priority - devices with critical vulnerabilities
        for device in report.devices:
            if device.status == FirmwareStatus.CRITICAL:
                report.add_recommendation(
                    "critical",
                    f"{device.device_name} has critical vulnerabilities",
                    device.device_name,
                    f"Upgrade from {device.current_version} to {device.latest_version} immediately",
                )

        # High priority - EOL devices
        for device in report.devices:
            if device.status == FirmwareStatus.EOL:
                report.add_recommendation(
                    "high",
                    f"{device.device_name} ({device.model}) is end-of-life",
                    device.device_name,
                    "Plan hardware replacement - device no longer receives security updates",
                )

        # High priority - security updates
        for device in report.devices:
            if device.status == FirmwareStatus.SECURITY_UPDATE:
                report.add_recommendation(
                    "high",
                    f"{device.device_name} needs security update",
                    device.device_name,
                    f"Upgrade from {device.current_version} to {device.latest_version}",
                )

        # Medium priority - family inconsistency
        for family in report.inconsistent_families:
            versions = report.family_groups[family]
            report.add_recommendation(
                "medium",
                f"Inconsistent firmware in {family} family: {', '.join(sorted(versions))}",
                "",
                "Standardize firmware versions across device family for consistency",
            )

        # Low priority - regular updates
        for device in report.devices:
            if device.status == FirmwareStatus.UPDATE_AVAILABLE:
                report.add_recommendation(
                    "low",
                    f"{device.device_name} has update available",
                    device.device_name,
                    f"Upgrade from {device.current_version} to {device.latest_version} at convenience",
                )

        # Info - auto-upgrade disabled on devices needing updates
        devices_need_update = [d for d in report.devices if d.needs_update and not d.auto_upgrade_enabled]
        if devices_need_update:
            report.add_recommendation(
                "info",
                f"{len(devices_need_update)} devices need updates but have auto-upgrade disabled",
                "",
                "Consider enabling auto-upgrade for non-critical devices or schedule maintenance window",
            )

    def generate_report(self, result: FirmwareSecurityReport) -> str:
        """Generate human-readable firmware security report."""
        # Security score color
        score = result.security_score
        if score >= 90:
            score_emoji = "🟢"
            score_status = "Excellent"
        elif score >= 70:
            score_emoji = "🟡"
            score_status = "Good"
        elif score >= 50:
            score_emoji = "🟠"
            score_status = "Fair"
        else:
            score_emoji = "🔴"
            score_status = "Poor"

        report = [
            "# Firmware Security Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Security Score",
            "",
            f"# {score_emoji} {score}/100 - {score_status}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Devices Checked | {result.devices_checked} |",
            f"| ✅ Current | {result.current_count} |",
            f"| 📦 Update Available | {result.update_available_count} |",
            f"| 🔐 Security Update | {result.security_update_count} |",
            f"| 🚨 Critical | {result.critical_count} |",
            f"| ⚰️ End of Life | {result.eol_count} |",
            "",
            "## Vulnerability Summary",
            "",
            f"| Type | Count |",
            f"|------|-------|",
            f"| Total Vulnerabilities | {result.total_vulnerabilities} |",
            f"| Critical Vulnerabilities | {result.critical_vulnerabilities} |",
            "",
        ]

        # Update priorities
        if result.critical_priority or result.high_priority or result.medium_priority:
            report.extend([
                "## Update Priorities",
                "",
                f"| Priority | Count |",
                f"|----------|-------|",
                f"| 🔴 Critical | {result.critical_priority} |",
                f"| 🟠 High | {result.high_priority} |",
                f"| 🟡 Medium | {result.medium_priority} |",
                "",
            ])

        # Family consistency
        if result.inconsistent_families:
            report.extend([
                "## Firmware Consistency Issues",
                "",
            ])
            for family in result.inconsistent_families:
                versions = sorted(result.family_groups[family])
                report.append(f"- **{family}**: {', '.join(versions)}")
            report.append("")

        # Device details table
        report.extend([
            "## Device Status",
            "",
            "| Device | Model | Current | Latest | Status | Priority |",
            "|--------|-------|---------|--------|--------|----------|",
        ])

        status_emoji = {
            FirmwareStatus.CURRENT: "✅",
            FirmwareStatus.UPDATE_AVAILABLE: "📦",
            FirmwareStatus.SECURITY_UPDATE: "🔐",
            FirmwareStatus.CRITICAL: "🚨",
            FirmwareStatus.EOL: "⚰️",
            FirmwareStatus.UNKNOWN: "❓",
        }

        priority_emoji = {
            UpdatePriority.CRITICAL: "🔴",
            UpdatePriority.HIGH: "🟠",
            UpdatePriority.MEDIUM: "🟡",
            UpdatePriority.LOW: "🔵",
            UpdatePriority.NONE: "⚪",
        }

        # Sort devices by priority
        priority_order = {
            UpdatePriority.CRITICAL: 0,
            UpdatePriority.HIGH: 1,
            UpdatePriority.MEDIUM: 2,
            UpdatePriority.LOW: 3,
            UpdatePriority.NONE: 4,
        }
        sorted_devices = sorted(
            result.devices,
            key=lambda d: priority_order.get(d.update_priority, 5),
        )

        for device in sorted_devices:
            s_emoji = status_emoji.get(device.status, "❓")
            p_emoji = priority_emoji.get(device.update_priority, "⚪")
            report.append(
                f"| {device.device_name} | {device.model} | "
                f"{device.current_version} | {device.latest_version or 'N/A'} | "
                f"{s_emoji} {device.status.value} | {p_emoji} {device.update_priority.value} |"
            )
        report.append("")

        # Vulnerability details
        devices_with_vulns = [d for d in result.devices if d.vulnerabilities]
        if devices_with_vulns:
            report.extend([
                "## Vulnerability Details",
                "",
            ])

            for device in devices_with_vulns:
                report.append(f"### {device.device_name}")
                report.append("")
                for vuln in device.vulnerabilities:
                    sev_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
                        vuln.severity, "⚪"
                    )
                    report.append(f"- {sev_emoji} **{vuln.cve_id}** ({vuln.severity})")
                    report.append(f"  - {vuln.description}")
                    report.append(f"  - Fixed in: {vuln.fixed_version}")
                report.append("")

        # Recommendations
        if result.recommendations:
            report.extend([
                "## Recommendations",
                "",
            ])

            priority_order = ["critical", "high", "medium", "low", "info"]
            priority_emoji_map = {
                "critical": "🚨",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
                "info": "ℹ️",
            }

            for priority in priority_order:
                recs = [r for r in result.recommendations if r["priority"] == priority]
                if recs:
                    emoji = priority_emoji_map.get(priority, "⚪")
                    report.append(f"### {emoji} {priority.upper()}")
                    report.append("")
                    for rec in recs:
                        report.append(f"- **{rec['message']}**")
                        if rec.get("action"):
                            report.append(f"  - Action: {rec['action']}")
                    report.append("")

        return "\n".join(report)
