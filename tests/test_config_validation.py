#!/usr/bin/env python3
"""
Unit tests for the ConfigValidation module.

Tests cover:
- TrunkPortValidator: VLAN blocking detection
- STPValidator: STP configuration checks
- SecurityValidator: Security best practices
- OperationalValidator: Operational checks
- DHCPValidator: DHCP configuration
- ConfigValidator: Orchestration and reporting
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.unifi_mapper.config_validation import (
    Severity,
    Category,
    ValidationFinding,
    ValidationResult,
    BaseValidator,
    TrunkPortValidator,
    STPValidator,
    SecurityValidator,
    OperationalValidator,
    DHCPValidator,
    ConfigValidator,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_api_client():
    """Create a mock API client."""
    client = Mock()
    client.is_unifi_os = True
    client.base_url = "https://192.168.1.1"
    client.timeout = 10
    client.session = Mock()
    return client


@pytest.fixture
def sample_devices():
    """Sample device data for testing."""
    return {
        'data': [
            {
                '_id': 'device1',
                'name': 'Core Switch',
                'type': 'usw',
                'model': 'USW-Pro-48-PoE',
                'version': '6.5.59',
                'stp_priority': 4096,
                'port_overrides': [
                    {
                        'port_idx': 1,
                        'name': 'Uplink to Gateway',
                        'forward': 'all',
                        'portconf_id': 'profile1'
                    },
                    {
                        'port_idx': 2,
                        'name': 'Server VLAN',
                        'forward': 'native',  # Problem!
                        'tagged_vlan_mgmt': 'block_all',  # Critical problem!
                        'native_networkconf_id': 'net1'
                    },
                ],
                'port_table': [
                    {'port_idx': 1, 'up': True, 'is_uplink': True, 'speed': 10000},
                    {'port_idx': 2, 'up': True, 'is_uplink': False, 'speed': 1000},
                ],
                'uplink': {'uplink_device_name': 'Gateway'},
            },
            {
                '_id': 'device2',
                'name': 'Dream Machine Pro',
                'type': 'udm',
                'model': 'UDM-Pro',
                'version': '3.2.7',
                'port_overrides': [
                    {
                        'port_idx': 10,
                        'name': 'SFP+ 1',
                        'forward': 'native',
                        'tagged_vlan_mgmt': 'block_all',
                        'native_networkconf_id': 'net1'
                    }
                ],
                'port_table': [
                    {'port_idx': 10, 'up': True, 'is_uplink': False, 'speed': 10000}
                ]
            }
        ]
    }


@pytest.fixture
def sample_networks():
    """Sample network data for testing."""
    return [
        {
            '_id': 'net1',
            'name': 'Home LAN',
            'purpose': 'corporate',
            'ip_subnet': '192.168.1.1/24',
            'vlan_enabled': False,
            'dhcpd_enabled': True,
            'dhcpd_start': '192.168.1.100',
            'dhcpd_stop': '192.168.1.200',
            'dhcpd_gateway_enabled': True,
            'dhcpd_gateway': '192.168.1.1',
            'dhcpd_dns_enabled': True,
            'dhcpguard_enabled': True,
            'dhcpd_leasetime': 86400,
        },
        {
            '_id': 'net2',
            'name': 'CCTV',
            'purpose': 'corporate',
            'ip_subnet': '192.168.10.254/24',
            'vlan': 10,
            'vlan_enabled': True,
            'dhcpd_enabled': True,
            'dhcpd_start': '192.168.10.51',
            'dhcpd_stop': '192.168.10.254',  # Problem: includes gateway!
            'dhcpd_gateway_enabled': False,  # Problem: gateway not sent!
            'dhcpd_dns_enabled': True,
            'dhcpguard_enabled': False,
            'dhcpd_leasetime': 86400,
        },
        {
            '_id': 'net3',
            'name': 'IoT',
            'purpose': 'corporate',
            'ip_subnet': '192.168.20.1/24',
            'vlan': 20,
            'vlan_enabled': True,
            'dhcpd_enabled': True,
            'dhcpd_gateway_enabled': True,
            'dhcpd_dns_enabled': True,
        },
        {
            '_id': 'net4',
            'name': 'Guest',
            'purpose': 'guest',
            'ip_subnet': '192.168.100.1/24',
            'vlan': 100,
            'vlan_enabled': True,
            'networkgroup': 'guest',
            'dhcpd_enabled': True,
            'dhcpd_gateway_enabled': True,
        }
    ]


@pytest.fixture
def sample_port_profiles():
    """Sample port profile data."""
    return [
        {
            '_id': 'profile1',
            'name': 'All VLANs Trunk',
            'forward': 'all',
            'native_networkconf_id': 'net1',
            'tagged_networkconf_ids': ['net2', 'net3', 'net4']
        },
        {
            '_id': 'profile2',
            'name': 'Trunk Missing VLANs',
            'forward': 'customize',
            'native_networkconf_id': 'net1',
            'tagged_networkconf_ids': ['net2']  # Missing net3, net4
        }
    ]


# ============================================================================
# ValidationFinding Tests
# ============================================================================

class TestValidationFinding:
    """Tests for ValidationFinding dataclass."""

    def test_creation(self):
        """Test creating a validation finding."""
        finding = ValidationFinding(
            severity=Severity.CRITICAL,
            category=Category.VLAN_ROUTING,
            title="Test Finding",
            description="Test description",
            device_name="Test Device"
        )

        assert finding.severity == Severity.CRITICAL
        assert finding.category == Category.VLAN_ROUTING
        assert finding.title == "Test Finding"
        assert finding.device_name == "Test Device"

    def test_to_dict(self):
        """Test converting finding to dictionary."""
        finding = ValidationFinding(
            severity=Severity.HIGH,
            category=Category.SECURITY,
            title="Security Issue",
            description="Description",
            device_name="Device1",
            device_id="id123",
            port_idx=5,
            current_value="bad",
            recommended_value="good",
            remediation="Fix it"
        )

        result = finding.to_dict()

        assert result['severity'] == 'HIGH'
        assert result['category'] == 'Security'
        assert result['title'] == 'Security Issue'
        assert result['port_idx'] == 5
        assert result['current_value'] == 'bad'
        assert result['recommended_value'] == 'good'


# ============================================================================
# ValidationResult Tests
# ============================================================================

class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_empty_result_passes(self):
        """Empty result should pass."""
        result = ValidationResult()
        assert result.passed is True
        assert result.critical_count == 0
        assert result.high_count == 0

    def test_critical_finding_fails(self):
        """Result with critical finding should fail."""
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.CRITICAL,
            category=Category.VLAN_ROUTING,
            title="Critical Issue",
            description="Desc",
            device_name="Device"
        ))

        assert result.passed is False
        assert result.critical_count == 1

    def test_high_finding_fails(self):
        """Result with high severity finding should fail."""
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.HIGH,
            category=Category.SECURITY,
            title="High Issue",
            description="Desc",
            device_name="Device"
        ))

        assert result.passed is False
        assert result.high_count == 1

    def test_medium_finding_passes(self):
        """Result with only medium finding should pass."""
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.MEDIUM,
            category=Category.OPERATIONAL,
            title="Medium Issue",
            description="Desc",
            device_name="Device"
        ))

        assert result.passed is True
        assert result.medium_count == 1

    def test_severity_counts(self):
        """Test counting findings by severity."""
        result = ValidationResult()

        for severity in [Severity.CRITICAL, Severity.CRITICAL,
                        Severity.HIGH, Severity.MEDIUM,
                        Severity.LOW, Severity.LOW, Severity.LOW,
                        Severity.INFO]:
            result.add_finding(ValidationFinding(
                severity=severity,
                category=Category.OPERATIONAL,
                title=f"{severity.value} Issue",
                description="Desc",
                device_name="Device"
            ))

        assert result.critical_count == 2
        assert result.high_count == 1
        assert result.medium_count == 1
        assert result.low_count == 3
        assert result.info_count == 1

    def test_get_by_severity(self):
        """Test filtering findings by severity."""
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.CRITICAL,
            category=Category.VLAN_ROUTING,
            title="Critical 1",
            description="Desc",
            device_name="Device"
        ))
        result.add_finding(ValidationFinding(
            severity=Severity.LOW,
            category=Category.OPERATIONAL,
            title="Low 1",
            description="Desc",
            device_name="Device"
        ))

        critical = result.get_by_severity(Severity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].title == "Critical 1"

    def test_get_by_category(self):
        """Test filtering findings by category."""
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.HIGH,
            category=Category.SECURITY,
            title="Security Issue",
            description="Desc",
            device_name="Device"
        ))
        result.add_finding(ValidationFinding(
            severity=Severity.HIGH,
            category=Category.VLAN_ROUTING,
            title="VLAN Issue",
            description="Desc",
            device_name="Device"
        ))

        security = result.get_by_category(Category.SECURITY)
        assert len(security) == 1
        assert security[0].title == "Security Issue"

    def test_summary(self):
        """Test summary generation."""
        result = ValidationResult()
        result.devices_checked = 5
        result.ports_checked = 50
        result.networks_checked = 3

        summary = result.summary()

        assert summary['passed'] is True
        assert summary['total_findings'] == 0
        assert summary['devices_checked'] == 5
        assert summary['ports_checked'] == 50
        assert summary['networks_checked'] == 3
        assert 'timestamp' in summary


# ============================================================================
# TrunkPortValidator Tests
# ============================================================================

class TestTrunkPortValidator:
    """Tests for TrunkPortValidator."""

    def test_detects_forward_native_on_trunk(self, mock_api_client, sample_devices, sample_networks):
        """Test detection of forward: native on trunk ports."""
        mock_api_client.get_devices.return_value = sample_devices

        # Mock network request
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        result = validator.validate()

        # Should find the forward: native issue
        critical_findings = result.get_by_severity(Severity.CRITICAL)
        assert len(critical_findings) >= 1

        native_findings = [f for f in critical_findings if 'native' in f.current_value.lower()]
        assert len(native_findings) >= 1

    def test_detects_block_all_tagged_vlans(self, mock_api_client, sample_devices, sample_networks):
        """Test detection of tagged_vlan_mgmt: block_all."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        result = validator.validate()

        critical_findings = result.get_by_severity(Severity.CRITICAL)
        block_findings = [f for f in critical_findings if 'block_all' in str(f.current_value).lower()]
        assert len(block_findings) >= 1

    def test_passes_correctly_configured_ports(self, mock_api_client):
        """Test that correctly configured ports pass validation."""
        good_devices = {
            'data': [{
                '_id': 'device1',
                'name': 'Good Switch',
                'type': 'usw',
                'port_overrides': [
                    {
                        'port_idx': 1,
                        'forward': 'all',
                        'portconf_id': 'trunk_profile'
                    }
                ],
                'port_table': [
                    {'port_idx': 1, 'up': True, 'is_uplink': True, 'speed': 10000}
                ]
            }]
        }

        mock_api_client.get_devices.return_value = good_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        result = validator.validate()

        # Should not have critical VLAN routing findings
        critical_vlan = [f for f in result.findings
                        if f.severity == Severity.CRITICAL
                        and f.category == Category.VLAN_ROUTING]
        assert len(critical_vlan) == 0


