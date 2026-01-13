"""Async UniFi Protect API client wrapper.

This module provides an async wrapper around the uiprotect library's
ProtectApiClient, adding connection management, error handling, and
convenient device access methods.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, AsyncIterator, Callable

from loguru import logger  # type: ignore[import-untyped]
from uiprotect import ProtectApiClient
from uiprotect.data import Bootstrap

from unifi_mapper.protect.config import ProtectConfig


if TYPE_CHECKING:
    from uiprotect.data import AiPort, Camera, Chime, Doorlock, Light, NVR, Sensor


class ConnectionState(Enum):
    """Enumeration of possible client connection states.

    Attributes:
        DISCONNECTED: Client is not connected to the controller.
        CONNECTING: Client is in the process of connecting.
        CONNECTED: Client is connected and authenticated.
        RECONNECTING: Client is attempting to reconnect after a failure.
        ERROR: Client encountered an error and cannot connect.
    """

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    ERROR = 'error'


class ProtectClientError(Exception):
    """Base exception for Protect client errors.

    Attributes:
        message: Human-readable error description.
        original_error: The underlying exception that caused this error.
    """

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Human-readable error description.
            original_error: The underlying exception, if any.
        """
        super().__init__(message)
        self.message = message
        self.original_error = original_error


class ConnectionError(ProtectClientError):
    """Raised when connection to the Protect controller fails."""

    pass


class AuthenticationError(ProtectClientError):
    """Raised when authentication to the Protect controller fails."""

    pass


