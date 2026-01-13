"""Unit tests for UniFi Protect device models.

This module tests the Pydantic models used to represent UniFi Protect devices,
including enum types, base device properties, and factory methods for
converting from uiprotect library objects.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from typing import Any
from unittest.mock import MagicMock

import pytest

from unifi_mapper.protect.models import (
    BaseDevice,
    DeviceState,
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


class TestDeviceType:
    """Tests for the DeviceType enum."""

    def test_all_device_types_exist(self) -> None:
        """Verify all expected device types are defined."""
        expected_types = ['camera', 'nvr', 'sensor', 'light', 'chime', 'doorlock', 'ai_port']
        actual_types = [t.value for t in DeviceType]
        assert set(actual_types) == set(expected_types)

    def test_device_type_values(self) -> None:
        """Verify device type enum values."""
        assert DeviceType.CAMERA.value == 'camera'
        assert DeviceType.NVR.value == 'nvr'
        assert DeviceType.SENSOR.value == 'sensor'
        assert DeviceType.LIGHT.value == 'light'
        assert DeviceType.CHIME.value == 'chime'
        assert DeviceType.DOORLOCK.value == 'doorlock'
        assert DeviceType.AI_PORT.value == 'ai_port'

    def test_device_type_is_str_enum(self) -> None:
        """Verify DeviceType is a string enum."""
        assert isinstance(DeviceType.CAMERA, str)
        assert DeviceType.CAMERA == 'camera'


class TestDeviceState:
    """Tests for the DeviceState enum."""

    def test_all_device_states_exist(self) -> None:
        """Verify all expected device states are defined."""
        expected_states = ['connected', 'disconnected', 'connecting', 'updating', 'adopting', 'unknown']
        actual_states = [s.value for s in DeviceState]
        assert set(actual_states) == set(expected_states)

    def test_device_state_values(self) -> None:
        """Verify device state enum values."""
        assert DeviceState.CONNECTED.value == 'connected'
        assert DeviceState.DISCONNECTED.value == 'disconnected'
        assert DeviceState.CONNECTING.value == 'connecting'
        assert DeviceState.UPDATING.value == 'updating'
        assert DeviceState.ADOPTING.value == 'adopting'
        assert DeviceState.UNKNOWN.value == 'unknown'


class TestBaseDeviceHelpers:
    """Tests for BaseDevice static helper methods."""

    def test_parse_state_connected(self) -> None:
        """Test parsing connected state."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='CONNECTED')
        assert BaseDevice._parse_state(mock_state) == DeviceState.CONNECTED  # type: ignore[reportPrivateUsage]

    def test_parse_state_disconnected(self) -> None:
        """Test parsing disconnected state."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='disconnected')
        assert BaseDevice._parse_state(mock_state) == DeviceState.DISCONNECTED  # type: ignore[reportPrivateUsage]

    def test_parse_state_connecting(self) -> None:
        """Test parsing connecting state."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='Connecting')
        assert BaseDevice._parse_state(mock_state) == DeviceState.CONNECTING  # type: ignore[reportPrivateUsage]

    def test_parse_state_updating(self) -> None:
        """Test parsing updating state."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='UPDATING')
        assert BaseDevice._parse_state(mock_state) == DeviceState.UPDATING  # type: ignore[reportPrivateUsage]

    def test_parse_state_adopting(self) -> None:
        """Test parsing adopting state."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='adopting')
        assert BaseDevice._parse_state(mock_state) == DeviceState.ADOPTING  # type: ignore[reportPrivateUsage]

    def test_parse_state_unknown_value(self) -> None:
        """Test parsing unknown state value returns UNKNOWN."""
        mock_state = MagicMock()
        mock_state.__str__ = MagicMock(return_value='some_random_state')
        assert BaseDevice._parse_state(mock_state) == DeviceState.UNKNOWN  # type: ignore[reportPrivateUsage]

    def test_parse_state_none(self) -> None:
        """Test parsing None state returns UNKNOWN."""
        assert BaseDevice._parse_state(None) == DeviceState.UNKNOWN  # type: ignore[reportPrivateUsage]

    def test_parse_host_string(self) -> None:
        """Test parsing string host."""
        assert BaseDevice._parse_host('192.168.1.100') == '192.168.1.100'  # type: ignore[reportPrivateUsage]

    def test_parse_host_ipv4address(self) -> None:
        """Test parsing IPv4Address host."""
        host = IPv4Address('192.168.1.100')
        assert BaseDevice._parse_host(host) == '192.168.1.100'  # type: ignore[reportPrivateUsage]

    def test_parse_host_none(self) -> None:
        """Test parsing None host."""
        assert BaseDevice._parse_host(None) is None  # type: ignore[reportPrivateUsage]


