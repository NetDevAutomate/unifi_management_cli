"""UniFi Protect tool wrappers for MCP server.

These wrappers handle the lifecycle of the Protect client connection
and provide a consistent async interface for MCP tool execution.

Each call opens its own ``UniFiProtectClient(config, read_only=True)``, whose
``ReadOnlyProtectApiClient`` sends GET and HEAD (to the opt-in request audit) and the
session login, and refuses anything else before any I/O. A refused write propagates, so
the runner reports ``READ_ONLY_VIOLATION``; other failures still return ``{'error': ...}``.
"""

from __future__ import annotations

from functools import lru_cache
from loguru import logger
from typing import Any
from unifi_mapper.core.utils.readonly import ReadOnlyViolation
from unifi_mapper.core.utils.redact import redact_text
from unifi_mapper.protect.client import UniFiProtectClient
from unifi_mapper.protect.config import ProtectConfig


# Long enough that a real message is never cut (the runner caps errors at 2,000).
FAILURE_TEXT_LIMIT = 2000


def _failure(action: str, error: Exception) -> str:
    """Log a tool's failure and return its error text, both redacted.

    A lower layer's message can carry a credential, and the server's stderr ends up in the
    MCP client's own logs, so neither the log line nor the returned ``error`` shows it raw.
    """
    text = redact_text(error, limit=FAILURE_TEXT_LIMIT)
    logger.error('Failed to {}: {}', action, text)
    return text


@lru_cache(maxsize=1)
def _get_config() -> ProtectConfig:
    """Get cached Protect configuration from environment."""
    return ProtectConfig.from_env()


async def get_cameras() -> list[dict[str, Any]]:
    """Get all cameras and their status.

    Returns:
        List of camera data as dictionaries, or error dict on failure.
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
    except ReadOnlyViolation:
        raise
    except Exception as e:
        return [{'error': _failure('get cameras', e)}]


async def get_nvr_info() -> dict[str, Any]:
    """Get NVR (Network Video Recorder) information and status.

    Returns:
        NVR data as dictionary, or error dict on failure.
    """
    try:
        config = _get_config()
        async with UniFiProtectClient(config, read_only=True) as client:
            nvr = client.nvr
            if nvr is None:
                return {'error': 'NVR not available'}
            return {
                'id': nvr.id,
                'name': nvr.name,
                'type': nvr.type,
                'version': getattr(nvr, 'version', 'unknown'),
                'uptime': getattr(nvr, 'uptime', None),
                'is_connected': getattr(nvr, 'is_connected', False),
            }
    except ReadOnlyViolation:
        raise
    except Exception as e:
        return {'error': _failure('get NVR info', e)}


async def get_sensors() -> list[dict[str, Any]]:
    """Get door/window sensors and their status.

    Returns:
        List of sensor data as dictionaries, or error dict on failure.
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
    except ReadOnlyViolation:
        raise
    except Exception as e:
        return [{'error': _failure('get sensors', e)}]


async def get_lights() -> list[dict[str, Any]]:
    """Get smart lights and floodlights.

    Returns:
        List of light data as dictionaries, or error dict on failure.
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
    except ReadOnlyViolation:
        raise
    except Exception as e:
        return [{'error': _failure('get lights', e)}]


async def get_doorbells() -> list[dict[str, Any]]:
    """Get video doorbells and their status.

    Returns:
        List of doorbell data as dictionaries, or error dict on failure.
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
    except ReadOnlyViolation:
        raise
    except Exception as e:
        return [{'error': _failure('get doorbells', e)}]
