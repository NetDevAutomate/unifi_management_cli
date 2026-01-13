"""Tests for AI Port management module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from unifi_mapper.protect.aiport import (
    AICapability,
    AICapabilityType,
    AIDetectionEvent,
    AIPortInfo,
    AIPortManager,
    AIPortStatus,
    PairedCamera,
)
from unifi_mapper.protect.analytics import SmartDetectType
from unifi_mapper.protect.events import (
    EventHandler,
    ProtectAction,
    ProtectEvent,
    ProtectEventType,
    ProtectModelType,
)
from unifi_mapper.protect.models import DeviceState, DeviceType, ProtectAIPort


# =============================================================================
# Test Fixtures
# =============================================================================


def create_protect_aiport(
    aiport_id: str = 'aiport-001',
    name: str = 'AI Port 1',
    state: DeviceState = DeviceState.CONNECTED,
    camera_count: int = 0,
    is_person_enabled: bool = False,
    is_vehicle_enabled: bool = False,
    is_animal_enabled: bool = False,
    is_package_enabled: bool = False,
    is_updating: bool = False,
) -> ProtectAIPort:
    """Create a ProtectAIPort for testing."""
    return ProtectAIPort(
        id=aiport_id,
        name=name,
        type=DeviceType.AI_PORT,
        mac='00:11:22:33:44:55',
        host='192.168.1.100',
        state=state,
        firmware_version='1.0.0',
        is_adopted=True,
        is_updating=is_updating,
        up_since=datetime.now(timezone.utc) - timedelta(hours=1),
        uptime=timedelta(hours=1),
        last_seen=datetime.now(timezone.utc),
        camera_count=camera_count,
        is_person_enabled=is_person_enabled,
        is_vehicle_enabled=is_vehicle_enabled,
        is_animal_enabled=is_animal_enabled,
        is_package_enabled=is_package_enabled,
    )


def create_smart_detect_event(
    device_id: str = 'cam-001',
    smart_types: list[str] | None = None,
) -> ProtectEvent:
    """Create a smart detection event for testing."""
    changed_data: dict[str, object] = {}
    if smart_types:
        changed_data['smartDetectTypes'] = smart_types
    return ProtectEvent(
        action=ProtectAction.UPDATE,
        model_type=ProtectModelType.CAMERA,
        device_id=device_id,
        timestamp=datetime.now(timezone.utc),
        event_type=ProtectEventType.SMART_DETECT,
        changed_data=changed_data,
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock UniFiProtectClient."""
    client = MagicMock()
    client.is_connected = True
    client.ai_ports = {}
    client.cameras = {}
    return client


@pytest.fixture
def mock_aiport() -> MagicMock:
    """Create a mock raw AI Port from uiprotect."""
    aiport = MagicMock()
    aiport.id = 'aiport-001'
    aiport.name = 'AI Port 1'
    aiport.state = MagicMock(value='connected')
    aiport.is_updating = False
    aiport.is_connected = True
    aiport.paired_cameras = ['cam-001', 'cam-002']
    aiport.smart_detect_types = ['person', 'vehicle', 'animal']
    return aiport


@pytest.fixture
def mock_camera() -> MagicMock:
    """Create a mock camera for pairing tests."""
    camera = MagicMock()
    camera.id = 'cam-001'
    camera.name = 'Front Door'
    camera.smart_detect_settings = MagicMock()
    camera.smart_detect_zones = [MagicMock(), MagicMock()]
    camera.last_smart_detect = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return camera


@pytest.fixture
def protect_aiport() -> ProtectAIPort:
    """Create a ProtectAIPort model for testing."""
    return create_protect_aiport(
        camera_count=2,
        is_person_enabled=True,
        is_vehicle_enabled=True,
    )


@pytest.fixture
def event_handler(mock_client: MagicMock) -> EventHandler:
    """Create an EventHandler for testing."""
    return EventHandler(mock_client)


@pytest.fixture
def manager(mock_client: MagicMock) -> AIPortManager:
    """Create an AIPortManager for testing."""
    return AIPortManager(mock_client)


# =============================================================================
# AICapabilityType Tests
# =============================================================================


