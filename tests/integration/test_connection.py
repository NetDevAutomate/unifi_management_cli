"""Integration tests for real UniFi controller connection."""

import pytest
from unifi_mcp.utils.auth import get_credentials
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError
from unittest.mock import AsyncMock, patch


@pytest.mark.live
@pytest.mark.asyncio
class TestLiveConnection:
    """Test connection to real UniFi controller.

    These tests require:
    1. UniFi controller running and accessible
    2. Credentials configured (env vars, keychain, or 1Password)
    3. Run with: pytest -m live
    """

    async def test_credential_chain(self):
        """Test credential chain can find valid credentials."""
        try:
            creds = await get_credentials()
            assert creds.host
            assert creds.username
            assert creds.password
            assert creds.site
        except ToolError as e:
            pytest.skip(f'No credentials available: {e}')

    async def test_controller_connection(self):
        """Test connection to real UniFi controller."""
        try:
            async with UniFiClient() as client:
                assert client._authenticated is True
                assert client._session_token is not None
                assert client._site_name
        except ToolError as e:
            if e.error_code in (
                'AUTHENTICATION_FAILED',
                'CONTROLLER_UNREACHABLE',
            ):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_basic_api_call(self):
        """Test basic API call to get device list."""
        try:
            async with UniFiClient() as client:
                # Get device list - this should work on any UniFi setup
                devices = await client.get(client.build_path('stat/device'))

                # Should return a list (even if empty)
                assert isinstance(devices, list)

                # If devices exist, check structure
                if devices:
                    device = devices[0]
                    assert 'mac' in device
                    assert 'name' in device or 'hostname' in device
                    assert 'model' in device

        except ToolError as e:
            if e.error_code in (
                'AUTHENTICATION_FAILED',
                'CONTROLLER_UNREACHABLE',
            ):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_site_api_call(self):
        """Test site-specific API call."""
        try:
            async with UniFiClient() as client:
                # Get site info
                sites = await client.get('/proxy/network/api/self/sites')

                # Should return site list
                assert isinstance(sites, list)

                if sites:
                    site = sites[0]
                    assert 'name' in site
                    assert 'desc' in site or 'description' in site

        except ToolError as e:
            if e.error_code in (
                'AUTHENTICATION_FAILED',
                'CONTROLLER_UNREACHABLE',
            ):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_invalid_endpoint(self):
        """Test API call to invalid endpoint."""
        try:
            async with UniFiClient() as client:
                # This should fail gracefully
                with pytest.raises(ToolError) as exc_info:
                    await client.get('/proxy/network/api/s/default/invalid/endpoint')

                # Should get API error, not a crash
                assert exc_info.value.error_code == ErrorCodes.API_ERROR

        except ToolError as e:
            if e.error_code in (
                'AUTHENTICATION_FAILED',
                'CONTROLLER_UNREACHABLE',
            ):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise

    async def test_connection_without_credentials(self):
        """Test connection attempt without any credentials configured."""
        # Clear environment and mock credential chain to fail
        with patch.dict('os.environ', {}, clear=True):
            with patch('keyring.get_password', return_value=None):
                mock_process = AsyncMock()
                mock_process.returncode = 1
                mock_process.communicate.return_value = (b'', b'not found')

                with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                    client = UniFiClient()

                    with pytest.raises(ToolError) as exc_info:
                        await client.connect()

                    assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
                    assert 'No credentials found' in str(exc_info.value)

    async def test_double_connect(self):
        """Test that multiple connect() calls don't cause issues."""
        try:
            async with UniFiClient() as client:
                # Already connected via context manager
                assert client._authenticated is True

                # Second connect should be no-op
                await client.connect()
                assert client._authenticated is True

        except ToolError as e:
            if e.error_code in (
                'AUTHENTICATION_FAILED',
                'CONTROLLER_UNREACHABLE',
            ):
                pytest.skip(f'Controller not available: {e}')
            else:
                raise