class TestProtectCamera:
    """Tests for ProtectCamera model."""

    def _create_mock_camera(self, **overrides: Any) -> MagicMock:
        """Create a mock camera with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as a Camera.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'cam-123')
        mock.name = overrides.get('name', 'Front Door')
        mock.mac = overrides.get('mac', 'AA:BB:CC:DD:EE:FF')
        mock.host = overrides.get('host', IPv4Address('192.168.1.100'))
        mock.firmware_version = overrides.get('firmware_version', '1.20.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=7))
        mock.last_seen = overrides.get('last_seen', now)
        mock.last_motion = overrides.get('last_motion', now)

        # Configure attributes accessed via getattr
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.is_recording = overrides.get('is_recording', True)
        mock.is_motion_detected = overrides.get('is_motion_detected', False)
        mock.is_smart_detected = overrides.get('is_smart_detected', False)
        mock.is_third_party_camera = overrides.get('is_third_party_camera', False)
        mock.is_paired_with_ai_port = overrides.get('is_paired_with_ai_port', False)
        mock.last_smart_detect = overrides.get('last_smart_detect', None)
        mock.has_recordings = overrides.get('has_recordings', True)

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectCamera from mock uiprotect Camera."""
        mock_camera = self._create_mock_camera()
        camera = ProtectCamera.from_uiprotect(mock_camera)

        assert camera.id == 'cam-123'
        assert camera.name == 'Front Door'
        assert camera.type == DeviceType.CAMERA
        assert camera.mac == 'AA:BB:CC:DD:EE:FF'
        assert camera.host == '192.168.1.100'
        assert camera.is_recording is True

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test camera with None name gets default."""
        mock_camera = self._create_mock_camera(name=None)
        camera = ProtectCamera.from_uiprotect(mock_camera)
        assert camera.name == 'Unknown Camera'

    def test_from_uiprotect_third_party(self) -> None:
        """Test third-party camera detection."""
        mock_camera = self._create_mock_camera(is_third_party_camera=True)
        camera = ProtectCamera.from_uiprotect(mock_camera)
        assert camera.is_third_party is True

    def test_from_uiprotect_ai_port_paired(self) -> None:
        """Test AI Port pairing detection."""
        mock_camera = self._create_mock_camera(is_paired_with_ai_port=True)
        camera = ProtectCamera.from_uiprotect(mock_camera)
        assert camera.is_paired_with_ai_port is True

    def test_from_uiprotect_motion_detected(self) -> None:
        """Test motion detection flag."""
        mock_camera = self._create_mock_camera(is_motion_detected=True)
        camera = ProtectCamera.from_uiprotect(mock_camera)
        assert camera.is_motion_detected is True


class TestProtectNVR:
    """Tests for ProtectNVR model."""

    def _create_mock_nvr(self, **overrides: Any) -> MagicMock:
        """Create a mock NVR with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as an NVR.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'nvr-001')
        mock.name = overrides.get('name', 'Cloud Key Gen2 Plus')
        mock.mac = overrides.get('mac', '11:22:33:44:55:66')
        mock.host = overrides.get('host', IPv4Address('192.168.1.1'))
        mock.firmware_version = overrides.get('firmware_version', '2.0.35')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=30))
        mock.last_seen = overrides.get('last_seen', now)

        # NVR-specific attributes
        mock.timezone = overrides.get('timezone', 'America/New_York')
        mock.version = overrides.get('version', '2.10.0')
        mock.hardware_platform = overrides.get('hardware_platform', 'uck-g2-plus')
        mock.is_station = overrides.get('is_station', False)
        mock.is_updating = overrides.get('is_updating', False)
        mock.enable_automatic_backups = overrides.get('enable_automatic_backups', True)

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectNVR from mock uiprotect NVR."""
        mock_nvr = self._create_mock_nvr()
        nvr = ProtectNVR.from_uiprotect(mock_nvr)

        assert nvr.id == 'nvr-001'
        assert nvr.name == 'Cloud Key Gen2 Plus'
        assert nvr.type == DeviceType.NVR
        assert nvr.mac == '11:22:33:44:55:66'
        assert nvr.host == '192.168.1.1'
        assert nvr.is_adopted is True  # NVR is always adopted

    def test_from_uiprotect_timezone(self) -> None:
        """Test timezone extraction."""
        mock_nvr = self._create_mock_nvr(timezone='America/Los_Angeles')
        nvr = ProtectNVR.from_uiprotect(mock_nvr)
        assert nvr.timezone == 'America/Los_Angeles'

    def test_from_uiprotect_version(self) -> None:
        """Test version extraction."""
        mock_nvr = self._create_mock_nvr(version='2.11.0')
        nvr = ProtectNVR.from_uiprotect(mock_nvr)
        assert nvr.version == '2.11.0'

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test NVR with None name gets default."""
        mock_nvr = self._create_mock_nvr(name=None)
        nvr = ProtectNVR.from_uiprotect(mock_nvr)
        assert nvr.name == 'Unknown NVR'

    def test_from_uiprotect_state_always_connected(self) -> None:
        """Test NVR state is always CONNECTED."""
        mock_nvr = self._create_mock_nvr()
        nvr = ProtectNVR.from_uiprotect(mock_nvr)
        assert nvr.state == DeviceState.CONNECTED


