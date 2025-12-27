#!/usr/bin/env python3
"""
Integration tests for ConfigValidation module.

These tests require a live UniFi controller connection.
Set the following environment variables to run:
- UNIFI_URL: Controller URL (e.g., https://192.168.1.1)
- UNIFI_API_TOKEN: API token for authentication
- UNIFI_SITE: Site name (default: "default")

Run with: pytest tests/test_config_validation_integration.py -v --run-integration
"""

import os
import pytest
from datetime import datetime

# Skip all tests if not running integration tests
pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_INTEGRATION_TESTS') != '1',
    reason="Integration tests disabled. Set RUN_INTEGRATION_TESTS=1 to run."
)


def get_test_client():
    """Get a configured API client for testing."""
    from src.unifi_mapper.api_client import UnifiApiClient

    url = os.environ.get('UNIFI_URL')
    token = os.environ.get('UNIFI_API_TOKEN')
    site = os.environ.get('UNIFI_SITE', 'default')

    if not url or not token:
        pytest.skip("UNIFI_URL and UNIFI_API_TOKEN environment variables required")

    client = UnifiApiClient(
        base_url=url,
        site=site,
        verify_ssl=False,
        api_token=token,
        timeout=30
    )

    if not client.login():
        pytest.skip("Failed to authenticate with UniFi controller")

    return client


class TestTrunkValidatorIntegration:
    """Integration tests for TrunkPortValidator."""

    def test_validate_real_network(self):
        """Test trunk validation against real network."""
        from src.unifi_mapper.config_validation import TrunkPortValidator

        client = get_test_client()
        validator = TrunkPortValidator(client)

        result = validator.validate()

        # Should complete without error
        assert result is not None
        assert result.devices_checked >= 0

        # Log findings for debugging
        for finding in result.findings:
            print(f"\n{finding.severity.value}: {finding.title}")
            print(f"  Device: {finding.device_name}")
            if finding.port_idx:
                print(f"  Port: {finding.port_idx}")
            print(f"  {finding.description}")

    def test_detect_actual_blocking_ports(self):
        """Test detection of blocking ports in real network."""
        from src.unifi_mapper.config_validation import (
            TrunkPortValidator, Severity, Category
        )

        client = get_test_client()
        validator = TrunkPortValidator(client)

        result = validator.validate()

        # Check for any VLAN routing issues
        vlan_issues = result.get_by_category(Category.VLAN_ROUTING)

        print(f"\nFound {len(vlan_issues)} VLAN routing issues:")
        for issue in vlan_issues:
            print(f"  [{issue.severity.value}] {issue.title}")
            print(f"    Device: {issue.device_name}, Port: {issue.port_idx}")
            print(f"    Current: {issue.current_value}")
            print(f"    Recommended: {issue.recommended_value}")


class TestSTPValidatorIntegration:
    """Integration tests for STPValidator."""

    def test_validate_stp_configuration(self):
        """Test STP validation against real network."""
        from src.unifi_mapper.config_validation import STPValidator, Category

        client = get_test_client()
        validator = STPValidator(client)

        result = validator.validate()

        assert result is not None

        stp_findings = result.get_by_category(Category.STP_CONFIG)
        print(f"\nFound {len(stp_findings)} STP findings:")
        for finding in stp_findings:
            print(f"  [{finding.severity.value}] {finding.title}")


class TestSecurityValidatorIntegration:
    """Integration tests for SecurityValidator."""

    def test_validate_security(self):
        """Test security validation against real network."""
        from src.unifi_mapper.config_validation import SecurityValidator, Category

        client = get_test_client()
        validator = SecurityValidator(client)

        result = validator.validate()

        assert result is not None

        security_findings = result.get_by_category(Category.SECURITY)
        print(f"\nFound {len(security_findings)} security findings:")
        for finding in security_findings:
            print(f"  [{finding.severity.value}] {finding.title}")
            print(f"    {finding.description[:100]}...")


class TestOperationalValidatorIntegration:
    """Integration tests for OperationalValidator."""

    def test_validate_operational(self):
        """Test operational validation against real network."""
        from src.unifi_mapper.config_validation import OperationalValidator

        client = get_test_client()
        validator = OperationalValidator(client)

        result = validator.validate()

        assert result is not None
        assert result.devices_checked >= 0

        print(f"\nOperational validation:")
        print(f"  Devices checked: {result.devices_checked}")
        print(f"  Ports checked: {result.ports_checked}")
        print(f"  Networks checked: {result.networks_checked}")
        print(f"  Findings: {len(result.findings)}")


class TestDHCPValidatorIntegration:
    """Integration tests for DHCPValidator."""

    def test_validate_dhcp(self):
        """Test DHCP validation against real network."""
        from src.unifi_mapper.config_validation import DHCPValidator, Category

        client = get_test_client()
        validator = DHCPValidator(client)

        result = validator.validate()

        assert result is not None

        dhcp_findings = result.get_by_category(Category.DHCP)
        print(f"\nFound {len(dhcp_findings)} DHCP findings:")
        for finding in dhcp_findings:
            print(f"  [{finding.severity.value}] {finding.title}")
            print(f"    Network: {finding.device_name}")


