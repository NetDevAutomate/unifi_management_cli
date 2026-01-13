"""WebSocket event handling for UniFi Protect real-time updates.

This module provides event types, filtering, and subscription management
for real-time WebSocket updates from UniFi Protect.

Example:
    >>> from unifi_mapper.protect import UniFiProtectClient
    >>> from unifi_mapper.protect.events import EventHandler, EventFilter, ProtectEventType
    >>>
    >>> async with UniFiProtectClient(config) as client:
    ...     handler = EventHandler(client)
    ...
    ...     def on_motion(event: ProtectEvent) -> None:
    ...         print(f"Motion on {event.device_id}")
    ...
    ...     filter = EventFilter(event_types=[ProtectEventType.MOTION])
    ...     unsub = handler.subscribe(on_motion, filter)
    ...     # ... handle events ...
    ...     unsub()  # Cleanup
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger  # type: ignore[import-untyped]
from uiprotect.data import (
    EventType,
    ModelType,
    ProtectModelWithId,
    WSAction,
    WSSubscriptionMessage,
)


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


class ProtectEventCategory(str, Enum):
    """High-level categories for UniFi Protect events.

    These categories group related event types for easier filtering
    and handling.
    """

    MOTION = 'motion'
    SMART_DETECT = 'smart_detect'
    DOORBELL = 'doorbell'
    SENSOR = 'sensor'
    DOORLOCK = 'doorlock'
    DEVICE_STATE = 'device_state'
    RECORDING = 'recording'
    SYSTEM = 'system'
    ACCESS = 'access'


class ProtectEventType(str, Enum):
    """Event types for UniFi Protect WebSocket updates.

    Maps to underlying uiprotect EventType values while providing
    a cleaner, more focused API.
    """

    # Motion events
    MOTION = 'motion'
    MOTION_SENSOR = 'sensorMotion'
    MOTION_LIGHT = 'lightMotion'

    # Smart detection events
    SMART_DETECT = 'smartDetectZone'
    SMART_DETECT_LINE = 'smartDetectLine'
    SMART_AUDIO_DETECT = 'smartAudioDetect'
    FACE_GROUP_DETECTED = 'faceGroupDetected'

    # Doorbell events
    RING = 'ring'
    NFC_CARD_SCANNED = 'nfcCardScanned'
    FINGERPRINT_IDENTIFIED = 'fingerprintIdentified'

    # Sensor events
    SENSOR_OPENED = 'sensorOpened'
    SENSOR_CLOSED = 'sensorClosed'
    SENSOR_ALARM = 'sensorAlarm'
    SENSOR_EXTREME_VALUE = 'sensorExtremeValues'
    SENSOR_WATER_LEAK = 'sensorWaterLeak'
    SENSOR_BATTERY_LOW = 'sensorBatteryLow'

    # Doorlock events
    DOORLOCK_OPEN = 'doorlockOpened'
    DOORLOCK_CLOSE = 'doorlockClosed'
    DOORLOCK_BATTERY_LOW = 'doorlockBatteryLow'

    # Device state events
    DEVICE_CONNECTED = 'deviceConnected'
    DEVICE_DISCONNECTED = 'deviceDisconnected'
    DEVICE_REBOOTED = 'deviceRebooted'
    CAMERA_CONNECTED = 'cameraConnected'
    CAMERA_DISCONNECTED = 'cameraDisconnected'
    CAMERA_REBOOTED = 'cameraRebooted'
    OFFLINE = 'offline'

    # Recording events
    RECORDING_MODE_CHANGED = 'recordingModeChanged'
    RECORDING_DELETED = 'recordingDeleted'
    RECORDING_OFF = 'recordingOff'

    # System events
    FIRMWARE_UPDATE = 'fwUpdate'
    APP_UPDATE = 'applicationUpdate'
    DEVICE_ADOPTED = 'deviceAdopted'
    DEVICE_UNADOPTED = 'deviceUnadopted'

    # Access events
    DOOR_ACCESS = 'doorAccess'
    ACCESS = 'access'
    USER_LEFT = 'userLeft'
    USER_ARRIVED = 'userArrived'

    # Update events (generic)
    UPDATE = 'update'

    @classmethod
    def from_uiprotect(cls, event_type: EventType) -> ProtectEventType | None:
        """Convert a uiprotect EventType to our ProtectEventType.

        Args:
            event_type: The uiprotect EventType enum value.

        Returns:
            Matching ProtectEventType, or None if not mapped.
        """
        try:
            return cls(event_type.value)
        except ValueError:
            return None

    @property
    def category(self) -> ProtectEventCategory:
        """Get the high-level category for this event type.

        Returns:
            The ProtectEventCategory this event belongs to.
        """
        motion_events = {self.MOTION, self.MOTION_SENSOR, self.MOTION_LIGHT}
        smart_events = {
            self.SMART_DETECT,
            self.SMART_DETECT_LINE,
            self.SMART_AUDIO_DETECT,
            self.FACE_GROUP_DETECTED,
        }
        doorbell_events = {
            self.RING,
            self.NFC_CARD_SCANNED,
            self.FINGERPRINT_IDENTIFIED,
        }
        sensor_events = {
            self.SENSOR_OPENED,
            self.SENSOR_CLOSED,
            self.SENSOR_ALARM,
            self.SENSOR_EXTREME_VALUE,
            self.SENSOR_WATER_LEAK,
            self.SENSOR_BATTERY_LOW,
        }
        doorlock_events = {
            self.DOORLOCK_OPEN,
            self.DOORLOCK_CLOSE,
            self.DOORLOCK_BATTERY_LOW,
        }
        device_state_events = {
            self.DEVICE_CONNECTED,
            self.DEVICE_DISCONNECTED,
            self.DEVICE_REBOOTED,
            self.CAMERA_CONNECTED,
            self.CAMERA_DISCONNECTED,
            self.CAMERA_REBOOTED,
            self.OFFLINE,
            self.UPDATE,
        }
        recording_events = {
            self.RECORDING_MODE_CHANGED,
            self.RECORDING_DELETED,
            self.RECORDING_OFF,
        }
        access_events = {
            self.DOOR_ACCESS,
            self.ACCESS,
            self.USER_LEFT,
            self.USER_ARRIVED,
        }

        if self in motion_events:
            return ProtectEventCategory.MOTION
        if self in smart_events:
            return ProtectEventCategory.SMART_DETECT
        if self in doorbell_events:
            return ProtectEventCategory.DOORBELL
        if self in sensor_events:
            return ProtectEventCategory.SENSOR
        if self in doorlock_events:
            return ProtectEventCategory.DOORLOCK
        if self in device_state_events:
            return ProtectEventCategory.DEVICE_STATE
        if self in recording_events:
            return ProtectEventCategory.RECORDING
        if self in access_events:
            return ProtectEventCategory.ACCESS

        return ProtectEventCategory.SYSTEM


class ProtectAction(str, Enum):
    """Actions that can occur in WebSocket updates.

    Maps directly to uiprotect WSAction.
    """

    ADD = 'add'
    UPDATE = 'update'
    REMOVE = 'remove'

    @classmethod
    def from_uiprotect(cls, action: WSAction) -> ProtectAction:
        """Convert a uiprotect WSAction to our ProtectAction.

        Args:
            action: The uiprotect WSAction enum value.

        Returns:
            Matching ProtectAction.
        """
        return cls(action.value)


class ProtectModelType(str, Enum):
    """Model types for UniFi Protect devices and entities.

    Maps to underlying uiprotect ModelType values.
    """

    CAMERA = 'camera'
    NVR = 'nvr'
    LIGHT = 'light'
    SENSOR = 'sensor'
    DOORLOCK = 'doorlock'
    CHIME = 'chime'
    AIPORT = 'aiport'
    EVENT = 'event'
    USER = 'user'
    BRIDGE = 'bridge'
    LIVEVIEW = 'liveview'
    GROUP = 'group'
    UNKNOWN = 'unknown'

    @classmethod
    def from_uiprotect(cls, model_type: ModelType) -> ProtectModelType:
        """Convert a uiprotect ModelType to our ProtectModelType.

        Args:
            model_type: The uiprotect ModelType enum value.

        Returns:
            Matching ProtectModelType, or UNKNOWN if not mapped.
        """
        try:
            return cls(model_type.value)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class ProtectEvent:
    """Represents a UniFi Protect WebSocket event.

    This is our clean representation of a WebSocket update,
    containing all relevant information about the event.

    Attributes:
        action: The type of action (ADD, UPDATE, REMOVE).
        model_type: The type of model being affected.
        device_id: The ID of the affected device or entity.
        timestamp: When the event was received.
        event_type: Specific event type, if applicable.
        changed_data: Dictionary of changed fields and values.
        new_obj: The updated object state (if available).
        old_obj: The previous object state (if available).
        update_id: Unique identifier for this update.
    """

    action: ProtectAction
    model_type: ProtectModelType
    device_id: str
    timestamp: datetime
    event_type: ProtectEventType | None = None
    changed_data: dict[str, Any] = field(default_factory=lambda: {})  # type: ignore[arg-type]
    new_obj: ProtectModelWithId | None = None
    old_obj: ProtectModelWithId | None = None
    update_id: str = ''

    @classmethod
    def from_ws_message(cls, msg: WSSubscriptionMessage) -> ProtectEvent:
        """Create a ProtectEvent from a WebSocket message.

        Args:
            msg: The WSSubscriptionMessage from uiprotect.

        Returns:
            A new ProtectEvent instance.
        """
        # Extract device ID from the new object if available
        device_id = ''
        if msg.new_obj is not None:
            device_id = msg.new_obj.id

        # Determine model type from the new object
        model_type = ProtectModelType.UNKNOWN
        if msg.new_obj is not None and hasattr(msg.new_obj, 'model_type'):
            raw_model_type: ModelType = getattr(msg.new_obj, 'model_type')
            model_type = ProtectModelType.from_uiprotect(raw_model_type)

        # Try to extract event type from changed data
        event_type: ProtectEventType | None = None
        if 'type' in msg.changed_data:
            try:
                raw_type = msg.changed_data['type']
                if isinstance(raw_type, EventType):
                    event_type = ProtectEventType.from_uiprotect(raw_type)
                elif isinstance(raw_type, str):
                    event_type = ProtectEventType(raw_type)
            except (ValueError, KeyError):
                pass

        return cls(
            action=ProtectAction.from_uiprotect(msg.action),
            model_type=model_type,
            device_id=device_id,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            changed_data=dict(msg.changed_data),
            new_obj=msg.new_obj,
            old_obj=msg.old_obj,
            update_id=msg.new_update_id,
        )

    @property
    def category(self) -> ProtectEventCategory | None:
        """Get the event category if an event type is set.

        Returns:
            The event category, or None if no event type.
        """
        if self.event_type is not None:
            return self.event_type.category
        return None


@dataclass
class EventFilter:
    """Filter configuration for WebSocket event subscriptions.

    Use this to subscribe to specific types of events rather than
    receiving all updates. All filter criteria are AND-combined
    (an event must match ALL specified criteria).

    Attributes:
        event_types: List of specific event types to match.
        categories: List of event categories to match.
        model_types: List of model types to match.
        device_ids: List of specific device IDs to match.
        actions: List of actions to match (ADD, UPDATE, REMOVE).

    Example:
        >>> # Match motion events from cameras only
        >>> filter = EventFilter(
        ...     categories=[ProtectEventCategory.MOTION],
        ...     model_types=[ProtectModelType.CAMERA]
        ... )
        >>>
        >>> # Match any event from specific devices
        >>> filter = EventFilter(device_ids=['camera-123', 'sensor-456'])
    """

    event_types: list[ProtectEventType] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    categories: list[ProtectEventCategory] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    model_types: list[ProtectModelType] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    device_ids: list[str] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    actions: list[ProtectAction] = field(default_factory=lambda: [])  # type: ignore[arg-type]

    def matches(self, event: ProtectEvent) -> bool:
        """Check if an event matches this filter.

        Args:
            event: The event to check against the filter.

        Returns:
            True if the event matches all specified criteria.
        """
        # If no filters are specified, match everything
        if not any([
            self.event_types,
            self.categories,
            self.model_types,
            self.device_ids,
            self.actions,
        ]):
            return True

        # Check each filter criterion (all must match if specified)
        if self.event_types and event.event_type not in self.event_types:
            return False

        if self.categories:
            event_category = event.category
            if event_category is None or event_category not in self.categories:
                return False

        if self.model_types and event.model_type not in self.model_types:
            return False

        if self.device_ids and event.device_id not in self.device_ids:
            return False

        if self.actions and event.action not in self.actions:
            return False

        return True


# Type alias for event callbacks
EventCallback = Callable[[ProtectEvent], Any]
UnsubscribeFunc = Callable[[], None]


@dataclass
class _Subscription:
    """Internal representation of an event subscription."""

    callback: EventCallback
    event_filter: EventFilter
    subscription_id: str


class EventHandler:
    """Manages WebSocket event subscriptions for UniFi Protect.

    This class provides a high-level interface for subscribing to
    real-time events from the UniFi Protect controller.

    The handler automatically converts low-level uiprotect messages
    to our cleaner ProtectEvent representation and handles filtering.

    Attributes:
        client: The connected UniFiProtectClient instance.

    Example:
        >>> async with UniFiProtectClient(config) as client:
        ...     handler = EventHandler(client)
        ...
        ...     def on_motion(event: ProtectEvent) -> None:
        ...         print(f"Motion detected: {event.device_id}")
        ...
        ...     unsub = handler.subscribe(on_motion, EventFilter(
        ...         categories=[ProtectEventCategory.MOTION]
        ...     ))
        ...
        ...     # Events are handled automatically
        ...     await asyncio.sleep(60)
        ...     unsub()
    """

    def __init__(self, client: UniFiProtectClient) -> None:
        """Initialize the event handler.

        Args:
            client: A connected UniFiProtectClient instance.
        """
        self._client = client
        self._subscriptions: dict[str, _Subscription] = {}
        self._next_subscription_id = 0
        self._ws_unsubscribe: UnsubscribeFunc | None = None
        self._is_subscribed = False

    @property
    def client(self) -> UniFiProtectClient:
        """Get the associated client.

        Returns:
            The UniFiProtectClient instance.
        """
        return self._client

    @property
    def subscription_count(self) -> int:
        """Get the number of active subscriptions.

        Returns:
            Count of active event subscriptions.
        """
        return len(self._subscriptions)

    def subscribe(
        self,
        callback: EventCallback,
        event_filter: EventFilter | None = None,
    ) -> UnsubscribeFunc:
        """Subscribe to WebSocket events.

        Args:
            callback: Function to call when matching events occur.
                Can be sync or async.
            event_filter: Optional filter to limit which events
                trigger the callback. If None, all events are received.

        Returns:
            Unsubscribe function - call to remove the subscription.

        Raises:
            ValueError: If the client is not connected.
        """
        if not self._client.is_connected:
            raise ValueError('Client must be connected to subscribe to events')

        if event_filter is None:
            event_filter = EventFilter()

        # Generate unique subscription ID
        sub_id = f'sub_{self._next_subscription_id}'
        self._next_subscription_id += 1

        subscription = _Subscription(
            callback=callback,
            event_filter=event_filter,
            subscription_id=sub_id,
        )
        self._subscriptions[sub_id] = subscription

        logger.debug(f'Added event subscription: {sub_id}')

        # Start WebSocket subscription if this is the first subscriber
        if not self._is_subscribed:
            self._start_ws_subscription()

        def unsubscribe() -> None:
            self._remove_subscription(sub_id)

        return unsubscribe

    def _remove_subscription(self, subscription_id: str) -> None:
        """Remove a subscription by ID.

        Args:
            subscription_id: The ID of the subscription to remove.
        """
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            logger.debug(f'Removed event subscription: {subscription_id}')

            # Stop WebSocket subscription if no more subscribers
            if not self._subscriptions and self._is_subscribed:
                self._stop_ws_subscription()

    def _start_ws_subscription(self) -> None:
        """Start the underlying WebSocket subscription."""
        api = self._client.api
        if api is None:
            logger.warning('Cannot start WebSocket subscription: API not initialized')
            return

        self._ws_unsubscribe = api.subscribe_websocket(
            self._handle_ws_message
        )
        self._is_subscribed = True
        logger.info('Started WebSocket event subscription')

    def _stop_ws_subscription(self) -> None:
        """Stop the underlying WebSocket subscription."""
        if self._ws_unsubscribe is not None:
            self._ws_unsubscribe()
            self._ws_unsubscribe = None
        self._is_subscribed = False
        logger.info('Stopped WebSocket event subscription')

    def _handle_ws_message(self, msg: WSSubscriptionMessage) -> None:
        """Handle incoming WebSocket messages.

        Converts the message to a ProtectEvent and dispatches
        to all matching subscribers.

        Args:
            msg: The raw WebSocket message from uiprotect.
        """
        try:
            event = ProtectEvent.from_ws_message(msg)
            logger.trace(
                f'WebSocket event: action={event.action.value}, '
                f'model={event.model_type.value}, device={event.device_id}'
            )

            # Dispatch to matching subscribers
            for subscription in self._subscriptions.values():
                if subscription.event_filter.matches(event):
                    self._dispatch_event(subscription, event)

        except Exception as e:
            logger.error(f'Error handling WebSocket message: {e}')

    def _dispatch_event(
        self,
        subscription: _Subscription,
        event: ProtectEvent,
    ) -> None:
        """Dispatch an event to a subscriber's callback.

        Handles both sync and async callbacks.

        Args:
            subscription: The subscription to dispatch to.
            event: The event to dispatch.
        """
        try:
            result = subscription.callback(event)

            # Handle async callbacks
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)  # type: ignore[arg-type]

        except Exception as e:
            logger.error(
                f'Error in event callback {subscription.subscription_id}: {e}'
            )

    def clear_subscriptions(self) -> None:
        """Remove all event subscriptions.

        This stops the WebSocket subscription if active.
        """
        self._subscriptions.clear()
        if self._is_subscribed:
            self._stop_ws_subscription()
        logger.debug('Cleared all event subscriptions')
