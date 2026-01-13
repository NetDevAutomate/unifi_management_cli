"""Event analytics and correlation for UniFi Protect.

This module provides analytics capabilities built on top of the WebSocket
event handling infrastructure. It includes event aggregation, pattern
correlation, smart detection statistics, and device health monitoring.

Example:
    >>> from unifi_mapper.protect import UniFiProtectClient
    >>> from unifi_mapper.protect.analytics import EventAnalytics
    >>>
    >>> async with UniFiProtectClient(config) as client:
    ...     analytics = EventAnalytics(client)
    ...     analytics.start()
    ...     # ... let events accumulate ...
    ...     stats = analytics.get_motion_stats()
    ...     print(f"Motion events last hour: {stats.total_events}")
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger  # type: ignore[import-untyped]

from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    ProtectModelType,
    UnsubscribeFunc,
)


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


class SmartDetectType(str, Enum):
    """Types of smart detections supported by UniFi Protect."""

    PERSON = 'person'
    VEHICLE = 'vehicle'
    ANIMAL = 'animal'
    PACKAGE = 'package'
    FACE = 'face'
    LICENSE_PLATE = 'licensePlate'
    SMOKE = 'smoke'
    CMONX = 'cmonx'  # Carbon monoxide


class DeviceHealthStatus(str, Enum):
    """Health status for monitored devices."""

    HEALTHY = 'healthy'
    WARNING = 'warning'
    CRITICAL = 'critical'
    OFFLINE = 'offline'
    UNKNOWN = 'unknown'


@dataclass
class TimeWindow:
    """Configuration for time-based analytics windows.

    Attributes:
        duration: Length of the time window.
        bucket_size: Size of each bucket for aggregation.
    """

    duration: timedelta
    bucket_size: timedelta

    @classmethod
    def last_hour(cls) -> TimeWindow:
        """Create a window for the last hour with 5-minute buckets."""
        return cls(duration=timedelta(hours=1), bucket_size=timedelta(minutes=5))

    @classmethod
    def last_day(cls) -> TimeWindow:
        """Create a window for the last 24 hours with 1-hour buckets."""
        return cls(duration=timedelta(days=1), bucket_size=timedelta(hours=1))

    @classmethod
    def last_week(cls) -> TimeWindow:
        """Create a window for the last 7 days with 1-day buckets."""
        return cls(duration=timedelta(weeks=1), bucket_size=timedelta(days=1))


@dataclass
class EventCount:
    """Count of events within a time bucket.

    Attributes:
        bucket_start: Start time of this bucket.
        bucket_end: End time of this bucket.
        count: Number of events in this bucket.
    """

    bucket_start: datetime
    bucket_end: datetime
    count: int = 0


@dataclass
class EventAggregation:
    """Aggregated event statistics.

    Attributes:
        total_events: Total number of events.
        events_by_type: Count broken down by event type.
        events_by_device: Count broken down by device ID.
        events_by_category: Count broken down by category.
        time_buckets: Events distributed across time buckets.
        window_start: Start of the aggregation window.
        window_end: End of the aggregation window.
    """

    total_events: int = 0
    events_by_type: dict[ProtectEventType, int] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    events_by_device: dict[str, int] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    events_by_category: dict[ProtectEventCategory, int] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    time_buckets: list[EventCount] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    window_start: datetime | None = None
    window_end: datetime | None = None


@dataclass
class SmartDetectStats:
    """Statistics for smart detection events.

    Attributes:
        total_detections: Total number of smart detections.
        detections_by_type: Count by detection type (person, vehicle, etc.).
        detections_by_camera: Count by camera device ID.
        recent_detections: List of recent detection events (max 100).
        peak_hour: Hour of day with most detections (0-23).
        average_daily: Average detections per day.
    """

    total_detections: int = 0
    detections_by_type: dict[SmartDetectType, int] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    detections_by_camera: dict[str, int] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    recent_detections: list[ProtectEvent] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    peak_hour: int | None = None
    average_daily: float = 0.0


@dataclass
class DeviceHealth:
    """Health information for a single device.

    Attributes:
        device_id: The device identifier.
        device_name: Human-readable device name.
        status: Current health status.
        last_seen: Last time the device was seen active.
        uptime_percentage: Percentage of time online (0-100).
        disconnect_count: Number of disconnections in window.
        battery_level: Battery percentage, if applicable.
        issues: List of current issues or warnings.
    """

    device_id: str
    device_name: str = ''
    status: DeviceHealthStatus = DeviceHealthStatus.UNKNOWN
    last_seen: datetime | None = None
    uptime_percentage: float = 100.0
    disconnect_count: int = 0
    battery_level: int | None = None
    issues: list[str] = field(default_factory=lambda: [])  # type: ignore[arg-type]


@dataclass
class CorrelatedEventGroup:
    """A group of correlated events.

    Events are considered correlated if they occur within
    a short time window and may be causally related.

    Attributes:
        correlation_id: Unique identifier for this group.
        trigger_event: The initial event that started the correlation.
        related_events: Events that correlate with the trigger.
        start_time: When the correlation window started.
        end_time: When the correlation window ended.
        confidence: Confidence score (0.0 to 1.0).
        pattern_type: Identified pattern type, if any.
    """

    correlation_id: str
    trigger_event: ProtectEvent
    related_events: list[ProtectEvent] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    start_time: datetime | None = None
    end_time: datetime | None = None
    confidence: float = 0.0
    pattern_type: str = ''


@dataclass
class CorrelationRule:
    """Rule for correlating related events.

    Attributes:
        name: Human-readable rule name.
        trigger_filter: Filter for trigger events.
        related_filter: Filter for related events.
        time_window: Maximum time between trigger and related events.
        min_confidence: Minimum confidence threshold.
    """

    name: str
    trigger_filter: EventFilter
    related_filter: EventFilter
    time_window: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    min_confidence: float = 0.5


# Type alias for correlation callbacks
CorrelationCallback = Callable[[CorrelatedEventGroup], Any]


class EventAnalytics:
    """Analytics engine for UniFi Protect events.

    Provides real-time event aggregation, smart detection statistics,
    device health monitoring, and event correlation.

    The analytics engine subscribes to all events and maintains
    rolling statistics that can be queried at any time.

    Attributes:
        client: The connected UniFiProtectClient instance.
        event_handler: The underlying event handler.

    Example:
        >>> analytics = EventAnalytics(client)
        >>> analytics.start()
        >>>
        >>> # Get motion statistics
        >>> motion_stats = analytics.get_motion_stats(TimeWindow.last_hour())
        >>> print(f"Motion events: {motion_stats.total_events}")
        >>>
        >>> # Get smart detection stats
        >>> smart_stats = analytics.get_smart_detect_stats()
        >>> print(f"People detected: {smart_stats.detections_by_type.get(SmartDetectType.PERSON, 0)}")
        >>>
        >>> analytics.stop()
    """

    # Maximum events to store in memory
    MAX_EVENT_HISTORY = 10000
    MAX_RECENT_DETECTIONS = 100

    def __init__(
        self,
        client: UniFiProtectClient,
        event_handler: EventHandler | None = None,
    ) -> None:
        """Initialize the analytics engine.

        Args:
            client: A connected UniFiProtectClient instance.
            event_handler: Optional existing EventHandler. If not provided,
                a new one will be created.
        """
        self._client = client
        self._event_handler = event_handler or EventHandler(client)
        self._unsubscribe: UnsubscribeFunc | None = None
        self._is_running = False

        # Event storage
        self._event_history: list[ProtectEvent] = []
        self._smart_detections: list[ProtectEvent] = []

        # Device health tracking
        self._device_last_seen: dict[str, datetime] = {}
        self._device_disconnect_count: dict[str, int] = defaultdict(int)
        self._device_battery_levels: dict[str, int] = {}

        # Correlation tracking
        self._correlation_rules: list[CorrelationRule] = []
        self._pending_correlations: dict[str, CorrelatedEventGroup] = {}
        self._correlation_callbacks: list[CorrelationCallback] = []
        self._next_correlation_id = 0

        # Initialize default correlation rules
        self._init_default_correlation_rules()

    @property
    def client(self) -> UniFiProtectClient:
        """Get the associated client."""
        return self._client

    @property
    def event_handler(self) -> EventHandler:
        """Get the underlying event handler."""
        return self._event_handler

    @property
    def is_running(self) -> bool:
        """Check if analytics is currently running."""
        return self._is_running

    def start(self) -> None:
        """Start collecting analytics data.

        Raises:
            ValueError: If client is not connected.
            RuntimeError: If analytics is already running.
        """
        if self._is_running:
            raise RuntimeError('Analytics is already running')

        if not self._client.is_connected:
            raise ValueError('Client must be connected to start analytics')

        # Subscribe to all events
        self._unsubscribe = self._event_handler.subscribe(
            self._on_event,
            event_filter=None,  # Receive all events
        )
        self._is_running = True
        logger.info('Event analytics started')

    def stop(self) -> None:
        """Stop collecting analytics data."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

        self._is_running = False
        logger.info('Event analytics stopped')

    def clear(self) -> None:
        """Clear all collected analytics data."""
        self._event_history.clear()
        self._smart_detections.clear()
        self._device_last_seen.clear()
        self._device_disconnect_count.clear()
        self._device_battery_levels.clear()
        self._pending_correlations.clear()
        logger.debug('Analytics data cleared')

    def _on_event(self, event: ProtectEvent) -> None:
        """Handle incoming events for analytics.

        Args:
            event: The received event.
        """
        # Store event in history
        self._event_history.append(event)

        # Trim history if needed
        if len(self._event_history) > self.MAX_EVENT_HISTORY:
            self._event_history = self._event_history[-self.MAX_EVENT_HISTORY:]

        # Track device health
        self._update_device_health(event)

        # Track smart detections
        if event.category == ProtectEventCategory.SMART_DETECT:
            self._track_smart_detection(event)

        # Check correlation rules
        self._check_correlations(event)

    def _update_device_health(self, event: ProtectEvent) -> None:
        """Update device health tracking from an event.

        Args:
            event: The event to process.
        """
        device_id = event.device_id
        if not device_id:
            return

        # Update last seen time
        self._device_last_seen[device_id] = event.timestamp

        # Track disconnections
        if event.event_type in (
            ProtectEventType.DEVICE_DISCONNECTED,
            ProtectEventType.CAMERA_DISCONNECTED,
            ProtectEventType.OFFLINE,
        ):
            self._device_disconnect_count[device_id] += 1

        # Track battery levels
        if 'batteryStatus' in event.changed_data:
            battery = event.changed_data.get('batteryStatus', {})
            if isinstance(battery, dict) and 'percentage' in battery:
                self._device_battery_levels[device_id] = battery['percentage']

    def _track_smart_detection(self, event: ProtectEvent) -> None:
        """Track smart detection events.

        Args:
            event: The smart detection event.
        """
        self._smart_detections.append(event)

        # Trim if needed
        if len(self._smart_detections) > self.MAX_RECENT_DETECTIONS:
            self._smart_detections = self._smart_detections[-self.MAX_RECENT_DETECTIONS:]

    def get_event_aggregation(
        self,
        window: TimeWindow | None = None,
        event_filter: EventFilter | None = None,
    ) -> EventAggregation:
        """Get aggregated event statistics.

        Args:
            window: Time window for aggregation. Defaults to last hour.
            event_filter: Optional filter to limit events included.

        Returns:
            EventAggregation with statistics for the window.
        """
        if window is None:
            window = TimeWindow.last_hour()

        now = datetime.now(timezone.utc)
        window_start = now - window.duration
        window_end = now

        # Filter events by time window
        events = [
            e for e in self._event_history
            if e.timestamp >= window_start
        ]

        # Apply additional filter if provided
        if event_filter is not None:
            events = [e for e in events if event_filter.matches(e)]

        # Build aggregation
        aggregation = EventAggregation(
            total_events=len(events),
            window_start=window_start,
            window_end=window_end,
        )

        # Count by type, device, and category
        events_by_type: dict[ProtectEventType, int] = {}
        events_by_device: dict[str, int] = {}
        events_by_category: dict[ProtectEventCategory, int] = {}

        for event in events:
            if event.event_type is not None:
                events_by_type[event.event_type] = events_by_type.get(event.event_type, 0) + 1

            if event.device_id:
                events_by_device[event.device_id] = events_by_device.get(event.device_id, 0) + 1

            category = event.category
            if category is not None:
                events_by_category[category] = events_by_category.get(category, 0) + 1

        aggregation.events_by_type = events_by_type
        aggregation.events_by_device = events_by_device
        aggregation.events_by_category = events_by_category

        # Create time buckets
        aggregation.time_buckets = self._create_time_buckets(
            events, window_start, window_end, window.bucket_size
        )

        return aggregation

    def _create_time_buckets(
        self,
        events: list[ProtectEvent],
        start: datetime,
        end: datetime,
        bucket_size: timedelta,
    ) -> list[EventCount]:
        """Create time-bucketed event counts.

        Args:
            events: Events to bucket.
            start: Start of the time range.
            end: End of the time range.
            bucket_size: Size of each bucket.

        Returns:
            List of EventCount objects.
        """
        buckets: list[EventCount] = []
        current_start = start

        while current_start < end:
            current_end = min(current_start + bucket_size, end)

            count = sum(
                1 for e in events
                if current_start <= e.timestamp < current_end
            )

            buckets.append(EventCount(
                bucket_start=current_start,
                bucket_end=current_end,
                count=count,
            ))

            current_start = current_end

        return buckets

    def get_motion_stats(
        self,
        window: TimeWindow | None = None,
    ) -> EventAggregation:
        """Get motion event statistics.

        Args:
            window: Time window for statistics. Defaults to last hour.

        Returns:
            EventAggregation for motion events only.
        """
        motion_filter = EventFilter(
            categories=[ProtectEventCategory.MOTION],
        )
        return self.get_event_aggregation(window, motion_filter)

    def get_smart_detect_stats(
        self,
        window: TimeWindow | None = None,
    ) -> SmartDetectStats:
        """Get smart detection statistics.

        Args:
            window: Time window for statistics. Defaults to last 24 hours.

        Returns:
            SmartDetectStats with detection information.
        """
        if window is None:
            window = TimeWindow.last_day()

        now = datetime.now(timezone.utc)
        window_start = now - window.duration

        # Filter detections by time window
        detections = [
            e for e in self._smart_detections
            if e.timestamp >= window_start
        ]

        stats = SmartDetectStats(
            total_detections=len(detections),
            recent_detections=detections[-100:],  # Last 100
        )

        # Count by type and camera
        detections_by_type: dict[SmartDetectType, int] = {}
        detections_by_camera: dict[str, int] = {}
        hour_counts: dict[int, int] = defaultdict(int)

        for detection in detections:
            # Track by camera
            if detection.device_id:
                detections_by_camera[detection.device_id] = (
                    detections_by_camera.get(detection.device_id, 0) + 1
                )

            # Track by hour
            hour_counts[detection.timestamp.hour] += 1

            # Try to extract smart detect type from changed data
            smart_types_raw = detection.changed_data.get('smartDetectTypes')
            if smart_types_raw is not None and isinstance(smart_types_raw, list):
                for item in smart_types_raw:  # type: ignore[reportUnknownVariableType]
                    if isinstance(item, str):
                        try:
                            detect_type = SmartDetectType(item)
                            detections_by_type[detect_type] = (
                                detections_by_type.get(detect_type, 0) + 1
                            )
                        except ValueError:
                            pass

        stats.detections_by_type = detections_by_type
        stats.detections_by_camera = detections_by_camera

        # Find peak hour
        if hour_counts:
            stats.peak_hour = max(hour_counts, key=lambda h: hour_counts[h])

        # Calculate daily average
        days_in_window = window.duration.total_seconds() / 86400
        if days_in_window > 0:
            stats.average_daily = len(detections) / days_in_window

        return stats

    def get_device_health(self, device_id: str) -> DeviceHealth:
        """Get health information for a specific device.

        Args:
            device_id: The device identifier.

        Returns:
            DeviceHealth information for the device.
        """
        health = DeviceHealth(device_id=device_id)

        # Get last seen time
        health.last_seen = self._device_last_seen.get(device_id)

        # Get disconnect count
        health.disconnect_count = self._device_disconnect_count.get(device_id, 0)

        # Get battery level
        health.battery_level = self._device_battery_levels.get(device_id)

        # Determine status
        issues: list[str] = []

        if health.last_seen is None:
            health.status = DeviceHealthStatus.UNKNOWN
        else:
            time_since_seen = datetime.now(timezone.utc) - health.last_seen

            if time_since_seen > timedelta(hours=1):
                health.status = DeviceHealthStatus.OFFLINE
                issues.append(f'Offline for {time_since_seen}')
            elif health.disconnect_count > 5:
                health.status = DeviceHealthStatus.WARNING
                issues.append(f'{health.disconnect_count} disconnections')
            elif health.battery_level is not None and health.battery_level < 20:
                health.status = DeviceHealthStatus.WARNING
                issues.append(f'Low battery: {health.battery_level}%')
            else:
                health.status = DeviceHealthStatus.HEALTHY

        health.issues = issues
        return health

    def get_all_device_health(self) -> list[DeviceHealth]:
        """Get health information for all tracked devices.

        Returns:
            List of DeviceHealth for all devices seen.
        """
        return [
            self.get_device_health(device_id)
            for device_id in self._device_last_seen.keys()
        ]

    def _init_default_correlation_rules(self) -> None:
        """Initialize default event correlation rules."""
        # Motion followed by doorbell ring
        self._correlation_rules.append(CorrelationRule(
            name='motion_then_doorbell',
            trigger_filter=EventFilter(
                categories=[ProtectEventCategory.MOTION],
                model_types=[ProtectModelType.CAMERA],
            ),
            related_filter=EventFilter(
                event_types=[ProtectEventType.RING],
            ),
            time_window=timedelta(seconds=60),
            min_confidence=0.7,
        ))

        # Motion followed by door sensor open
        self._correlation_rules.append(CorrelationRule(
            name='motion_then_door_open',
            trigger_filter=EventFilter(
                categories=[ProtectEventCategory.MOTION],
            ),
            related_filter=EventFilter(
                event_types=[ProtectEventType.SENSOR_OPENED],
            ),
            time_window=timedelta(seconds=30),
            min_confidence=0.6,
        ))

        # Person detection followed by doorbell
        self._correlation_rules.append(CorrelationRule(
            name='person_then_doorbell',
            trigger_filter=EventFilter(
                event_types=[ProtectEventType.SMART_DETECT],
            ),
            related_filter=EventFilter(
                event_types=[ProtectEventType.RING],
            ),
            time_window=timedelta(seconds=120),
            min_confidence=0.9,
        ))

    def add_correlation_rule(self, rule: CorrelationRule) -> None:
        """Add a custom correlation rule.

        Args:
            rule: The correlation rule to add.
        """
        self._correlation_rules.append(rule)
        logger.debug(f'Added correlation rule: {rule.name}')

    def subscribe_correlations(
        self,
        callback: CorrelationCallback,
    ) -> UnsubscribeFunc:
        """Subscribe to correlation events.

        Args:
            callback: Function to call when correlations are detected.

        Returns:
            Unsubscribe function.
        """
        self._correlation_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._correlation_callbacks:
                self._correlation_callbacks.remove(callback)

        return unsubscribe

    def _check_correlations(self, event: ProtectEvent) -> None:
        """Check if event triggers or completes any correlations.

        Args:
            event: The event to check.
        """
        now = datetime.now(timezone.utc)

        # Check for new correlation triggers
        for rule in self._correlation_rules:
            if rule.trigger_filter.matches(event):
                correlation_id = f'corr_{self._next_correlation_id}'
                self._next_correlation_id += 1

                self._pending_correlations[correlation_id] = CorrelatedEventGroup(
                    correlation_id=correlation_id,
                    trigger_event=event,
                    start_time=event.timestamp,
                    pattern_type=rule.name,
                )
                logger.trace(f'Started correlation: {correlation_id} ({rule.name})')

        # Check pending correlations for matches
        completed_correlations: list[str] = []

        for correlation_id, group in self._pending_correlations.items():
            # Find matching rule
            rule = next(
                (r for r in self._correlation_rules if r.name == group.pattern_type),
                None,
            )
            if rule is None:
                continue

            # Check if time window expired
            if group.start_time is not None:
                elapsed = now - group.start_time
                if elapsed > rule.time_window:
                    completed_correlations.append(correlation_id)
                    continue

            # Check if event matches related filter
            if rule.related_filter.matches(event):
                group.related_events.append(event)
                group.confidence = min(1.0, group.confidence + 0.3)

                # Complete correlation if high enough confidence
                if group.confidence >= rule.min_confidence:
                    group.end_time = event.timestamp
                    self._emit_correlation(group)
                    completed_correlations.append(correlation_id)

        # Cleanup completed correlations
        for correlation_id in completed_correlations:
            del self._pending_correlations[correlation_id]

    def _emit_correlation(self, group: CorrelatedEventGroup) -> None:
        """Emit a detected correlation to subscribers.

        Args:
            group: The correlated event group.
        """
        logger.info(
            f'Correlation detected: {group.pattern_type} '
            f'(confidence={group.confidence:.2f}, '
            f'events={len(group.related_events) + 1})'
        )

        for callback in self._correlation_callbacks:
            try:
                callback(group)
            except Exception as e:
                logger.error(f'Error in correlation callback: {e}')

    def get_recent_correlations(
        self,
        pattern_type: str | None = None,
        limit: int = 50,
    ) -> list[CorrelatedEventGroup]:
        """Get recently detected correlations.

        Note: This only returns pending correlations. For historical
        correlations, subscribe to correlation events.

        Args:
            pattern_type: Optional pattern type to filter by.
            limit: Maximum number to return.

        Returns:
            List of pending CorrelatedEventGroup objects.
        """
        correlations = list(self._pending_correlations.values())

        if pattern_type is not None:
            correlations = [c for c in correlations if c.pattern_type == pattern_type]

        return correlations[:limit]

    def get_event_history(
        self,
        limit: int = 100,
        event_filter: EventFilter | None = None,
    ) -> list[ProtectEvent]:
        """Get recent event history.

        Args:
            limit: Maximum number of events to return.
            event_filter: Optional filter to apply.

        Returns:
            List of recent events (newest first).
        """
        events = self._event_history.copy()

        if event_filter is not None:
            events = [e for e in events if event_filter.matches(e)]

        return events[-limit:][::-1]  # Return newest first