class TestAICapabilityType:
    """Tests for AICapabilityType enum."""

    def test_all_capability_types_exist(self) -> None:
        """Verify all expected capability types exist."""
        expected = ['person', 'vehicle', 'animal', 'package', 'face',
                    'licensePlate', 'smoke', 'cmonx']
        values = [t.value for t in AICapabilityType]
        for exp in expected:
            assert exp in values

    def test_capability_type_values(self) -> None:
        """Test specific capability type values."""
        assert AICapabilityType.PERSON.value == 'person'
        assert AICapabilityType.LICENSE_PLATE.value == 'licensePlate'
        assert AICapabilityType.CARBON_MONOXIDE.value == 'cmonx'


# =============================================================================
# AIPortStatus Tests
# =============================================================================


class TestAIPortStatus:
    """Tests for AIPortStatus enum."""

    def test_all_status_values_exist(self) -> None:
        """Verify all expected status values exist."""
        expected = ['online', 'offline', 'processing', 'idle', 'error', 'updating']
        values = [s.value for s in AIPortStatus]
        for exp in expected:
            assert exp in values


# =============================================================================
# AICapability Tests
# =============================================================================


class TestAICapability:
    """Tests for AICapability dataclass."""

    def test_default_values(self) -> None:
        """Test default capability values."""
        cap = AICapability(capability_type=AICapabilityType.PERSON)
        assert cap.enabled is False
        assert cap.available is True
        assert cap.confidence_threshold == 0.5
        assert cap.last_detection is None
        assert cap.detection_count == 0

    def test_name_property(self) -> None:
        """Test human-readable name property."""
        cap = AICapability(capability_type=AICapabilityType.PERSON)
        assert cap.name == 'Person Detection'

        cap2 = AICapability(capability_type=AICapabilityType.LICENSE_PLATE)
        assert cap2.name == 'License Plate Recognition'

    def test_enabled_capability(self) -> None:
        """Test creating an enabled capability."""
        cap = AICapability(
            capability_type=AICapabilityType.VEHICLE,
            enabled=True,
            confidence_threshold=0.8,
        )
        assert cap.enabled is True
        assert cap.confidence_threshold == 0.8


# =============================================================================
# PairedCamera Tests
# =============================================================================


class TestPairedCamera:
    """Tests for PairedCamera dataclass."""

    def test_default_values(self) -> None:
        """Test default paired camera values."""
        cam = PairedCamera(camera_id='cam-001')
        assert cam.camera_id == 'cam-001'
        assert cam.camera_name == ''
        assert cam.aiport_id == ''
        assert cam.smart_detect_enabled is False
        assert cam.detection_zones == 0
        assert cam.last_detection is None

    def test_full_values(self) -> None:
        """Test paired camera with all values."""
        now = datetime.now(timezone.utc)
        cam = PairedCamera(
            camera_id='cam-001',
            camera_name='Front Door',
            aiport_id='aiport-001',
            smart_detect_enabled=True,
            detection_zones=3,
            last_detection=now,
        )
        assert cam.camera_name == 'Front Door'
        assert cam.smart_detect_enabled is True
        assert cam.detection_zones == 3
        assert cam.last_detection == now


# =============================================================================
# AIPortInfo Tests
# =============================================================================


class TestAIPortInfo:
    """Tests for AIPortInfo dataclass."""

    def test_basic_info(self, protect_aiport: ProtectAIPort) -> None:
        """Test basic AIPortInfo creation."""
        info = AIPortInfo(aiport=protect_aiport)
        assert info.id == 'aiport-001'
        assert info.name == 'AI Port 1'
        assert info.status == AIPortStatus.IDLE
        assert info.camera_count == 0
        assert info.total_detections == 0

    def test_with_paired_cameras(self, protect_aiport: ProtectAIPort) -> None:
        """Test AIPortInfo with paired cameras."""
        cameras = [
            PairedCamera(camera_id='cam-001', camera_name='Front'),
            PairedCamera(camera_id='cam-002', camera_name='Back'),
        ]
        info = AIPortInfo(
            aiport=protect_aiport,
            paired_cameras=cameras,
        )
        assert info.camera_count == 2

    def test_enabled_capabilities(self, protect_aiport: ProtectAIPort) -> None:
        """Test filtering enabled capabilities."""
        caps = [
            AICapability(capability_type=AICapabilityType.PERSON, enabled=True),
            AICapability(capability_type=AICapabilityType.VEHICLE, enabled=False),
            AICapability(capability_type=AICapabilityType.ANIMAL, enabled=True),
        ]
        info = AIPortInfo(
            aiport=protect_aiport,
            capabilities=caps,
        )
        enabled = info.enabled_capabilities
        assert len(enabled) == 2
        assert all(c.enabled for c in enabled)


