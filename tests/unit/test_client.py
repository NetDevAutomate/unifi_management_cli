"""Unit tests for UniFi API client."""

import httpx
import pytest
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError
from unittest.mock import AsyncMock, Mock, patch


class TestUniFiClient:
    """Test UniFi API client."""

    @pytest.fixture
    def mock_httpx_client(self):
        """Mock httpx.AsyncClient for testing."""
        client = AsyncMock(spec=httpx.AsyncClient)
        return client

    @pytest.fixture
    def unifi_client(self, sample_credentials):
        """UniFi client with sample credentials."""
        return UniFiClient(credentials=sample_credentials)

    @pytest.mark.asyncio
    async def test_context_manager(self, sample_credentials, mock_httpx_client):
        """Test async context manager."""
        client = UniFiClient(credentials=sample_credentials)

        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock successful authentication
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='test-token')]
            mock_httpx_client.post.return_value = auth_response

            async with client:
                assert client._authenticated is True

            # Should call disconnect
            mock_httpx_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_authentication_success(self, unifi_client, mock_httpx_client):
        """Test successful authentication."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock successful auth response
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='session-token-123')]
            mock_httpx_client.post.return_value = auth_response

            await unifi_client.connect()

            assert unifi_client._authenticated is True
            assert unifi_client._session_token == 'session-token-123'

            # Verify auth request
            mock_httpx_client.post.assert_called_with(
                '/api/auth/login',
                json={
                    'username': 'admin',
                    'password': 'password123',  # pragma: allowlist secret
                    'remember': False,
                },
            )

    @pytest.mark.asyncio
    async def test_authentication_invalid_credentials(self, unifi_client, mock_httpx_client):
        """Test authentication with invalid credentials."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock 401 response
            error_response = Mock()
            error_response.status_code = 401
            error_response.text = 'Unauthorized'
            mock_httpx_client.post.side_effect = httpx.HTTPStatusError(
                'Unauthorized', request=Mock(), response=error_response
            )

            with pytest.raises(ToolError) as exc_info:
                await unifi_client.connect()

            assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
            assert 'invalid username/password' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_authentication_no_token(self, unifi_client, mock_httpx_client):
        """Test authentication response without session token."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock response with no token in cookies
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = []  # No cookies
            mock_httpx_client.post.return_value = auth_response

            with pytest.raises(ToolError) as exc_info:
                await unifi_client.connect()

            assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
            assert 'No session token' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_request_success(self, unifi_client, mock_httpx_client):
        """Test successful GET request."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock authentication
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='test-token')]
            mock_httpx_client.post.return_value = auth_response

            # Mock GET response
            get_response = Mock()
            get_response.raise_for_status.return_value = None
            get_response.json.return_value = {
                'meta': {'rc': 'ok'},
                'data': [{'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'Test Device'}],
            }
            mock_httpx_client.request.return_value = get_response

            await unifi_client.connect()
            result = await unifi_client.get('/proxy/network/api/s/default/stat/device')

            assert result == [{'mac': 'aa:bb:cc:dd:ee:ff', 'name': 'Test Device'}]
            mock_httpx_client.request.assert_called_with(
                'GET', '/proxy/network/api/s/default/stat/device'
            )

    @pytest.mark.asyncio
    async def test_get_request_api_error(self, unifi_client, mock_httpx_client):
        """Test GET request with UniFi API error."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock authentication success
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='test-token')]
            mock_httpx_client.post.return_value = auth_response

            # Mock API error response
            error_response = Mock()
            error_response.raise_for_status.return_value = None
            error_response.json.return_value = {
                'meta': {'rc': 'error', 'msg': 'Invalid site'},
                'data': [],
            }
            mock_httpx_client.request.return_value = error_response

            await unifi_client.connect()

            with pytest.raises(ToolError) as exc_info:
                await unifi_client.get('/proxy/network/api/s/invalid/stat/device')

            assert exc_info.value.error_code == ErrorCodes.API_ERROR
            assert 'Invalid site' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_build_path(self, unifi_client):
        """Test API path building."""
        unifi_client._site_name = 'test-site'

        path = unifi_client.build_path('stat/device')
        assert path == '/proxy/network/api/s/test-site/stat/device'

        path = unifi_client.build_path('rest/networkconf')
        assert path == '/proxy/network/api/s/test-site/rest/networkconf'

    @pytest.mark.asyncio
    async def test_disconnect_cleanup(self, unifi_client, mock_httpx_client):
        """Test proper cleanup on disconnect."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock successful connection
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='test-token')]
            mock_httpx_client.post.return_value = auth_response

            await unifi_client.connect()
            assert unifi_client._authenticated is True

            await unifi_client.disconnect()

            # Should logout and close client
            logout_calls = [
                call
                for call in mock_httpx_client.post.call_args_list
                if call[0][0] == '/api/logout'
            ]
            assert len(logout_calls) >= 1  # May have auth + logout calls

            mock_httpx_client.aclose.assert_called_once()
            assert unifi_client._authenticated is False
            assert unifi_client._session_token is None

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_401(self, unifi_client, mock_httpx_client):
        """Test automatic re-authentication on 401 error."""
        with patch('httpx.AsyncClient', return_value=mock_httpx_client):
            # Mock initial authentication
            auth_response = Mock()
            auth_response.raise_for_status.return_value = None
            auth_response.cookies = [Mock(name='TOKEN', value='test-token')]

            # Mock 401 error, then success on retry
            error_response = Mock()
            error_response.status_code = 401
            success_response = Mock()
            success_response.raise_for_status.return_value = None
            success_response.json.return_value = {'meta': {'rc': 'ok'}, 'data': []}

            mock_httpx_client.post.return_value = auth_response
            mock_httpx_client.request.side_effect = [
                httpx.HTTPStatusError('Unauthorized', request=Mock(), response=error_response),
                success_response,
            ]

            await unifi_client.connect()
            result = await unifi_client.get('/test/endpoint')

            # Should succeed after re-auth
            assert result == []
            # Should have made 2 requests (first failed, second succeeded)
            assert mock_httpx_client.request.call_count == 2
