"""Unit tests for UniFi Protect device repository.

This module tests the DeviceRepository and ProtectDeviceCache classes
used for caching and accessing device data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address
from unittest.mock import MagicMock

import pytest

from unifi_mapper.protect.models import (
    DeviceType,
    ProtectCamera,
    ProtectNVR,
    ProtectSensor,
)
from unifi_mapper.protect.repository import (
    DeviceRepository,
    ProtectDeviceCache,
)


class TestDeviceRepository:
    """Tests for the generic DeviceRepository class."""

    def _create_camera(self, camera_id: str = 'cam-1', name: str = 'Test Camera') -> ProtectCamera:
        """Create a test camera instance."""
        return ProtectCamera(  # type: ignore[call-arg]
            id=camera_id,
            name=name,
            type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:FF',
            is_recording=True,
        )

    def test_init_empty(self) -> None:
        """Test repository initializes empty."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        assert repo.device_type == DeviceType.CAMERA
        assert len(repo) == 0

    def test_add_device(self) -> None:
        """Test adding a device to the repository."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera()
        repo.add(camera)
        assert len(repo) == 1
        assert 'cam-1' in repo

    def test_get_device_by_id(self) -> None:
        """Test getting a device by ID."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera()
        repo.add(camera)

        result = repo.get('cam-1')
        assert result is not None
        assert result.name == 'Test Camera'

    def test_get_device_not_found(self) -> None:
        """Test getting a non-existent device returns None."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        result = repo.get('nonexistent')
        assert result is None

    def test_get_by_name(self) -> None:
        """Test getting a device by name (case-insensitive)."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera(name='Front Door Camera')
        repo.add(camera)

        # Exact match
        result = repo.get_by_name('Front Door Camera')
        assert result is not None
        assert result.id == 'cam-1'

        # Case-insensitive match
        result = repo.get_by_name('front door camera')
        assert result is not None
        assert result.id == 'cam-1'

    def test_get_by_name_not_found(self) -> None:
        """Test getting by name when not found."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        result = repo.get_by_name('Nonexistent')
        assert result is None

    def test_all(self) -> None:
        """Test getting all devices."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera1 = self._create_camera('cam-1', 'Camera 1')
        camera2 = self._create_camera('cam-2', 'Camera 2')
        repo.add(camera1)
        repo.add(camera2)

        all_cameras = repo.all()
        assert len(all_cameras) == 2
        assert any(c.id == 'cam-1' for c in all_cameras)
        assert any(c.id == 'cam-2' for c in all_cameras)

    def test_filter_single_attribute(self) -> None:
        """Test filtering by a single attribute."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)

        recording_cam = ProtectCamera(  # type: ignore[call-arg]
            id='cam-1', name='Recording', type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:01', is_recording=True
        )
        not_recording_cam = ProtectCamera(  # type: ignore[call-arg]
            id='cam-2', name='Not Recording', type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:02', is_recording=False
        )
        repo.add(recording_cam)
        repo.add(not_recording_cam)

        recording = repo.filter(is_recording=True)
        assert len(recording) == 1
        assert recording[0].id == 'cam-1'

    def test_filter_multiple_attributes(self) -> None:
        """Test filtering by multiple attributes."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)

        cam1 = ProtectCamera(  # type: ignore[call-arg]
            id='cam-1', name='Cam 1', type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:01', is_recording=True, is_motion_detected=True
        )
        cam2 = ProtectCamera(  # type: ignore[call-arg]
            id='cam-2', name='Cam 2', type=DeviceType.CAMERA,
            mac='AA:BB:CC:DD:EE:02', is_recording=True, is_motion_detected=False
        )
        repo.add(cam1)
        repo.add(cam2)

        results = repo.filter(is_recording=True, is_motion_detected=True)
        assert len(results) == 1
        assert results[0].id == 'cam-1'

    def test_filter_no_match(self) -> None:
        """Test filtering with no matches."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera()
        repo.add(camera)

        results = repo.filter(is_recording=False)
        assert len(results) == 0

    def test_remove_device(self) -> None:
        """Test removing a device."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera()
        repo.add(camera)

        result = repo.remove('cam-1')
        assert result is True
        assert len(repo) == 0
        assert 'cam-1' not in repo

    def test_remove_nonexistent(self) -> None:
        """Test removing a non-existent device returns False."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        result = repo.remove('nonexistent')
        assert result is False

    def test_clear(self) -> None:
        """Test clearing all devices."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        repo.add(self._create_camera('cam-1'))
        repo.add(self._create_camera('cam-2'))

        repo.clear()
        assert len(repo) == 0

    def test_iterate(self) -> None:
        """Test iterating over devices."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera1 = self._create_camera('cam-1')
        camera2 = self._create_camera('cam-2')
        repo.add(camera1)
        repo.add(camera2)

        ids = [cam.id for cam in repo]
        assert 'cam-1' in ids
        assert 'cam-2' in ids

    def test_contains(self) -> None:
        """Test checking if device exists."""
        repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        camera = self._create_camera()
        repo.add(camera)

        assert 'cam-1' in repo
        assert 'nonexistent' not in repo


class TestProtectDeviceCache:
    """Tests for the ProtectDeviceCache class."""

    def _create_mock_client(
        self,
        cameras: list[MagicMock] | None = None,
        sensors: list[MagicMock] | None = None,
        lights: list[MagicMock] | None = None,
        chimes: list[MagicMock] | None = None,
        doorlocks: list[MagicMock] | None = None,
        ai_ports: list[MagicMock] | None = None,
        nvr: MagicMock | None = None,
    ) -> MagicMock:
        """Create a mock UniFiProtectClient."""
        client = MagicMock()
        client.is_connected = True

        # Configure NVR
        if nvr is None:
            nvr = self._create_mock_nvr()
        client.nvr = nvr

        # Configure device collections as dicts
        cameras = cameras or []
        client.cameras = {cam.id: cam for cam in cameras}

        sensors = sensors or []
        client.sensors = {s.id: s for s in sensors}

        lights = lights or []
        client.lights = {lt.id: lt for lt in lights}

        chimes = chimes or []
        client.chimes = {ch.id: ch for ch in chimes}

        doorlocks = doorlocks or []
        client.doorlocks = {dl.id: dl for dl in doorlocks}

        ai_ports = ai_ports or []
        client.ai_ports = {ap.id: ap for ap in ai_ports}

        return client

    def _create_mock_nvr(self, nvr_id: str = 'nvr-001') -> MagicMock:
        """Create a mock NVR."""
        now = datetime.now(timezone.utc)
        nvr = MagicMock()
        nvr.id = nvr_id
        nvr.name = 'Test NVR'
        nvr.mac = '11:22:33:44:55:66'
        nvr.host = IPv4Address('192.168.1.1')
        nvr.firmware_version = '2.0.35'
        nvr.up_since = now
        nvr.uptime = timedelta(days=30)
        nvr.last_seen = now
        nvr.timezone = 'America/New_York'
        nvr.version = '2.10.0'
        nvr.hardware_platform = 'uck-g2-plus'
        nvr.is_station = False
        nvr.is_updating = False
        nvr.enable_automatic_backups = True
        return nvr

    def _create_mock_camera(self, camera_id: str = 'cam-001') -> MagicMock:
        """Create a mock camera."""
        now = datetime.now(timezone.utc)
        camera = MagicMock()
        camera.id = camera_id
        camera.name = 'Test Camera'
        camera.mac = 'AA:BB:CC:DD:EE:FF'
        camera.host = IPv4Address('192.168.1.100')
        camera.firmware_version = '1.20.0'
        camera.up_since = now
        camera.uptime = timedelta(days=7)
        camera.last_seen = now
        camera.last_motion = now
        camera.state = None
        camera.is_adopted = True
        camera.is_updating = False
        camera.is_recording = True
        camera.is_motion_detected = False
        camera.is_smart_detected = False
        camera.is_third_party_camera = False
        camera.is_paired_with_ai_port = False
        camera.last_smart_detect = None
        camera.has_recordings = True
        return camera

    def _create_mock_sensor(self, sensor_id: str = 'sensor-001') -> MagicMock:
        """Create a mock sensor."""
        now = datetime.now(timezone.utc)
        sensor = MagicMock()
        sensor.id = sensor_id
        sensor.name = 'Test Sensor'
        sensor.mac = 'BB:CC:DD:EE:FF:00'
        sensor.host = None
        sensor.firmware_version = '1.5.0'
        sensor.up_since = now
        sensor.uptime = timedelta(days=10)
        sensor.last_seen = now
        sensor.state = None
        sensor.is_adopted = True
        sensor.is_updating = False
        sensor.is_motion_detected = False
        sensor.is_opened = False
        sensor.motion_detected_at = now
        sensor.open_status_changed_at = now
        sensor.tampering_detected_at = None
        sensor.alarm_triggered_at = None
        sensor.leak_detected_at = None
        sensor.mount_type = 'door'
        return sensor

    def test_init_empty(self) -> None:
        """Test cache initializes empty."""
        cache = ProtectDeviceCache()
        assert cache.nvr is None
        assert len(cache.cameras) == 0
        assert len(cache.sensors) == 0
        assert len(cache.lights) == 0
        assert len(cache.chimes) == 0
        assert len(cache.doorlocks) == 0
        assert len(cache.ai_ports) == 0
        assert cache.total_device_count == 0

    @pytest.mark.asyncio
    async def test_refresh_client_not_connected(self) -> None:
        """Test refresh fails if client not connected."""
        cache = ProtectDeviceCache()
        client = MagicMock()
        client.is_connected = False

        with pytest.raises(ValueError, match='Client must be connected'):
            await cache.refresh(client)

    @pytest.mark.asyncio
    async def test_refresh_populates_nvr(self) -> None:
        """Test refresh populates NVR."""
        cache = ProtectDeviceCache()
        client = self._create_mock_client()

        await cache.refresh(client)

        assert cache.nvr is not None
        assert cache.nvr.name == 'Test NVR'

    @pytest.mark.asyncio
    async def test_refresh_populates_cameras(self) -> None:
        """Test refresh populates cameras."""
        cache = ProtectDeviceCache()
        mock_cam = self._create_mock_camera('cam-001')
        client = self._create_mock_client(cameras=[mock_cam])

        await cache.refresh(client)

        assert len(cache.cameras) == 1
        camera = cache.cameras.get('cam-001')
        assert camera is not None
        assert camera.name == 'Test Camera'

    @pytest.mark.asyncio
    async def test_refresh_populates_sensors(self) -> None:
        """Test refresh populates sensors."""
        cache = ProtectDeviceCache()
        mock_sensor = self._create_mock_sensor('sensor-001')
        client = self._create_mock_client(sensors=[mock_sensor])

        await cache.refresh(client)

        assert len(cache.sensors) == 1
        sensor = cache.sensors.get('sensor-001')
        assert sensor is not None
        assert sensor.name == 'Test Sensor'

    @pytest.mark.asyncio
    async def test_refresh_clears_existing_data(self) -> None:
        """Test refresh clears existing cached data."""
        cache = ProtectDeviceCache()

        # First refresh with some data
        mock_cam1 = self._create_mock_camera('cam-001')
        client1 = self._create_mock_client(cameras=[mock_cam1])
        await cache.refresh(client1)
        assert len(cache.cameras) == 1

        # Second refresh with different data
        mock_cam2 = self._create_mock_camera('cam-002')
        client2 = self._create_mock_client(cameras=[mock_cam2])
        await cache.refresh(client2)

        # Should only have new camera
        assert len(cache.cameras) == 1
        assert cache.cameras.get('cam-001') is None
        assert cache.cameras.get('cam-002') is not None

    def test_clear(self) -> None:
        """Test clearing the cache."""
        cache = ProtectDeviceCache()
        # Manually add some data
        cache._cameras.add(ProtectCamera(  # type: ignore[call-arg]
            id='cam-1', name='Test', type=DeviceType.CAMERA, mac='AA:BB:CC:DD:EE:FF'
        ))
        cache._nvr = ProtectNVR(  # type: ignore[call-arg]
            id='nvr-1', name='NVR', type=DeviceType.NVR, mac='11:22:33:44:55:66'
        )

        cache.clear()

        assert len(cache.cameras) == 0
        assert cache.nvr is None
        assert cache.total_device_count == 0

    @pytest.mark.asyncio
    async def test_get_all_devices(self) -> None:
        """Test getting all devices from cache."""
        cache = ProtectDeviceCache()
        mock_cam = self._create_mock_camera('cam-001')
        mock_sensor = self._create_mock_sensor('sensor-001')
        client = self._create_mock_client(cameras=[mock_cam], sensors=[mock_sensor])

        await cache.refresh(client)

        all_devices = cache.get_all_devices()
        # NVR + camera + sensor = 3
        assert len(all_devices) == 3
        device_ids = [d.id for d in all_devices]
        assert 'nvr-001' in device_ids
        assert 'cam-001' in device_ids
        assert 'sensor-001' in device_ids

    @pytest.mark.asyncio
    async def test_get_device_by_id(self) -> None:
        """Test getting device by ID from any repository."""
        cache = ProtectDeviceCache()
        mock_cam = self._create_mock_camera('cam-001')
        mock_sensor = self._create_mock_sensor('sensor-001')
        client = self._create_mock_client(cameras=[mock_cam], sensors=[mock_sensor])

        await cache.refresh(client)

        # Get NVR
        nvr = cache.get_device_by_id('nvr-001')
        assert nvr is not None
        assert nvr.type == DeviceType.NVR

        # Get camera
        camera = cache.get_device_by_id('cam-001')
        assert camera is not None
        assert camera.type == DeviceType.CAMERA

        # Get sensor
        sensor = cache.get_device_by_id('sensor-001')
        assert sensor is not None
        assert sensor.type == DeviceType.SENSOR

    def test_get_device_by_id_not_found(self) -> None:
        """Test getting non-existent device by ID."""
        cache = ProtectDeviceCache()
        result = cache.get_device_by_id('nonexistent')
        assert result is None

    @pytest.mark.asyncio
    async def test_get_device_by_mac(self) -> None:
        """Test getting device by MAC address."""
        cache = ProtectDeviceCache()
        mock_cam = self._create_mock_camera('cam-001')
        client = self._create_mock_client(cameras=[mock_cam])

        await cache.refresh(client)

        # Find by MAC (exact case)
        device = cache.get_device_by_mac('AA:BB:CC:DD:EE:FF')
        assert device is not None
        assert device.id == 'cam-001'

        # Find by MAC (different case)
        device = cache.get_device_by_mac('aa:bb:cc:dd:ee:ff')
        assert device is not None
        assert device.id == 'cam-001'

    @pytest.mark.asyncio
    async def test_get_device_by_mac_nvr(self) -> None:
        """Test getting NVR by MAC address."""
        cache = ProtectDeviceCache()
        client = self._create_mock_client()

        await cache.refresh(client)

        device = cache.get_device_by_mac('11:22:33:44:55:66')
        assert device is not None
        assert device.type == DeviceType.NVR

    def test_get_device_by_mac_not_found(self) -> None:
        """Test getting device by non-existent MAC."""
        cache = ProtectDeviceCache()
        result = cache.get_device_by_mac('FF:FF:FF:FF:FF:FF')
        assert result is None

    @pytest.mark.asyncio
    async def test_total_device_count(self) -> None:
        """Test total device count."""
        cache = ProtectDeviceCache()
        mock_cam1 = self._create_mock_camera('cam-001')
        mock_cam2 = self._create_mock_camera('cam-002')
        mock_sensor = self._create_mock_sensor('sensor-001')
        client = self._create_mock_client(
            cameras=[mock_cam1, mock_cam2],
            sensors=[mock_sensor],
        )

        await cache.refresh(client)

        # NVR + 2 cameras + 1 sensor = 4
        assert cache.total_device_count == 4

    @pytest.mark.asyncio
    async def test_repositories_are_typed(self) -> None:
        """Test that repositories return correctly typed devices."""
        cache = ProtectDeviceCache()
        mock_cam = self._create_mock_camera('cam-001')
        client = self._create_mock_client(cameras=[mock_cam])

        await cache.refresh(client)

        # Type check - cameras repository returns ProtectCamera
        camera = cache.cameras.get('cam-001')
        if camera is not None:
            # These should work without type errors
            assert camera.is_recording is True
            assert camera.type == DeviceType.CAMERA


class TestDeviceRepositoryTypeSafety:
    """Tests verifying type safety of DeviceRepository."""

    def test_filter_with_device_specific_attribute(self) -> None:
        """Test filtering works with device-specific attributes."""
        repo: DeviceRepository[ProtectSensor] = DeviceRepository(DeviceType.SENSOR)

        sensor1 = ProtectSensor(  # type: ignore[call-arg]
            id='s1', name='Door', type=DeviceType.SENSOR,
            mac='AA:BB:CC:DD:EE:01', is_opened=True
        )
        sensor2 = ProtectSensor(  # type: ignore[call-arg]
            id='s2', name='Window', type=DeviceType.SENSOR,
            mac='AA:BB:CC:DD:EE:02', is_opened=False
        )
        repo.add(sensor1)
        repo.add(sensor2)

        open_sensors = repo.filter(is_opened=True)
        assert len(open_sensors) == 1
        assert open_sensors[0].id == 's1'

    def test_device_type_property(self) -> None:
        """Test device_type property returns correct type."""
        camera_repo: DeviceRepository[ProtectCamera] = DeviceRepository(DeviceType.CAMERA)
        sensor_repo: DeviceRepository[ProtectSensor] = DeviceRepository(DeviceType.SENSOR)

        assert camera_repo.device_type == DeviceType.CAMERA
        assert sensor_repo.device_type == DeviceType.SENSOR
