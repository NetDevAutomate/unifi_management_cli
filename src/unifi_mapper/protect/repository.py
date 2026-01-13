"""Device repository for caching and accessing UniFi Protect devices.

This module provides a repository pattern for managing device data,
including caching, filtering, and convenient access methods.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Generic, TypeVar

from loguru import logger  # type: ignore[import-untyped]

from unifi_mapper.protect.models import (
    DeviceType,
    ProtectAIPort,
    ProtectCamera,
    ProtectChime,
    ProtectDevice,
    ProtectDoorlock,
    ProtectLight,
    ProtectNVR,
    ProtectSensor,
)


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


T = TypeVar('T', bound=ProtectDevice)


class DeviceRepository(Generic[T]):
    """Generic repository for a specific device type.

    Provides type-safe access to devices of a specific type with
    filtering and lookup methods.

    Attributes:
        device_type: The DeviceType this repository manages.

    Example:
        >>> repo = DeviceRepository[ProtectCamera](DeviceType.CAMERA)
        >>> repo.add(camera)
        >>> camera = repo.get('camera-123')
    """

    def __init__(self, device_type: DeviceType) -> None:
        """Initialize the device repository.

        Args:
            device_type: The type of devices this repository manages.
        """
        self._device_type = device_type
        self._devices: dict[str, T] = {}

    @property
    def device_type(self) -> DeviceType:
        """Get the device type managed by this repository.

        Returns:
            The DeviceType enum value.
        """
        return self._device_type

    def add(self, device: T) -> None:
        """Add a device to the repository.

        Args:
            device: The device to add.
        """
        self._devices[device.id] = device

    def get(self, device_id: str) -> T | None:
        """Get a device by its ID.

        Args:
            device_id: The unique identifier of the device.

        Returns:
            The device if found, None otherwise.
        """
        return self._devices.get(device_id)

    def get_by_name(self, name: str) -> T | None:
        """Get a device by its display name (case-insensitive).

        Args:
            name: The display name to search for.

        Returns:
            The first matching device, or None if not found.
        """
        name_lower = name.lower()
        for device in self._devices.values():
            if device.name.lower() == name_lower:
                return device
        return None

    def all(self) -> list[T]:
        """Get all devices in the repository.

        Returns:
            List of all devices.
        """
        return list(self._devices.values())

    def filter(self, **kwargs: object) -> list[T]:
        """Filter devices by attribute values.

        Args:
            **kwargs: Attribute name/value pairs to filter by.

        Returns:
            List of devices matching all filter criteria.

        Example:
            >>> cameras = repo.filter(is_recording=True)
            >>> sensors = repo.filter(is_opened=True, is_motion_detected=False)
        """
        results: list[T] = []
        for device in self._devices.values():
            match = True
            for attr, value in kwargs.items():
                if not hasattr(device, attr) or getattr(device, attr) != value:
                    match = False
                    break
            if match:
                results.append(device)
        return results

    def remove(self, device_id: str) -> bool:
        """Remove a device from the repository.

        Args:
            device_id: The ID of the device to remove.

        Returns:
            True if the device was removed, False if not found.
        """
        if device_id in self._devices:
            del self._devices[device_id]
            return True
        return False

    def clear(self) -> None:
        """Remove all devices from the repository."""
        self._devices.clear()

    def __len__(self) -> int:
        """Get the number of devices in the repository.

        Returns:
            The device count.
        """
        return len(self._devices)

    def __iter__(self) -> Iterator[T]:
        """Iterate over all devices.

        Yields:
            Each device in the repository.
        """
        return iter(self._devices.values())

    def __contains__(self, device_id: str) -> bool:
        """Check if a device exists in the repository.

        Args:
            device_id: The device ID to check.

        Returns:
            True if the device exists, False otherwise.
        """
        return device_id in self._devices


class ProtectDeviceCache:
    """Centralized cache for all UniFi Protect device types.

    Provides typed repositories for each device type and methods
    to populate the cache from a UniFiProtectClient.

    Attributes:
        cameras: Repository of camera devices.
        nvr: The NVR device (singular).
        sensors: Repository of sensor devices.
        lights: Repository of light devices.
        chimes: Repository of chime devices.
        doorlocks: Repository of doorlock devices.
        ai_ports: Repository of AI Port devices.

    Example:
        >>> cache = ProtectDeviceCache()
        >>> await cache.refresh(client)
        >>> for camera in cache.cameras:
        ...     print(f"{camera.name}: recording={camera.is_recording}")
    """

    def __init__(self) -> None:
        """Initialize the device cache with empty repositories."""
        self._cameras: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        self._nvr: ProtectNVR | None = None
        self._sensors: DeviceRepository[ProtectSensor] = DeviceRepository(DeviceType.SENSOR)
        self._lights: DeviceRepository[ProtectLight] = DeviceRepository(DeviceType.LIGHT)
        self._chimes: DeviceRepository[ProtectChime] = DeviceRepository(DeviceType.CHIME)
        self._doorlocks: DeviceRepository[ProtectDoorlock] = DeviceRepository(DeviceType.DOORLOCK)
        self._ai_ports: DeviceRepository[ProtectAIPort] = DeviceRepository(DeviceType.AI_PORT)

    @property
    def cameras(self) -> DeviceRepository[ProtectCamera]:
        """Get the camera repository.

        Returns:
            Repository containing all cached cameras.
        """
        return self._cameras

    @property
    def nvr(self) -> ProtectNVR | None:
        """Get the NVR device.

        Returns:
            The cached NVR, or None if not populated.
        """
        return self._nvr

    @property
    def sensors(self) -> DeviceRepository[ProtectSensor]:
        """Get the sensor repository.

        Returns:
            Repository containing all cached sensors.
        """
        return self._sensors

    @property
    def lights(self) -> DeviceRepository[ProtectLight]:
        """Get the light repository.

        Returns:
            Repository containing all cached lights.
        """
        return self._lights

    @property
    def chimes(self) -> DeviceRepository[ProtectChime]:
        """Get the chime repository.

        Returns:
            Repository containing all cached chimes.
        """
        return self._chimes

    @property
    def doorlocks(self) -> DeviceRepository[ProtectDoorlock]:
        """Get the doorlock repository.

        Returns:
            Repository containing all cached doorlocks.
        """
        return self._doorlocks

    @property
    def ai_ports(self) -> DeviceRepository[ProtectAIPort]:
        """Get the AI Port repository.

        Returns:
            Repository containing all cached AI Ports.
        """
        return self._ai_ports

    async def refresh(self, client: UniFiProtectClient) -> None:
        """Refresh the cache from a connected client.

        Clears all existing data and repopulates from the client's
        bootstrap data. The client must be connected.

        Args:
            client: A connected UniFiProtectClient instance.

        Raises:
            ValueError: If the client is not connected.
        """
        if not client.is_connected:
            raise ValueError('Client must be connected to refresh cache')

        logger.debug('Refreshing device cache from client')
        self.clear()

        # Populate NVR
        nvr = client.nvr
        if nvr is not None:
            self._nvr = ProtectNVR.from_uiprotect(nvr)
            logger.debug(f'Cached NVR: {self._nvr.name}')

        # Populate cameras
        for camera in client.cameras.values():
            self._cameras.add(ProtectCamera.from_uiprotect(camera))
        logger.debug(f'Cached {len(self._cameras)} cameras')

        # Populate sensors
        for sensor in client.sensors.values():
            self._sensors.add(ProtectSensor.from_uiprotect(sensor))
        logger.debug(f'Cached {len(self._sensors)} sensors')

        # Populate lights
        for light in client.lights.values():
            self._lights.add(ProtectLight.from_uiprotect(light))
        logger.debug(f'Cached {len(self._lights)} lights')

        # Populate chimes
        for chime in client.chimes.values():
            self._chimes.add(ProtectChime.from_uiprotect(chime))
        logger.debug(f'Cached {len(self._chimes)} chimes')

        # Populate doorlocks
        for doorlock in client.doorlocks.values():
            self._doorlocks.add(ProtectDoorlock.from_uiprotect(doorlock))
        logger.debug(f'Cached {len(self._doorlocks)} doorlocks')

        # Populate AI Ports
        for aiport in client.ai_ports.values():
            self._ai_ports.add(ProtectAIPort.from_uiprotect(aiport))
        logger.debug(f'Cached {len(self._ai_ports)} AI ports')

        logger.info(
            f'Device cache refreshed: {len(self._cameras)} cameras, '
            f'{len(self._sensors)} sensors, {len(self._lights)} lights, '
            f'{len(self._chimes)} chimes, {len(self._doorlocks)} doorlocks, '
            f'{len(self._ai_ports)} AI ports'
        )

    def clear(self) -> None:
        """Clear all cached data."""
        self._cameras.clear()
        self._nvr = None
        self._sensors.clear()
        self._lights.clear()
        self._chimes.clear()
        self._doorlocks.clear()
        self._ai_ports.clear()
        logger.debug('Device cache cleared')

    def get_all_devices(self) -> list[ProtectDevice]:
        """Get all devices from all repositories.

        Returns:
            Combined list of all cached devices.
        """
        devices: list[ProtectDevice] = []
        if self._nvr is not None:
            devices.append(self._nvr)
        devices.extend(self._cameras.all())
        devices.extend(self._sensors.all())
        devices.extend(self._lights.all())
        devices.extend(self._chimes.all())
        devices.extend(self._doorlocks.all())
        devices.extend(self._ai_ports.all())
        return devices

    def get_device_by_id(self, device_id: str) -> ProtectDevice | None:
        """Get any device by its ID, searching all repositories.

        Args:
            device_id: The unique identifier of the device.

        Returns:
            The device if found in any repository, None otherwise.
        """
        # Check NVR first
        if self._nvr is not None and self._nvr.id == device_id:
            return self._nvr

        # Check each repository
        for repo in [
            self._cameras,
            self._sensors,
            self._lights,
            self._chimes,
            self._doorlocks,
            self._ai_ports,
        ]:
            device = repo.get(device_id)
            if device is not None:
                return device

        return None

    def get_device_by_mac(self, mac: str) -> ProtectDevice | None:
        """Get any device by its MAC address.

        Args:
            mac: The MAC address (case-insensitive).

        Returns:
            The device if found, None otherwise.
        """
        mac_upper = mac.upper()

        # Check NVR
        if self._nvr is not None and self._nvr.mac.upper() == mac_upper:
            return self._nvr

        # Check all devices
        for device in self.get_all_devices():
            if device.mac.upper() == mac_upper:
                return device

        return None

    @property
    def total_device_count(self) -> int:
        """Get the total number of cached devices.

        Returns:
            Total count across all repositories.
        """
        count = 1 if self._nvr is not None else 0
        count += len(self._cameras)
        count += len(self._sensors)
        count += len(self._lights)
        count += len(self._chimes)
        count += len(self._doorlocks)
        count += len(self._ai_ports)
        return count
