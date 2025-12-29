"""Comprehensive integration tests for analysis tools against live UniFi controller.

This test suite validates all P1, P2, and P3 analysis tools against a real
UniFi controller. Tests are marked with @pytest.mark.live and should only
be run when a controller is available.

Test Categories:
- P1 (High Priority): IP conflicts, storm detection, VLAN diagnostics
- P2 (Medium Priority): Link quality, capacity planning, LAG monitoring, QoS validation
- P3 (Lower Priority): MAC analyzer, firmware advisor

Run with: pytest tests/integration/test_live_analysis.py -v -m live
"""

import os
import pytest
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from unifi_mcp.utils.errors import ToolError  # noqa: E402


# =============================================================================
# P1 Tools - High Priority (IP Conflicts, Storm Detection, VLAN Diagnostics)
# =============================================================================


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveIPConflictDetection:
    """Test IP conflict detection against real controller."""

    async def test_detect_ip_conflicts_network_wide(self):
        """Test IP conflict detection across entire network."""
        try:
            from unifi_mcp.tools.analysis.ip_conflicts import detect_ip_conflicts

            report = await detect_ip_conflicts()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'total_clients_scanned')
            assert hasattr(report, 'conflicts_found')
            assert hasattr(report, 'conflicts')
            assert hasattr(report, 'healthy')
            assert hasattr(report, 'recommendations')

            # Basic assertions
            assert report.total_clients_scanned >= 0
            assert report.conflicts_found >= 0
            assert isinstance(report.conflicts, list)
            assert isinstance(report.healthy, bool)
            assert isinstance(report.recommendations, list)

            # If conflicts found, validate structure
            for conflict in report.conflicts:
                assert hasattr(conflict, 'ip_address')
                assert hasattr(conflict, 'clients')
                assert hasattr(conflict, 'conflict_count')
                assert hasattr(conflict, 'severity')
                assert conflict.conflict_count >= 2
                assert conflict.severity in ('low', 'medium', 'high', 'critical')

            print(
                f'✓ IP conflict detection: {report.total_clients_scanned} clients scanned, '
                f'{report.conflicts_found} conflicts found'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveStormDetection:
    """Test broadcast/multicast storm detection against real controller."""

    async def test_detect_storms_all_devices(self):
        """Test storm detection across all devices."""
        try:
            from unifi_mcp.tools.analysis.storm_detection import detect_storms

            report = await detect_storms()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_analyzed')
            assert hasattr(report, 'ports_analyzed')
            assert hasattr(report, 'storms_detected')
            assert hasattr(report, 'active_storms')
            assert hasattr(report, 'high_risk_ports')
            assert hasattr(report, 'network_healthy')
            assert hasattr(report, 'thresholds')

            # Basic assertions
            assert report.devices_analyzed >= 0
            assert report.ports_analyzed >= 0
            assert report.storms_detected >= 0
            assert isinstance(report.active_storms, list)
            assert isinstance(report.high_risk_ports, list)
            assert isinstance(report.network_healthy, bool)

            # Validate storm event structure if any
            for storm in report.active_storms:
                assert hasattr(storm, 'device_id')
                assert hasattr(storm, 'device_name')
                assert hasattr(storm, 'storm_type')
                assert hasattr(storm, 'severity')
                assert hasattr(storm, 'recommendation')

            print(
                f'✓ Storm detection: {report.devices_analyzed} devices, '
                f'{report.ports_analyzed} ports analyzed, '
                f'{report.storms_detected} storms detected'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_detect_storms_custom_thresholds(self):
        """Test storm detection with custom thresholds."""
        try:
            from unifi_mcp.tools.analysis.storm_detection import detect_storms

            # Use thresholds dict as expected by the function signature
            custom_thresholds = {
                'broadcast': 50.0,  # Very high threshold - unlikely to trigger
                'multicast': 50.0,
            }
            report = await detect_storms(thresholds=custom_thresholds)

            assert report.devices_analyzed >= 0
            # With high thresholds, fewer storms should be detected
            assert isinstance(report.thresholds, dict)

            print(f'✓ Storm detection with custom thresholds: {report.storms_detected} storms')

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveVLANDiagnostics:
    """Test VLAN diagnostics against real controller."""

    async def test_diagnose_vlans_all(self):
        """Test VLAN diagnostics across entire network."""
        try:
            from unifi_mcp.tools.analysis.vlan_diagnostics import diagnose_vlans

            report = await diagnose_vlans()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'vlans_configured')
            assert hasattr(report, 'vlans')
            assert hasattr(report, 'port_configs')
            assert hasattr(report, 'diagnostic_checks')
            assert hasattr(report, 'issues_found')
            assert hasattr(report, 'warnings_found')
            assert hasattr(report, 'overall_health')

            # Basic assertions
            assert report.vlans_configured >= 0
            assert isinstance(report.vlans, list)
            assert isinstance(report.port_configs, list)
            assert isinstance(report.diagnostic_checks, list)
            assert report.overall_health in ('HEALTHY', 'WARNING', 'DEGRADED', 'CRITICAL')

            # Validate VLAN info structure
            for vlan in report.vlans:
                assert hasattr(vlan, 'vlan_id')
                assert hasattr(vlan, 'name')
                assert hasattr(vlan, 'enabled')

            # Validate diagnostic check structure
            for check in report.diagnostic_checks:
                assert hasattr(check, 'check_name')
                assert hasattr(check, 'status')
                assert hasattr(check, 'message')
                assert check.status in ('PASS', 'FAIL', 'WARNING')

            print(
                f'✓ VLAN diagnostics: {report.vlans_configured} VLANs, '
                f'{report.issues_found} issues, {report.warnings_found} warnings, '
                f'health: {report.overall_health}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_diagnose_vlans_specific(self):
        """Test VLAN diagnostics for specific source VLAN."""
        try:
            from unifi_mcp.tools.analysis.vlan_diagnostics import diagnose_vlans
            from unifi_mcp.utils.client import UniFiClient

            # Get available VLANs first
            async with UniFiClient() as client:
                networks = await client.get(client.build_path('rest/networkconf'))

                if not networks:
                    pytest.skip('No VLANs configured')

                # Find first VLAN with a VLAN ID
                test_vlan = None
                for net in networks:
                    if net.get('vlan'):
                        test_vlan = net.get('vlan')
                        break

                if not test_vlan:
                    pytest.skip('No VLANs with VLAN IDs found')

            # Use source_vlan parameter as expected by function signature
            report = await diagnose_vlans(source_vlan=test_vlan)

            assert report.vlans_configured >= 1
            print(f'✓ VLAN diagnostics for VLAN {test_vlan}: {report.issues_found} issues')

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


# =============================================================================
# P2 Tools - Medium Priority (Link Quality, Capacity, LAGs, QoS)
# =============================================================================


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveLinkQualityAnalysis:
    """Test link quality analysis against real controller."""

    async def test_analyze_link_quality_all(self):
        """Test link quality analysis across all ports."""
        try:
            from unifi_mcp.tools.analysis.link_quality import analyze_link_quality

            report = await analyze_link_quality()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_analyzed')
            assert hasattr(report, 'ports_analyzed')
            assert hasattr(report, 'healthy_ports')
            assert hasattr(report, 'degraded_ports')
            assert hasattr(report, 'critical_ports')
            assert hasattr(report, 'port_metrics')
            assert hasattr(report, 'overall_health')
            assert hasattr(report, 'top_issues')

            # Basic assertions
            assert report.devices_analyzed >= 0
            assert report.ports_analyzed >= 0
            assert report.healthy_ports >= 0
            assert report.degraded_ports >= 0
            assert report.critical_ports >= 0
            assert report.overall_health in ('HEALTHY', 'WARNING', 'DEGRADED', 'CRITICAL')

            # Validate port metrics
            for metric in report.port_metrics:
                assert hasattr(metric, 'device_id')
                assert hasattr(metric, 'port_idx')
                assert hasattr(metric, 'link_speed')
                assert hasattr(metric, 'health_score')
                assert 0 <= metric.health_score <= 100

            print(
                f'✓ Link quality: {report.ports_analyzed} ports analyzed, '
                f'health: {report.overall_health}, '
                f'degraded: {report.degraded_ports}, critical: {report.critical_ports}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveCapacityPlanning:
    """Test capacity planning against real controller."""

    async def test_get_capacity_report_all(self):
        """Test capacity report across all devices."""
        try:
            from unifi_mcp.tools.analysis.capacity_planning import get_capacity_report

            report = await get_capacity_report()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'total_devices')
            assert hasattr(report, 'total_ports')
            assert hasattr(report, 'used_ports')
            assert hasattr(report, 'available_ports')
            assert hasattr(report, 'overall_utilization')
            assert hasattr(report, 'total_poe_budget')
            assert hasattr(report, 'total_poe_used')
            assert hasattr(report, 'devices')
            assert hasattr(report, 'bottlenecks')
            assert hasattr(report, 'expansion_needed')
            assert hasattr(report, 'recommendations')

            # Basic assertions
            assert report.total_devices >= 0
            assert report.total_ports >= 0
            assert report.used_ports >= 0
            assert report.available_ports >= 0
            assert 0 <= report.overall_utilization <= 100
            assert isinstance(report.expansion_needed, bool)

            # Validate device capacity
            for device in report.devices:
                assert hasattr(device, 'device_id')
                assert hasattr(device, 'device_name')
                assert hasattr(device, 'total_ports')
                assert hasattr(device, 'used_ports')
                assert hasattr(device, 'utilization_percent')
                assert device.used_ports <= device.total_ports

            print(
                f'✓ Capacity report: {report.total_devices} devices, '
                f'{report.used_ports}/{report.total_ports} ports used '
                f'({report.overall_utilization:.1f}%)'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveLAGMonitoring:
    """Test LAG monitoring against real controller."""

    async def test_monitor_lags_all(self):
        """Test LAG monitoring across all devices."""
        try:
            from unifi_mcp.tools.analysis.lag_monitoring import monitor_lags

            report = await monitor_lags()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_analyzed')
            assert hasattr(report, 'total_lags')
            assert hasattr(report, 'healthy_lags')
            assert hasattr(report, 'degraded_lags')
            assert hasattr(report, 'critical_lags')
            assert hasattr(report, 'lag_groups')
            assert hasattr(report, 'network_healthy')
            assert hasattr(report, 'recommendations')

            # Basic assertions
            assert report.devices_analyzed >= 0
            assert report.total_lags >= 0
            assert isinstance(report.network_healthy, bool)

            # Validate LAG groups if any
            for lag in report.lag_groups:
                assert hasattr(lag, 'lag_id')
                assert hasattr(lag, 'device_id')
                assert hasattr(lag, 'device_name')
                assert hasattr(lag, 'members')
                assert hasattr(lag, 'status')
                assert lag.status in (
                    'healthy',
                    'degraded',
                    'critical',
                    'inactive',
                    'misconfigured',
                )

            print(
                f'✓ LAG monitoring: {report.total_lags} LAGs found, '
                f'healthy: {report.healthy_lags}, degraded: {report.degraded_lags}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveQoSValidation:
    """Test QoS validation against real controller."""

    async def test_validate_qos_all(self):
        """Test QoS validation across all devices."""
        try:
            from unifi_mcp.tools.analysis.qos_validation import validate_qos

            report = await validate_qos()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_analyzed')
            assert hasattr(report, 'ports_analyzed')
            assert hasattr(report, 'findings')
            assert hasattr(report, 'critical_count')
            assert hasattr(report, 'error_count')
            assert hasattr(report, 'warning_count')
            assert hasattr(report, 'info_count')
            assert hasattr(report, 'port_configs')
            assert hasattr(report, 'overall_health')
            assert hasattr(report, 'recommendations')

            # Basic assertions
            assert report.devices_analyzed >= 0
            assert report.ports_analyzed >= 0
            assert report.overall_health in ('HEALTHY', 'WARNING', 'DEGRADED', 'CRITICAL')

            # Validate findings
            for finding in report.findings:
                assert hasattr(finding, 'severity')
                assert hasattr(finding, 'category')
                assert hasattr(finding, 'message')
                assert hasattr(finding, 'recommendation')
                assert finding.severity in ('info', 'warning', 'error', 'critical')

            print(
                f'✓ QoS validation: {report.ports_analyzed} ports analyzed, '
                f'health: {report.overall_health}, '
                f'findings: {len(report.findings)}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


# =============================================================================
# P3 Tools - Lower Priority (MAC Analyzer, Firmware Advisor)
# =============================================================================


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveMACAnalyzer:
    """Test MAC address table analysis against real controller."""

    async def test_analyze_mac_table_all(self):
        """Test MAC table analysis across all switches."""
        try:
            from unifi_mcp.tools.analysis.mac_analyzer import analyze_mac_table

            report = await analyze_mac_table()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_analyzed')
            assert hasattr(report, 'total_mac_entries')
            assert hasattr(report, 'unique_mac_addresses')
            assert hasattr(report, 'static_mac_count')
            assert hasattr(report, 'flapping_events')
            assert hasattr(report, 'alerts')
            assert hasattr(report, 'port_mac_counts')
            assert hasattr(report, 'network_healthy')
            assert hasattr(report, 'recommendations')

            # Basic assertions
            assert report.devices_analyzed >= 0
            assert report.total_mac_entries >= 0
            assert report.unique_mac_addresses >= 0
            assert report.unique_mac_addresses <= report.total_mac_entries
            assert isinstance(report.network_healthy, bool)

            # Validate flapping events
            for event in report.flapping_events:
                assert hasattr(event, 'mac_address')
                assert hasattr(event, 'device_id')
                assert hasattr(event, 'ports_involved')
                assert hasattr(event, 'flap_count')
                assert hasattr(event, 'severity')
                assert len(event.ports_involved) >= 2

            # Validate alerts
            for alert in report.alerts:
                assert hasattr(alert, 'alert_type')
                assert hasattr(alert, 'severity')
                assert hasattr(alert, 'message')
                assert hasattr(alert, 'recommendation')

            print(
                f'✓ MAC analysis: {report.devices_analyzed} devices, '
                f'{report.total_mac_entries} MAC entries, '
                f'{report.unique_mac_addresses} unique MACs, '
                f'{len(report.flapping_events)} flapping events'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_analyze_mac_table_custom_threshold(self):
        """Test MAC table analysis with custom threshold."""
        try:
            from unifi_mcp.tools.analysis.mac_analyzer import analyze_mac_table

            report = await analyze_mac_table(max_macs_per_port=10)

            assert report.devices_analyzed >= 0
            # With higher threshold, fewer ports should exceed it
            print(
                f'✓ MAC analysis with custom threshold: '
                f'{report.ports_exceeding_threshold} ports exceeding threshold'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveFirmwareAdvisor:
    """Test firmware security assessment against real controller."""

    async def test_get_firmware_report_all(self):
        """Test firmware report across all devices."""
        try:
            from unifi_mcp.tools.analysis.firmware_advisor import get_firmware_report

            report = await get_firmware_report()

            # Validate report structure
            assert hasattr(report, 'timestamp')
            assert hasattr(report, 'devices_checked')
            assert hasattr(report, 'security_score')
            assert hasattr(report, 'current_count')
            assert hasattr(report, 'update_available_count')
            assert hasattr(report, 'security_update_count')
            assert hasattr(report, 'critical_count')
            assert hasattr(report, 'eol_count')
            assert hasattr(report, 'devices')
            assert hasattr(report, 'recommendations')
            assert hasattr(report, 'network_healthy')

            # Basic assertions
            assert report.devices_checked >= 0
            assert 0 <= report.security_score <= 100
            assert isinstance(report.network_healthy, bool)

            # Validate device firmware info
            for device in report.devices:
                assert hasattr(device, 'device_id')
                assert hasattr(device, 'device_name')
                assert hasattr(device, 'model')
                assert hasattr(device, 'current_version')
                assert hasattr(device, 'status')
                assert hasattr(device, 'update_priority')
                assert device.status in (
                    'current',
                    'update_available',
                    'security_update',
                    'critical',
                    'end_of_life',
                    'unknown',
                )
                assert device.update_priority in ('critical', 'high', 'medium', 'low', 'none')

            # Validate recommendations
            for rec in report.recommendations:
                assert hasattr(rec, 'priority')
                assert hasattr(rec, 'message')
                assert rec.priority in ('critical', 'high', 'medium', 'low', 'info')

            print(
                f'✓ Firmware report: {report.devices_checked} devices, '
                f'security score: {report.security_score}/100, '
                f'current: {report.current_count}, updates available: {report.update_available_count}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_get_firmware_report_specific_device(self):
        """Test firmware report for specific device."""
        try:
            from unifi_mcp.tools.analysis.firmware_advisor import get_firmware_report
            from unifi_mcp.utils.client import UniFiClient

            # Get first device
            async with UniFiClient() as client:
                devices = await client.get_devices()

                if not devices:
                    pytest.skip('No devices available')

                test_device = devices[0]
                device_id = test_device.get('_id')

            report = await get_firmware_report(device_id=device_id)

            assert report.devices_checked == 1
            assert len(report.devices) == 1
            assert report.devices[0].device_id == device_id

            print(
                f'✓ Firmware report for device {report.devices[0].device_name}: '
                f'version {report.devices[0].current_version}, '
                f'status: {report.devices[0].status}'
            )

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


# =============================================================================
# Cross-Tool Integration Tests
# =============================================================================


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveAnalysisIntegration:
    """Integration tests combining multiple analysis tools."""

    async def test_comprehensive_network_health_check(self):
        """Run all analysis tools and generate comprehensive health status."""
        try:
            from unifi_mcp.tools.analysis import (
                analyze_link_quality,
                analyze_mac_table,
                detect_ip_conflicts,
                detect_storms,
                diagnose_vlans,
                get_capacity_report,
                get_firmware_report,
                monitor_lags,
                validate_qos,
            )

            results = {}
            issues_found = 0

            # P1 Tools
            print('\n=== P1 Tools (High Priority) ===')

            ip_report = await detect_ip_conflicts()
            results['ip_conflicts'] = ip_report.healthy
            if not ip_report.healthy:
                issues_found += ip_report.conflicts_found
            print(
                f'  IP Conflicts: {"✓ Healthy" if ip_report.healthy else f"✗ {ip_report.conflicts_found} conflicts"}'
            )

            storm_report = await detect_storms()
            results['storms'] = storm_report.network_healthy
            if not storm_report.network_healthy:
                issues_found += storm_report.storms_detected
            print(
                f'  Storm Detection: {"✓ Healthy" if storm_report.network_healthy else f"✗ {storm_report.storms_detected} storms"}'
            )

            vlan_report = await diagnose_vlans()
            results['vlans'] = vlan_report.overall_health == 'HEALTHY'
            issues_found += vlan_report.issues_found
            print(
                f'  VLAN Diagnostics: {vlan_report.overall_health} ({vlan_report.issues_found} issues)'
            )

            # P2 Tools
            print('\n=== P2 Tools (Medium Priority) ===')

            link_report = await analyze_link_quality()
            results['link_quality'] = link_report.overall_health == 'HEALTHY'
            issues_found += link_report.degraded_ports + link_report.critical_ports
            print(
                f'  Link Quality: {link_report.overall_health} ({link_report.degraded_ports} degraded, {link_report.critical_ports} critical)'
            )

            capacity_report = await get_capacity_report()
            results['capacity'] = not capacity_report.expansion_needed
            print(
                f'  Capacity: {capacity_report.overall_utilization:.1f}% utilized, expansion {"needed" if capacity_report.expansion_needed else "not needed"}'
            )

            lag_report = await monitor_lags()
            results['lags'] = lag_report.network_healthy
            issues_found += lag_report.degraded_lags + lag_report.critical_lags
            print(
                f'  LAGs: {"✓ Healthy" if lag_report.network_healthy else "✗ Issues"} ({lag_report.total_lags} LAGs)'
            )

            qos_report = await validate_qos()
            results['qos'] = qos_report.overall_health == 'HEALTHY'
            issues_found += qos_report.critical_count + qos_report.error_count
            print(
                f'  QoS: {qos_report.overall_health} ({qos_report.critical_count} critical, {qos_report.error_count} errors)'
            )

            # P3 Tools
            print('\n=== P3 Tools (Lower Priority) ===')

            mac_report = await analyze_mac_table()
            results['mac_table'] = mac_report.network_healthy
            issues_found += mac_report.critical_alerts + len(mac_report.flapping_events)
            print(
                f'  MAC Table: {"✓ Healthy" if mac_report.network_healthy else "✗ Issues"} ({mac_report.unique_mac_addresses} unique MACs)'
            )

            firmware_report = await get_firmware_report()
            results['firmware'] = firmware_report.network_healthy
            issues_found += firmware_report.critical_count + firmware_report.eol_count
            print(
                f'  Firmware: Score {firmware_report.security_score}/100, {"✓ Healthy" if firmware_report.network_healthy else "✗ Needs attention"}'
            )

            # Summary
            healthy_count = sum(1 for v in results.values() if v)
            total_count = len(results)

            print('\n=== Summary ===')
            print(f'  Overall: {healthy_count}/{total_count} checks passed')
            print(f'  Total issues found: {issues_found}')

            # At minimum, all tools should run successfully
            assert len(results) == 9, 'All 9 analysis tools should execute'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveAnalysisErrorHandling:
    """Test error handling for analysis tools."""

    async def test_invalid_device_id(self):
        """Test tools with invalid device ID."""
        try:
            from unifi_mcp.tools.analysis.firmware_advisor import get_firmware_report

            with pytest.raises(ToolError) as exc_info:
                await get_firmware_report(device_id='invalid-device-id-12345')

            assert exc_info.value.error_code == 'DEVICE_NOT_FOUND'
            print('✓ Invalid device ID correctly raises DEVICE_NOT_FOUND')

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            elif e.error_code == 'DEVICE_NOT_FOUND':
                # This is expected
                print('✓ Invalid device ID correctly raises DEVICE_NOT_FOUND')
            else:
                raise

    async def test_invalid_vlan_id(self):
        """Test VLAN diagnostics with invalid VLAN ID."""
        try:
            from unifi_mcp.tools.analysis.vlan_diagnostics import diagnose_vlans

            # VLAN 9999 unlikely to exist - use source_vlan parameter
            report = await diagnose_vlans(source_vlan=9999)

            # Should return empty/minimal report rather than error
            assert report.vlans_configured >= 0
            print('✓ Invalid VLAN ID handled gracefully')

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            elif e.error_code == 'VLAN_NOT_FOUND':
                print('✓ Invalid VLAN ID correctly raises VLAN_NOT_FOUND')
            else:
                raise
