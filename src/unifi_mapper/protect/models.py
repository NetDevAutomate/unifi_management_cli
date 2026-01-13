"""Pydantic models for UniFi Protect devices.

This module provides clean, simplified Pydantic models for representing
UniFi Protect devices. Each model extracts essential fields from the
uiprotect library's complex data structures.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field


if TYPE_CHECKING:
    from uiprotect.data import AiPort, Camera, Chime, Doorlock, Light, NVR, Sensor


class DeviceType(str, Enum):
    """Enumeration of UniFi Protect device types.

    Attributes:
        CAMERA: Standard or third-party camera.
        NVR: Network Video Recorder.
        SENSOR: Motion, door, or environmental sensor.
        LIGHT: Smart floodlight.
        CHIME: Doorbell chime.
        DOORLOCK: Smart door lock.
        AI_PORT: AI Port for third-party cameras.
    """

    CAMERA = 'camera'
    NVR = 'nvr'
    SENSOR = 'sensor'
    LIGHT = 'light'
    CHIME = 'chime'
    DOORLOCK = 'doorlock'
    AI_PORT = 'ai_port'


class DeviceState(str, Enum):
    """Enumeration of device connection states.

    Attributes:
        CONNECTED: Device is online and communicating.
        DISCONNECTED: Device is offline or unreachable.
        CONNECTING: Device is attempting to connect.
        UPDATING: Device is currently updating firmware.
        ADOPTING: Device is being adopted by the controller.
        UNKNOWN: Device state cannot be determined.
    """

    CONNECTED = 'connected'
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    UPDATING = 'updating'
    ADOPTING = 'adopting'
    UNKNOWN = 'unknown'


class BaseDevice(BaseModel):
    """Base model for all UniFi Protect devices.

    Contains common fields shared by all device types.

    Attributes:
        id: Unique device identifier.
        name: Human-readable device name.
        type: Device type category.
        mac: MAC address of the device.
        host: IP address or hostname.
        state: Current connection state.
        firmware_version: Installed firmware version.
        is_adopted: Whether the device is adopted by the controller.
        is_updating: Whether the device is currently updating.
        up_since: Timestamp when the device came online.
        uptime: Duration the device has been online.
        last_seen: Last communication timestamp.
    """

    id: Annotated[str, Field(description='Unique device identifier')]
    name: Annotated[str, Field(description='Human-readable device name')]
    type: Annotated[DeviceType, Field(description='Device type category')]
    mac: Annotated[str, Field(description='MAC address')]
    host: Annotated[str | None, Field(default=None, description='IP address or hostname')]
    state: Annotated[DeviceState, Field(default=DeviceState.UNKNOWN, description='Connection state')]
    firmware_version: Annotated[str | None, Field(default=None, description='Firmware version')]
    is_adopted: Annotated[bool, Field(default=False, description='Adopted by controller')]
    is_updating: Annotated[bool, Field(default=False, description='Currently updating')]
    up_since: Annotated[datetime | None, Field(default=None, description='Online since')]
    uptime: Annotated[timedelta | None, Field(default=None, description='Time online')]
    last_seen: Annotated[datetime | None, Field(default=None, description='Last seen timestamp')]

    model_config = {'extra': 'forbid', 'from_attributes': True}

    @staticmethod
    def _parse_state(uiprotect_state: Any) -> DeviceState:
        """Parse uiprotect state enum to our DeviceState.

        Args:
            uiprotect_state: State value from uiprotect library.

        Returns:
            Corresponding DeviceState enum value.
        """
        if uiprotect_state is None:
            return DeviceState.UNKNOWN

        state_str = str(uiprotect_state).lower()
        state_mapping = {
            'connected': DeviceState.CONNECTED,
            'disconnected': DeviceState.DISCONNECTED,
            'connecting': DeviceState.CONNECTING,
            'updating': DeviceState.UPDATING,
            'adopting': DeviceState.ADOPTING,
        }
        return state_mapping.get(state_str, DeviceState.UNKNOWN)

    @staticmethod
    def _parse_host(host: Any) -> str | None:
        """Parse host value to string.

        Args:
            host: Host value (IPv4Address, IPv6Address, or str).

        Returns:
            String representation of host or None.
        """
        if host is None:
            return None
        return str(host)


class ProtectCamera(BaseDevice):
    """Model representing a UniFi Protect camera.

    Includes camera-specific fields for recording, motion detection,
    and smart detection features.

    Attributes:
        is_recording: Whether the camera is currently recording.
        is_motion_detected: Whether motion is currently detected.
        is_smart_detected: Whether smart detection is active.
        is_third_party: Whether this is a third-party (non-UniFi) camera.
        is_paired_with_ai_port: Whether paired with an AI Port.
        last_motion: Timestamp of last motion detection.
        last_smart_detect: Timestamp of last smart detection.
        has_recordings: Whether the camera has stored recordings.
    """

    is_recording: Annotated[bool, Field(default=False, description='Currently recording')]
    is_motion_detected: Annotated[bool, Field(default=False, description='Motion detected')]
    is_smart_detected: Annotated[bool, Field(default=False, description='Smart detection active')]
    is_third_party: Annotated[bool, Field(default=False, description='Third-party camera')]
    is_paired_with_ai_port: Annotated[bool, Field(default=False, description='Paired with AI Port')]
    last_motion: Annotated[datetime | None, Field(default=None, description='Last motion time')]
    last_smart_detect: Annotated[datetime | None, Field(default=None, description='Last smart detect')]
    has_recordings: Annotated[bool, Field(default=False, description='Has stored recordings')]

    @classmethod
    def from_uiprotect(cls, camera: Camera) -> ProtectCamera:
        """Create a ProtectCamera from a uiprotect Camera object.

        Args:
            camera: Camera instance from uiprotect library.

        Returns:
            ProtectCamera instance with extracted data.
        """
        return cls(
            id=camera.id,
            name=camera.name or 'Unknown Camera',
            type=DeviceType.CAMERA,
            mac=camera.mac,
            host=cls._parse_host(camera.host),
            state=cls._parse_state(getattr(camera, 'state', None)),
            firmware_version=camera.firmware_version,
            is_adopted=getattr(camera, 'is_adopted', False),
            is_updating=getattr(camera, 'is_updating', False),
            up_since=camera.up_since,
            uptime=camera.uptime,
            last_seen=camera.last_seen,
            is_recording=getattr(camera, 'is_recording', False),
            is_motion_detected=getattr(camera, 'is_motion_detected', False),
            is_smart_detected=getattr(camera, 'is_smart_detected', False),
            is_third_party=getattr(camera, 'is_third_party_camera', False) or False,
            is_paired_with_ai_port=getattr(camera, 'is_paired_with_ai_port', False) or False,
            last_motion=camera.last_motion,
            last_smart_detect=getattr(camera, 'last_smart_detect', None),
            has_recordings=getattr(camera, 'has_recordings', False) or False,
        )


class ProtectNVR(BaseDevice):
    """Model representing a UniFi Protect NVR.

    Network Video Recorder with storage and system information.

    Attributes:
        version: NVR software version.
        hardware_platform: Hardware platform identifier.
        timezone: Configured timezone.
        is_station: Whether this is a Cloud Key or station device.
        enable_automatic_backups: Whether auto backups are enabled.
    """

    version: Annotated[str | None, Field(default=None, description='NVR software version')]
    hardware_platform: Annotated[str | None, Field(default=None, description='Hardware platform')]
    timezone: Annotated[str | None, Field(default=None, description='Configured timezone')]
    is_station: Annotated[bool, Field(default=False, description='Is Cloud Key/station')]
    enable_automatic_backups: Annotated[bool, Field(default=False, description='Auto backups enabled')]

    @classmethod
    def from_uiprotect(cls, nvr: NVR) -> ProtectNVR:
        """Create a ProtectNVR from a uiprotect NVR object.

        Args:
            nvr: NVR instance from uiprotect library.

        Returns:
            ProtectNVR instance with extracted data.
        """
        timezone_str = str(nvr.timezone) if hasattr(nvr, 'timezone') else None

        version_str = str(nvr.version) if hasattr(nvr, 'version') else None

        return cls(
            id=nvr.id,
            name=nvr.name or 'Unknown NVR',
            type=DeviceType.NVR,
            mac=nvr.mac,
            host=cls._parse_host(nvr.host),
            state=DeviceState.CONNECTED,  # NVR is always connected if we can access it
            firmware_version=nvr.firmware_version,
            is_adopted=True,  # NVR is always adopted
            is_updating=getattr(nvr, 'is_updating', False),
            up_since=nvr.up_since,
            uptime=nvr.uptime,
            last_seen=nvr.last_seen,
            version=version_str,
            hardware_platform=getattr(nvr, 'hardware_platform', None),
            timezone=timezone_str,
            is_station=getattr(nvr, 'is_station', False),
            enable_automatic_backups=getattr(nvr, 'enable_automatic_backups', False),
        )


class ProtectSensor(BaseDevice):
    """Model representing a UniFi Protect sensor.

    Includes sensor-specific fields for motion, door open/close,
    and environmental readings.

    Attributes:
        is_motion_detected: Whether motion is currently detected.
        is_opened: Whether the door/window is open (for door sensors).
        motion_detected_at: Last motion detection timestamp.
        open_status_changed_at: Last open/close status change.
        tampering_detected_at: Last tampering detection.
        alarm_triggered_at: Last alarm trigger timestamp.
        leak_detected_at: Last water leak detection (if supported).
        mount_type: How the sensor is mounted.
    """

    is_motion_detected: Annotated[bool, Field(default=False, description='Motion detected')]
    is_opened: Annotated[bool, Field(default=False, description='Door/window open')]
    motion_detected_at: Annotated[datetime | None, Field(default=None, description='Last motion')]
    open_status_changed_at: Annotated[datetime | None, Field(default=None, description='Last open/close')]
    tampering_detected_at: Annotated[datetime | None, Field(default=None, description='Last tampering')]
    alarm_triggered_at: Annotated[datetime | None, Field(default=None, description='Last alarm')]
    leak_detected_at: Annotated[datetime | None, Field(default=None, description='Last leak')]
    mount_type: Annotated[str | None, Field(default=None, description='Mount type')]

    @classmethod
    def from_uiprotect(cls, sensor: Sensor) -> ProtectSensor:
        """Create a ProtectSensor from a uiprotect Sensor object.

        Args:
            sensor: Sensor instance from uiprotect library.

        Returns:
            ProtectSensor instance with extracted data.
        """
        mount_type_str = str(sensor.mount_type) if hasattr(sensor, 'mount_type') else None

        return cls(
            id=sensor.id,
            name=sensor.name or 'Unknown Sensor',
            type=DeviceType.SENSOR,
            mac=sensor.mac,
            host=cls._parse_host(sensor.host),
            state=cls._parse_state(getattr(sensor, 'state', None)),
            firmware_version=sensor.firmware_version,
            is_adopted=getattr(sensor, 'is_adopted', False),
            is_updating=getattr(sensor, 'is_updating', False),
            up_since=sensor.up_since,
            uptime=sensor.uptime,
            last_seen=sensor.last_seen,
            is_motion_detected=getattr(sensor, 'is_motion_detected', False),
            is_opened=getattr(sensor, 'is_opened', False),
            motion_detected_at=getattr(sensor, 'motion_detected_at', None),
            open_status_changed_at=getattr(sensor, 'open_status_changed_at', None),
            tampering_detected_at=getattr(sensor, 'tampering_detected_at', None),
            alarm_triggered_at=getattr(sensor, 'alarm_triggered_at', None),
            leak_detected_at=getattr(sensor, 'leak_detected_at', None),
            mount_type=mount_type_str,
        )


class ProtectLight(BaseDevice):
    """Model representing a UniFi Protect smart light.

    Includes light-specific fields for brightness and motion.

    Attributes:
        is_light_on: Whether the light is currently on.
        light_level: Current brightness level (0-100).
        is_motion_detected: Whether motion is detected.
        last_motion: Last motion detection timestamp.
        is_pir_motion_detected: Whether PIR sensor detected motion.
    """

    is_light_on: Annotated[bool, Field(default=False, description='Light is on')]
    light_level: Annotated[int, Field(default=0, ge=0, le=100, description='Brightness level')]
    is_motion_detected: Annotated[bool, Field(default=False, description='Motion detected')]
    last_motion: Annotated[datetime | None, Field(default=None, description='Last motion')]
    is_pir_motion_detected: Annotated[bool, Field(default=False, description='PIR motion detected')]

    @classmethod
    def from_uiprotect(cls, light: Light) -> ProtectLight:
        """Create a ProtectLight from a uiprotect Light object.

        Args:
            light: Light instance from uiprotect library.

        Returns:
            ProtectLight instance with extracted data.
        """
        return cls(
            id=light.id,
            name=light.name or 'Unknown Light',
            type=DeviceType.LIGHT,
            mac=light.mac,
            host=cls._parse_host(light.host),
            state=cls._parse_state(getattr(light, 'state', None)),
            firmware_version=light.firmware_version,
            is_adopted=getattr(light, 'is_adopted', False),
            is_updating=getattr(light, 'is_updating', False),
            up_since=light.up_since,
            uptime=light.uptime,
            last_seen=light.last_seen,
            is_light_on=getattr(light, 'is_light_on', False),
            light_level=getattr(light, 'light_device_settings', {}).get('led_level', 0) if hasattr(light, 'light_device_settings') else 0,
            is_motion_detected=getattr(light, 'is_motion_detected', False),
            last_motion=getattr(light, 'last_motion', None),
            is_pir_motion_detected=getattr(light, 'is_pir_motion_detected', False),
        )


class ProtectChime(BaseDevice):
    """Model representing a UniFi Protect doorbell chime.

    Attributes:
        volume: Chime volume level (0-100).
        is_ringing: Whether the chime is currently ringing.
    """

    volume: Annotated[int, Field(default=100, ge=0, le=100, description='Volume level')]
    is_ringing: Annotated[bool, Field(default=False, description='Currently ringing')]

    @classmethod
    def from_uiprotect(cls, chime: Chime) -> ProtectChime:
        """Create a ProtectChime from a uiprotect Chime object.

        Args:
            chime: Chime instance from uiprotect library.

        Returns:
            ProtectChime instance with extracted data.
        """
        return cls(
            id=chime.id,
            name=chime.name or 'Unknown Chime',
            type=DeviceType.CHIME,
            mac=chime.mac,
            host=cls._parse_host(chime.host),
            state=cls._parse_state(getattr(chime, 'state', None)),
            firmware_version=chime.firmware_version,
            is_adopted=getattr(chime, 'is_adopted', False),
            is_updating=getattr(chime, 'is_updating', False),
            up_since=chime.up_since,
            uptime=chime.uptime,
            last_seen=chime.last_seen,
            volume=getattr(chime, 'volume', 100),
            is_ringing=getattr(chime, 'is_ringing', False),
        )


class ProtectDoorlock(BaseDevice):
    """Model representing a UniFi Protect smart door lock.

    Attributes:
        is_locked: Whether the lock is currently locked.
        lock_status: Current lock status string.
        auto_close_time: Auto-lock delay in seconds.
    """

    is_locked: Annotated[bool, Field(default=True, description='Currently locked')]
    lock_status: Annotated[str | None, Field(default=None, description='Lock status')]
    auto_close_time: Annotated[int | None, Field(default=None, description='Auto-lock delay seconds')]

    @classmethod
    def from_uiprotect(cls, doorlock: Doorlock) -> ProtectDoorlock:
        """Create a ProtectDoorlock from a uiprotect Doorlock object.

        Args:
            doorlock: Doorlock instance from uiprotect library.

        Returns:
            ProtectDoorlock instance with extracted data.
        """
        lock_status_str = str(doorlock.lock_status) if hasattr(doorlock, 'lock_status') else None

        return cls(
            id=doorlock.id,
            name=doorlock.name or 'Unknown Doorlock',
            type=DeviceType.DOORLOCK,
            mac=doorlock.mac,
            host=cls._parse_host(doorlock.host),
            state=cls._parse_state(getattr(doorlock, 'state', None)),
            firmware_version=doorlock.firmware_version,
            is_adopted=getattr(doorlock, 'is_adopted', False),
            is_updating=getattr(doorlock, 'is_updating', False),
            up_since=doorlock.up_since,
            uptime=doorlock.uptime,
            last_seen=doorlock.last_seen,
            is_locked=getattr(doorlock, 'is_locked', True),
            lock_status=lock_status_str,
            auto_close_time=getattr(doorlock, 'auto_close_time', None),
        )


class ProtectAIPort(BaseDevice):
    """Model representing a UniFi AI Port.

    AI Ports add smart detection capabilities to third-party cameras.

    Attributes:
        camera_count: Number of cameras connected to this AI Port.
        is_package_enabled: Whether package detection is enabled.
        is_person_enabled: Whether person detection is enabled.
        is_vehicle_enabled: Whether vehicle detection is enabled.
        is_animal_enabled: Whether animal detection is enabled.
    """

    camera_count: Annotated[int, Field(default=0, ge=0, description='Connected cameras')]
    is_package_enabled: Annotated[bool, Field(default=False, description='Package detection')]
    is_person_enabled: Annotated[bool, Field(default=False, description='Person detection')]
    is_vehicle_enabled: Annotated[bool, Field(default=False, description='Vehicle detection')]
    is_animal_enabled: Annotated[bool, Field(default=False, description='Animal detection')]

    @classmethod
    def from_uiprotect(cls, aiport: AiPort) -> ProtectAIPort:
        """Create a ProtectAIPort from a uiprotect AiPort object.

        Args:
            aiport: AiPort instance from uiprotect library.

        Returns:
            ProtectAIPort instance with extracted data.
        """
        # Get smart detect settings if available
        smart_settings = getattr(aiport, 'smart_detect_settings', None)
        is_package = False
        is_person = False
        is_vehicle = False
        is_animal = False

        if smart_settings is not None:
            object_types = getattr(smart_settings, 'object_types', []) or []
            type_strings = [str(t).lower() for t in object_types]
            is_package = 'package' in type_strings
            is_person = 'person' in type_strings
            is_vehicle = 'vehicle' in type_strings
            is_animal = 'animal' in type_strings

        return cls(
            id=aiport.id,
            name=aiport.name or 'Unknown AI Port',
            type=DeviceType.AI_PORT,
            mac=aiport.mac,
            host=cls._parse_host(aiport.host),
            state=cls._parse_state(getattr(aiport, 'state', None)),
            firmware_version=aiport.firmware_version,
            is_adopted=getattr(aiport, 'is_adopted', False),
            is_updating=getattr(aiport, 'is_updating', False),
            up_since=aiport.up_since,
            uptime=aiport.uptime,
            last_seen=aiport.last_seen,
            camera_count=len(getattr(aiport, 'cameras', []) or []),
            is_package_enabled=is_package,
            is_person_enabled=is_person,
            is_vehicle_enabled=is_vehicle,
            is_animal_enabled=is_animal,
        )


# Type alias for any Protect device model
ProtectDevice = ProtectCamera | ProtectNVR | ProtectSensor | ProtectLight | ProtectChime | ProtectDoorlock | ProtectAIPort
