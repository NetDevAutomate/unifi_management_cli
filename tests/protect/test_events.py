"""Unit tests for UniFi Protect WebSocket event handling.

This module tests the event types, filtering, and subscription management
for real-time WebSocket updates from UniFi Protect.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectAction,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    ProtectModelType,
)


class TestProtectEventCategory:
    """Tests for the ProtectEventCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that all expected categories are defined."""
        expected = [
            'MOTION',
            'SMART_DETECT',
            'DOORBELL',
            'SENSOR',
            'DOORLOCK',
            'DEVICE_STATE',
            'RECORDING',
            'SYSTEM',
            'ACCESS',
        ]
        for name in expected:
            assert hasattr(ProtectEventCategory, name)

    def test_category_values(self) -> None:
        """Test that categories have expected string values."""
        assert ProtectEventCategory.MOTION.value == 'motion'
        assert ProtectEventCategory.SMART_DETECT.value == 'smart_detect'
        assert ProtectEventCategory.DOORBELL.value == 'doorbell'


class TestProtectEventType:
    """Tests for the ProtectEventType enum."""

    def test_motion_events_exist(self) -> None:
        """Test that motion event types are defined."""
        assert ProtectEventType.MOTION.value == 'motion'
        assert ProtectEventType.MOTION_SENSOR.value == 'sensorMotion'
        assert ProtectEventType.MOTION_LIGHT.value == 'lightMotion'

    def test_smart_detect_events_exist(self) -> None:
        """Test that smart detection event types are defined."""
        assert ProtectEventType.SMART_DETECT.value == 'smartDetectZone'
        assert ProtectEventType.SMART_DETECT_LINE.value == 'smartDetectLine'
        assert ProtectEventType.SMART_AUDIO_DETECT.value == 'smartAudioDetect'

    def test_sensor_events_exist(self) -> None:
        """Test that sensor event types are defined."""
        assert ProtectEventType.SENSOR_OPENED.value == 'sensorOpened'
        assert ProtectEventType.SENSOR_CLOSED.value == 'sensorClosed'
        assert ProtectEventType.SENSOR_ALARM.value == 'sensorAlarm'

    def test_doorlock_events_exist(self) -> None:
        """Test that doorlock event types are defined."""
        assert ProtectEventType.DOORLOCK_OPEN.value == 'doorlockOpened'
        assert ProtectEventType.DOORLOCK_CLOSE.value == 'doorlockClosed'

    def test_from_uiprotect_known_type(self) -> None:
        """Test conversion from uiprotect EventType."""
        mock_event_type = MagicMock()
        mock_event_type.value = 'motion'

        result = ProtectEventType.from_uiprotect(mock_event_type)
        assert result == ProtectEventType.MOTION

    def test_from_uiprotect_unknown_type(self) -> None:
        """Test conversion from unknown uiprotect EventType."""
        mock_event_type = MagicMock()
        mock_event_type.value = 'unknown_event_type_xyz'

        result = ProtectEventType.from_uiprotect(mock_event_type)
        assert result is None

    def test_category_motion_events(self) -> None:
        """Test that motion events return MOTION category."""
        assert ProtectEventType.MOTION.category == ProtectEventCategory.MOTION
        assert ProtectEventType.MOTION_SENSOR.category == ProtectEventCategory.MOTION
        assert ProtectEventType.MOTION_LIGHT.category == ProtectEventCategory.MOTION

    def test_category_smart_detect_events(self) -> None:
        """Test that smart detect events return SMART_DETECT category."""
        assert ProtectEventType.SMART_DETECT.category == ProtectEventCategory.SMART_DETECT
        assert ProtectEventType.SMART_DETECT_LINE.category == ProtectEventCategory.SMART_DETECT
        assert ProtectEventType.SMART_AUDIO_DETECT.category == ProtectEventCategory.SMART_DETECT

    def test_category_doorbell_events(self) -> None:
        """Test that doorbell events return DOORBELL category."""
        assert ProtectEventType.RING.category == ProtectEventCategory.DOORBELL
        assert ProtectEventType.NFC_CARD_SCANNED.category == ProtectEventCategory.DOORBELL

    def test_category_sensor_events(self) -> None:
        """Test that sensor events return SENSOR category."""
        assert ProtectEventType.SENSOR_OPENED.category == ProtectEventCategory.SENSOR
        assert ProtectEventType.SENSOR_CLOSED.category == ProtectEventCategory.SENSOR
        assert ProtectEventType.SENSOR_ALARM.category == ProtectEventCategory.SENSOR

    def test_category_doorlock_events(self) -> None:
        """Test that doorlock events return DOORLOCK category."""
        assert ProtectEventType.DOORLOCK_OPEN.category == ProtectEventCategory.DOORLOCK
        assert ProtectEventType.DOORLOCK_CLOSE.category == ProtectEventCategory.DOORLOCK

    def test_category_device_state_events(self) -> None:
        """Test that device state events return DEVICE_STATE category."""
        assert ProtectEventType.DEVICE_CONNECTED.category == ProtectEventCategory.DEVICE_STATE
        assert ProtectEventType.CAMERA_DISCONNECTED.category == ProtectEventCategory.DEVICE_STATE

    def test_category_recording_events(self) -> None:
        """Test that recording events return RECORDING category."""
        assert ProtectEventType.RECORDING_MODE_CHANGED.category == ProtectEventCategory.RECORDING
        assert ProtectEventType.RECORDING_OFF.category == ProtectEventCategory.RECORDING

    def test_category_system_events(self) -> None:
        """Test that system events return SYSTEM category."""
        assert ProtectEventType.FIRMWARE_UPDATE.category == ProtectEventCategory.SYSTEM
        assert ProtectEventType.DEVICE_ADOPTED.category == ProtectEventCategory.SYSTEM


class TestProtectAction:
    """Tests for the ProtectAction enum."""

    def test_all_actions_exist(self) -> None:
        """Test that all expected actions are defined."""
        assert ProtectAction.ADD.value == 'add'
        assert ProtectAction.UPDATE.value == 'update'
        assert ProtectAction.REMOVE.value == 'remove'

    def test_from_uiprotect(self) -> None:
        """Test conversion from uiprotect WSAction."""
        mock_action = MagicMock()
        mock_action.value = 'update'

        result = ProtectAction.from_uiprotect(mock_action)
        assert result == ProtectAction.UPDATE


class TestProtectModelType:
    """Tests for the ProtectModelType enum."""

    def test_device_types_exist(self) -> None:
        """Test that device model types are defined."""
        assert ProtectModelType.CAMERA.value == 'camera'
        assert ProtectModelType.NVR.value == 'nvr'
        assert ProtectModelType.SENSOR.value == 'sensor'
        assert ProtectModelType.LIGHT.value == 'light'
        assert ProtectModelType.CHIME.value == 'chime'
        assert ProtectModelType.DOORLOCK.value == 'doorlock'
        assert ProtectModelType.AIPORT.value == 'aiport'

    def test_from_uiprotect_known_type(self) -> None:
        """Test conversion from known uiprotect ModelType."""
        mock_model_type = MagicMock()
        mock_model_type.value = 'camera'

        result = ProtectModelType.from_uiprotect(mock_model_type)
        assert result == ProtectModelType.CAMERA

    def test_from_uiprotect_unknown_type(self) -> None:
        """Test conversion from unknown uiprotect ModelType."""
        mock_model_type = MagicMock()
        mock_model_type.value = 'unknown_model_xyz'

        result = ProtectModelType.from_uiprotect(mock_model_type)
        assert result == ProtectModelType.UNKNOWN


class TestProtectEvent:
    """Tests for the ProtectEvent dataclass."""

    def _create_event(
        self,
        action: ProtectAction = ProtectAction.UPDATE,
        model_type: ProtectModelType = ProtectModelType.CAMERA,
        device_id: str = 'cam-123',
        event_type: ProtectEventType | None = None,
    ) -> ProtectEvent:
        """Create a test event."""
        return ProtectEvent(
            action=action,
            model_type=model_type,
            device_id=device_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            changed_data={'test': 'data'},
        )

    def test_create_event(self) -> None:
        """Test creating a basic event."""
        event = self._create_event()

        assert event.action == ProtectAction.UPDATE
        assert event.model_type == ProtectModelType.CAMERA
        assert event.device_id == 'cam-123'
        assert event.changed_data == {'test': 'data'}

    def test_event_with_event_type(self) -> None:
        """Test creating an event with event type."""
        event = self._create_event(event_type=ProtectEventType.MOTION)

        assert event.event_type == ProtectEventType.MOTION
        assert event.category == ProtectEventCategory.MOTION

    def test_event_category_without_event_type(self) -> None:
        """Test category property when no event type set."""
        event = self._create_event(event_type=None)

        assert event.event_type is None
        assert event.category is None

    def test_from_ws_message(self) -> None:
        """Test creating event from WebSocket message."""
        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='update')
        mock_msg.new_update_id = 'update-123'
        mock_msg.changed_data = {'state': 'active'}
        mock_msg.new_obj = MagicMock()
        mock_msg.new_obj.id = 'device-456'
        mock_msg.new_obj.model_type = MagicMock(value='camera')
        mock_msg.old_obj = None

        event = ProtectEvent.from_ws_message(mock_msg)

        assert event.action == ProtectAction.UPDATE
        assert event.device_id == 'device-456'
        assert event.model_type == ProtectModelType.CAMERA
        assert event.update_id == 'update-123'
        assert event.changed_data == {'state': 'active'}

    def test_from_ws_message_no_new_obj(self) -> None:
        """Test creating event when new_obj is None."""
        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='remove')
        mock_msg.new_update_id = 'update-789'
        mock_msg.changed_data = {}
        mock_msg.new_obj = None
        mock_msg.old_obj = None

        event = ProtectEvent.from_ws_message(mock_msg)

        assert event.action == ProtectAction.REMOVE
        assert event.device_id == ''
        assert event.model_type == ProtectModelType.UNKNOWN

    def test_from_ws_message_extracts_event_type(self) -> None:
        """Test that event type is extracted from changed_data."""
        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='add')
        mock_msg.new_update_id = 'update-001'
        mock_msg.changed_data = {'type': 'motion'}
        mock_msg.new_obj = MagicMock()
        mock_msg.new_obj.id = 'event-123'
        # No model_type attribute
        del mock_msg.new_obj.model_type
        mock_msg.old_obj = None

        event = ProtectEvent.from_ws_message(mock_msg)

        assert event.event_type == ProtectEventType.MOTION


class TestEventFilter:
    """Tests for the EventFilter dataclass."""

    def _create_event(
        self,
        action: ProtectAction = ProtectAction.UPDATE,
        model_type: ProtectModelType = ProtectModelType.CAMERA,
        device_id: str = 'cam-123',
        event_type: ProtectEventType | None = None,
    ) -> ProtectEvent:
        """Create a test event."""
        return ProtectEvent(
            action=action,
            model_type=model_type,
            device_id=device_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
        )

    def test_empty_filter_matches_everything(self) -> None:
        """Test that empty filter matches all events."""
        filter_obj = EventFilter()
        event = self._create_event()

        assert filter_obj.matches(event) is True

    def test_filter_by_event_type_matches(self) -> None:
        """Test filtering by event type - matching."""
        filter_obj = EventFilter(event_types=[ProtectEventType.MOTION])
        event = self._create_event(event_type=ProtectEventType.MOTION)

        assert filter_obj.matches(event) is True

    def test_filter_by_event_type_no_match(self) -> None:
        """Test filtering by event type - not matching."""
        filter_obj = EventFilter(event_types=[ProtectEventType.MOTION])
        event = self._create_event(event_type=ProtectEventType.RING)

        assert filter_obj.matches(event) is False

    def test_filter_by_event_type_none_event_type(self) -> None:
        """Test filtering by event type when event has no type."""
        filter_obj = EventFilter(event_types=[ProtectEventType.MOTION])
        event = self._create_event(event_type=None)

        assert filter_obj.matches(event) is False

    def test_filter_by_category_matches(self) -> None:
        """Test filtering by category - matching."""
        filter_obj = EventFilter(categories=[ProtectEventCategory.MOTION])
        event = self._create_event(event_type=ProtectEventType.MOTION)

        assert filter_obj.matches(event) is True

    def test_filter_by_category_no_match(self) -> None:
        """Test filtering by category - not matching."""
        filter_obj = EventFilter(categories=[ProtectEventCategory.DOORBELL])
        event = self._create_event(event_type=ProtectEventType.MOTION)

        assert filter_obj.matches(event) is False

    def test_filter_by_category_no_event_type(self) -> None:
        """Test filtering by category when event has no type."""
        filter_obj = EventFilter(categories=[ProtectEventCategory.MOTION])
        event = self._create_event(event_type=None)

        assert filter_obj.matches(event) is False

    def test_filter_by_model_type_matches(self) -> None:
        """Test filtering by model type - matching."""
        filter_obj = EventFilter(model_types=[ProtectModelType.CAMERA])
        event = self._create_event(model_type=ProtectModelType.CAMERA)

        assert filter_obj.matches(event) is True

    def test_filter_by_model_type_no_match(self) -> None:
        """Test filtering by model type - not matching."""
        filter_obj = EventFilter(model_types=[ProtectModelType.SENSOR])
        event = self._create_event(model_type=ProtectModelType.CAMERA)

        assert filter_obj.matches(event) is False

    def test_filter_by_device_id_matches(self) -> None:
        """Test filtering by device ID - matching."""
        filter_obj = EventFilter(device_ids=['cam-123'])
        event = self._create_event(device_id='cam-123')

        assert filter_obj.matches(event) is True

    def test_filter_by_device_id_no_match(self) -> None:
        """Test filtering by device ID - not matching."""
        filter_obj = EventFilter(device_ids=['cam-456'])
        event = self._create_event(device_id='cam-123')

        assert filter_obj.matches(event) is False

    def test_filter_by_action_matches(self) -> None:
        """Test filtering by action - matching."""
        filter_obj = EventFilter(actions=[ProtectAction.UPDATE])
        event = self._create_event(action=ProtectAction.UPDATE)

        assert filter_obj.matches(event) is True

    def test_filter_by_action_no_match(self) -> None:
        """Test filtering by action - not matching."""
        filter_obj = EventFilter(actions=[ProtectAction.ADD])
        event = self._create_event(action=ProtectAction.UPDATE)

        assert filter_obj.matches(event) is False

    def test_filter_multiple_criteria_all_match(self) -> None:
        """Test filtering with multiple criteria - all match."""
        filter_obj = EventFilter(
            event_types=[ProtectEventType.MOTION],
            model_types=[ProtectModelType.CAMERA],
            device_ids=['cam-123'],
        )
        event = self._create_event(
            event_type=ProtectEventType.MOTION,
            model_type=ProtectModelType.CAMERA,
            device_id='cam-123',
        )

        assert filter_obj.matches(event) is True

    def test_filter_multiple_criteria_one_no_match(self) -> None:
        """Test filtering with multiple criteria - one doesn't match."""
        filter_obj = EventFilter(
            event_types=[ProtectEventType.MOTION],
            model_types=[ProtectModelType.SENSOR],  # Won't match
        )
        event = self._create_event(
            event_type=ProtectEventType.MOTION,
            model_type=ProtectModelType.CAMERA,
        )

        assert filter_obj.matches(event) is False

    def test_filter_multiple_values_in_criteria(self) -> None:
        """Test filtering with multiple values in a criterion."""
        filter_obj = EventFilter(
            event_types=[ProtectEventType.MOTION, ProtectEventType.RING]
        )
        event = self._create_event(event_type=ProtectEventType.RING)

        assert filter_obj.matches(event) is True


