"""Unit tests for UniFi Protect client module.

Tests cover:
- UniFiProtectClient initialization
- Connection state management
- Device property access
- Context manager usage
- Error handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from unifi_mapper.protect.client import (
    AuthenticationError,
    ConnectionError,
    ConnectionState,
    ProtectClientError,
    UniFiProtectClient,
    create_client,
)
from unifi_mapper.protect.config import ProtectConfig


if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def protect_config() -> ProtectConfig:
    """Create a test ProtectConfig instance.

    Returns:
        A ProtectConfig with test values.
    """
    return ProtectConfig(
        host='192.168.1.1',
        username='admin',
        password=SecretStr('password123'),
    )


@pytest.fixture
def mock_bootstrap() -> MagicMock:
    """Create a mock Bootstrap object.

    Returns:
        A MagicMock configured as a Bootstrap instance.
    """
    bootstrap = MagicMock()
    bootstrap.nvr = MagicMock()
    bootstrap.nvr.name = 'Test NVR'
    bootstrap.cameras = {'cam1': MagicMock(name='Camera 1', is_third_party_camera=False)}
    bootstrap.aiports = {'ai1': MagicMock(name='AI Port 1')}
    bootstrap.sensors = {'sensor1': MagicMock(name='Sensor 1')}
    bootstrap.lights = {'light1': MagicMock(name='Light 1')}
    bootstrap.chimes = {'chime1': MagicMock(name='Chime 1')}
    bootstrap.doorlocks = {'lock1': MagicMock(name='Lock 1')}
    return bootstrap


class TestConnectionState:
    """Test suite for ConnectionState enum."""

    def test_all_states_exist(self) -> None:
        """Test that all expected connection states are defined."""
        assert ConnectionState.DISCONNECTED.value == 'disconnected'
        assert ConnectionState.CONNECTING.value == 'connecting'
        assert ConnectionState.CONNECTED.value == 'connected'
        assert ConnectionState.RECONNECTING.value == 'reconnecting'
        assert ConnectionState.ERROR.value == 'error'


class TestProtectClientError:
    """Test suite for ProtectClientError exception classes."""

    def test_base_error_with_message(self) -> None:
        """Test creating base error with message only."""
        error = ProtectClientError('Test error message')

        assert str(error) == 'Test error message'
        assert error.message == 'Test error message'
        assert error.original_error is None

    def test_base_error_with_original(self) -> None:
        """Test creating base error with original exception."""
        original = ValueError('Original error')
        error = ProtectClientError('Wrapped error', original_error=original)

        assert error.message == 'Wrapped error'
        assert error.original_error is original

    def test_connection_error_inheritance(self) -> None:
        """Test that ConnectionError inherits from ProtectClientError."""
        error = ConnectionError('Connection failed')

        assert isinstance(error, ProtectClientError)
        assert str(error) == 'Connection failed'

    def test_authentication_error_inheritance(self) -> None:
        """Test that AuthenticationError inherits from ProtectClientError."""
        error = AuthenticationError('Auth failed')

        assert isinstance(error, ProtectClientError)
        assert str(error) == 'Auth failed'


class TestUniFiProtectClientInit:
    """Test suite for UniFiProtectClient initialization."""

    def test_init_sets_config(self, protect_config: ProtectConfig) -> None:
        """Test that init stores the config."""
        client = UniFiProtectClient(protect_config)

        assert client.config is protect_config

    def test_init_sets_disconnected_state(self, protect_config: ProtectConfig) -> None:
        """Test that init sets state to DISCONNECTED."""
        client = UniFiProtectClient(protect_config)

        assert client.state == ConnectionState.DISCONNECTED

    def test_init_not_connected(self, protect_config: ProtectConfig) -> None:
        """Test that client is not connected after init."""
        client = UniFiProtectClient(protect_config)

        assert client.is_connected is False

    def test_init_empty_device_collections(self, protect_config: ProtectConfig) -> None:
        """Test that device collections are empty after init."""
        client = UniFiProtectClient(protect_config)

        assert client.cameras == {}
        assert client.ai_ports == {}
        assert client.sensors == {}
        assert client.lights == {}
        assert client.chimes == {}
        assert client.doorlocks == {}

    def test_init_bootstrap_is_none(self, protect_config: ProtectConfig) -> None:
        """Test that bootstrap is None after init."""
        client = UniFiProtectClient(protect_config)

        assert client.bootstrap is None
        assert client.nvr is None

    def test_init_api_is_none(self, protect_config: ProtectConfig) -> None:
        """Test that api is None after init."""
        client = UniFiProtectClient(protect_config)

        assert client.api is None


class TestUniFiProtectClientConnect:
    """Test suite for UniFiProtectClient.connect()."""

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test successful connection."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            result = await client.connect()

            assert result is True
            assert client.state == ConnectionState.CONNECTED
            assert client.is_connected is True
            assert client.bootstrap is mock_bootstrap

    @pytest.mark.asyncio
    async def test_connect_already_connected(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that connect returns True if already connected."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            # First connection
            await client.connect()

            # Second connection should skip
            mock_api.get_bootstrap.reset_mock()
            result = await client.connect()

            assert result is True
            mock_api.get_bootstrap.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_authentication_error(
        self, protect_config: ProtectConfig
    ) -> None:
        """Test that authentication failures raise AuthenticationError."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(
                side_effect=Exception('Unauthorized access')
            )
            mock_api_class.return_value = mock_api

            with pytest.raises(AuthenticationError) as exc_info:
                await client.connect()

            assert 'authenticate' in str(exc_info.value).lower()
            assert client.state == ConnectionState.ERROR

    @pytest.mark.asyncio
    async def test_connect_connection_error(
        self, protect_config: ProtectConfig
    ) -> None:
        """Test that connection failures raise ConnectionError."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(
                side_effect=Exception('Connection refused')
            )
            mock_api_class.return_value = mock_api

            with pytest.raises(ConnectionError) as exc_info:
                await client.connect()

            assert 'connect' in str(exc_info.value).lower()
            assert client.state == ConnectionState.ERROR


class TestUniFiProtectClientDisconnect:
    """Test suite for UniFiProtectClient.disconnect()."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that disconnect clears all state."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            await client.connect()
            await client.disconnect()

            assert client.state == ConnectionState.DISCONNECTED
            assert client.is_connected is False
            assert client.bootstrap is None
            assert client.api is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(
        self, protect_config: ProtectConfig
    ) -> None:
        """Test that disconnect is safe when not connected."""
        client = UniFiProtectClient(protect_config)

        # Should not raise
        await client.disconnect()

        assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_disconnect_handles_close_error(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that disconnect handles close_session errors gracefully."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock(side_effect=Exception('Close error'))
            mock_api_class.return_value = mock_api

            await client.connect()

            # Should not raise
            await client.disconnect()

            assert client.state == ConnectionState.DISCONNECTED


class TestUniFiProtectClientRefresh:
    """Test suite for UniFiProtectClient.refresh()."""

    @pytest.mark.asyncio
    async def test_refresh_updates_bootstrap(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that refresh updates the bootstrap data."""
        client = UniFiProtectClient(protect_config)
        new_bootstrap = MagicMock()
        new_bootstrap.nvr = MagicMock()
        new_bootstrap.cameras = {'cam2': MagicMock()}
        new_bootstrap.aiports = {}
        new_bootstrap.sensors = {}
        new_bootstrap.lights = {}
        new_bootstrap.chimes = {}
        new_bootstrap.doorlocks = {}

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(
                side_effect=[mock_bootstrap, new_bootstrap]
            )
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            await client.connect()
            assert len(client.cameras) == 1

            await client.refresh()
            assert len(client.cameras) == 1  # new_bootstrap has 1 camera too

    @pytest.mark.asyncio
    async def test_refresh_when_not_connected_raises_error(
        self, protect_config: ProtectConfig
    ) -> None:
        """Test that refresh raises ConnectionError when not connected."""
        client = UniFiProtectClient(protect_config)

        with pytest.raises(ConnectionError) as exc_info:
            await client.refresh()

        assert 'not connected' in str(exc_info.value).lower()


class TestUniFiProtectClientDeviceAccess:
    """Test suite for device access methods."""

    @pytest.mark.asyncio
    async def test_get_camera_by_id(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test getting a camera by ID."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            await client.connect()

            camera = client.get_camera('cam1')
            assert camera is not None

            camera = client.get_camera('nonexistent')
            assert camera is None

    @pytest.mark.asyncio
    async def test_get_camera_by_name(
        self,
        protect_config: ProtectConfig,
    ) -> None:
        """Test getting a camera by name."""
        client = UniFiProtectClient(protect_config)

        mock_camera = MagicMock()
        mock_camera.name = 'Front Door'
        mock_camera.is_third_party_camera = False

        mock_bootstrap = MagicMock()
        mock_bootstrap.nvr = MagicMock()
        mock_bootstrap.nvr.name = 'Test NVR'
        mock_bootstrap.cameras = {'cam1': mock_camera}
        mock_bootstrap.aiports = {}
        mock_bootstrap.sensors = {}
        mock_bootstrap.lights = {}
        mock_bootstrap.chimes = {}
        mock_bootstrap.doorlocks = {}

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            await client.connect()

            # Exact match
            camera = client.get_camera_by_name('Front Door')
            assert camera is mock_camera

            # Case-insensitive
            camera = client.get_camera_by_name('front door')
            assert camera is mock_camera

            # No match
            camera = client.get_camera_by_name('Back Door')
            assert camera is None

    @pytest.mark.asyncio
    async def test_get_ai_port(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test getting an AI Port by ID."""
        client = UniFiProtectClient(protect_config)

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            await client.connect()

            ai_port = client.get_ai_port('ai1')
            assert ai_port is not None

            ai_port = client.get_ai_port('nonexistent')
            assert ai_port is None

    @pytest.mark.asyncio
    async def test_get_third_party_cameras(
        self,
        protect_config: ProtectConfig,
    ) -> None:
        """Test getting third-party cameras."""
        client = UniFiProtectClient(protect_config)

        native_cam = MagicMock()
        native_cam.is_third_party_camera = False

        third_party_cam = MagicMock()
        third_party_cam.is_third_party_camera = True

        mock_bootstrap = MagicMock()
        mock_bootstrap.nvr = MagicMock()
        mock_bootstrap.nvr.name = 'Test NVR'
        mock_bootstrap.cameras = {'cam1': native_cam, 'cam2': third_party_cam}
        mock_bootstrap.aiports = {}
        mock_bootstrap.sensors = {}
        mock_bootstrap.lights = {}
        mock_bootstrap.chimes = {}
        mock_bootstrap.doorlocks = {}

        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api_class.return_value = mock_api

            await client.connect()

            third_party = client.get_third_party_cameras()
            assert len(third_party) == 1
            assert third_party[0] is third_party_cam


class TestUniFiProtectClientContextManager:
    """Test suite for async context manager usage."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_disconnects(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that context manager handles connect/disconnect."""
        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            async with UniFiProtectClient(protect_config) as client:
                assert client.is_connected is True
                assert client.state == ConnectionState.CONNECTED

            # After context exit
            assert client.state == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that context manager disconnects even on exception."""
        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            with pytest.raises(ValueError):
                async with UniFiProtectClient(protect_config) as client:
                    raise ValueError('Test error')

            mock_api.close_session.assert_called_once()


class TestCreateClient:
    """Test suite for create_client() helper function."""

    @pytest.mark.asyncio
    async def test_create_client_yields_connected_client(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that create_client yields a connected client."""
        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            async with create_client(protect_config) as client:
                assert client.is_connected is True
                assert isinstance(client, UniFiProtectClient)

    @pytest.mark.asyncio
    async def test_create_client_disconnects_after_use(
        self,
        protect_config: ProtectConfig,
        mock_bootstrap: MagicMock,
    ) -> None:
        """Test that create_client disconnects after the context."""
        with patch('unifi_mapper.protect.client.ProtectApiClient') as mock_api_class:
            mock_api = AsyncMock()
            mock_api.get_bootstrap = AsyncMock(return_value=mock_bootstrap)
            mock_api.close_session = AsyncMock()
            mock_api_class.return_value = mock_api

            async with create_client(protect_config) as client:
                pass

            mock_api.close_session.assert_called_once()