class TestConfigValidatorIntegration:
    """Integration tests for main ConfigValidator."""

    def test_full_validation(self):
        """Test full validation suite against real network."""
        from src.unifi_mapper.config_validation import ConfigValidator, Severity

        client = get_test_client()
        validator = ConfigValidator(client)

        result = validator.validate_all()

        assert result is not None

        # Print summary
        print("\n" + "=" * 60)
        print("FULL VALIDATION RESULTS")
        print("=" * 60)
        print(f"Status: {'PASSED' if result.passed else 'FAILED'}")
        print(f"Devices checked: {result.devices_checked}")
        print(f"Ports checked: {result.ports_checked}")
        print(f"Networks checked: {result.networks_checked}")
        print(f"\nFindings by severity:")
        print(f"  Critical: {result.critical_count}")
        print(f"  High: {result.high_count}")
        print(f"  Medium: {result.medium_count}")
        print(f"  Low: {result.low_count}")
        print(f"  Info: {result.info_count}")

        # Print critical and high findings
        if result.critical_count > 0 or result.high_count > 0:
            print("\nCritical and High Issues:")
            for finding in result.findings:
                if finding.severity in [Severity.CRITICAL, Severity.HIGH]:
                    print(f"\n  [{finding.severity.value}] {finding.title}")
                    print(f"    Device: {finding.device_name}")
                    print(f"    {finding.description[:150]}...")
                    if finding.remediation:
                        print(f"    Fix: {finding.remediation[:100]}...")

    def test_generate_reports(self):
        """Test report generation with real data."""
        from src.unifi_mapper.config_validation import ConfigValidator

        client = get_test_client()
        validator = ConfigValidator(client)

        result = validator.validate_all()

        # Generate markdown report
        md_report = validator.generate_report(result, format="markdown")
        assert "# UniFi Configuration Validation Report" in md_report
        assert "Summary" in md_report

        # Generate JSON report
        json_report = validator.generate_report(result, format="json")
        import json
        parsed = json.loads(json_report)
        assert 'summary' in parsed
        assert 'findings' in parsed

        print("\n" + "=" * 60)
        print("GENERATED MARKDOWN REPORT")
        print("=" * 60)
        print(md_report[:2000])
        if len(md_report) > 2000:
            print(f"\n... (truncated, total {len(md_report)} characters)")


class TestSpecificIssueDetection:
    """
    Integration tests for specific issue patterns.
    These replicate real-world issues encountered.
    """

    def test_detect_gateway_port_vlan_blocking(self):
        """
        Test detection of the exact issue pattern that caused VLAN 10 cameras
        to be unreachable:
        - Gateway port with forward: native
        - Gateway port with tagged_vlan_mgmt: block_all
        """
        from src.unifi_mapper.config_validation import (
            ConfigValidator, Category, Severity
        )

        client = get_test_client()
        validator = ConfigValidator(client)

        result = validator.validate_trunk_ports()

        # Look for the specific pattern
        blocking_findings = [
            f for f in result.findings
            if f.category == Category.VLAN_ROUTING
            and f.severity == Severity.CRITICAL
        ]

        print(f"\nVLAN blocking check found {len(blocking_findings)} critical issues:")
        for finding in blocking_findings:
            print(f"\n  {finding.title}")
            print(f"    Device: {finding.device_name}")
            print(f"    Port: {finding.port_idx}")
            print(f"    Current: {finding.current_value}")
            print(f"    Recommended: {finding.recommended_value}")

    def test_detect_dhcp_gateway_issues(self):
        """Test detection of DHCP gateway configuration issues."""
        from src.unifi_mapper.config_validation import (
            ConfigValidator, Category
        )

        client = get_test_client()
        validator = ConfigValidator(client)

        result = validator.validate_dhcp()

        dhcp_issues = result.get_by_category(Category.DHCP)

        print(f"\nDHCP check found {len(dhcp_issues)} issues:")
        for finding in dhcp_issues:
            print(f"\n  [{finding.severity.value}] {finding.title}")
            print(f"    Network: {finding.device_name}")
            if finding.current_value:
                print(f"    Current: {finding.current_value}")


class TestValidationPerformance:
    """Performance tests for validation."""

    def test_validation_completes_in_reasonable_time(self):
        """Test that full validation completes within timeout."""
        import time
        from src.unifi_mapper.config_validation import ConfigValidator

        client = get_test_client()
        validator = ConfigValidator(client)

        start = time.time()
        result = validator.validate_all()
        elapsed = time.time() - start

        print(f"\nFull validation completed in {elapsed:.2f} seconds")
        print(f"Devices: {result.devices_checked}")
        print(f"Ports: {result.ports_checked}")
        print(f"Networks: {result.networks_checked}")

        # Should complete in under 60 seconds for most networks
        assert elapsed < 60, f"Validation took too long: {elapsed:.2f}s"


if __name__ == '__main__':
    # Run with integration tests enabled
    os.environ['RUN_INTEGRATION_TESTS'] = '1'
    pytest.main([__file__, '-v', '-s'])