class UniFiProtectClient:
    """Async wrapper for UniFi Protect API client.

    This class provides a high-level async interface for interacting with
    a UniFi Protect controller. It handles connection lifecycle, provides
    convenient device access methods, and supports WebSocket subscriptions
    for real-time updates.

    Attributes:
        config: The configuration for this client instance.
        state: Current connection state of the client.

    Example:
        >>> async with UniFiProtectClient(config) as client:
        ...     cameras = client.cameras
        ...     for cam_id, camera in cameras.items():
        ...         print(f"{camera.name}: {camera.state}")
    """

    def __init__(self, config: ProtectConfig) -> None:
        """Initialize the UniFi Protect client.

        Args:
            config: Configuration containing connection parameters.
        """
        self._config = config
        self._client: ProtectApiClient | None = None
        self._state = ConnectionState.DISCONNECTED
        self._bootstrap: Bootstrap | None = None
        self._ws_unsub: Callable[[], None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None

    @property
    def config(self) -> ProtectConfig:
        """Get the client configuration.

        Returns:
            The ProtectConfig instance for this client.
        """
        return self._config

    @property
    def state(self) -> ConnectionState:
        """Get the current connection state.

        Returns:
            The current ConnectionState of the client.
        """
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected.

        Returns:
            True if connected and authenticated, False otherwise.
        """
        return self._state == ConnectionState.CONNECTED and self._client is not None

    @property
    def bootstrap(self) -> Bootstrap | None:
        """Get the cached bootstrap data.

        The bootstrap contains the complete device inventory and
        configuration from the Protect controller.

        Returns:
            The Bootstrap data if connected, None otherwise.
        """
        return self._bootstrap

    @property
    def nvr(self) -> NVR | None:
        """Get the NVR (Network Video Recorder) device.

        Returns:
            The NVR instance if connected, None otherwise.
        """
        if self._bootstrap is None:
            return None
        return self._bootstrap.nvr

    @property
    def cameras(self) -> dict[str, Camera]:
        """Get all cameras from the bootstrap data.

        Returns:
            Dictionary mapping camera IDs to Camera instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.cameras)

    @property
    def ai_ports(self) -> dict[str, AiPort]:
        """Get all AI Ports from the bootstrap data.

        AI Ports are devices that add smart detection capabilities
        to third-party ONVIF cameras.

        Returns:
            Dictionary mapping AI Port IDs to AiPort instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.aiports)

    @property
    def sensors(self) -> dict[str, Sensor]:
        """Get all sensors from the bootstrap data.

        Returns:
            Dictionary mapping sensor IDs to Sensor instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.sensors)

    @property
    def lights(self) -> dict[str, Light]:
        """Get all lights from the bootstrap data.

        Returns:
            Dictionary mapping light IDs to Light instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.lights)

    @property
    def chimes(self) -> dict[str, Chime]:
        """Get all chimes from the bootstrap data.

        Returns:
            Dictionary mapping chime IDs to Chime instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.chimes)

    @property
    def doorlocks(self) -> dict[str, Doorlock]:
        """Get all door locks from the bootstrap data.

        Returns:
            Dictionary mapping doorlock IDs to Doorlock instances.
            Empty dict if not connected.
        """
        if self._bootstrap is None:
            return {}
        return dict(self._bootstrap.doorlocks)

    @property
    def api(self) -> ProtectApiClient | None:
        """Get the underlying uiprotect API client.

        This provides access to the full uiprotect API for advanced
        operations not covered by this wrapper.

        Returns:
            The ProtectApiClient instance if connected, None otherwise.
        """
        return self._client

    async def connect(self) -> bool:
        """Establish connection to the UniFi Protect controller.

        Authenticates with the controller and loads the bootstrap data
        containing all device information.

        Returns:
            True if connection was successful, False otherwise.

        Raises:
            ConnectionError: If unable to reach the controller.
            AuthenticationError: If credentials are invalid.
        """
        if self.is_connected:
            logger.debug('Already connected to Protect controller')
            return True

        self._state = ConnectionState.CONNECTING
        logger.info(f'Connecting to Protect controller at {self._config.host}')

        try:
            self._client = ProtectApiClient(**self._config.to_client_kwargs())
            self._bootstrap = await self._client.get_bootstrap()
            self._state = ConnectionState.CONNECTED

            nvr_name = self._bootstrap.nvr.name if self._bootstrap.nvr else 'Unknown'
            logger.info(
                f'Connected to Protect controller: {nvr_name} '
                f'({len(self.cameras)} cameras, {len(self.ai_ports)} AI ports)'
            )
            return True

        except Exception as e:
            self._state = ConnectionState.ERROR
            error_msg = str(e).lower()

            if 'unauthorized' in error_msg or 'authentication' in error_msg:
                logger.error(f'Authentication failed: {e}')
                raise AuthenticationError(
                    f'Failed to authenticate with Protect controller: {e}',
                    original_error=e,
                )
            else:
                logger.error(f'Connection failed: {e}')
                raise ConnectionError(
                    f'Failed to connect to Protect controller: {e}',
                    original_error=e,
                )

    async def disconnect(self) -> None:
        """Disconnect from the UniFi Protect controller.

        Closes the connection and cleans up resources. Safe to call
        even if not currently connected.
        """
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception as e:
                logger.warning(f'Error unsubscribing from WebSocket: {e}')
            self._ws_unsub = None

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._client is not None:
            try:
                await self._client.close_session()
            except Exception as e:
                logger.warning(f'Error closing session: {e}')
            self._client = None

        self._bootstrap = None
        self._state = ConnectionState.DISCONNECTED
        logger.info('Disconnected from Protect controller')

    async def refresh(self) -> None:
        """Refresh the bootstrap data from the controller.

        Fetches the latest device inventory and configuration.

        Raises:
            ConnectionError: If not connected to the controller.
        """
        if not self.is_connected or self._client is None:
            raise ConnectionError('Not connected to Protect controller')

        logger.debug('Refreshing bootstrap data')
        try:
            self._bootstrap = await self._client.get_bootstrap()
            logger.debug(
                f'Bootstrap refreshed: {len(self.cameras)} cameras, '
                f'{len(self.ai_ports)} AI ports'
            )
        except Exception as e:
            logger.error(f'Failed to refresh bootstrap: {e}')
            raise ConnectionError(f'Failed to refresh data: {e}', original_error=e)

    def get_camera(self, camera_id: str) -> Camera | None:
        """Get a camera by its ID.

        Args:
            camera_id: The unique identifier of the camera.

        Returns:
            The Camera instance if found, None otherwise.
        """
        return self.cameras.get(camera_id)

    def get_camera_by_name(self, name: str) -> Camera | None:
        """Get a camera by its display name.

        Performs a case-insensitive search for the camera name.

        Args:
            name: The display name of the camera.

        Returns:
            The Camera instance if found, None otherwise.
        """
        name_lower = name.lower()
        for camera in self.cameras.values():
            camera_name: str | None = getattr(camera, 'name', None)
            if camera_name is not None and camera_name.lower() == name_lower:
                return camera
        return None

    def get_ai_port(self, ai_port_id: str) -> AiPort | None:
        """Get an AI Port by its ID.

        Args:
            ai_port_id: The unique identifier of the AI Port.

        Returns:
            The AiPort instance if found, None otherwise.
        """
        return self.ai_ports.get(ai_port_id)

    def get_cameras_by_ai_port(self, ai_port_id: str) -> list[Camera]:
        """Get all cameras paired with a specific AI Port.

        Args:
            ai_port_id: The unique identifier of the AI Port.

        Returns:
            List of Camera instances paired with the AI Port.
        """
        cameras: list[Camera] = []
        for camera in self.cameras.values():
            # Check if camera is connected to this AI port
            aiport_id: str | None = getattr(camera, 'aiport_id', None)
            if aiport_id is not None and aiport_id == ai_port_id:
                cameras.append(camera)
        return cameras

    def get_third_party_cameras(self) -> list[Camera]:
        """Get all third-party (non-UniFi) cameras.

        Third-party cameras are typically ONVIF cameras connected
        through an AI Port or directly to the NVR.

        Returns:
            List of Camera instances that are third-party cameras.
        """
        return [
            cam
            for cam in self.cameras.values()
            if getattr(cam, 'is_third_party_camera', False)
        ]

    async def __aenter__(self) -> UniFiProtectClient:
        """Async context manager entry.

        Connects to the Protect controller when entering the context.

        Returns:
            The connected client instance.

        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If authentication fails.
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit.

        Disconnects from the controller when exiting the context.

        Args:
            exc_type: Exception type if an exception was raised.
            exc_val: Exception value if an exception was raised.
            exc_tb: Exception traceback if an exception was raised.
        """
        await self.disconnect()


@asynccontextmanager
async def create_client(config: ProtectConfig) -> AsyncIterator[UniFiProtectClient]:
    """Create and connect a UniFi Protect client.

    A convenience function that creates a client and manages its
    lifecycle using an async context manager.

    Args:
        config: Configuration for the client connection.

    Yields:
        A connected UniFiProtectClient instance.

    Raises:
        ConnectionError: If connection fails.
        AuthenticationError: If authentication fails.

    Example:
        >>> async with create_client(config) as client:
        ...     for camera in client.cameras.values():
        ...         print(camera.name)
    """
    client = UniFiProtectClient(config)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()
