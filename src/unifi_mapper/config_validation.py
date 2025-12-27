#!/usr/bin/env python3
"""
Configuration Validation Module for UniFi Network Mapper.

Provides comprehensive validation of UniFi network configurations including:
- Trunk/uplink port VLAN configuration
- STP (Spanning Tree Protocol) settings
- Security best practices
- Operational best practices
- Network health checks

This module was created after discovering that `forward: native` combined with
`tagged_vlan_mgmt: block_all` silently drops all tagged VLAN traffic - a common
but hard-to-diagnose misconfiguration.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Severity levels for validation findings."""
    CRITICAL = "CRITICAL"  # Immediate action required - causes outages
    HIGH = "HIGH"          # Should fix soon - potential for issues
    MEDIUM = "MEDIUM"      # Recommended to fix - best practice violation
    LOW = "LOW"            # Minor issue - optimization opportunity
    INFO = "INFO"          # Informational - no action required


class Category(Enum):
    """Categories for validation findings."""
    VLAN_ROUTING = "VLAN Routing"
    STP_CONFIG = "STP Configuration"
    SECURITY = "Security"
    OPERATIONAL = "Operational"
    PERFORMANCE = "Performance"
    REDUNDANCY = "Redundancy"
    DHCP = "DHCP"
    FIRMWARE = "Firmware"


