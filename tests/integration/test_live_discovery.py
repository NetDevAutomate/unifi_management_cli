"""Integration tests for discovery tools against real UniFi controller."""

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
class TestLiveDiscoveryTools:
    """Test discovery tools against real controller.

    These tests require:
    1. UniFi controller running and accessible
    2. Credentials configured (env vars, keychain, or 1Password)
    3. Run with: pytest -m live
    """

    async def test_find_device_by_gateway(self):
        """Test finding gateway device (should always exist)."""
        try:
            from unifi_mcp.tools.discovery.find_device import find_device

            # Try to find gateway - every network should have one
            device = await find_device('gateway')

            assert device.type == 'gateway'
            assert device.mac
            assert device.model
            # Gateway may or may not have a name, but should have MAC and model

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_find_device_by_ip(self):
        """Test finding device by IP address."""
        try:
            from unifi_mcp.tools.discovery.find_device import find_device

            # Find gateway first to get a known IP
            gateway = await find_device('gateway')
            if gateway.ip:
                # Try to find the same device by IP
                device_by_ip = await find_device(gateway.ip)
                assert device_by_ip.mac == gateway.mac
                assert device_by_ip.ip == gateway.ip

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_find_device_not_found(self):
        """Test find_device with non-existent identifier."""
        try:
            from unifi_mcp.tools.discovery.find_device import find_device

            # Try to find a device that definitely doesn't exist
            with pytest.raises(ToolError) as exc_info:
                await find_device('definitely-does-not-exist-12345')

            assert exc_info.value.error_code == 'DEVICE_NOT_FOUND'
            assert 'related_tools' in exc_info.value.to_dict()

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_find_mac_gateway(self):
        """Test finding MAC address location (using gateway MAC)."""
        try:
            from unifi_mcp.tools.discovery.find_device import find_device
            from unifi_mcp.tools.discovery.find_mac import find_mac

            # Get gateway MAC first
            gateway = await find_device('gateway')

            # Find the same device by MAC
            mac_result = await find_mac(gateway.mac)

            assert isinstance(mac_result, dict)
            assert mac_result.get('device_type') == 'infrastructure'
            assert mac_result.get('device_name')
            assert mac_result.get('is_online') is True

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_find_ip_gateway(self):
        """Test finding IP address location (using gateway IP)."""
        try:
            from unifi_mcp.tools.discovery.find_device import find_device
            from unifi_mcp.tools.discovery.find_ip import find_ip

            # Get gateway IP first
            gateway = await find_device('gateway')
            if gateway.ip:
                # Find the same device by IP
                ip_result = await find_ip(gateway.ip)

                assert isinstance(ip_result, dict)
                assert ip_result.get('device_mac') == gateway.mac
                assert ip_result.get('device_type') == 'infrastructure'
                assert ip_result.get('is_online') is True

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_client_trace_if_clients_exist(self):
        """Test client trace if any clients are connected."""
        try:
            from unifi_mcp.tools.discovery.client_trace import client_trace
            from unifi_mcp.utils.client import UniFiClient

            # Check if any clients exist first
            async with UniFiClient() as client:
                clients_data = await client.get(client.build_path('stat/sta'))

                if not clients_data:
                    pytest.skip('No clients connected to test client_trace')

                # Try to trace first client
                first_client = clients_data[0]
                client_mac = first_client.get('mac')

                if client_mac:
                    path = await client_trace(client_mac)
                    assert path.source_resolved == client_mac
                    assert len(path.hops) > 0
                    assert path.hops[0].device_type == 'client'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            elif e.error_code == 'DEVICE_NOT_FOUND':
                pytest.skip('No suitable client found for tracing')
            else:
                raise

    async def test_invalid_mac_format(self):
        """Test find_mac with invalid MAC format."""
        try:
            from unifi_mcp.tools.discovery.find_mac import find_mac

            with pytest.raises(ToolError) as exc_info:
                await find_mac('invalid-mac-format')

            assert exc_info.value.error_code == 'INVALID_MAC'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_invalid_ip_format(self):
        """Test find_ip with invalid IP format."""
        try:
            from unifi_mcp.tools.discovery.find_ip import find_ip

            with pytest.raises(ToolError) as exc_info:
                await find_ip('invalid.ip.format')

            assert exc_info.value.error_code == 'INVALID_IP'

        except ToolError as e:
            if e.error_code in ('AUTHENTICATION_FAILED', 'CONTROLLER_UNREACHABLE'):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise
