"""Integration tests for connectivity tools against real UniFi controller."""

import os
import pytest
import sys


# Add src to path for imports
src_path = os.path.join(os.getcwd(), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from unifi_mcp.utils.errors import ToolError  # noqa: E402


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveConnectivityTools:
    """Test connectivity tools against real controller."""

    async def test_traceroute_gateway_to_internet(self):
        """Test traceroute from gateway to internet."""
        try:
            from unifi_mcp.tools.connectivity.traceroute import traceroute

            # Trace from gateway to internet
            path = await traceroute(
                source='gateway', destination='internet', include_firewall=True, verbosity='guided'
            )

            assert path.source == 'gateway'
            assert path.destination == 'internet'
            assert len(path.hops) >= 1
            assert path.hops[0].device_type == 'gateway'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_traceroute_same_device(self):
        """Test traceroute from device to itself (should be simple path)."""
        try:
            from unifi_mcp.tools.connectivity.traceroute import traceroute
            from unifi_mcp.tools.discovery.find_device import find_device

            # Find gateway first
            gateway = await find_device('gateway')

            # Trace from gateway to itself
            path = await traceroute(
                source=gateway.mac, destination=gateway.mac, include_firewall=False
            )

            assert path.source_resolved == gateway.mac
            assert path.destination_resolved == gateway.mac
            assert len(path.hops) >= 1

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_firewall_check_any_to_any(self):
        """Test firewall check with basic any-to-any traffic."""
        try:
            from unifi_mcp.tools.connectivity.firewall_check import firewall_check

            result = await firewall_check(source='any', destination='any', protocol='all')

            assert isinstance(result, dict)
            assert 'verdict' in result
            assert result['verdict'] in ('allow', 'deny')
            assert 'matching_rules' in result
            assert isinstance(result['matching_rules'], list)

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_firewall_check_vlan_to_vlan(self):
        """Test firewall check between VLANs if multiple VLANs exist."""
        try:
            from unifi_mcp.tools.connectivity.firewall_check import firewall_check
            from unifi_mcp.utils.client import UniFiClient

            # Check if multiple VLANs exist
            async with UniFiClient() as client:
                vlans_data = await client.get(client.build_path('rest/networkconf'))

                if len(vlans_data) < 2:
                    pytest.skip('Need at least 2 VLANs to test inter-VLAN rules')

                # Test between first two VLANs
                vlan1 = vlans_data[0]
                vlan2 = vlans_data[1]

                result = await firewall_check(
                    source=vlan1.get('name', f'VLAN_{vlan1.get("vlan", 1)}'),
                    destination=vlan2.get('name', f'VLAN_{vlan2.get("vlan", 2)}'),
                    protocol='all',
                )

                assert isinstance(result, dict)
                assert 'verdict' in result
                assert 'vlan_matrix' in result

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_path_analysis_basic(self):
        """Test path analysis with simple path."""
        try:
            from unifi_mcp.tools.connectivity.path_analysis import path_analysis
            from unifi_mcp.tools.connectivity.traceroute import traceroute

            # Get a simple path first
            path = await traceroute(
                source='gateway', destination='internet', include_firewall=False
            )

            # Analyze the path
            analysis = await path_analysis(path)

            assert isinstance(analysis, dict)
            assert 'path_summary' in analysis
            assert 'hop_analysis' in analysis
            assert 'performance_metrics' in analysis
            assert 'recommendations' in analysis

            # Check path summary
            summary = analysis['path_summary']
            assert 'total_hops' in summary
            assert summary['total_hops'] == len(path.hops)

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_connectivity_error_handling(self):
        """Test connectivity tools error handling."""
        try:
            from unifi_mcp.tools.connectivity.traceroute import traceroute

            # Test with invalid endpoint
            with pytest.raises(ToolError) as exc_info:
                await traceroute('invalid-endpoint', 'another-invalid-endpoint')

            assert exc_info.value.error_code == 'ENDPOINT_NOT_FOUND'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise
