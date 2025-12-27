#!/usr/bin/env python3
"""
Unit tests for the ConfigAutoFix module.

Tests cover:
- FixResult and AutoFixResult dataclasses
- ConfigAutoFix fix operations
- Dry run vs live mode
- Device and port filtering
- Report generation
- Rollback script generation
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from src.unifi_mapper.config_validation import (
    Severity,
    Category,
    ValidationFinding,
    ValidationResult,
)
from src.unifi_mapper.config_autofix import (
    FixStatus,
    FixResult,
    AutoFixResult,
    ConfigAutoFix,
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
def sample_finding():
    """Create a sample validation finding."""
    return ValidationFinding(
        severity=Severity.CRITICAL,
        category=Category.VLAN_ROUTING,
        title="Port explicitly blocks all tagged VLANs",
        description="Port has tagged_vlan_mgmt: block_all",
        device_name="Dream Machine Pro Max",
        device_id="device123",
        port_idx=10,
        current_value="tagged_vlan_mgmt: block_all",
        recommended_value="tagged_vlan_mgmt: auto",
        remediation="Remove tagged_vlan_mgmt setting"
    )


@pytest.fixture
def sample_devices():
    """Sample device data for testing."""
    return {
        'data': [
            {
                '_id': 'device123',
                'name': 'Dream Machine Pro Max',
                'type': 'udm',
                'model': 'UDMPROMAX',
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
            },
            {
                '_id': 'device456',
                'name': 'Core Switch',
                'type': 'usw',
                'model': 'USW-Pro-48-PoE',
                'port_overrides': [
                    {
                        'port_idx': 1,
                        'forward': 'all',
                        'portconf_id': 'trunk'
                    },
                    {
                        'port_idx': 2,
                        'forward': 'native',
                        'tagged_vlan_mgmt': 'block_all'
                    }
                ],
                'port_table': [
                    {'port_idx': 1, 'up': True, 'is_uplink': True, 'speed': 10000},
                    {'port_idx': 2, 'up': True, 'is_uplink': False, 'speed': 1000}
                ]
            }
        ]
    }


# ============================================================================
# FixResult Tests
# ============================================================================

class TestFixResult:
    """Tests for FixResult dataclass."""

    def test_creation(self, sample_finding):
        """Test creating a fix result."""
        result = FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Successfully fixed",
            original_value="block_all",
            new_value="(removed)"
        )

        assert result.status == FixStatus.SUCCESS
        assert result.message == "Successfully fixed"
        assert result.original_value == "block_all"
        assert result.new_value == "(removed)"

    def test_to_dict(self, sample_finding):
        """Test converting fix result to dictionary."""
        result = FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed",
            original_value="block_all",
            new_value="(removed)",
            rollback_command="# rollback command"
        )

        d = result.to_dict()

        assert d['device_name'] == "Dream Machine Pro Max"
        assert d['device_id'] == "device123"
        assert d['port_idx'] == 10
        assert d['status'] == "success"
        assert d['original_value'] == "block_all"
        assert d['new_value'] == "(removed)"

    def test_failed_result(self, sample_finding):
        """Test creating a failed fix result."""
        result = FixResult(
            finding=sample_finding,
            status=FixStatus.FAILED,
            message="API error",
            error="Connection timeout"
        )

        assert result.status == FixStatus.FAILED
        assert result.error == "Connection timeout"


# ============================================================================
# AutoFixResult Tests
# ============================================================================

class TestAutoFixResult:
    """Tests for AutoFixResult dataclass."""

    def test_empty_result(self):
        """Test empty auto-fix result."""
        result = AutoFixResult()

        assert result.success_count == 0
        assert result.failed_count == 0
        assert result.skipped_count == 0
        assert result.all_succeeded is False  # No successes

    def test_success_counts(self, sample_finding):
        """Test counting successful fixes."""
        result = AutoFixResult()

        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed 1"
        ))
        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed 2"
        ))
        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.FAILED,
            message="Failed"
        ))

        assert result.success_count == 2
        assert result.failed_count == 1
        assert result.all_succeeded is False

    def test_all_succeeded(self, sample_finding):
        """Test all_succeeded property."""
        result = AutoFixResult()

        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed"
        ))

        assert result.all_succeeded is True

    def test_skipped_count(self, sample_finding):
        """Test counting skipped fixes."""
        result = AutoFixResult()

        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SKIPPED,
            message="Skipped - not in filter"
        ))

        assert result.skipped_count == 1
        assert result.success_count == 0

    def test_summary(self, sample_finding):
        """Test summary generation."""
        result = AutoFixResult(dry_run=True)

        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.DRY_RUN,
            message="Would fix"
        ))

        summary = result.summary()

        assert summary['dry_run'] is True
        assert summary['total_fixes'] == 1
        assert 'timestamp' in summary

    def test_rollback_script(self, sample_finding):
        """Test rollback script generation."""
        result = AutoFixResult()

        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed",
            rollback_command="# Rollback: set tagged_vlan_mgmt=block_all"
        ))

        script = result.get_rollback_script()

        assert "#!/usr/bin/env bash" in script
        assert "Rollback script" in script
        assert "tagged_vlan_mgmt=block_all" in script


# ============================================================================
# ConfigAutoFix Tests
# ============================================================================

class TestConfigAutoFix:
    """Tests for ConfigAutoFix class."""

    def test_initialization(self, mock_api_client):
        """Test ConfigAutoFix initialization."""
        fixer = ConfigAutoFix(mock_api_client, site="default")

        assert fixer.api_client == mock_api_client
        assert fixer.site == "default"
        assert fixer.validator is not None

    def test_fix_tagged_vlan_blocking_dry_run(self, mock_api_client, sample_devices):
        """Test dry run of tagged_vlan_mgmt fix."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_tagged_vlan_blocking(dry_run=True)

        assert result.dry_run is True
        # Should find the block_all issues
        dry_run_fixes = [f for f in result.fixes if f.status == FixStatus.DRY_RUN]
        assert len(dry_run_fixes) >= 1

    def test_fix_forward_native_dry_run(self, mock_api_client, sample_devices):
        """Test dry run of forward: native fix."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_forward_native(dry_run=True)

        assert result.dry_run is True

    def test_device_filter(self, mock_api_client, sample_devices):
        """Test device filtering."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_tagged_vlan_blocking(
            dry_run=True,
            device_filter=["Dream Machine Pro Max"]
        )

        # Only Dream Machine fixes should be included, others skipped
        for fix in result.fixes:
            if fix.status != FixStatus.SKIPPED:
                assert fix.finding.device_name == "Dream Machine Pro Max"

    def test_port_filter(self, mock_api_client, sample_devices):
        """Test port filtering."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_tagged_vlan_blocking(
            dry_run=True,
            port_filter=[10]
        )

        # Only port 10 fixes should be included
        for fix in result.fixes:
            if fix.status != FixStatus.SKIPPED:
                assert fix.finding.port_idx == 10

    def test_fix_all_vlan_blocking_combines_fixes(self, mock_api_client, sample_devices):
        """Test that fix_all combines both fix types."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_all_vlan_blocking(dry_run=True)

        # Should have fixes from both tagged_vlan_mgmt and forward: native
        assert len(result.fixes) >= 1

    def test_update_port_override_success(self, mock_api_client, sample_devices):
        """Test successful port override update."""
        mock_api_client.get_devices.return_value = sample_devices

        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': sample_devices['data'][0]}
        mock_api_client.session.put.return_value = mock_response
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        success, message = fixer._update_port_override(
            'device123',
            10,
            {'tagged_vlan_mgmt': None},
            dry_run=False
        )

        assert success is True
        assert "Successfully" in message

    def test_update_port_override_failure(self, mock_api_client, sample_devices):
        """Test failed port override update."""
        mock_api_client.get_devices.return_value = sample_devices

        # Mock failed API response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {'meta': {'msg': 'Invalid parameter'}}
        mock_api_client.session.put.return_value = mock_response

        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_get_response

        fixer = ConfigAutoFix(mock_api_client)
        success, message = fixer._update_port_override(
            'device123',
            10,
            {'tagged_vlan_mgmt': None},
            dry_run=False
        )

        assert success is False
        assert "API error" in message

    def test_generate_text_report(self, mock_api_client, sample_finding):
        """Test text report generation."""
        fixer = ConfigAutoFix(mock_api_client)

        result = AutoFixResult()
        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed successfully",
            original_value="block_all",
            new_value="(removed)"
        ))

        report = fixer.generate_report(result, format="text")

        assert "AUTO-FIX RESULTS" in report
        assert "SUCCESS" in report
        assert "Dream Machine Pro Max" in report

    def test_generate_markdown_report(self, mock_api_client, sample_finding):
        """Test markdown report generation."""
        fixer = ConfigAutoFix(mock_api_client)

        result = AutoFixResult()
        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed successfully",
            original_value="block_all",
            new_value="(removed)"
        ))

        report = fixer.generate_report(result, format="markdown")

        assert "# UniFi Config Auto-Fix Report" in report
        assert "## Summary" in report
        assert "Dream Machine Pro Max" in report

    def test_generate_json_report(self, mock_api_client, sample_finding):
        """Test JSON report generation."""
        import json

        fixer = ConfigAutoFix(mock_api_client)

        result = AutoFixResult()
        result.add_fix(FixResult(
            finding=sample_finding,
            status=FixStatus.SUCCESS,
            message="Fixed successfully"
        ))

        report = fixer.generate_report(result, format="json")
        parsed = json.loads(report)

        assert 'summary' in parsed
        assert 'fixes' in parsed
        assert len(parsed['fixes']) == 1