# ============================================================================
# STPValidator Tests
# ============================================================================

class TestSTPValidator:
    """Tests for STPValidator."""

    def test_detects_non_deterministic_root(self, mock_api_client):
        """Test detection of non-deterministic STP root bridge."""
        devices_same_priority = {
            'data': [
                {
                    '_id': 'sw1',
                    'name': 'Switch 1',
                    'type': 'usw',
                    'stp_priority': 32768,
                    'port_table': [],
                    'port_overrides': []
                },
                {
                    '_id': 'sw2',
                    'name': 'Switch 2',
                    'type': 'usw',
                    'stp_priority': 32768,
                    'port_table': [],
                    'port_overrides': []
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices_same_priority

        validator = STPValidator(mock_api_client)
        result = validator.validate()

        # Should detect non-deterministic root
        stp_findings = result.get_by_category(Category.STP_CONFIG)
        non_deterministic = [f for f in stp_findings if 'deterministic' in f.title.lower()]
        assert len(non_deterministic) >= 1

    def test_accepts_proper_stp_hierarchy(self, mock_api_client):
        """Test that proper STP hierarchy passes."""
        devices_proper_hierarchy = {
            'data': [
                {
                    '_id': 'sw1',
                    'name': 'Core Switch',
                    'type': 'usw',
                    'stp_priority': 4096,  # Root
                    'port_table': [],
                    'port_overrides': []
                },
                {
                    '_id': 'sw2',
                    'name': 'Distribution Switch',
                    'type': 'usw',
                    'stp_priority': 8192,  # Secondary
                    'port_table': [],
                    'port_overrides': []
                },
                {
                    '_id': 'sw3',
                    'name': 'Access Switch',
                    'type': 'usw',
                    'stp_priority': 32768,  # Default
                    'port_table': [],
                    'port_overrides': []
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices_proper_hierarchy

        validator = STPValidator(mock_api_client)
        result = validator.validate()

        # Should not have HIGH severity STP issues
        high_stp = [f for f in result.findings
                   if f.severity == Severity.HIGH
                   and f.category == Category.STP_CONFIG]
        assert len(high_stp) == 0


# ============================================================================
# SecurityValidator Tests
# ============================================================================

class TestSecurityValidator:
    """Tests for SecurityValidator."""

    def test_detects_guest_without_isolation(self, mock_api_client, sample_networks):
        """Test detection of guest network without proper isolation."""
        # Modify guest network to lack isolation
        networks = sample_networks.copy()
        for net in networks:
            if net['name'] == 'Guest':
                net['networkgroup'] = 'LAN'  # Wrong - should be 'guest'

        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': networks}
        mock_api_client.session.get.return_value = mock_response

        validator = SecurityValidator(mock_api_client)
        result = validator.validate()

        security_findings = result.get_by_category(Category.SECURITY)
        guest_findings = [f for f in security_findings if 'guest' in f.title.lower()]
        assert len(guest_findings) >= 1

    def test_detects_dhcp_guard_disabled(self, mock_api_client, sample_networks):
        """Test detection of DHCP guarding disabled."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = SecurityValidator(mock_api_client)
        result = validator.validate()

        security_findings = result.get_by_category(Category.SECURITY)
        dhcp_guard_findings = [f for f in security_findings if 'dhcp guard' in f.title.lower()]
        # CCTV network has dhcpguard_enabled: False
        assert len(dhcp_guard_findings) >= 1


# ============================================================================
# OperationalValidator Tests
# ============================================================================

class TestOperationalValidator:
    """Tests for OperationalValidator."""

    def test_detects_unnamed_devices(self, mock_api_client):
        """Test detection of unnamed devices."""
        devices = {
            'data': [
                {
                    '_id': 'dev1',
                    'name': '',  # No name
                    'model': 'USW-Lite-8-PoE',
                    'type': 'usw',
                    'version': '6.5.59',
                    'port_table': [],
                    'port_overrides': []
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = OperationalValidator(mock_api_client)
        result = validator.validate()

        operational_findings = result.get_by_category(Category.OPERATIONAL)
        unnamed_findings = [f for f in operational_findings if 'not named' in f.title.lower()]
        assert len(unnamed_findings) >= 1

    def test_detects_firmware_inconsistency(self, mock_api_client):
        """Test detection of inconsistent firmware versions."""
        devices = {
            'data': [
                {
                    '_id': 'dev1',
                    'name': 'Switch 1',
                    'type': 'usw',
                    'version': '6.5.59',
                    'port_table': [],
                    'port_overrides': []
                },
                {
                    '_id': 'dev2',
                    'name': 'Switch 2',
                    'type': 'usw',
                    'version': '6.4.50',  # Different version
                    'port_table': [],
                    'port_overrides': []
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = OperationalValidator(mock_api_client)
        result = validator.validate()

        firmware_findings = result.get_by_category(Category.FIRMWARE)
        inconsistent = [f for f in firmware_findings if 'inconsistent' in f.title.lower()]
        assert len(inconsistent) >= 1

    def test_detects_high_poe_utilization(self, mock_api_client):
        """Test detection of high PoE budget utilization."""
        devices = {
            'data': [
                {
                    '_id': 'dev1',
                    'name': 'PoE Switch',
                    'type': 'usw',
                    'version': '6.5.59',
                    'poe_budget': 100,  # 100W budget
                    'sys_stats': {
                        'poe_power': 95  # 95W used = 95%
                    },
                    'port_table': [],
                    'port_overrides': []
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = OperationalValidator(mock_api_client)
        result = validator.validate()

        # Should detect high PoE utilization
        poe_findings = [f for f in result.findings if 'poe' in f.title.lower()]
        assert len(poe_findings) >= 1
        assert any(f.severity == Severity.HIGH for f in poe_findings)


# ============================================================================
# DHCPValidator Tests
# ============================================================================

class TestDHCPValidator:
    """Tests for DHCPValidator."""

    def test_detects_dhcp_gateway_disabled(self, mock_api_client, sample_networks):
        """Test detection of DHCP gateway not enabled."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = DHCPValidator(mock_api_client)
        result = validator.validate()

        dhcp_findings = result.get_by_category(Category.DHCP)
        gateway_findings = [f for f in dhcp_findings if 'gateway' in f.title.lower()]
        # CCTV network has dhcpd_gateway_enabled: False
        assert len(gateway_findings) >= 1

    def test_detects_dhcp_range_including_gateway(self, mock_api_client, sample_networks):
        """Test detection of DHCP range including gateway IP."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = OperationalValidator(mock_api_client)  # This check is in OperationalValidator
        result = validator.validate()

        dhcp_findings = result.get_by_category(Category.DHCP)
        range_findings = [f for f in dhcp_findings if 'range' in f.title.lower()]
        # CCTV network has dhcpd_stop = gateway IP
        assert len(range_findings) >= 1


# ============================================================================
# ConfigValidator Integration Tests
# ============================================================================

class TestConfigValidator:
    """Tests for ConfigValidator orchestration."""

    def test_validate_all_runs_all_validators(self, mock_api_client, sample_devices, sample_networks):
        """Test that validate_all runs all validators."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_networks}
        mock_api_client.session.get.return_value = mock_response

        validator = ConfigValidator(mock_api_client)
        result = validator.validate_all()

        # Should have findings from multiple categories
        categories = {f.category for f in result.findings}
        assert len(categories) >= 2

    def test_generate_markdown_report(self, mock_api_client):
        """Test markdown report generation."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = ConfigValidator(mock_api_client)

        # Create a result with findings
        result = ValidationResult()
        result.add_finding(ValidationFinding(
            severity=Severity.CRITICAL,
            category=Category.VLAN_ROUTING,
            title="Test Critical Issue",
            description="Test description",
            device_name="Test Device",
            remediation="Fix it"
        ))

        report = validator.generate_report(result, format="markdown")

        assert "# UniFi Configuration Validation Report" in report
        assert "CRITICAL" in report
        assert "Test Critical Issue" in report
        assert "FAILED" in report  # Because of critical finding

    def test_generate_json_report(self, mock_api_client):
        """Test JSON report generation."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = ConfigValidator(mock_api_client)
        result = ValidationResult()

        import json
        report = validator.generate_report(result, format="json")
        parsed = json.loads(report)

        assert 'summary' in parsed
        assert 'findings' in parsed
        assert parsed['summary']['passed'] is True


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_device_list(self, mock_api_client):
        """Test handling of empty device list."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = ConfigValidator(mock_api_client)
        result = validator.validate_all()

        assert result.passed is True
        assert result.devices_checked == 0

    def test_missing_port_overrides(self, mock_api_client):
        """Test handling of devices without port_overrides."""
        devices = {
            'data': [{
                '_id': 'dev1',
                'name': 'Simple Device',
                'type': 'usw',
                # No port_overrides key
                'port_table': []
            }]
        }

        mock_api_client.get_devices.return_value = devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        # Should not raise exception
        result = validator.validate()
        assert isinstance(result, ValidationResult)

    def test_api_error_handling(self, mock_api_client):
        """Test handling of API errors."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 500  # Error
        mock_response.json.return_value = {}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        # Should handle gracefully
        result = validator.validate()
        assert isinstance(result, ValidationResult)


# ============================================================================
# Real-World Scenario Tests
# ============================================================================

class TestRealWorldScenarios:
    """Test real-world scenarios based on actual issues encountered."""

    def test_scenario_dream_machine_port_blocking_vlans(self, mock_api_client):
        """
        Test the exact scenario that caused the VLAN 10 CCTV issue:
        Dream Machine SFP+ port with forward: native and tagged_vlan_mgmt: block_all
        """
        devices = {
            'data': [
                {
                    '_id': 'udm1',
                    'name': 'Dream Machine Pro Max',
                    'type': 'udm',
                    'model': 'UDMPROMAX',
                    'port_overrides': [
                        {
                            'port_idx': 10,
                            'name': 'SFP+ 1',
                            'forward': 'native',
                            'tagged_vlan_mgmt': 'block_all',
                            'native_networkconf_id': 'home_lan_id',
                            'speed': 10000
                        }
                    ],
                    'port_table': [
                        {
                            'port_idx': 10,
                            'up': True,
                            'is_uplink': False,
                            'speed': 10000,
                            'name': 'SFP+ 1'
                        }
                    ]
                }
            ]
        }

        mock_api_client.get_devices.return_value = devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        validator = TrunkPortValidator(mock_api_client)
        result = validator.validate()

        # Must find BOTH issues
        critical_findings = result.get_by_severity(Severity.CRITICAL)

        # Check for forward: native finding
        native_findings = [f for f in critical_findings
                         if 'forward' in f.current_value.lower()
                         and 'native' in f.current_value.lower()]
        assert len(native_findings) >= 1, "Should detect forward: native issue"

        # Check for tagged_vlan_mgmt: block_all finding
        block_findings = [f for f in critical_findings
                        if 'block_all' in str(f.current_value).lower()]
        assert len(block_findings) >= 1, "Should detect tagged_vlan_mgmt: block_all issue"

        # Verify device name in findings
        for finding in critical_findings:
            assert 'Dream Machine' in finding.device_name

    def test_scenario_dhcp_not_sending_gateway(self, mock_api_client):
        """
        Test the DHCP gateway issue where cameras get IP but no gateway.
        """
        networks = [
            {
                '_id': 'cctv_net',
                'name': 'CCTV',
                'vlan': 10,
                'vlan_enabled': True,
                'ip_subnet': '192.168.10.254/24',
                'dhcpd_enabled': True,
                'dhcpd_gateway_enabled': False,  # THE PROBLEM
                'dhcpd_dns_enabled': True,
                'dhcpd_start': '192.168.10.51',
                'dhcpd_stop': '192.168.10.254'  # Also includes gateway
            }
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': networks}
        mock_api_client.session.get.return_value = mock_response

        validator = DHCPValidator(mock_api_client)
        result = validator.validate()

        dhcp_findings = result.get_by_category(Category.DHCP)

        # Must find gateway not enabled
        gateway_findings = [f for f in dhcp_findings
                          if 'gateway' in f.title.lower()
                          and 'not' in f.title.lower()]
        assert len(gateway_findings) >= 1, "Should detect DHCP gateway not enabled"

    def test_scenario_complete_validation_with_issues(self, mock_api_client):
        """Test complete validation catching multiple real-world issues."""
        devices = {
            'data': [
                {
                    '_id': 'udm1',
                    'name': 'Dream Machine Pro Max',
                    'type': 'udm',
                    'port_overrides': [
                        {
                            'port_idx': 10,
                            'forward': 'native',
                            'tagged_vlan_mgmt': 'block_all'
                        }
                    ],
                    'port_table': [{'port_idx': 10, 'up': True, 'is_uplink': False, 'speed': 10000}]
                },
                {
                    '_id': 'sw1',
                    'name': '',  # Unnamed
                    'type': 'usw',
                    'model': 'USW-Lite-8',
                    'version': '6.5.59',
                    'stp_priority': 32768,
                    'port_overrides': [],
                    'port_table': []
                },
                {
                    '_id': 'sw2',
                    'name': '',  # Unnamed
                    'type': 'usw',
                    'model': 'USW-Lite-8',
                    'version': '6.4.50',  # Different version
                    'stp_priority': 32768,  # Same priority - non-deterministic
                    'port_overrides': [],
                    'port_table': []
                }
            ]
        }

        networks = [
            {
                '_id': 'net1',
                'name': 'CCTV',
                'vlan': 10,
                'vlan_enabled': True,
                'dhcpd_enabled': True,
                'dhcpd_gateway_enabled': False,
                'dhcpd_dns_enabled': True,
                'dhcpguard_enabled': False
            }
        ]

        mock_api_client.get_devices.return_value = devices

        def mock_get(url, **kwargs):
            response = Mock()
            response.status_code = 200
            if 'networkconf' in url:
                response.json.return_value = {'data': networks}
            elif 'portconf' in url:
                response.json.return_value = {'data': []}
            else:
                response.json.return_value = {'data': []}
            return response

        mock_api_client.session.get.side_effect = mock_get

        validator = ConfigValidator(mock_api_client)
        result = validator.validate_all()

        # Should fail due to critical issues
        assert result.passed is False

        # Should have findings from multiple categories
        categories = {f.category for f in result.findings}
        assert Category.VLAN_ROUTING in categories
        assert Category.DHCP in categories or Category.SECURITY in categories


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
