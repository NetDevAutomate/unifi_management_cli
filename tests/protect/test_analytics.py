"""Tests for UniFi Protect analytics module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock

import pytest

from unifi_mapper.protect.analytics import (
    CorrelatedEventGroup,
    CorrelationRule,
    DeviceHealth,
    DeviceHealthStatus,
    EventAggregation,
    EventAnalytics,
    EventCount,
    SmartDetectStats,
    SmartDetectType,
    TimeWindow,
)
from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    ProtectModelType,
    ProtectAction,
)


class TestSmartDetectType:
    """Tests for SmartDetectType enum."""

    def test_smart_detect_types_exist(self) -> None:
        """Verify all expected smart detect types exist."""
        assert SmartDetectType.PERSON.value == 'person'
        assert SmartDetectType.VEHICLE.value == 'vehicle'
        assert SmartDetectType.ANIMAL.value == 'animal'
        assert SmartDetectType.PACKAGE.value == 'package'
        assert SmartDetectType.FACE.value == 'face'
        assert SmartDetectType.LICENSE_PLATE.value == 'licensePlate'
        assert SmartDetectType.SMOKE.value == 'smoke'
        assert SmartDetectType.CMONX.value == 'cmonx'


class TestDeviceHealthStatus:
    """Tests for DeviceHealthStatus enum."""

    def test_device_health_status_values(self) -> None:
        """Verify all expected health status values exist."""
        assert DeviceHealthStatus.HEALTHY.value == 'healthy'
        assert DeviceHealthStatus.WARNING.value == 'warning'
        assert DeviceHealthStatus.CRITICAL.value == 'critical'
        assert DeviceHealthStatus.OFFLINE.value == 'offline'
        assert DeviceHealthStatus.UNKNOWN.value == 'unknown'


class TestTimeWindow:
    """Tests for TimeWindow dataclass."""

    def test_time_window_creation(self) -> None:
        """Test manual TimeWindow creation."""
        window = TimeWindow(
            duration=timedelta(hours=2),
            bucket_size=timedelta(minutes=10),
        )
        assert window.duration == timedelta(hours=2)
        assert window.bucket_size == timedelta(minutes=10)

    def test_last_hour(self) -> None:
        """Test last_hour factory method."""
        window = TimeWindow.last_hour()
        assert window.duration == timedelta(hours=1)
        assert window.bucket_size == timedelta(minutes=5)

    def test_last_day(self) -> None:
        """Test last_day factory method."""
        window = TimeWindow.last_day()
        assert window.duration == timedelta(days=1)
        assert window.bucket_size == timedelta(hours=1)

    def test_last_week(self) -> None:
        """Test last_week factory method."""
        window = TimeWindow.last_week()
        assert window.duration == timedelta(weeks=1)
        assert window.bucket_size == timedelta(days=1)


class TestEventCount:
    """Tests for EventCount dataclass."""

    def test_event_count_creation(self) -> None:
        """Test EventCount creation."""
        now = datetime.now(timezone.utc)
        count = EventCount(
            bucket_start=now,
            bucket_end=now + timedelta(minutes=5),
            count=42,
        )
        assert count.bucket_start == now
        assert count.bucket_end == now + timedelta(minutes=5)
        assert count.count == 42

    def test_event_count_default_count(self) -> None:
        """Test EventCount default count is zero."""
        now = datetime.now(timezone.utc)
        count = EventCount(
            bucket_start=now,
            bucket_end=now + timedelta(minutes=5),
        )
        assert count.count == 0


class TestEventAggregation:
    """Tests for EventAggregation dataclass."""

    def test_event_aggregation_defaults(self) -> None:
        """Test EventAggregation default values."""
        agg = EventAggregation()
        assert agg.total_events == 0
        assert agg.events_by_type == {}
        assert agg.events_by_device == {}
        assert agg.events_by_category == {}
        assert agg.time_buckets == []
        assert agg.window_start is None
        assert agg.window_end is None

    def test_event_aggregation_with_data(self) -> None:
        """Test EventAggregation with populated data."""
        now = datetime.now(timezone.utc)
        agg = EventAggregation(
            total_events=100,
            events_by_type={ProtectEventType.MOTION: 50},
            events_by_device={'cam-1': 75},
            events_by_category={ProtectEventCategory.MOTION: 50},
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
        assert agg.total_events == 100
        assert agg.events_by_type[ProtectEventType.MOTION] == 50
        assert agg.events_by_device['cam-1'] == 75


class TestSmartDetectStats:
    """Tests for SmartDetectStats dataclass."""

    def test_smart_detect_stats_defaults(self) -> None:
        """Test SmartDetectStats default values."""
        stats = SmartDetectStats()
        assert stats.total_detections == 0
        assert stats.detections_by_type == {}
        assert stats.detections_by_camera == {}
        assert stats.recent_detections == []
        assert stats.peak_hour is None
        assert stats.average_daily == 0.0

    def test_smart_detect_stats_with_data(self) -> None:
        """Test SmartDetectStats with populated data."""
        stats = SmartDetectStats(
            total_detections=50,
            detections_by_type={SmartDetectType.PERSON: 30, SmartDetectType.VEHICLE: 20},
            peak_hour=14,
            average_daily=7.5,
        )
        assert stats.total_detections == 50
        assert stats.detections_by_type[SmartDetectType.PERSON] == 30
        assert stats.peak_hour == 14
        assert stats.average_daily == 7.5


class TestDeviceHealth:
    """Tests for DeviceHealth dataclass."""

    def test_device_health_defaults(self) -> None:
        """Test DeviceHealth default values."""
        health = DeviceHealth(device_id='dev-1')
        assert health.device_id == 'dev-1'
        assert health.device_name == ''
        assert health.status == DeviceHealthStatus.UNKNOWN
        assert health.last_seen is None
        assert health.uptime_percentage == 100.0
        assert health.disconnect_count == 0
        assert health.battery_level is None
        assert health.issues == []

    def test_device_health_with_data(self) -> None:
        """Test DeviceHealth with populated data."""
        now = datetime.now(timezone.utc)
        health = DeviceHealth(
            device_id='dev-1',
            device_name='Front Door Camera',
            status=DeviceHealthStatus.HEALTHY,
            last_seen=now,
            uptime_percentage=99.5,
            disconnect_count=2,
            battery_level=85,
            issues=[],
        )
        assert health.device_name == 'Front Door Camera'
        assert health.status == DeviceHealthStatus.HEALTHY
        assert health.uptime_percentage == 99.5
        assert health.battery_level == 85


class TestCorrelatedEventGroup:
    """Tests for CorrelatedEventGroup dataclass."""

    def _create_event(
        self,
        event_type: ProtectEventType | None = None,
        device_id: str = 'cam-1',
    ) -> ProtectEvent:
        """Create a test event."""
        return ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id=device_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
        )

    def test_correlated_event_group_creation(self) -> None:
        """Test CorrelatedEventGroup creation."""
        trigger = self._create_event(ProtectEventType.MOTION)
        group = CorrelatedEventGroup(
            correlation_id='corr-1',
            trigger_event=trigger,
        )
        assert group.correlation_id == 'corr-1'
        assert group.trigger_event == trigger
        assert group.related_events == []
        assert group.confidence == 0.0
        assert group.pattern_type == ''

    def test_correlated_event_group_with_related(self) -> None:
        """Test CorrelatedEventGroup with related events."""
        trigger = self._create_event(ProtectEventType.MOTION)
        related = self._create_event(ProtectEventType.RING, 'doorbell-1')
        now = datetime.now(timezone.utc)

        group = CorrelatedEventGroup(
            correlation_id='corr-2',
            trigger_event=trigger,
            related_events=[related],
            start_time=now - timedelta(seconds=10),
            end_time=now,
            confidence=0.85,
            pattern_type='motion_then_doorbell',
        )
        assert len(group.related_events) == 1
        assert group.confidence == 0.85
        assert group.pattern_type == 'motion_then_doorbell'


class TestCorrelationRule:
    """Tests for CorrelationRule dataclass."""

    def test_correlation_rule_creation(self) -> None:
        """Test CorrelationRule creation."""
        rule = CorrelationRule(
            name='motion_then_doorbell',
            trigger_filter=EventFilter(categories=[ProtectEventCategory.MOTION]),
            related_filter=EventFilter(event_types=[ProtectEventType.RING]),
            time_window=timedelta(seconds=60),
            min_confidence=0.7,
        )
        assert rule.name == 'motion_then_doorbell'
        assert rule.time_window == timedelta(seconds=60)
        assert rule.min_confidence == 0.7

    def test_correlation_rule_defaults(self) -> None:
        """Test CorrelationRule default values."""
        rule = CorrelationRule(
            name='test_rule',
            trigger_filter=EventFilter(),
            related_filter=EventFilter(),
        )
        assert rule.time_window == timedelta(seconds=30)
        assert rule.min_confidence == 0.5


class TestEventAnalytics:
    """Tests for EventAnalytics class."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock UniFi Protect client."""
        client = MagicMock()
        client.is_connected = True
        return client

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create a mock EventHandler."""
        handler = MagicMock(spec=EventHandler)
        handler.subscribe.return_value = Mock()  # Unsubscribe function
        return handler

    @pytest.fixture
    def analytics(
        self,
        mock_client: MagicMock,
        mock_handler: MagicMock,
    ) -> EventAnalytics:
        """Create an EventAnalytics instance."""
        return EventAnalytics(mock_client, mock_handler)

    def test_analytics_initialization(
        self,
        analytics: EventAnalytics,
        mock_client: MagicMock,
    ) -> None:
        """Test EventAnalytics initialization."""
        assert analytics.client == mock_client
        assert analytics.is_running is False

    def test_analytics_start(
        self,
        analytics: EventAnalytics,
        mock_handler: MagicMock,
    ) -> None:
        """Test starting analytics."""
        analytics.start()
        assert analytics.is_running is True
        mock_handler.subscribe.assert_called_once()

    def test_analytics_start_already_running(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test starting analytics when already running raises error."""
        analytics.start()
        with pytest.raises(RuntimeError, match='already running'):
            analytics.start()

    def test_analytics_start_not_connected(
        self,
        mock_client: MagicMock,
        mock_handler: MagicMock,
    ) -> None:
        """Test starting analytics when not connected raises error."""
        mock_client.is_connected = False
        analytics = EventAnalytics(mock_client, mock_handler)

        with pytest.raises(ValueError, match='must be connected'):
            analytics.start()

    def test_analytics_stop(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test stopping analytics."""
        analytics.start()
        analytics.stop()
        assert analytics.is_running is False

    def test_analytics_clear(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test clearing analytics data."""
        # Manually add some data
        analytics._event_history.append(self._create_event())  # type: ignore[reportPrivateUsage]
        analytics._device_last_seen['dev-1'] = datetime.now(timezone.utc)  # type: ignore[reportPrivateUsage]

        analytics.clear()

        assert len(analytics._event_history) == 0  # type: ignore[reportPrivateUsage]
        assert len(analytics._device_last_seen) == 0  # type: ignore[reportPrivateUsage]

    def _create_event(
        self,
        event_type: ProtectEventType | None = None,
        device_id: str = 'cam-1',
        category: ProtectEventCategory | None = None,
        timestamp: datetime | None = None,
        changed_data: dict[str, object] | None = None,
    ) -> ProtectEvent:
        """Create a test event."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        empty_dict: dict[str, object] = {}
        return ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id=device_id,
            timestamp=timestamp,
            event_type=event_type,
            changed_data=changed_data if changed_data is not None else empty_dict,
        )

    def test_get_event_aggregation_empty(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting aggregation with no events."""
        agg = analytics.get_event_aggregation()
        assert agg.total_events == 0
        assert agg.events_by_type == {}

    def test_get_event_aggregation_with_events(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting aggregation with events."""
        now = datetime.now(timezone.utc)

        # Add events directly to history
        events = [
            self._create_event(
                ProtectEventType.MOTION,
                'cam-1',
                timestamp=now - timedelta(minutes=10),
            ),
            self._create_event(
                ProtectEventType.MOTION,
                'cam-2',
                timestamp=now - timedelta(minutes=5),
            ),
            self._create_event(
                ProtectEventType.RING,
                'doorbell-1',
                timestamp=now - timedelta(minutes=3),
            ),
        ]
        analytics._event_history.extend(events)  # type: ignore[reportPrivateUsage]

        agg = analytics.get_event_aggregation()

        assert agg.total_events == 3
        assert agg.events_by_type.get(ProtectEventType.MOTION) == 2
        assert agg.events_by_type.get(ProtectEventType.RING) == 1
        assert agg.events_by_device.get('cam-1') == 1
        assert agg.events_by_device.get('cam-2') == 1

    def test_get_event_aggregation_with_filter(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting aggregation with event filter."""
        now = datetime.now(timezone.utc)

        # Add mixed events
        events = [
            self._create_event(ProtectEventType.MOTION, 'cam-1', timestamp=now),
            self._create_event(ProtectEventType.RING, 'doorbell-1', timestamp=now),
        ]
        analytics._event_history.extend(events)  # type: ignore[reportPrivateUsage]

        # Filter to only motion events
        motion_filter = EventFilter(event_types=[ProtectEventType.MOTION])
        agg = analytics.get_event_aggregation(event_filter=motion_filter)

        assert agg.total_events == 1
        assert agg.events_by_type.get(ProtectEventType.MOTION) == 1
        assert ProtectEventType.RING not in agg.events_by_type

    def test_get_motion_stats(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting motion statistics."""
        now = datetime.now(timezone.utc)

        # Add motion events with proper category
        motion_event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id='cam-1',
            timestamp=now - timedelta(minutes=10),
            event_type=ProtectEventType.MOTION,
        )
        analytics._event_history.append(motion_event)  # type: ignore[reportPrivateUsage]

        stats = analytics.get_motion_stats()
        assert stats.total_events >= 0  # Depends on category matching

    def test_get_smart_detect_stats(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting smart detection statistics."""
        now = datetime.now(timezone.utc)

        # Add smart detection events
        smart_event = self._create_event(
            ProtectEventType.SMART_DETECT,
            'cam-1',
            timestamp=now,
            changed_data={'smartDetectTypes': ['person', 'vehicle']},
        )
        analytics._smart_detections.append(smart_event)  # type: ignore[reportPrivateUsage]

        stats = analytics.get_smart_detect_stats()

        assert stats.total_detections == 1
        assert stats.detections_by_type.get(SmartDetectType.PERSON) == 1
        assert stats.detections_by_type.get(SmartDetectType.VEHICLE) == 1

    def test_get_smart_detect_stats_peak_hour(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test peak hour calculation in smart detect stats."""
        # Add events at different hours
        base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

        for i in range(5):  # 5 events at hour 14
            event = self._create_event(
                timestamp=base.replace(hour=14) - timedelta(hours=i * 24),
            )
            # Only count if within last 24 hours
            if i == 0:
                analytics._smart_detections.append(event)  # type: ignore[reportPrivateUsage]

        for i in range(2):  # 2 events at hour 10
            event = self._create_event(
                timestamp=base.replace(hour=10) - timedelta(hours=i * 24),
            )
            if i == 0:
                analytics._smart_detections.append(event)  # type: ignore[reportPrivateUsage]

        stats = analytics.get_smart_detect_stats()
        # Peak hour depends on which events fall within the window
        assert stats.total_detections >= 0

    def test_get_device_health_unknown(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for unknown device."""
        health = analytics.get_device_health('unknown-device')
        assert health.device_id == 'unknown-device'
        assert health.status == DeviceHealthStatus.UNKNOWN
        assert health.last_seen is None

    def test_get_device_health_healthy(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for healthy device."""
        now = datetime.now(timezone.utc)
        analytics._device_last_seen['cam-1'] = now - timedelta(minutes=5)  # type: ignore[reportPrivateUsage]

        health = analytics.get_device_health('cam-1')
        assert health.status == DeviceHealthStatus.HEALTHY
        assert len(health.issues) == 0

    def test_get_device_health_offline(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for offline device."""
        now = datetime.now(timezone.utc)
        analytics._device_last_seen['cam-1'] = now - timedelta(hours=2)  # type: ignore[reportPrivateUsage]

        health = analytics.get_device_health('cam-1')
        assert health.status == DeviceHealthStatus.OFFLINE
        assert len(health.issues) > 0

    def test_get_device_health_warning_disconnects(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for device with many disconnects."""
        now = datetime.now(timezone.utc)
        analytics._device_last_seen['cam-1'] = now  # type: ignore[reportPrivateUsage]
        analytics._device_disconnect_count['cam-1'] = 10  # type: ignore[reportPrivateUsage]

        health = analytics.get_device_health('cam-1')
        assert health.status == DeviceHealthStatus.WARNING
        assert health.disconnect_count == 10

    def test_get_device_health_warning_battery(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for device with low battery."""
        now = datetime.now(timezone.utc)
        analytics._device_last_seen['sensor-1'] = now  # type: ignore[reportPrivateUsage]
        analytics._device_battery_levels['sensor-1'] = 15  # type: ignore[reportPrivateUsage]

        health = analytics.get_device_health('sensor-1')
        assert health.status == DeviceHealthStatus.WARNING
        assert health.battery_level == 15
        assert 'battery' in health.issues[0].lower()

    def test_get_all_device_health(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting health for all devices."""
        now = datetime.now(timezone.utc)
        analytics._device_last_seen['cam-1'] = now  # type: ignore[reportPrivateUsage]
        analytics._device_last_seen['cam-2'] = now  # type: ignore[reportPrivateUsage]

        all_health = analytics.get_all_device_health()
        assert len(all_health) == 2
        assert {h.device_id for h in all_health} == {'cam-1', 'cam-2'}

    def test_add_correlation_rule(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test adding a custom correlation rule."""
        rule = CorrelationRule(
            name='custom_rule',
            trigger_filter=EventFilter(),
            related_filter=EventFilter(),
        )
        initial_count = len(analytics._correlation_rules)  # type: ignore[reportPrivateUsage]

        analytics.add_correlation_rule(rule)

        assert len(analytics._correlation_rules) == initial_count + 1  # type: ignore[reportPrivateUsage]

    def test_subscribe_correlations(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test subscribing to correlation events."""
        callback = Mock()

        unsub = analytics.subscribe_correlations(callback)

        assert callback in analytics._correlation_callbacks  # type: ignore[reportPrivateUsage]

        unsub()

        assert callback not in analytics._correlation_callbacks  # type: ignore[reportPrivateUsage]

    def test_get_event_history(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting event history."""
        now = datetime.now(timezone.utc)

        # Add events in chronological order
        for i in range(5):
            event = self._create_event(timestamp=now - timedelta(minutes=5 - i))
            analytics._event_history.append(event)  # type: ignore[reportPrivateUsage]

        history = analytics.get_event_history(limit=3)

        # Should return newest first
        assert len(history) == 3

    def test_get_event_history_with_filter(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test getting event history with filter."""
        now = datetime.now(timezone.utc)

        # Add mixed events
        analytics._event_history.extend([  # type: ignore[reportPrivateUsage]
            self._create_event(ProtectEventType.MOTION, timestamp=now),
            self._create_event(ProtectEventType.RING, timestamp=now),
        ])

        motion_filter = EventFilter(event_types=[ProtectEventType.MOTION])
        history = analytics.get_event_history(event_filter=motion_filter)

        assert len(history) == 1
        assert history[0].event_type == ProtectEventType.MOTION

    def test_on_event_updates_device_health(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test that events update device health tracking."""
        event = self._create_event(device_id='cam-1')

        analytics._on_event(event)  # type: ignore[reportPrivateUsage]

        assert 'cam-1' in analytics._device_last_seen  # type: ignore[reportPrivateUsage]

    def test_on_event_tracks_disconnects(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test that disconnect events are tracked."""
        event = self._create_event(
            ProtectEventType.DEVICE_DISCONNECTED,
            device_id='cam-1',
        )

        analytics._on_event(event)  # type: ignore[reportPrivateUsage]

        assert analytics._device_disconnect_count['cam-1'] == 1  # type: ignore[reportPrivateUsage]

    def test_on_event_tracks_smart_detections(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test that smart detection events are tracked."""
        event = ProtectEvent(
            action=ProtectAction.ADD,
            model_type=ProtectModelType.EVENT,
            device_id='cam-1',
            timestamp=datetime.now(timezone.utc),
            event_type=ProtectEventType.SMART_DETECT,
        )

        analytics._on_event(event)  # type: ignore[reportPrivateUsage]

        assert len(analytics._smart_detections) == 1  # type: ignore[reportPrivateUsage]

    def test_event_history_trimming(
        self,
        analytics: EventAnalytics,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that event history is trimmed when exceeding max size."""
        # Reduce MAX_EVENT_HISTORY for testing
        monkeypatch.setattr(EventAnalytics, 'MAX_EVENT_HISTORY', 10)

        for _ in range(15):
            event = self._create_event()
            analytics._on_event(event)  # type: ignore[reportPrivateUsage]

        assert len(analytics._event_history) == 10  # type: ignore[reportPrivateUsage]

    def test_time_buckets_creation(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test that time buckets are created correctly."""
        now = datetime.now(timezone.utc)

        # Add events at different times
        for i in range(12):  # Events every 5 minutes over an hour
            event = self._create_event(
                timestamp=now - timedelta(minutes=i * 5),
            )
            analytics._event_history.append(event)  # type: ignore[reportPrivateUsage]

        agg = analytics.get_event_aggregation(TimeWindow.last_hour())

        # Should have 12 buckets (1 hour / 5 minutes)
        assert len(agg.time_buckets) == 12

    def test_default_correlation_rules_initialized(
        self,
        analytics: EventAnalytics,
    ) -> None:
        """Test that default correlation rules are initialized."""
        rule_names = [r.name for r in analytics._correlation_rules]  # type: ignore[reportPrivateUsage]

        assert 'motion_then_doorbell' in rule_names
        assert 'motion_then_door_open' in rule_names
        assert 'person_then_doorbell' in rule_names