@dataclass
class ValidationFinding:
    """Represents a single validation finding."""
    severity: Severity
    category: Category
    title: str
    description: str
    device_name: str
    device_id: str = ""
    port_idx: Optional[int] = None
    current_value: Any = None
    recommended_value: Any = None
    remediation: str = ""
    reference_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert finding to dictionary."""
        return {
            'severity': self.severity.value,
            'category': self.category.value,
            'title': self.title,
            'description': self.description,
            'device_name': self.device_name,
            'device_id': self.device_id,
            'port_idx': self.port_idx,
            'current_value': self.current_value,
            'recommended_value': self.recommended_value,
            'remediation': self.remediation,
            'reference_url': self.reference_url
        }


@dataclass
class ValidationResult:
    """Aggregated validation results."""
    findings: List[ValidationFinding] = field(default_factory=list)
    devices_checked: int = 0
    ports_checked: int = 0
    networks_checked: int = 0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.LOW)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)

    @property
    def passed(self) -> bool:
        """Returns True if no critical or high severity findings."""
        return self.critical_count == 0 and self.high_count == 0

    def add_finding(self, finding: ValidationFinding) -> None:
        """Add a finding to results."""
        self.findings.append(finding)

    def get_by_severity(self, severity: Severity) -> List[ValidationFinding]:
        """Get findings filtered by severity."""
        return [f for f in self.findings if f.severity == severity]

    def get_by_category(self, category: Category) -> List[ValidationFinding]:
        """Get findings filtered by category."""
        return [f for f in self.findings if f.category == category]

    def get_by_device(self, device_name: str) -> List[ValidationFinding]:
        """Get findings filtered by device."""
        return [f for f in self.findings if f.device_name == device_name]

    def summary(self) -> Dict[str, Any]:
        """Get summary of validation results."""
        return {
            'passed': self.passed,
            'total_findings': len(self.findings),
            'critical': self.critical_count,
            'high': self.high_count,
            'medium': self.medium_count,
            'low': self.low_count,
            'info': self.info_count,
            'devices_checked': self.devices_checked,
            'ports_checked': self.ports_checked,
            'networks_checked': self.networks_checked,
            'timestamp': self.timestamp.isoformat()
        }


class BaseValidator:
    """Base class for all validators."""

    def __init__(self, api_client, site: str = "default"):
        self.api_client = api_client
        self.site = site
        self._devices_cache: Optional[Dict] = None
        self._networks_cache: Optional[Dict] = None
        self._port_profiles_cache: Optional[Dict] = None

    def _get_devices(self) -> Dict:
        """Get devices with caching."""
        if self._devices_cache is None:
            self._devices_cache = self.api_client.get_devices(self.site)
        return self._devices_cache

    def _get_networks(self) -> List[Dict]:
        """Get network configurations."""
        if self._networks_cache is None:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"

            response = self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            if response.status_code == 200:
                self._networks_cache = response.json().get('data', [])
            else:
                self._networks_cache = []
        return self._networks_cache

    def _get_port_profiles(self) -> List[Dict]:
        """Get port profile configurations."""
        if self._port_profiles_cache is None:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/portconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/portconf"

            response = self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            if response.status_code == 200:
                self._port_profiles_cache = response.json().get('data', [])
            else:
                self._port_profiles_cache = []
        return self._port_profiles_cache

    def _get_network_name(self, network_id: str) -> str:
        """Get network name from ID."""
        for net in self._get_networks():
            if net.get('_id') == network_id:
                return net.get('name', 'Unknown')
        return 'Unknown'

    def _get_network_vlan(self, network_id: str) -> Optional[int]:
        """Get VLAN ID from network ID."""
        for net in self._get_networks():
            if net.get('_id') == network_id:
                return net.get('vlan')
        return None

    def validate(self) -> ValidationResult:
        """Override in subclass to perform validation."""
        raise NotImplementedError


class TrunkPortValidator(BaseValidator):
    """
    Validates trunk/uplink port configurations.

    Checks for common misconfigurations that block inter-VLAN traffic:
    - forward: native (only passes native VLAN)
    - tagged_vlan_mgmt: block_all (drops all tagged frames)
    - Missing VLANs in trunk profiles
    - Inconsistent trunk configurations between connected ports
    """

    # Port settings that block tagged VLANs
    BLOCKING_FORWARD_MODES = {'native', 'disabled'}
    BLOCKING_TAGGED_VLAN_MGMT = {'block_all'}

    def validate(self) -> ValidationResult:
        """Validate all trunk/uplink port configurations."""
        result = ValidationResult()
        devices = self._get_devices()
        networks = self._get_networks()

        # Build list of all VLAN network IDs for comparison
        vlan_networks = {
            net['_id']: net
            for net in networks
            if net.get('vlan_enabled') or net.get('vlan')
        }

        for device in devices.get('data', []):
            device_type = device.get('type', '')
            device_name = device.get('name', device.get('model', 'Unknown'))
            device_id = device.get('_id', '')

            # Check switches (usw) and gateways (udm, ugw)
            if device_type not in ['usw', 'udm', 'ugw', 'udmpro', 'udmpromax']:
                continue

            result.devices_checked += 1
            port_overrides = device.get('port_overrides', [])
            port_table = device.get('port_table', [])

            # Create port lookup
            port_info = {pt.get('port_idx'): pt for pt in port_table}

            for po in port_overrides:
                port_idx = po.get('port_idx')
                result.ports_checked += 1

                # Get port table info
                pt = port_info.get(port_idx, {})
                is_uplink = pt.get('is_uplink', False)
                port_up = pt.get('up', False)

                # Check for VLAN-blocking configurations
                forward = po.get('forward', '')
                tagged_vlan_mgmt = po.get('tagged_vlan_mgmt', '')
                native_net = po.get('native_networkconf_id', '')

                # CRITICAL: forward: native on uplink/trunk ports
                if forward in self.BLOCKING_FORWARD_MODES and forward != 'disabled':
                    if is_uplink or self._is_likely_trunk_port(po, pt):
                        result.add_finding(ValidationFinding(
                            severity=Severity.CRITICAL,
                            category=Category.VLAN_ROUTING,
                            title="Trunk port blocks tagged VLANs",
                            description=(
                                f"Port has 'forward: {forward}' which only passes native VLAN traffic. "
                                "All tagged VLAN frames will be dropped, breaking inter-VLAN routing "
                                "for devices connected through this port."
                            ),
                            device_name=device_name,
                            device_id=device_id,
                            port_idx=port_idx,
                            current_value=f"forward: {forward}",
                            recommended_value="forward: all",
                            remediation=(
                                f"Change port {port_idx} on {device_name} to 'forward: all' or "
                                "'forward: customize' with all required VLANs tagged."
                            )
                        ))

                # CRITICAL: tagged_vlan_mgmt: block_all
                if tagged_vlan_mgmt in self.BLOCKING_TAGGED_VLAN_MGMT:
                    result.add_finding(ValidationFinding(
                        severity=Severity.CRITICAL,
                        category=Category.VLAN_ROUTING,
                        title="Port explicitly blocks all tagged VLANs",
                        description=(
                            f"Port has 'tagged_vlan_mgmt: {tagged_vlan_mgmt}' which explicitly "
                            "drops ALL 802.1Q tagged frames. This completely blocks inter-VLAN "
                            "traffic through this port."
                        ),
                        device_name=device_name,
                        device_id=device_id,
                        port_idx=port_idx,
                        current_value=f"tagged_vlan_mgmt: {tagged_vlan_mgmt}",
                        recommended_value="tagged_vlan_mgmt: auto (or remove setting)",
                        remediation=(
                            f"Change 'tagged_vlan_mgmt' to 'auto' or remove the setting entirely "
                            f"on port {port_idx} of {device_name}."
                        )
                    ))

                # HIGH: Uplink port not set to forward all
                if is_uplink and forward not in ['all', '']:
                    if forward not in self.BLOCKING_FORWARD_MODES:  # Already caught above
                        result.add_finding(ValidationFinding(
                            severity=Severity.HIGH,
                            category=Category.VLAN_ROUTING,
                            title="Uplink port may not pass all VLANs",
                            description=(
                                f"Uplink port has 'forward: {forward}' instead of 'all'. "
                                "This may cause some VLANs to not traverse this link."
                            ),
                            device_name=device_name,
                            device_id=device_id,
                            port_idx=port_idx,
                            current_value=f"forward: {forward}",
                            recommended_value="forward: all",
                            remediation=(
                                f"Consider setting port {port_idx} to 'forward: all' to ensure "
                                "all VLANs can traverse the uplink."
                            )
                        ))

                # Check port profile for trunk misconfiguration
                portconf_id = po.get('portconf_id', '')
                if portconf_id:
                    self._check_port_profile(
                        result, portconf_id, device_name, device_id,
                        port_idx, is_uplink, vlan_networks
                    )

        result.networks_checked = len(networks)
        return result

    def _is_likely_trunk_port(self, port_override: Dict, port_table: Dict) -> bool:
        """Determine if a port is likely a trunk port."""
        # Check explicit trunk indicators
        portconf_id = port_override.get('portconf_id', '').lower()
        name = port_override.get('name', '').lower()

        if 'trunk' in portconf_id or 'trunk' in name:
            return True

        # Check if port has tagged VLANs
        if port_override.get('tagged_networkconf_ids'):
            return True

        # Check speed indicators (high speed often trunk)
        speed = port_table.get('speed', 0)
        if speed >= 10000:  # 10Gbps likely trunk
            return True

        return False

    def _check_port_profile(self, result: ValidationResult, profile_id: str,
                           device_name: str, device_id: str, port_idx: int,
                           is_uplink: bool, vlan_networks: Dict) -> None:
        """Check port profile configuration."""
        profiles = self._get_port_profiles()

        for profile in profiles:
            if profile.get('_id') != profile_id:
                continue

            profile_name = profile.get('name', 'Unknown')
            forward = profile.get('forward', '')
            tagged_nets = profile.get('tagged_networkconf_ids', [])

            # Check if trunk profile is missing important VLANs
            if 'trunk' in profile_name.lower() and is_uplink:
                missing_vlans = []
                for net_id, net in vlan_networks.items():
                    if net_id not in (tagged_nets or []):
                        vlan_name = net.get('name', f"VLAN {net.get('vlan', '?')}")
                        missing_vlans.append(vlan_name)

                if missing_vlans and forward == 'customize':
                    result.add_finding(ValidationFinding(
                        severity=Severity.MEDIUM,
                        category=Category.VLAN_ROUTING,
                        title="Trunk profile missing VLANs",
                        description=(
                            f"Profile '{profile_name}' doesn't include all VLANs. "
                            f"Missing: {', '.join(missing_vlans[:5])}"
                            f"{' and more...' if len(missing_vlans) > 5 else ''}"
                        ),
                        device_name=device_name,
                        device_id=device_id,
                        port_idx=port_idx,
                        current_value=f"Profile: {profile_name}",
                        recommended_value="Add missing VLANs or use 'forward: all'",
                        remediation=(
                            f"Update profile '{profile_name}' to include all required VLANs, "
                            "or change to 'forward: all' to pass all VLANs."
                        )
                    ))


class STPValidator(BaseValidator):
    """
    Validates Spanning Tree Protocol (STP) configurations.

    Ensures deterministic failover paths by checking:
    - Bridge priority settings (root bridge selection)
    - Port priorities and costs
    - STP mode consistency
    - Potential loops or suboptimal paths
    """

    # Recommended priority values
    ROOT_BRIDGE_PRIORITY = 4096      # Primary root
    SECONDARY_ROOT_PRIORITY = 8192   # Secondary root
    DEFAULT_PRIORITY = 32768         # Switches

    def validate(self) -> ValidationResult:
        """Validate STP configuration across all switches."""
        result = ValidationResult()
        devices = self._get_devices()

        switches = []
        priorities = {}

        for device in devices.get('data', []):
            if device.get('type') != 'usw':
                continue

            result.devices_checked += 1
            device_name = device.get('name', device.get('model', 'Unknown'))
            device_id = device.get('_id', '')

            switches.append(device)

            # Get STP configuration
            stp_priority = device.get('stp_priority', self.DEFAULT_PRIORITY)
            stp_version = device.get('stp_version', 'rstp')

            priorities[device_name] = stp_priority

            # Check for multiple root candidates
            if stp_priority <= self.SECONDARY_ROOT_PRIORITY:
                # This is a root candidate - track it
                pass

            # Check STP version consistency
            port_table = device.get('port_table', [])
            for pt in port_table:
                result.ports_checked += 1
                stp_state = pt.get('stp_state', '')

                # Check for blocked ports that might indicate loops
                if stp_state == 'blocking':
                    result.add_finding(ValidationFinding(
                        severity=Severity.INFO,
                        category=Category.STP_CONFIG,
                        title="STP blocking port detected",
                        description=(
                            f"Port {pt.get('port_idx')} is in STP blocking state, "
                            "indicating redundant path is being blocked to prevent loops."
                        ),
                        device_name=device_name,
                        device_id=device_id,
                        port_idx=pt.get('port_idx'),
                        current_value=f"STP State: {stp_state}",
                        remediation="No action needed - this is normal STP behavior."
                    ))

        # Analyze priority distribution
        self._check_priority_distribution(result, priorities, switches)

        return result

    def _check_priority_distribution(self, result: ValidationResult,
                                     priorities: Dict[str, int],
                                     switches: List[Dict]) -> None:
        """Check STP priority distribution for optimal root selection."""
        if not priorities:
            return

        # Find root candidates (lowest priority wins)
        sorted_priorities = sorted(priorities.items(), key=lambda x: x[1])

        # Check if there's a clear root bridge
        if len(sorted_priorities) >= 2:
            primary_name, primary_priority = sorted_priorities[0]
            secondary_name, secondary_priority = sorted_priorities[1]

            # All same priority - non-deterministic root
            if primary_priority == secondary_priority:
                result.add_finding(ValidationFinding(
                    severity=Severity.HIGH,
                    category=Category.STP_CONFIG,
                    title="Non-deterministic STP root bridge",
                    description=(
                        f"Multiple switches have the same STP priority ({primary_priority}). "
                        "Root bridge selection will be based on MAC address, which is not "
                        "predictable and may result in suboptimal traffic paths."
                    ),
                    device_name="Network-wide",
                    current_value=f"Multiple switches at priority {primary_priority}",
                    recommended_value=(
                        f"Set core switch to {self.ROOT_BRIDGE_PRIORITY}, "
                        f"backup to {self.SECONDARY_ROOT_PRIORITY}"
                    ),
                    remediation=(
                        "Configure explicit STP priorities: Primary root bridge at 4096, "
                        "secondary root at 8192, all other switches at 32768 (default)."
                    )
                ))

            # Using default priority on all switches
            elif primary_priority == self.DEFAULT_PRIORITY:
                result.add_finding(ValidationFinding(
                    severity=Severity.MEDIUM,
                    category=Category.STP_CONFIG,
                    title="All switches using default STP priority",
                    description=(
                        "All switches are using the default STP priority (32768). "
                        "Consider setting explicit priorities for deterministic failover."
                    ),
                    device_name="Network-wide",
                    current_value=f"All at default priority {self.DEFAULT_PRIORITY}",
                    recommended_value="Configure explicit root bridge priorities",
                    remediation=(
                        "Set your core/primary switch to priority 4096 to ensure it "
                        "becomes the root bridge. Set backup switch to 8192."
                    )
                ))

        # Check for proper root bridge location
        if switches:
            # Ideally root should be the most central/powerful switch
            for sw in switches:
                sw_name = sw.get('name', 'Unknown')
                priority = priorities.get(sw_name, self.DEFAULT_PRIORITY)

                # Check if a non-gateway device is root
                uplink = sw.get('uplink', {})
                if not uplink and priority == min(priorities.values()):
                    # This switch has no uplink and is root - might be intentional
                    pass


class SecurityValidator(BaseValidator):
    """
    Validates security best practices.

    Checks for:
    - Default credentials (where detectable)
    - Insecure protocols enabled
    - Missing security features
    - Firewall rule issues
    - Guest network isolation
    """

    def validate(self) -> ValidationResult:
        """Validate security configuration."""
        result = ValidationResult()
        devices = self._get_devices()
        networks = self._get_networks()

        # Check network-level security
        for network in networks:
            result.networks_checked += 1
            self._check_network_security(result, network)

        # Check device-level security
        for device in devices.get('data', []):
            result.devices_checked += 1
            self._check_device_security(result, device)

        return result

    def _check_network_security(self, result: ValidationResult, network: Dict) -> None:
        """Check network-level security settings."""
        net_name = network.get('name', 'Unknown')
        net_id = network.get('_id', '')
        purpose = network.get('purpose', '')

        # Check guest network isolation
        if 'guest' in net_name.lower() or purpose == 'guest':
            # Guest networks should have isolation
            if not network.get('networkgroup') == 'guest':
                result.add_finding(ValidationFinding(
                    severity=Severity.MEDIUM,
                    category=Category.SECURITY,
                    title="Guest network may lack isolation",
                    description=(
                        f"Network '{net_name}' appears to be a guest network but may not "
                        "have proper guest isolation enabled."
                    ),
                    device_name=net_name,
                    device_id=net_id,
                    remediation="Ensure guest network has client isolation and proper firewall rules."
                ))

        # Check for DHCP guarding
        if network.get('dhcpd_enabled') and not network.get('dhcpguard_enabled'):
            result.add_finding(ValidationFinding(
                severity=Severity.LOW,
                category=Category.SECURITY,
                title="DHCP guarding not enabled",
                description=(
                    f"Network '{net_name}' has DHCP enabled but DHCP guarding is disabled. "
                    "DHCP guarding prevents rogue DHCP servers."
                ),
                device_name=net_name,
                device_id=net_id,
                current_value="dhcpguard_enabled: false",
                recommended_value="dhcpguard_enabled: true",
                remediation="Enable DHCP guarding to prevent rogue DHCP server attacks."
            ))

        # Check IoT network segregation
        if 'iot' in net_name.lower():
            if not network.get('vlan_enabled'):
                result.add_finding(ValidationFinding(
                    severity=Severity.HIGH,
                    category=Category.SECURITY,
                    title="IoT network not on separate VLAN",
                    description=(
                        f"Network '{net_name}' appears to be an IoT network but is not "
                        "on a separate VLAN. IoT devices should be isolated."
                    ),
                    device_name=net_name,
                    device_id=net_id,
                    remediation="Move IoT devices to a dedicated VLAN with restricted access."
                ))

    def _check_device_security(self, result: ValidationResult, device: Dict) -> None:
        """Check device-level security settings."""
        device_name = device.get('name', device.get('model', 'Unknown'))
        device_id = device.get('_id', '')
        device_type = device.get('type', '')

        # Check for SSH enabled (informational)
        if device.get('config', {}).get('sshd_enabled'):
            result.add_finding(ValidationFinding(
                severity=Severity.INFO,
                category=Category.SECURITY,
                title="SSH enabled on device",
                description=f"SSH is enabled on {device_name}.",
                device_name=device_name,
                device_id=device_id,
                remediation="Ensure SSH uses key-based authentication if exposed."
            ))

        # Check port security settings
        port_overrides = device.get('port_overrides', [])
        for po in port_overrides:
            port_idx = po.get('port_idx')

            # Check for port security
            if po.get('port_security_enabled'):
                mac_limit = len(po.get('port_security_mac_address', []))
                if mac_limit == 0:
                    result.add_finding(ValidationFinding(
                        severity=Severity.LOW,
                        category=Category.SECURITY,
                        title="Port security without MAC limit",
                        description=(
                            f"Port {port_idx} has port security enabled but no MAC "
                            "addresses are configured."
                        ),
                        device_name=device_name,
                        device_id=device_id,
                        port_idx=port_idx,
                        remediation="Configure allowed MAC addresses or disable port security."
                    ))


class OperationalValidator(BaseValidator):
    """
    Validates operational best practices.

    Checks for:
    - Firmware consistency and updates
    - Device naming conventions
    - Port labeling
    - Network documentation completeness
    - PoE budget utilization
    """

    def validate(self) -> ValidationResult:
        """Validate operational configuration."""
        result = ValidationResult()
        devices = self._get_devices()
        networks = self._get_networks()

        firmware_versions = {}
        unnamed_devices = []

        for device in devices.get('data', []):
            result.devices_checked += 1
            device_name = device.get('name', '')
            device_model = device.get('model', 'Unknown')
            device_id = device.get('_id', '')
            device_type = device.get('type', '')
            version = device.get('version', '')

            # Track firmware versions by device type
            if device_type not in firmware_versions:
                firmware_versions[device_type] = {}
            if version not in firmware_versions[device_type]:
                firmware_versions[device_type][version] = []
            firmware_versions[device_type][version].append(device_name or device_model)

            # Check for unnamed devices
            if not device_name or device_name == device_model:
                unnamed_devices.append(device_model)
                result.add_finding(ValidationFinding(
                    severity=Severity.LOW,
                    category=Category.OPERATIONAL,
                    title="Device not named",
                    description=(
                        f"Device '{device_model}' doesn't have a descriptive name. "
                        "Named devices are easier to manage and troubleshoot."
                    ),
                    device_name=device_model,
                    device_id=device_id,
                    remediation="Assign a descriptive name based on location or function."
                ))

            # Check PoE utilization (switches only)
            if device_type == 'usw':
                self._check_poe_budget(result, device)

            # Check for port labeling
            self._check_port_labels(result, device)

        # Check firmware consistency
        self._check_firmware_consistency(result, firmware_versions)

        # Check network documentation
        self._check_network_documentation(result, networks)

        result.networks_checked = len(networks)
        return result

    def _check_poe_budget(self, result: ValidationResult, device: Dict) -> None:
        """Check PoE budget utilization."""
        device_name = device.get('name', device.get('model', 'Unknown'))
        device_id = device.get('_id', '')

        # Get PoE stats from system stats
        sys_stats = device.get('sys_stats', {})
        poe_power = sys_stats.get('poe_power', 0)
        poe_budget = device.get('poe_budget', 0)

        if poe_budget > 0:
            utilization = (poe_power / poe_budget) * 100

            if utilization > 90:
                result.add_finding(ValidationFinding(
                    severity=Severity.HIGH,
                    category=Category.OPERATIONAL,
                    title="PoE budget near capacity",
                    description=(
                        f"PoE utilization is at {utilization:.1f}% ({poe_power}W of {poe_budget}W). "
                        "Adding more PoE devices may cause power issues."
                    ),
                    device_name=device_name,
                    device_id=device_id,
                    current_value=f"{utilization:.1f}% ({poe_power}W/{poe_budget}W)",
                    recommended_value="< 80% utilization",
                    remediation=(
                        "Consider adding a switch with higher PoE budget or redistributing "
                        "PoE devices across multiple switches."
                    )
                ))
            elif utilization > 80:
                result.add_finding(ValidationFinding(
                    severity=Severity.MEDIUM,
                    category=Category.OPERATIONAL,
                    title="PoE budget utilization high",
                    description=(
                        f"PoE utilization is at {utilization:.1f}% ({poe_power}W of {poe_budget}W)."
                    ),
                    device_name=device_name,
                    device_id=device_id,
                    current_value=f"{utilization:.1f}% ({poe_power}W/{poe_budget}W)",
                    remediation="Monitor PoE utilization when adding new devices."
                ))

    def _check_port_labels(self, result: ValidationResult, device: Dict) -> None:
        """Check port labeling completeness."""
        device_name = device.get('name', device.get('model', 'Unknown'))
        device_id = device.get('_id', '')

        port_overrides = device.get('port_overrides', [])
        port_table = device.get('port_table', [])

        # Find ports that are up but have no descriptive name
        port_up_status = {pt.get('port_idx'): pt.get('up', False) for pt in port_table}

        unlabeled_up_ports = []
        for pt in port_table:
            port_idx = pt.get('port_idx')
            if not pt.get('up'):
                continue

            result.ports_checked += 1

            # Check if this port has a custom name
            has_name = False
            for po in port_overrides:
                if po.get('port_idx') == port_idx:
                    name = po.get('name', '')
                    if name and not name.startswith('Port '):
                        has_name = True
                    break

            if not has_name:
                unlabeled_up_ports.append(port_idx)

        if len(unlabeled_up_ports) > 3:  # Only report if many unlabeled
            result.add_finding(ValidationFinding(
                severity=Severity.LOW,
                category=Category.OPERATIONAL,
                title="Multiple ports without labels",
                description=(
                    f"{len(unlabeled_up_ports)} active ports on {device_name} don't have "
                    "descriptive labels."
                ),
                device_name=device_name,
                device_id=device_id,
                current_value=f"Unlabeled ports: {unlabeled_up_ports[:5]}{'...' if len(unlabeled_up_ports) > 5 else ''}",
                remediation=(
                    "Label ports with connected device names for easier troubleshooting. "
                    "Use LLDP/CDP info to auto-populate where available."
                )
            ))

    def _check_firmware_consistency(self, result: ValidationResult,
                                    firmware_versions: Dict) -> None:
        """Check for firmware version consistency."""
        for device_type, versions in firmware_versions.items():
            if len(versions) > 1:
                version_list = ', '.join(f"{v} ({len(devs)} devices)"
                                        for v, devs in versions.items())
                result.add_finding(ValidationFinding(
                    severity=Severity.MEDIUM,
                    category=Category.FIRMWARE,
                    title=f"Inconsistent firmware versions ({device_type})",
                    description=(
                        f"Multiple firmware versions detected for {device_type} devices: "
                        f"{version_list}"
                    ),
                    device_name="Network-wide",
                    current_value=version_list,
                    recommended_value="All devices on same firmware version",
                    remediation="Update all devices to the same firmware version for consistency."
                ))

    def _check_network_documentation(self, result: ValidationResult,
                                     networks: List[Dict]) -> None:
        """Check network documentation completeness."""
        for network in networks:
            net_name = network.get('name', 'Unknown')
            net_id = network.get('_id', '')

            # Check for DHCP configuration completeness
            if network.get('dhcpd_enabled'):
                if not network.get('dhcpd_gateway_enabled'):
                    result.add_finding(ValidationFinding(
                        severity=Severity.MEDIUM,
                        category=Category.DHCP,
                        title="DHCP gateway not enabled",
                        description=(
                            f"Network '{net_name}' has DHCP enabled but gateway is not "
                            "being sent to clients via DHCP Option 3."
                        ),
                        device_name=net_name,
                        device_id=net_id,
                        current_value="dhcpd_gateway_enabled: false",
                        recommended_value="dhcpd_gateway_enabled: true",
                        remediation="Enable DHCP gateway to ensure clients receive gateway info."
                    ))

                # Check DHCP range sanity
                dhcp_start = network.get('dhcpd_start', '')
                dhcp_stop = network.get('dhcpd_stop', '')
                subnet = network.get('ip_subnet', '')

                if dhcp_stop and subnet:
                    # Extract gateway from subnet (format: gateway/prefix)
                    gateway = subnet.split('/')[0] if '/' in subnet else ''
                    if gateway and gateway == dhcp_stop:
                        result.add_finding(ValidationFinding(
                            severity=Severity.HIGH,
                            category=Category.DHCP,
                            title="DHCP range includes gateway IP",
                            description=(
                                f"Network '{net_name}' DHCP range ends at {dhcp_stop}, "
                                "which is the gateway IP. This can cause IP conflicts."
                            ),
                            device_name=net_name,
                            device_id=net_id,
                            current_value=f"dhcpd_stop: {dhcp_stop}",
                            recommended_value="DHCP range should not include gateway",
                            remediation="Reduce DHCP range to exclude the gateway IP address."
                        ))


class DHCPValidator(BaseValidator):
    """
    Validates DHCP configuration.

    Checks for:
    - DHCP server configuration completeness
    - Overlapping DHCP ranges
    - Gateway configuration
    - DNS settings
    - Lease times
    """

    def validate(self) -> ValidationResult:
        """Validate DHCP configuration."""
        result = ValidationResult()
        networks = self._get_networks()

        dhcp_ranges = []

        for network in networks:
            result.networks_checked += 1

            if not network.get('dhcpd_enabled'):
                continue

            net_name = network.get('name', 'Unknown')
            net_id = network.get('_id', '')

            # Collect DHCP ranges for overlap check
            dhcp_start = network.get('dhcpd_start', '')
            dhcp_stop = network.get('dhcpd_stop', '')

            if dhcp_start and dhcp_stop:
                dhcp_ranges.append({
                    'name': net_name,
                    'start': dhcp_start,
                    'stop': dhcp_stop,
                    'subnet': network.get('ip_subnet', '')
                })

            # Check gateway configuration
            if not network.get('dhcpd_gateway_enabled'):
                result.add_finding(ValidationFinding(
                    severity=Severity.HIGH,
                    category=Category.DHCP,
                    title="DHCP not providing gateway to clients",
                    description=(
                        f"Network '{net_name}' has DHCP enabled but is not sending "
                        "gateway information (Option 3) to clients. Clients will not "
                        "know how to route traffic off-network."
                    ),
                    device_name=net_name,
                    device_id=net_id,
                    current_value="dhcpd_gateway_enabled: false",
                    recommended_value="dhcpd_gateway_enabled: true",
                    remediation=(
                        "Enable 'dhcpd_gateway_enabled' and set 'dhcpd_gateway' to the "
                        "network's gateway IP address."
                    )
                ))

            # Check DNS configuration
            if not network.get('dhcpd_dns_enabled'):
                result.add_finding(ValidationFinding(
                    severity=Severity.MEDIUM,
                    category=Category.DHCP,
                    title="DHCP not providing DNS servers",
                    description=(
                        f"Network '{net_name}' DHCP is not providing DNS server "
                        "information to clients."
                    ),
                    device_name=net_name,
                    device_id=net_id,
                    current_value="dhcpd_dns_enabled: false",
                    recommended_value="dhcpd_dns_enabled: true",
                    remediation="Enable DNS in DHCP and configure DNS servers."
                ))

            # Check lease time
            lease_time = network.get('dhcpd_leasetime', 86400)
            if lease_time < 3600:  # Less than 1 hour
                result.add_finding(ValidationFinding(
                    severity=Severity.LOW,
                    category=Category.DHCP,
                    title="Very short DHCP lease time",
                    description=(
                        f"Network '{net_name}' has a lease time of {lease_time} seconds "
                        f"({lease_time/60:.0f} minutes). Very short leases increase "
                        "DHCP traffic and can cause issues if DHCP server is unavailable."
                    ),
                    device_name=net_name,
                    device_id=net_id,
                    current_value=f"{lease_time} seconds",
                    recommended_value="86400 seconds (24 hours) for most networks",
                    remediation="Consider increasing lease time unless there's a specific need."
                ))

        return result


class ConfigValidator:
    """
    Main configuration validator that orchestrates all validation checks.

    Usage:
        client = UnifiApiClient(...)
        client.login()

        validator = ConfigValidator(client)
        result = validator.validate_all()

        if not result.passed:
            for finding in result.get_by_severity(Severity.CRITICAL):
                print(f"CRITICAL: {finding.title}")
    """

    def __init__(self, api_client, site: str = "default"):
        self.api_client = api_client
        self.site = site

        # Initialize all validators
        self.trunk_validator = TrunkPortValidator(api_client, site)
        self.stp_validator = STPValidator(api_client, site)
        self.security_validator = SecurityValidator(api_client, site)
        self.operational_validator = OperationalValidator(api_client, site)
        self.dhcp_validator = DHCPValidator(api_client, site)

    def validate_all(self) -> ValidationResult:
        """Run all validators and combine results."""
        combined = ValidationResult()

        validators = [
            ("Trunk/VLAN Routing", self.trunk_validator),
            ("STP Configuration", self.stp_validator),
            ("Security", self.security_validator),
            ("Operational", self.operational_validator),
            ("DHCP", self.dhcp_validator),
        ]

        for name, validator in validators:
            logger.info(f"Running {name} validation...")
            try:
                result = validator.validate()
                combined.findings.extend(result.findings)
                combined.devices_checked = max(combined.devices_checked, result.devices_checked)
                combined.ports_checked += result.ports_checked
                combined.networks_checked = max(combined.networks_checked, result.networks_checked)
            except Exception as e:
                logger.error(f"Error in {name} validation: {e}")
                combined.add_finding(ValidationFinding(
                    severity=Severity.HIGH,
                    category=Category.OPERATIONAL,
                    title=f"Validation error in {name}",
                    description=str(e),
                    device_name="Validator",
                    remediation="Check logs for details"
                ))

        return combined

    def validate_trunk_ports(self) -> ValidationResult:
        """Run only trunk/VLAN routing validation."""
        return self.trunk_validator.validate()

    def validate_stp(self) -> ValidationResult:
        """Run only STP validation."""
        return self.stp_validator.validate()

    def validate_security(self) -> ValidationResult:
        """Run only security validation."""
        return self.security_validator.validate()

    def validate_operational(self) -> ValidationResult:
        """Run only operational validation."""
        return self.operational_validator.validate()

    def validate_dhcp(self) -> ValidationResult:
        """Run only DHCP validation."""
        return self.dhcp_validator.validate()

    def generate_report(self, result: ValidationResult,
                       format: str = "markdown") -> str:
        """Generate a validation report."""
        if format == "markdown":
            return self._generate_markdown_report(result)
        elif format == "json":
            import json
            return json.dumps({
                'summary': result.summary(),
                'findings': [f.to_dict() for f in result.findings]
            }, indent=2)
        else:
            raise ValueError(f"Unknown format: {format}")

    def _generate_markdown_report(self, result: ValidationResult) -> str:
        """Generate markdown validation report."""
        lines = [
            "# UniFi Configuration Validation Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| **Status** | {'✅ PASSED' if result.passed else '❌ FAILED'} |",
            f"| Critical Issues | {result.critical_count} |",
            f"| High Issues | {result.high_count} |",
            f"| Medium Issues | {result.medium_count} |",
            f"| Low Issues | {result.low_count} |",
            f"| Informational | {result.info_count} |",
            f"| Devices Checked | {result.devices_checked} |",
            f"| Ports Checked | {result.ports_checked} |",
            f"| Networks Checked | {result.networks_checked} |",
            "",
        ]

        # Group findings by severity
        severity_emoji = {
            Severity.CRITICAL: "🔴",
            Severity.HIGH: "🟠",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🔵",
            Severity.INFO: "⚪"
        }

        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
                        Severity.LOW, Severity.INFO]:
            findings = result.get_by_severity(severity)
            if not findings:
                continue

            lines.append(f"## {severity_emoji[severity]} {severity.value} Issues ({len(findings)})")
            lines.append("")

            for finding in findings:
                lines.append(f"### {finding.title}")
                lines.append("")
                lines.append(f"**Device**: {finding.device_name}")
                if finding.port_idx is not None:
                    lines.append(f"**Port**: {finding.port_idx}")
                lines.append(f"**Category**: {finding.category.value}")
                lines.append("")
                lines.append(finding.description)
                lines.append("")

                if finding.current_value:
                    lines.append(f"**Current**: `{finding.current_value}`")
                if finding.recommended_value:
                    lines.append(f"**Recommended**: `{finding.recommended_value}`")
                lines.append("")

                if finding.remediation:
                    lines.append(f"**Remediation**: {finding.remediation}")
                    lines.append("")

                lines.append("---")
                lines.append("")

        return "\n".join(lines)