# ============================================================================
# Integration Tests (Mock-based)
# ============================================================================

class TestConfigAutoFixIntegration:
    """Integration tests using mocked API responses."""

    def test_full_dry_run_workflow(self, mock_api_client, sample_devices):
        """Test complete dry run workflow."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)

        # Dry run
        result = fixer.fix_all_vlan_blocking(dry_run=True)

        # Verify dry run behavior
        assert result.dry_run is True
        assert result.success_count == 0  # No actual changes
        assert all(f.status in [FixStatus.DRY_RUN, FixStatus.SKIPPED]
                   for f in result.fixes)

    def test_full_live_workflow(self, mock_api_client, sample_devices):
        """Test complete live fix workflow."""
        mock_api_client.get_devices.return_value = sample_devices

        # Mock successful responses
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response
        mock_api_client.session.put.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)

        # Live run
        result = fixer.fix_all_vlan_blocking(dry_run=False)

        # Verify live behavior
        assert result.dry_run is False

    def test_rollback_script_generation(self, mock_api_client, sample_devices):
        """Test that rollback scripts are generated for successful fixes."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response
        mock_api_client.session.put.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_all_vlan_blocking(dry_run=False)

        # Generate rollback script
        script = result.get_rollback_script()

        assert "#!/usr/bin/env bash" in script
        assert "Rollback script" in script


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_device_list(self, mock_api_client):
        """Test with no devices."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        result = fixer.fix_all_vlan_blocking(dry_run=True)

        assert len(result.fixes) == 0

    def test_device_not_found(self, mock_api_client):
        """Test updating non-existent device."""
        mock_api_client.get_devices.return_value = {'data': []}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_response

        fixer = ConfigAutoFix(mock_api_client)
        success, message = fixer._update_port_override(
            'nonexistent',
            1,
            {'tagged_vlan_mgmt': None},
            dry_run=False
        )

        assert success is False
        assert "not found" in message

    def test_api_exception_handling(self, mock_api_client, sample_devices):
        """Test handling of API exceptions."""
        mock_api_client.get_devices.return_value = sample_devices

        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {'data': []}
        mock_api_client.session.get.return_value = mock_get_response

        # Make PUT raise an exception
        mock_api_client.session.put.side_effect = Exception("Connection refused")

        fixer = ConfigAutoFix(mock_api_client)
        success, message = fixer._update_port_override(
            'device123',
            10,
            {'tagged_vlan_mgmt': None},
            dry_run=False
        )

        assert success is False
        assert "Exception" in message


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
