"""UniFi Protect tool wrappers for MCP server.

These wrappers handle the lifecycle of the Protect client connection
and provide a consistent async interface for MCP tool execution.

Each call opens its own ``UniFiProtectClient(config, read_only=True)``, whose
``ReadOnlyProtectApiClient`` sends GET and HEAD (to the opt-in request audit) and the
session login, and refuses anything else before any I/O. A refused write propagates, so
the runner reports ``READ_ONLY_VIOLATION``.

A failure is an error result, never a success value (issue 011): a client error the wrapper
can name is a :class:`ToolError` with its domain code (``CONTROLLER_UNREACHABLE``,
``AUTHENTICATION_FAILED``, ``API_ERROR``; ``NO_DATA`` when the controller reports no NVR);
anything else propagates to the runner, which reports it as ``TOOL_FAILED``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.mcp.failure_text import tool_failure
from unifi_mapper.protect.client import (
    AuthenticationError,
    ConnectionError,
    ProtectClientError,
    UniFiProtectClient,
)
from unifi_mapper.protect.config import ProtectConfig


CONNECTION_SUGGESTION = 'Check PROTECT_HOST and that the Protect controller is reachable.'
AUTHENTICATION_SUGGESTION = 'Check PROTECT_USERNAME and PROTECT_PASSWORD.'
API_SUGGESTION = 'Check the Protect controller status and try again.'


def _tool_error(action: str, error: ProtectClientError) -> ToolError:
    """Map a Protect client failure to a ``ToolError`` with its domain code.

    Args:
        action: What the tool was doing, for the log line.
        error: The client's typed exception.

    Returns:
        The error to raise; its message is the client's text, redacted.
    """
    if isinstance(error, AuthenticationError):
        code, suggestion = ErrorCodes.AUTHENTICATION_FAILED, AUTHENTICATION_SUGGESTION
    elif isinstance(error, ConnectionError):
        code, suggestion = ErrorCodes.CONTROLLER_UNREACHABLE, CONNECTION_SUGGESTION
    else:
        code, suggestion = ErrorCodes.API_ERROR, API_SUGGESTION
    return ToolError(message=tool_failure(action, error), error_code=code, suggestion=suggestion)


@lru_cache(maxsize=1)
def _get_config() -> ProtectConfig:
    """Get cached Protect configuration from environment."""
    return ProtectConfig.from_env()


async def get_cameras() -> list[dict[str, Any]]:
    """Get all cameras and their status.

    Returns:
        List of camera data as dictionaries.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            cameras = client.cameras
            return [
                {
                    'id': cam.id,
                    'name': cam.name,
                    'type': cam.type,
                    'state': str(cam.state) if hasattr(cam, 'state') else 'unknown',
                    'is_recording': getattr(cam, 'is_recording', False),
                    'is_connected': getattr(cam, 'is_connected', False),
                }
                for cam in cameras.values()
            ]
    except ProtectClientError as e:
        raise _tool_error('get cameras', e) from e


async def get_nvr_info() -> dict[str, Any]:
    """Get NVR (Network Video Recorder) information and status.

    Returns:
        NVR data as dictionary.

    Raises:
        ToolError: ``NO_DATA`` when the controller reports no NVR.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            nvr = client.nvr
            if nvr is None:
                raise ToolError(
                    message='NVR not available',
                    error_code=ErrorCodes.NO_DATA,
                    suggestion='The Protect controller reported no NVR; check its status.',
                )
            return {
                'id': nvr.id,
                'name': nvr.name,
                'type': nvr.type,
                'version': getattr(nvr, 'version', 'unknown'),
                'uptime': getattr(nvr, 'uptime', None),
                'is_connected': getattr(nvr, 'is_connected', False),
            }
    except ProtectClientError as e:
        raise _tool_error('get NVR info', e) from e


async def get_sensors() -> list[dict[str, Any]]:
    """Get door/window sensors and their status.

    Returns:
        List of sensor data as dictionaries.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            sensors = client.sensors
            return [
                {
                    'id': sensor.id,
                    'name': sensor.name,
                    'type': sensor.type,
                    'is_open': getattr(sensor, 'is_open', None),
                    'battery_status': getattr(sensor, 'battery_status', None),
                    'is_connected': getattr(sensor, 'is_connected', False),
                }
                for sensor in sensors.values()
            ]
    except ProtectClientError as e:
        raise _tool_error('get sensors', e) from e


async def get_lights() -> list[dict[str, Any]]:
    """Get smart lights and floodlights.

    Returns:
        List of light data as dictionaries.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            lights = client.lights
            return [
                {
                    'id': light.id,
                    'name': light.name,
                    'type': light.type,
                    'is_on': getattr(light, 'is_light_on', False),
                    'is_connected': getattr(light, 'is_connected', False),
                }
                for light in lights.values()
            ]
    except ProtectClientError as e:
        raise _tool_error('get lights', e) from e


async def get_doorbells() -> list[dict[str, Any]]:
    """Get video doorbells and their status.

    Returns:
        List of doorbell data as dictionaries.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            cameras = client.cameras
            doorbells = [
                cam
                for cam in cameras.values()
                if getattr(getattr(cam, 'feature_flags', None), 'has_chime', False)
            ]
            return [
                {
                    'id': db.id,
                    'name': db.name,
                    'type': db.type,
                    'state': str(db.state) if hasattr(db, 'state') else 'unknown',
                    'is_connected': getattr(db, 'is_connected', False),
                }
                for db in doorbells
            ]
    except ProtectClientError as e:
        raise _tool_error('get doorbells', e) from e