class TestProtectSensor:
    """Tests for ProtectSensor model."""

    def _create_mock_sensor(self, **overrides: Any) -> MagicMock:
        """Create a mock sensor with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as a Sensor.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'sensor-001')
        mock.name = overrides.get('name', 'Front Door Sensor')
        mock.mac = overrides.get('mac', 'AA:BB:CC:11:22:33')
        mock.host = overrides.get('host', None)
        mock.firmware_version = overrides.get('firmware_version', '1.5.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=10))
        mock.last_seen = overrides.get('last_seen', now)

        # Sensor-specific attributes
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.is_motion_detected = overrides.get('is_motion_detected', False)
        mock.is_opened = overrides.get('is_opened', False)
        mock.motion_detected_at = overrides.get('motion_detected_at', now)
        mock.open_status_changed_at = overrides.get('open_status_changed_at', now)
        mock.tampering_detected_at = overrides.get('tampering_detected_at', None)
        mock.alarm_triggered_at = overrides.get('alarm_triggered_at', None)
        mock.leak_detected_at = overrides.get('leak_detected_at', None)
        mock.mount_type = overrides.get('mount_type', 'door')

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectSensor from mock uiprotect Sensor."""
        mock_sensor = self._create_mock_sensor()
        sensor = ProtectSensor.from_uiprotect(mock_sensor)

        assert sensor.id == 'sensor-001'
        assert sensor.name == 'Front Door Sensor'
        assert sensor.type == DeviceType.SENSOR
        assert sensor.mac == 'AA:BB:CC:11:22:33'

    def test_from_uiprotect_door_open(self) -> None:
        """Test door open detection."""
        mock_sensor = self._create_mock_sensor(is_opened=True)
        sensor = ProtectSensor.from_uiprotect(mock_sensor)
        assert sensor.is_opened is True

    def test_from_uiprotect_motion_detected(self) -> None:
        """Test motion detection."""
        mock_sensor = self._create_mock_sensor(is_motion_detected=True)
        sensor = ProtectSensor.from_uiprotect(mock_sensor)
        assert sensor.is_motion_detected is True

    def test_from_uiprotect_mount_type(self) -> None:
        """Test mount type extraction."""
        mock_sensor = self._create_mock_sensor(mount_type='window')
        sensor = ProtectSensor.from_uiprotect(mock_sensor)
        assert sensor.mount_type == 'window'

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test sensor with None name gets default."""
        mock_sensor = self._create_mock_sensor(name=None)
        sensor = ProtectSensor.from_uiprotect(mock_sensor)
        assert sensor.name == 'Unknown Sensor'


class TestProtectLight:
    """Tests for ProtectLight model."""

    def _create_mock_light(self, **overrides: Any) -> MagicMock:
        """Create a mock light with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as a Light.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'light-001')
        mock.name = overrides.get('name', 'Backyard Floodlight')
        mock.mac = overrides.get('mac', 'BB:CC:DD:EE:FF:00')
        mock.host = overrides.get('host', IPv4Address('192.168.1.50'))
        mock.firmware_version = overrides.get('firmware_version', '1.10.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=5))
        mock.last_seen = overrides.get('last_seen', now)

        # Light-specific attributes
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.is_light_on = overrides.get('is_light_on', False)
        mock.is_motion_detected = overrides.get('is_motion_detected', False)
        mock.is_pir_motion_detected = overrides.get('is_pir_motion_detected', False)
        mock.last_motion = overrides.get('last_motion', now)

        # Light device settings for LED level
        if 'light_device_settings' in overrides:
            mock.light_device_settings = overrides['light_device_settings']
        else:
            mock.light_device_settings = {'led_level': 50}

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectLight from mock uiprotect Light."""
        mock_light = self._create_mock_light()
        light = ProtectLight.from_uiprotect(mock_light)

        assert light.id == 'light-001'
        assert light.name == 'Backyard Floodlight'
        assert light.type == DeviceType.LIGHT
        assert light.mac == 'BB:CC:DD:EE:FF:00'
        assert light.host == '192.168.1.50'

    def test_from_uiprotect_light_on(self) -> None:
        """Test light on state."""
        mock_light = self._create_mock_light(is_light_on=True)
        light = ProtectLight.from_uiprotect(mock_light)
        assert light.is_light_on is True

    def test_from_uiprotect_light_level(self) -> None:
        """Test light level extraction."""
        mock_light = self._create_mock_light(light_device_settings={'led_level': 75})
        light = ProtectLight.from_uiprotect(mock_light)
        assert light.light_level == 75

    def test_from_uiprotect_motion_detected(self) -> None:
        """Test motion detection."""
        mock_light = self._create_mock_light(is_motion_detected=True)
        light = ProtectLight.from_uiprotect(mock_light)
        assert light.is_motion_detected is True

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test light with None name gets default."""
        mock_light = self._create_mock_light(name=None)
        light = ProtectLight.from_uiprotect(mock_light)
        assert light.name == 'Unknown Light'


class TestProtectChime:
    """Tests for ProtectChime model."""

    def _create_mock_chime(self, **overrides: Any) -> MagicMock:
        """Create a mock chime with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as a Chime.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'chime-001')
        mock.name = overrides.get('name', 'Living Room Chime')
        mock.mac = overrides.get('mac', 'CC:DD:EE:FF:00:11')
        mock.host = overrides.get('host', IPv4Address('192.168.1.60'))
        mock.firmware_version = overrides.get('firmware_version', '1.8.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=3))
        mock.last_seen = overrides.get('last_seen', now)

        # Chime-specific attributes
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.volume = overrides.get('volume', 80)
        mock.is_ringing = overrides.get('is_ringing', False)

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectChime from mock uiprotect Chime."""
        mock_chime = self._create_mock_chime()
        chime = ProtectChime.from_uiprotect(mock_chime)

        assert chime.id == 'chime-001'
        assert chime.name == 'Living Room Chime'
        assert chime.type == DeviceType.CHIME
        assert chime.mac == 'CC:DD:EE:FF:00:11'

    def test_from_uiprotect_volume(self) -> None:
        """Test volume extraction."""
        mock_chime = self._create_mock_chime(volume=50)
        chime = ProtectChime.from_uiprotect(mock_chime)
        assert chime.volume == 50

    def test_from_uiprotect_ringing(self) -> None:
        """Test ringing state."""
        mock_chime = self._create_mock_chime(is_ringing=True)
        chime = ProtectChime.from_uiprotect(mock_chime)
        assert chime.is_ringing is True

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test chime with None name gets default."""
        mock_chime = self._create_mock_chime(name=None)
        chime = ProtectChime.from_uiprotect(mock_chime)
        assert chime.name == 'Unknown Chime'


class TestProtectDoorlock:
    """Tests for ProtectDoorlock model."""

    def _create_mock_doorlock(self, **overrides: Any) -> MagicMock:
        """Create a mock doorlock with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as a Doorlock.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'lock-001')
        mock.name = overrides.get('name', 'Front Door Lock')
        mock.mac = overrides.get('mac', 'DD:EE:FF:00:11:22')
        mock.host = overrides.get('host', None)
        mock.firmware_version = overrides.get('firmware_version', '1.2.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=14))
        mock.last_seen = overrides.get('last_seen', now)

        # Doorlock-specific attributes
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.is_locked = overrides.get('is_locked', True)
        mock.lock_status = overrides.get('lock_status', 'CLOSED')
        mock.auto_close_time = overrides.get('auto_close_time', 30)

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectDoorlock from mock uiprotect Doorlock."""
        mock_doorlock = self._create_mock_doorlock()
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)

        assert doorlock.id == 'lock-001'
        assert doorlock.name == 'Front Door Lock'
        assert doorlock.type == DeviceType.DOORLOCK
        assert doorlock.mac == 'DD:EE:FF:00:11:22'

    def test_from_uiprotect_locked(self) -> None:
        """Test locked state."""
        mock_doorlock = self._create_mock_doorlock(is_locked=True)
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)
        assert doorlock.is_locked is True

    def test_from_uiprotect_unlocked(self) -> None:
        """Test unlocked state."""
        mock_doorlock = self._create_mock_doorlock(is_locked=False)
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)
        assert doorlock.is_locked is False

    def test_from_uiprotect_lock_status(self) -> None:
        """Test lock status extraction."""
        mock_doorlock = self._create_mock_doorlock(lock_status='OPEN')
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)
        assert doorlock.lock_status == 'OPEN'

    def test_from_uiprotect_auto_close_time(self) -> None:
        """Test auto close time extraction."""
        mock_doorlock = self._create_mock_doorlock(auto_close_time=60)
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)
        assert doorlock.auto_close_time == 60

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test doorlock with None name gets default."""
        mock_doorlock = self._create_mock_doorlock(name=None)
        doorlock = ProtectDoorlock.from_uiprotect(mock_doorlock)
        assert doorlock.name == 'Unknown Doorlock'


class TestProtectAIPort:
    """Tests for ProtectAIPort model."""

    def _create_mock_aiport(self, **overrides: Any) -> MagicMock:
        """Create a mock AI Port with default values.

        Args:
            **overrides: Values to override in the mock.

        Returns:
            MagicMock configured as an AiPort.
        """
        now = datetime.now(timezone.utc)
        mock = MagicMock()
        mock.id = overrides.get('id', 'aiport-001')
        mock.name = overrides.get('name', 'AI Port 1')
        mock.mac = overrides.get('mac', 'EE:FF:00:11:22:33')
        mock.host = overrides.get('host', IPv4Address('192.168.1.70'))
        mock.firmware_version = overrides.get('firmware_version', '1.3.0')
        mock.up_since = overrides.get('up_since', now)
        mock.uptime = overrides.get('uptime', timedelta(days=7))
        mock.last_seen = overrides.get('last_seen', now)

        # AI Port-specific attributes
        mock.state = overrides.get('state', None)
        mock.is_adopted = overrides.get('is_adopted', True)
        mock.is_updating = overrides.get('is_updating', False)
        mock.cameras = overrides.get('cameras', ['cam-1', 'cam-2'])

        # Smart detect settings
        if 'smart_detect_settings' in overrides:
            mock.smart_detect_settings = overrides['smart_detect_settings']
        else:
            smart_settings = MagicMock()
            smart_settings.object_types = ['person', 'vehicle']
            mock.smart_detect_settings = smart_settings

        return mock

    def test_from_uiprotect_basic(self) -> None:
        """Test creating ProtectAIPort from mock uiprotect AiPort."""
        mock_aiport = self._create_mock_aiport()
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)

        assert aiport.id == 'aiport-001'
        assert aiport.name == 'AI Port 1'
        assert aiport.type == DeviceType.AI_PORT
        assert aiport.mac == 'EE:FF:00:11:22:33'
        assert aiport.host == '192.168.1.70'

    def test_from_uiprotect_camera_count(self) -> None:
        """Test camera count extraction."""
        mock_aiport = self._create_mock_aiport(cameras=['cam-1', 'cam-2', 'cam-3'])
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.camera_count == 3

    def test_from_uiprotect_no_cameras(self) -> None:
        """Test AI Port with no cameras."""
        mock_aiport = self._create_mock_aiport(cameras=[])
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.camera_count == 0

    def test_from_uiprotect_smart_detect_person(self) -> None:
        """Test person detection enabled."""
        smart_settings = MagicMock()
        smart_settings.object_types = ['person']
        mock_aiport = self._create_mock_aiport(smart_detect_settings=smart_settings)
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.is_person_enabled is True
        assert aiport.is_vehicle_enabled is False

    def test_from_uiprotect_smart_detect_all(self) -> None:
        """Test all detection types enabled."""
        smart_settings = MagicMock()
        smart_settings.object_types = ['person', 'vehicle', 'package', 'animal']
        mock_aiport = self._create_mock_aiport(smart_detect_settings=smart_settings)
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.is_person_enabled is True
        assert aiport.is_vehicle_enabled is True
        assert aiport.is_package_enabled is True
        assert aiport.is_animal_enabled is True

    def test_from_uiprotect_no_smart_detect_settings(self) -> None:
        """Test AI Port without smart detect settings."""
        mock_aiport = self._create_mock_aiport(smart_detect_settings=None)
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.is_person_enabled is False
        assert aiport.is_vehicle_enabled is False

    def test_from_uiprotect_unknown_name(self) -> None:
        """Test AI Port with None name gets default."""
        mock_aiport = self._create_mock_aiport(name=None)
        aiport = ProtectAIPort.from_uiprotect(mock_aiport)
        assert aiport.name == 'Unknown AI Port'