# =============================================================================
# AIDetectionEvent Tests
# =============================================================================


class TestAIDetectionEvent:
    """Tests for AIDetectionEvent dataclass."""

    def test_basic_detection(self) -> None:
        """Test basic detection event."""
        now = datetime.now(timezone.utc)
        event = AIDetectionEvent(
            aiport_id='aiport-001',
            camera_id='cam-001',
            detection_type=SmartDetectType.PERSON,
            timestamp=now,
        )
        assert event.aiport_id == 'aiport-001'
        assert event.camera_id == 'cam-001'
        assert event.detection_type == SmartDetectType.PERSON
        assert event.confidence == 0.0
        assert event.zone_id is None

    def test_detection_with_confidence(self) -> None:
        """Test detection event with confidence score."""
        now = datetime.now(timezone.utc)
        event = AIDetectionEvent(
            aiport_id='aiport-001',
            camera_id='cam-001',
            detection_type=SmartDetectType.VEHICLE,
            timestamp=now,
            confidence=0.95,
            zone_id='zone-1',
        )
        assert event.confidence == 0.95
        assert event.zone_id == 'zone-1'


# =============================================================================
# AIPortManager Tests
# =============================================================================


class TestAIPortManager:
    """Tests for AIPortManager class."""

    def test_init(self, mock_client: MagicMock) -> None:
        """Test manager initialization."""
        manager = AIPortManager(mock_client)
        assert manager.client is mock_client
        assert manager.event_handler is not None
        assert manager._is_subscribed is False  # type: ignore[reportPrivateUsage]

    def test_init_with_event_handler(
        self,
        mock_client: MagicMock,
        event_handler: EventHandler,
    ) -> None:
        """Test manager initialization with existing event handler."""
        manager = AIPortManager(mock_client, event_handler)
        assert manager.event_handler is event_handler

    def test_get_all_aiports_disconnected(self, mock_client: MagicMock) -> None:
        """Test get_all_aiports when client is disconnected."""
        mock_client.is_connected = False
        manager = AIPortManager(mock_client)
        assert manager.get_all_aiports() == []

    def test_get_all_aiports_connected(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test get_all_aiports with connected client."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        with patch.object(
            ProtectAIPort,
            'from_uiprotect',
            return_value=create_protect_aiport(),
        ):
            aiports = manager.get_all_aiports()
            assert len(aiports) == 1
            assert aiports[0].id == 'aiport-001'

    def test_get_aiport_not_found(self, manager: AIPortManager) -> None:
        """Test get_aiport when AI Port doesn't exist."""
        result = manager.get_aiport('nonexistent')
        assert result is None

    def test_get_aiport_disconnected(self, mock_client: MagicMock) -> None:
        """Test get_aiport when client is disconnected."""
        mock_client.is_connected = False
        manager = AIPortManager(mock_client)
        assert manager.get_aiport('aiport-001') is None

    def test_get_aiport_info_not_found(self, manager: AIPortManager) -> None:
        """Test get_aiport_info when AI Port doesn't exist."""
        result = manager.get_aiport_info('nonexistent')
        assert result is None

    def test_get_capabilities(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test get_capabilities for an AI Port."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        with patch.object(
            ProtectAIPort,
            'from_uiprotect',
            return_value=create_protect_aiport(
                is_person_enabled=True,
                is_vehicle_enabled=True,
            ),
        ):
            caps = manager.get_capabilities('aiport-001')
            assert len(caps) == 4
            person_cap = next(
                c for c in caps
                if c.capability_type == AICapabilityType.PERSON
            )
            assert person_cap.enabled is True

    def test_get_capabilities_not_found(self, manager: AIPortManager) -> None:
        """Test get_capabilities when AI Port doesn't exist."""
        assert manager.get_capabilities('nonexistent') == []