class TestEventHandler:
    """Tests for the EventHandler class."""

    def _create_mock_client(self, connected: bool = True) -> MagicMock:
        """Create a mock UniFiProtectClient."""
        mock_client = MagicMock()
        mock_client.is_connected = connected
        mock_client.api = MagicMock() if connected else None
        return mock_client

    def test_init(self) -> None:
        """Test EventHandler initialization."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        assert handler.client is mock_client
        assert handler.subscription_count == 0

    def test_subscribe_adds_subscription(self) -> None:
        """Test that subscribe adds a subscription."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock()
        handler.subscribe(callback)

        assert handler.subscription_count == 1

    def test_subscribe_returns_unsubscribe_function(self) -> None:
        """Test that subscribe returns an unsubscribe function."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock()
        unsub = handler.subscribe(callback)

        assert callable(unsub)

    def test_unsubscribe_removes_subscription(self) -> None:
        """Test that unsubscribe removes the subscription."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock()
        unsub = handler.subscribe(callback)
        assert handler.subscription_count == 1

        unsub()
        assert handler.subscription_count == 0

    def test_subscribe_when_not_connected_raises_error(self) -> None:
        """Test that subscribing when not connected raises ValueError."""
        mock_client = self._create_mock_client(connected=False)
        handler = EventHandler(mock_client)

        callback = MagicMock()
        with pytest.raises(ValueError, match='Client must be connected'):
            handler.subscribe(callback)

    def test_subscribe_with_filter(self) -> None:
        """Test subscribing with a filter."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock()
        filter_obj = EventFilter(event_types=[ProtectEventType.MOTION])
        unsub = handler.subscribe(callback, filter_obj)

        assert handler.subscription_count == 1
        unsub()

    def test_multiple_subscriptions(self) -> None:
        """Test multiple concurrent subscriptions."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback1 = MagicMock()
        callback2 = MagicMock()

        unsub1 = handler.subscribe(callback1)
        unsub2 = handler.subscribe(callback2)

        assert handler.subscription_count == 2

        unsub1()
        assert handler.subscription_count == 1

        unsub2()
        assert handler.subscription_count == 0

    def test_clear_subscriptions(self) -> None:
        """Test clearing all subscriptions."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback1 = MagicMock()
        callback2 = MagicMock()
        handler.subscribe(callback1)
        handler.subscribe(callback2)

        assert handler.subscription_count == 2

        handler.clear_subscriptions()

        assert handler.subscription_count == 0

    def test_handle_ws_message_dispatches_to_callbacks(self) -> None:
        """Test that WebSocket messages are dispatched to callbacks."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock()
        handler.subscribe(callback, EventFilter())

        # Create a mock WebSocket message
        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='update')
        mock_msg.new_update_id = 'update-123'
        mock_msg.changed_data = {}
        mock_msg.new_obj = MagicMock()
        mock_msg.new_obj.id = 'device-123'
        del mock_msg.new_obj.model_type
        mock_msg.old_obj = None

        handler._handle_ws_message(mock_msg)  # type: ignore[reportPrivateUsage]

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, ProtectEvent)
        assert event.device_id == 'device-123'

    def test_handle_ws_message_filters_correctly(self) -> None:
        """Test that WebSocket messages are filtered correctly."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        # Subscribe to only SENSOR events
        callback = MagicMock()
        handler.subscribe(
            callback,
            EventFilter(model_types=[ProtectModelType.SENSOR]),
        )

        # Create a CAMERA message (should be filtered out)
        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='update')
        mock_msg.new_update_id = 'update-123'
        mock_msg.changed_data = {}
        mock_msg.new_obj = MagicMock()
        mock_msg.new_obj.id = 'camera-123'
        mock_msg.new_obj.model_type = MagicMock(value='camera')
        mock_msg.old_obj = None

        handler._handle_ws_message(mock_msg)  # type: ignore[reportPrivateUsage]

        callback.assert_not_called()

    def test_handle_ws_message_error_handling(self) -> None:
        """Test that errors in callbacks don't crash the handler."""
        mock_client = self._create_mock_client()
        handler = EventHandler(mock_client)

        callback = MagicMock(side_effect=RuntimeError('Callback error'))
        handler.subscribe(callback, EventFilter())

        mock_msg = MagicMock()
        mock_msg.action = MagicMock(value='update')
        mock_msg.new_update_id = 'update-123'
        mock_msg.changed_data = {}
        mock_msg.new_obj = MagicMock()
        mock_msg.new_obj.id = 'device-123'
        del mock_msg.new_obj.model_type
        mock_msg.old_obj = None

        # Should not raise an exception
        handler._handle_ws_message(mock_msg)  # type: ignore[reportPrivateUsage]

    def test_start_ws_subscription_api_not_initialized(self) -> None:
        """Test starting WS subscription when API is None."""
        mock_client = self._create_mock_client()
        mock_client.api = None
        handler = EventHandler(mock_client)

        # Should not raise, just log warning
        handler._start_ws_subscription()  # type: ignore[reportPrivateUsage]

    def test_stop_ws_subscription(self) -> None:
        """Test stopping the WebSocket subscription."""
        mock_client = self._create_mock_client()
        mock_unsubscribe = MagicMock()
        mock_client.api.subscribe_websocket.return_value = mock_unsubscribe

        handler = EventHandler(mock_client)

        callback = MagicMock()
        unsub = handler.subscribe(callback)

        # Verify WS subscription was started
        mock_client.api.subscribe_websocket.assert_called_once()

        # Unsubscribe the last callback
        unsub()

        # Verify WS unsubscribe was called
        mock_unsubscribe.assert_called_once()