class TestProtectDeviceTypeAlias:
    """Tests for the ProtectDevice type alias."""

    def test_camera_is_protect_device(self) -> None:
        """Test that ProtectCamera is a valid ProtectDevice."""
        # Note: Pydantic Field defaults make these params optional at runtime
        camera = ProtectCamera(  # type: ignore[call-arg]
            id='test',
            name='Test Camera',
            type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:FF',
        )
        # Type check - this is mainly for mypy/pyright validation
        device: ProtectDevice = camera
        assert device.type == DeviceType.CAMERA

    def test_nvr_is_protect_device(self) -> None:
        """Test that ProtectNVR is a valid ProtectDevice."""
        nvr = ProtectNVR(  # type: ignore[call-arg]
            id='test',
            name='Test NVR',
            type=DeviceType.NVR,
            mac='11:22:33:44:55:66',
        )
        device: ProtectDevice = nvr
        assert device.type == DeviceType.NVR

    def test_all_device_types_are_protect_device(self) -> None:
        """Test all device types can be assigned to ProtectDevice."""
        # Note: Pydantic Field defaults make extra params optional at runtime
        devices: list[ProtectDevice] = [
            ProtectCamera(id='1', name='Cam', type=DeviceType.CAMERA, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectNVR(id='2', name='NVR', type=DeviceType.NVR, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectSensor(id='3', name='Sensor', type=DeviceType.SENSOR, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectLight(id='4', name='Light', type=DeviceType.LIGHT, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectChime(id='5', name='Chime', type=DeviceType.CHIME, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectDoorlock(id='6', name='Lock', type=DeviceType.DOORLOCK, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
            ProtectAIPort(id='7', name='AI', type=DeviceType.AI_PORT, mac='AA:BB:CC:DD:EE:FF'),  # type: ignore[call-arg]
        ]
        assert len(devices) == 7


class TestBaseDeviceValidation:
    """Tests for BaseDevice Pydantic validation."""

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields raise validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProtectCamera(
                id='test',
                name='Test',
                type=DeviceType.CAMERA,
                mac='AA:BB:CC:DD:EE:FF',
                extra_field='not allowed',  # type: ignore[call-arg]
            )

    def test_required_fields(self) -> None:
        """Test that required fields must be provided."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProtectCamera(name='Test')  # type: ignore[call-arg]

    def test_default_values_applied(self) -> None:
        """Test that default values are applied correctly."""
        # Note: Pydantic Field defaults make extra params optional at runtime
        camera = ProtectCamera(  # type: ignore[call-arg]
            id='test',
            name='Test',
            type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:FF',
        )
        assert camera.host is None
        assert camera.state == DeviceState.UNKNOWN
        assert camera.firmware_version is None
        assert camera.is_adopted is False
        assert camera.is_recording is False