# =============================================================================
# Status Determination Tests
# =============================================================================


class TestStatusDetermination:
    """Tests for AI Port status determination."""

    def test_status_updating(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test status when AI Port is updating."""
        mock_aiport.is_updating = True
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        aiport = create_protect_aiport(is_updating=True)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.UPDATING

    def test_status_offline(self, manager: AIPortManager) -> None:
        """Test status when AI Port is disconnected."""
        aiport = create_protect_aiport(state=DeviceState.DISCONNECTED)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.OFFLINE

    def test_status_error(self, manager: AIPortManager) -> None:
        """Test status when AI Port has error state."""
        aiport = create_protect_aiport(state=DeviceState.CONNECTING)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.ERROR

    def test_status_idle(self, manager: AIPortManager) -> None:
        """Test status when AI Port is idle with no cameras."""
        aiport = create_protect_aiport(camera_count=0)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.IDLE

    def test_status_online(self, manager: AIPortManager) -> None:
        """Test status when AI Port is online with cameras."""
        aiport = create_protect_aiport(camera_count=3)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.ONLINE

    def test_status_processing(self, manager: AIPortManager) -> None:
        """Test status when AI Port has recent activity."""
        # Add recent detection
        manager._last_detections['aiport-001'] = datetime.now(timezone.utc)  # type: ignore[reportPrivateUsage]

        aiport = create_protect_aiport(camera_count=3)
        status = manager._determine_status(aiport)  # type: ignore[reportPrivateUsage]
        assert status == AIPortStatus.PROCESSING


# =============================================================================
# Detection Subscription Tests
# =============================================================================


class TestDetectionSubscription:
    """Tests for detection subscription functionality."""

    def test_subscribe_detections(self, manager: AIPortManager) -> None:
        """Test subscribing to detections."""
        callback = MagicMock()
        unsub = manager.subscribe_detections(callback)

        assert manager._is_subscribed is True  # type: ignore[reportPrivateUsage]
        assert len(manager._detection_callbacks) == 1  # type: ignore[reportPrivateUsage]

        unsub()
        assert len(manager._detection_callbacks) == 0  # type: ignore[reportPrivateUsage]

    def test_subscribe_with_filter(self, manager: AIPortManager) -> None:
        """Test subscribing with AI Port filter."""
        callback = MagicMock()
        unsub = manager.subscribe_detections(callback, aiport_id='aiport-001')

        callbacks = manager._detection_callbacks  # type: ignore[reportPrivateUsage]
        assert len(callbacks) == 1
        assert callbacks[0] == (callback, 'aiport-001')

        unsub()

    def test_multiple_subscriptions(self, manager: AIPortManager) -> None:
        """Test multiple subscriptions."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        unsub1 = manager.subscribe_detections(callback1)
        unsub2 = manager.subscribe_detections(callback2)

        assert len(manager._detection_callbacks) == 2  # type: ignore[reportPrivateUsage]

        unsub1()
        assert len(manager._detection_callbacks) == 1  # type: ignore[reportPrivateUsage]
        assert manager._is_subscribed is True  # type: ignore[reportPrivateUsage]

        unsub2()
        assert len(manager._detection_callbacks) == 0  # type: ignore[reportPrivateUsage]

    def test_dispatch_detection(self, manager: AIPortManager) -> None:
        """Test dispatching detection to callbacks."""
        callback = MagicMock()
        manager.subscribe_detections(callback)

        detection = AIDetectionEvent(
            aiport_id='aiport-001',
            camera_id='cam-001',
            detection_type=SmartDetectType.PERSON,
            timestamp=datetime.now(timezone.utc),
        )

        manager._dispatch_detection(detection)  # type: ignore[reportPrivateUsage]
        callback.assert_called_once_with(detection)

    def test_dispatch_with_filter(self, manager: AIPortManager) -> None:
        """Test dispatching respects AI Port filter."""
        callback = MagicMock()
        manager.subscribe_detections(callback, aiport_id='aiport-002')

        # Detection from different AI Port
        detection = AIDetectionEvent(
            aiport_id='aiport-001',
            camera_id='cam-001',
            detection_type=SmartDetectType.PERSON,
            timestamp=datetime.now(timezone.utc),
        )

        manager._dispatch_detection(detection)  # type: ignore[reportPrivateUsage]
        callback.assert_not_called()

    def test_dispatch_callback_error(self, manager: AIPortManager) -> None:
        """Test that callback errors don't break dispatch."""
        callback1 = MagicMock(side_effect=ValueError('test error'))
        callback2 = MagicMock()

        manager.subscribe_detections(callback1)
        manager.subscribe_detections(callback2)

        detection = AIDetectionEvent(
            aiport_id='aiport-001',
            camera_id='cam-001',
            detection_type=SmartDetectType.PERSON,
            timestamp=datetime.now(timezone.utc),
        )

        # Should not raise
        manager._dispatch_detection(detection)  # type: ignore[reportPrivateUsage]
        callback2.assert_called_once()


# =============================================================================
# Event Handling Tests
# =============================================================================


class TestEventHandling:
    """Tests for event handling functionality."""

    def test_extract_detection_types(self, manager: AIPortManager) -> None:
        """Test extracting detection types from event."""
        event = create_smart_detect_event(smart_types=['person', 'vehicle'])

        types = manager._extract_detection_types(event)  # type: ignore[reportPrivateUsage]
        assert len(types) == 2
        assert SmartDetectType.PERSON in types
        assert SmartDetectType.VEHICLE in types

    def test_extract_detection_types_empty(self, manager: AIPortManager) -> None:
        """Test extracting when no detection types present."""
        event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id='cam-001',
            timestamp=datetime.now(timezone.utc),
            event_type=ProtectEventType.MOTION,
            changed_data={},
        )

        types = manager._extract_detection_types(event)  # type: ignore[reportPrivateUsage]
        assert types == []

    def test_extract_detection_types_invalid(self, manager: AIPortManager) -> None:
        """Test extracting with invalid detection type."""
        event = create_smart_detect_event(smart_types=['person', 'invalid_type'])

        types = manager._extract_detection_types(event)  # type: ignore[reportPrivateUsage]
        assert len(types) == 1
        assert SmartDetectType.PERSON in types

    def test_find_aiport_for_camera(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test finding AI Port for a camera."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        result = manager._find_aiport_for_camera('cam-001')  # type: ignore[reportPrivateUsage]
        assert result == 'aiport-001'

    def test_find_aiport_for_camera_not_found(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test finding AI Port for unpaired camera."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        result = manager._find_aiport_for_camera('cam-999')  # type: ignore[reportPrivateUsage]
        assert result is None


# =============================================================================
# Detection Stats Tests
# =============================================================================


class TestDetectionStats:
    """Tests for detection statistics functionality."""

    def test_get_detection_stats_empty(self, manager: AIPortManager) -> None:
        """Test getting stats when no detections recorded."""
        stats = manager.get_detection_stats()
        assert stats['total_detections'] == 0
        assert stats['by_aiport'] == []

    def test_get_detection_stats_with_data(self, manager: AIPortManager) -> None:
        """Test getting stats with recorded detections."""
        now = datetime.now(timezone.utc)
        manager._detection_counts['aiport-001'] = 10  # type: ignore[reportPrivateUsage]
        manager._last_detections['aiport-001'] = now  # type: ignore[reportPrivateUsage]

        stats = manager.get_detection_stats()
        assert stats['total_detections'] == 10
        assert len(stats['by_aiport']) == 1
        assert stats['by_aiport'][0]['aiport_id'] == 'aiport-001'
        assert stats['by_aiport'][0]['detections'] == 10

    def test_get_detection_stats_specific_aiport(
        self,
        manager: AIPortManager,
    ) -> None:
        """Test getting stats for specific AI Port."""
        now = datetime.now(timezone.utc)
        manager._detection_counts['aiport-001'] = 5  # type: ignore[reportPrivateUsage]
        manager._last_detections['aiport-001'] = now  # type: ignore[reportPrivateUsage]

        stats = manager.get_detection_stats(aiport_id='aiport-001')
        assert stats['aiport_id'] == 'aiport-001'
        assert stats['total_detections'] == 5

    def test_get_detection_stats_aiport_not_found(
        self,
        manager: AIPortManager,
    ) -> None:
        """Test getting stats for nonexistent AI Port."""
        stats = manager.get_detection_stats(aiport_id='nonexistent')
        assert stats['total_detections'] == 0
        assert stats['last_detection'] is None

    def test_clear_stats(self, manager: AIPortManager) -> None:
        """Test clearing detection stats."""
        manager._detection_counts['aiport-001'] = 10  # type: ignore[reportPrivateUsage]
        manager._last_detections['aiport-001'] = datetime.now(timezone.utc)  # type: ignore[reportPrivateUsage]
        manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
            AIDetectionEvent(
                aiport_id='aiport-001',
                camera_id='cam-001',
                detection_type=SmartDetectType.PERSON,
                timestamp=datetime.now(timezone.utc),
            )
        )

        manager.clear_stats()

        assert len(manager._detection_counts) == 0  # type: ignore[reportPrivateUsage]
        assert len(manager._last_detections) == 0  # type: ignore[reportPrivateUsage]
        assert len(manager._recent_detections) == 0  # type: ignore[reportPrivateUsage]


# =============================================================================
# Recent Detections Tests
# =============================================================================


class TestRecentDetections:
    """Tests for recent detection retrieval."""

    def test_get_recent_detections_empty(self, manager: AIPortManager) -> None:
        """Test getting recent detections when none exist."""
        result = manager.get_recent_detections()
        assert result == []

    def test_get_recent_detections(self, manager: AIPortManager) -> None:
        """Test getting recent detections."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
                AIDetectionEvent(
                    aiport_id='aiport-001',
                    camera_id=f'cam-{i:03d}',
                    detection_type=SmartDetectType.PERSON,
                    timestamp=now + timedelta(seconds=i),
                )
            )

        result = manager.get_recent_detections()
        assert len(result) == 5
        # Should be newest first
        assert result[0].camera_id == 'cam-004'

    def test_get_recent_detections_with_limit(
        self,
        manager: AIPortManager,
    ) -> None:
        """Test getting recent detections with limit."""
        now = datetime.now(timezone.utc)
        for i in range(10):
            manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
                AIDetectionEvent(
                    aiport_id='aiport-001',
                    camera_id=f'cam-{i:03d}',
                    detection_type=SmartDetectType.PERSON,
                    timestamp=now + timedelta(seconds=i),
                )
            )

        result = manager.get_recent_detections(limit=3)
        assert len(result) == 3

    def test_get_recent_detections_filtered(
        self,
        manager: AIPortManager,
    ) -> None:
        """Test getting recent detections filtered by AI Port."""
        now = datetime.now(timezone.utc)
        manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
            AIDetectionEvent(
                aiport_id='aiport-001',
                camera_id='cam-001',
                detection_type=SmartDetectType.PERSON,
                timestamp=now,
            )
        )
        manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
            AIDetectionEvent(
                aiport_id='aiport-002',
                camera_id='cam-002',
                detection_type=SmartDetectType.VEHICLE,
                timestamp=now,
            )
        )

        result = manager.get_recent_detections(aiport_id='aiport-001')
        assert len(result) == 1
        assert result[0].aiport_id == 'aiport-001'


# =============================================================================
# Paired Camera Tests
# =============================================================================


class TestPairedCameras:
    """Tests for paired camera functionality."""

    def test_get_cameras_by_aiport_not_found(
        self,
        manager: AIPortManager,
    ) -> None:
        """Test getting cameras for nonexistent AI Port."""
        result = manager.get_cameras_by_aiport('nonexistent')
        assert result == []

    def test_get_paired_cameras_empty(self, manager: AIPortManager) -> None:
        """Test getting paired cameras when raw AI Port is None."""
        aiport = create_protect_aiport()
        result = manager._get_paired_cameras(aiport, None)  # type: ignore[reportPrivateUsage]
        assert result == []

    def test_get_paired_cameras_with_data(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
        mock_camera: MagicMock,
    ) -> None:
        """Test getting paired cameras with data."""
        mock_client.cameras = {'cam-001': mock_camera}
        manager = AIPortManager(mock_client)

        aiport = create_protect_aiport()

        result = manager._get_paired_cameras(aiport, mock_aiport)  # type: ignore[reportPrivateUsage]
        assert len(result) == 1
        assert result[0].camera_id == 'cam-001'
        assert result[0].camera_name == 'Front Door'
        assert result[0].smart_detect_enabled is True
        assert result[0].detection_zones == 2


# =============================================================================
# AIPortInfo Building Tests
# =============================================================================


class TestBuildAIPortInfo:
    """Tests for building AIPortInfo."""

    def test_build_aiport_info(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test building complete AIPortInfo."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        aiport = create_protect_aiport(
            camera_count=2,
            is_person_enabled=True,
            is_vehicle_enabled=True,
        )

        info = manager._build_aiport_info(aiport)  # type: ignore[reportPrivateUsage]
        assert info.id == 'aiport-001'
        assert info.name == 'AI Port 1'
        assert len(info.capabilities) == 4
        assert info.total_detections == 0

    def test_build_aiport_info_with_stats(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test building AIPortInfo with detection stats."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        now = datetime.now(timezone.utc)
        manager._detection_counts['aiport-001'] = 25  # type: ignore[reportPrivateUsage]
        manager._last_detections['aiport-001'] = now  # type: ignore[reportPrivateUsage]

        aiport = create_protect_aiport()

        info = manager._build_aiport_info(aiport)  # type: ignore[reportPrivateUsage]
        assert info.total_detections == 25
        assert info.last_activity == now


# =============================================================================
# Full Event Processing Tests
# =============================================================================


class TestOnEvent:
    """Tests for full event processing."""

    def test_on_event_no_aiport(self, manager: AIPortManager) -> None:
        """Test event from camera not paired with AI Port."""
        callback = MagicMock()
        manager.subscribe_detections(callback)

        event = create_smart_detect_event(device_id='cam-999', smart_types=['person'])

        manager._on_event(event)  # type: ignore[reportPrivateUsage]
        callback.assert_not_called()

    def test_on_event_no_detection_types(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test event without detection types."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        callback = MagicMock()
        manager.subscribe_detections(callback)

        event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id='cam-001',
            timestamp=datetime.now(timezone.utc),
            event_type=ProtectEventType.MOTION,
            changed_data={},
        )

        manager._on_event(event)  # type: ignore[reportPrivateUsage]
        callback.assert_not_called()

    def test_on_event_full_flow(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test full event processing flow."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        callback = MagicMock()
        manager.subscribe_detections(callback)

        now = datetime.now(timezone.utc)
        event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id='cam-001',
            timestamp=now,
            event_type=ProtectEventType.SMART_DETECT,
            changed_data={'smartDetectTypes': ['person', 'vehicle']},
        )

        manager._on_event(event)  # type: ignore[reportPrivateUsage]

        # Should be called twice (once for each detection type)
        assert callback.call_count == 2

        # Stats should be updated
        assert manager._detection_counts['aiport-001'] == 2  # type: ignore[reportPrivateUsage]
        assert manager._last_detections['aiport-001'] == now  # type: ignore[reportPrivateUsage]
        assert len(manager._recent_detections) == 2  # type: ignore[reportPrivateUsage]


# =============================================================================
# Detection History Limit Tests
# =============================================================================


class TestDetectionHistoryLimit:
    """Tests for detection history limiting."""

    def test_recent_detections_limit(
        self,
        mock_client: MagicMock,
        mock_aiport: MagicMock,
    ) -> None:
        """Test that recent detections are limited to 100."""
        mock_client.ai_ports = {'aiport-001': mock_aiport}
        manager = AIPortManager(mock_client)

        # Pre-fill with 95 detections
        now = datetime.now(timezone.utc)
        for _ in range(95):
            manager._recent_detections.append(  # type: ignore[reportPrivateUsage]
                AIDetectionEvent(
                    aiport_id='aiport-001',
                    camera_id='cam-001',
                    detection_type=SmartDetectType.PERSON,
                    timestamp=now,
                )
            )

        # Process event that adds 10 more
        for _ in range(10):
            event = create_smart_detect_event(smart_types=['person'])
            manager._on_event(event)  # type: ignore[reportPrivateUsage]

        # Should be capped at 100
        assert len(manager._recent_detections) == 100  # type: ignore[reportPrivateUsage]
