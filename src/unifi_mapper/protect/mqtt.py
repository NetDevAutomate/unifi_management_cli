"""MQTT Bridge for Home Assistant integration with UniFi Protect.

This module provides MQTT publishing of UniFi Protect events with
Home Assistant MQTT Discovery support for automatic device configuration.

Example:
    >>> from unifi_mapper.protect import UniFiProtectClient, MQTTBridge, MQTTConfig
    >>>
    >>> mqtt_config = MQTTConfig(host='localhost', port=1883)
    >>> async with UniFiProtectClient(protect_config) as client:
    ...     bridge = MQTTBridge(client, mqtt_config)
    ...     await bridge.start()
    ...     # Events are now published to MQTT
    ...     await bridge.stop()
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, SecretStr

from unifi_mapper.protect.events import (
    EventHandler,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
)


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


class MQTTConfig(BaseModel):
    """Configuration for MQTT connection.

    Attributes:
        host: MQTT broker hostname.
        port: MQTT broker port.
        username: Optional username for authentication.
        password: Optional password for authentication.
        client_id: Client identifier for MQTT connection.
        topic_prefix: Base topic prefix for all messages.
        discovery_prefix: Home Assistant discovery prefix.
        retain_state: Whether to retain state messages.
        qos: Quality of Service level (0, 1, or 2).
        keepalive: Connection keepalive interval in seconds.
        reconnect_interval: Interval between reconnection attempts.
        ssl: Whether to use SSL/TLS.
    """

    host: str = Field(default='localhost', description='MQTT broker hostname')
    port: int = Field(default=1883, ge=1, le=65535, description='MQTT broker port')
    username: str | None = Field(default=None, description='MQTT username')
    password: SecretStr | None = Field(default=None, description='MQTT password')
    client_id: str = Field(
        default='unifi-protect-bridge',
        description='MQTT client identifier',
    )
    topic_prefix: str = Field(
        default='unifi/protect',
        description='Base topic prefix',
    )
    discovery_prefix: str = Field(
        default='homeassistant',
        description='Home Assistant discovery prefix',
    )
    retain_state: bool = Field(default=True, description='Retain state messages')
    qos: int = Field(default=1, ge=0, le=2, description='QoS level')
    keepalive: int = Field(default=60, ge=10, description='Keepalive interval')
    reconnect_interval: float = Field(
        default=5.0,
        ge=1.0,
        description='Reconnect interval in seconds',
    )
    ssl: bool = Field(default=False, description='Use SSL/TLS')

    model_config = {'extra': 'forbid'}


class MQTTConnectionState(str, Enum):
    """MQTT connection states."""

    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    RECONNECTING = 'reconnecting'
    FAILED = 'failed'


class HADeviceClass(str, Enum):
    """Home Assistant device classes for binary sensors and sensors."""

    # Binary sensor classes
    MOTION = 'motion'
    OCCUPANCY = 'occupancy'
    DOOR = 'door'
    WINDOW = 'window'
    MOISTURE = 'moisture'
    SMOKE = 'smoke'
    SOUND = 'sound'
    PROBLEM = 'problem'
    CONNECTIVITY = 'connectivity'
    BATTERY = 'battery'
    LOCK = 'lock'
    SAFETY = 'safety'

    # Sensor classes
    TEMPERATURE = 'temperature'
    HUMIDITY = 'humidity'
    ILLUMINANCE = 'illuminance'


class HAEntityCategory(str, Enum):
    """Home Assistant entity categories."""

    CONFIG = 'config'
    DIAGNOSTIC = 'diagnostic'


@dataclass
class MQTTMessage:
    """MQTT message to be published.

    Attributes:
        topic: The MQTT topic to publish to.
        payload: The message payload (will be JSON-encoded if dict).
        retain: Whether to retain the message.
        qos: Quality of Service level.
    """

    topic: str
    payload: str | dict[str, Any]
    retain: bool = False
    qos: int = 1

    def encoded_payload(self) -> bytes:
        """Get the encoded payload bytes.

        Returns:
            UTF-8 encoded payload, JSON-encoded if dict.
        """
        if isinstance(self.payload, dict):
            return json.dumps(self.payload).encode('utf-8')
        return str(self.payload).encode('utf-8')


@dataclass
class DeviceDiscoveryInfo:
    """Home Assistant device discovery information.

    Attributes:
        identifiers: Unique identifiers for the device.
        name: Display name.
        manufacturer: Device manufacturer.
        model: Device model.
        sw_version: Software/firmware version.
        via_device: Parent device identifier.
    """

    identifiers: list[str]
    name: str
    manufacturer: str = 'Ubiquiti'
    model: str = ''
    sw_version: str = ''
    via_device: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to Home Assistant device info dict.

        Returns:
            Dictionary formatted for HA discovery.
        """
        info: dict[str, Any] = {
            'identifiers': self.identifiers,
            'name': self.name,
            'manufacturer': self.manufacturer,
        }
        if self.model:
            info['model'] = self.model
        if self.sw_version:
            info['sw_version'] = self.sw_version
        if self.via_device:
            info['via_device'] = self.via_device
        return info


@dataclass
class EntityDiscoveryConfig:
    """Home Assistant entity discovery configuration.

    Attributes:
        component: HA component type (binary_sensor, sensor, etc).
        object_id: Unique object ID within device.
        name: Entity display name.
        device_class: Optional device class.
        state_topic: Topic for state updates.
        value_template: Optional value extraction template.
        payload_on: Value indicating ON state.
        payload_off: Value indicating OFF state.
        entity_category: Optional entity category.
        icon: Optional MDI icon.
        device: Device information.
        extra_config: Additional configuration options.
    """

    component: str
    object_id: str
    name: str
    state_topic: str
    device: DeviceDiscoveryInfo
    device_class: str | None = None
    value_template: str | None = None
    payload_on: str = 'ON'
    payload_off: str = 'OFF'
    entity_category: str | None = None
    icon: str | None = None
    extra_config: dict[str, Any] = field(default_factory=dict)  # type: ignore[arg-type]

    def to_discovery_payload(self, unique_id: str) -> dict[str, Any]:
        """Generate Home Assistant discovery payload.

        Args:
            unique_id: Unique identifier for the entity.

        Returns:
            Discovery payload dictionary.
        """
        payload: dict[str, Any] = {
            'unique_id': unique_id,
            'name': self.name,
            'state_topic': self.state_topic,
            'device': self.device.to_dict(),
        }

        if self.device_class:
            payload['device_class'] = self.device_class
        if self.value_template:
            payload['value_template'] = self.value_template
        if self.entity_category:
            payload['entity_category'] = self.entity_category
        if self.icon:
            payload['icon'] = self.icon

        # Binary sensor specific
        if self.component == 'binary_sensor':
            payload['payload_on'] = self.payload_on
            payload['payload_off'] = self.payload_off

        # Merge extra config
        payload.update(self.extra_config)

        return payload


# Type alias for connection state callbacks
MQTTConnectionCallback = Callable[[MQTTConnectionState], None]


class MQTTBridge:
    """MQTT bridge for publishing UniFi Protect events to Home Assistant.

    Bridges UniFi Protect events to MQTT, supporting Home Assistant
    MQTT Discovery for automatic device and entity configuration.

    Attributes:
        client: The UniFi Protect client instance.
        config: MQTT configuration.
        state: Current connection state.
    """

    def __init__(
        self,
        client: UniFiProtectClient,
        config: MQTTConfig,
    ) -> None:
        """Initialize the MQTT bridge.

        Args:
            client: UniFi Protect client instance.
            config: MQTT configuration.
        """
        self._client = client
        self._config = config
        self._state = MQTTConnectionState.DISCONNECTED
        self._mqtt_client: Any = None  # Will be aiomqtt.Client
        self._event_handler: EventHandler | None = None
        self._event_unsubscribe: Callable[[], None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._message_queue: asyncio.Queue[MQTTMessage] = asyncio.Queue()
        self._publish_task: asyncio.Task[None] | None = None
        self._connection_callbacks: list[MQTTConnectionCallback] = []
        self._discovered_devices: set[str] = set()
        self._running = False

    @property
    def state(self) -> MQTTConnectionState:
        """Get the current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to MQTT broker."""
        return self._state == MQTTConnectionState.CONNECTED

    @property
    def config(self) -> MQTTConfig:
        """Get the MQTT configuration."""
        return self._config

    def subscribe_connection_state(
        self,
        callback: MQTTConnectionCallback,
    ) -> Callable[[], None]:
        """Subscribe to connection state changes.

        Args:
            callback: Function called when connection state changes.

        Returns:
            Unsubscribe function.
        """
        self._connection_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._connection_callbacks:
                self._connection_callbacks.remove(callback)

        return unsubscribe

    def _notify_connection_state(self, state: MQTTConnectionState) -> None:
        """Notify subscribers of connection state change.

        Args:
            state: New connection state.
        """
        self._state = state
        for callback in self._connection_callbacks:
            try:
                callback(state)
            except Exception as e:
                logger.error(f'Connection callback error: {e}')

    async def start(self) -> None:
        """Start the MQTT bridge.

        Connects to the MQTT broker and starts publishing events.
        Requires aiomqtt to be installed.

        Raises:
            ImportError: If aiomqtt is not installed.
        """
        if self._running:
            logger.warning('MQTT bridge already running')
            return

        self._running = True
        self._notify_connection_state(MQTTConnectionState.CONNECTING)

        try:
            await self._connect()
            self._setup_event_subscription()
            self._publish_task = asyncio.create_task(self._publish_loop())
            await self._publish_discovery()
            logger.info('MQTT bridge started successfully')
        except ImportError:
            self._running = False
            self._notify_connection_state(MQTTConnectionState.FAILED)
            raise
        except Exception as e:
            logger.error(f'Failed to start MQTT bridge: {e}')
            self._running = False
            self._notify_connection_state(MQTTConnectionState.FAILED)
            raise

    async def stop(self) -> None:
        """Stop the MQTT bridge.

        Disconnects from MQTT broker and stops event publishing.
        """
        if not self._running:
            return

        self._running = False

        # Cancel tasks
        if self._publish_task:
            self._publish_task.cancel()
            try:
                await self._publish_task
            except asyncio.CancelledError:
                pass
            self._publish_task = None

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        # Unsubscribe from events
        if self._event_unsubscribe:
            self._event_unsubscribe()
            self._event_unsubscribe = None

        # Disconnect MQTT
        await self._disconnect()

        self._notify_connection_state(MQTTConnectionState.DISCONNECTED)
        logger.info('MQTT bridge stopped')

    async def _connect(self) -> None:
        """Connect to the MQTT broker.

        Raises:
            ImportError: If aiomqtt is not installed.
        """
        try:
            import aiomqtt  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                'aiomqtt is required for MQTT support. '
                'Install with: pip install aiomqtt'
            ) from e

        password = (
            self._config.password.get_secret_value()
            if self._config.password
            else None
        )

        self._mqtt_client = aiomqtt.Client(  # type: ignore[reportUnknownMemberType]
            hostname=self._config.host,
            port=self._config.port,
            username=self._config.username,
            password=password,
            identifier=self._config.client_id,
            keepalive=self._config.keepalive,
        )

        await self._mqtt_client.__aenter__()  # type: ignore[reportUnknownMemberType]
        self._notify_connection_state(MQTTConnectionState.CONNECTED)
        logger.info(f'Connected to MQTT broker at {self._config.host}:{self._config.port}')

    async def _disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._mqtt_client:
            try:
                await self._mqtt_client.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f'Error during MQTT disconnect: {e}')
            finally:
                self._mqtt_client = None

    async def _reconnect_loop(self) -> None:
        """Background task for reconnection attempts."""
        while self._running:
            try:
                await asyncio.sleep(self._config.reconnect_interval)
                if not self.is_connected and self._running:
                    logger.info('Attempting MQTT reconnection...')
                    self._notify_connection_state(MQTTConnectionState.RECONNECTING)
                    await self._connect()
                    await self._publish_discovery()
                    break
            except Exception as e:
                logger.warning(f'Reconnection failed: {e}')

    def _setup_event_subscription(self) -> None:
        """Set up subscription to UniFi Protect events."""
        self._event_handler = EventHandler(self._client)

        # Subscribe to all events
        self._event_unsubscribe = self._event_handler.subscribe(
            callback=self._on_protect_event,
            event_filter=None,  # All events
        )

        logger.debug('Subscribed to UniFi Protect events')

    def _on_protect_event(self, event: ProtectEvent) -> None:
        """Handle incoming UniFi Protect event.

        Args:
            event: The Protect event to process.
        """
        try:
            messages = self._event_to_mqtt_messages(event)
            for message in messages:
                self._message_queue.put_nowait(message)
        except Exception as e:
            logger.error(f'Error processing event {event.event_type}: {e}')

    def _event_to_mqtt_messages(
        self,
        event: ProtectEvent,
    ) -> list[MQTTMessage]:
        """Convert a Protect event to MQTT messages.

        Args:
            event: The Protect event.

        Returns:
            List of MQTT messages to publish.
        """
        messages: list[MQTTMessage] = []
        prefix = self._config.topic_prefix

        # Skip events without an event type
        if event.event_type is None:
            return messages

        # Event topic
        event_topic = f'{prefix}/event/{event.device_id}/{event.event_type.value}'
        category = event.category
        event_payload: dict[str, Any] = {
            'event_type': event.event_type.value,
            'category': category.value if category else None,
            'device_id': event.device_id,
            'model_type': event.model_type.value,
            'timestamp': event.timestamp.isoformat(),
            'changed_data': event.changed_data,
        }
        messages.append(MQTTMessage(
            topic=event_topic,
            payload=event_payload,
            retain=False,
            qos=self._config.qos,
        ))

        # Update device state for relevant events
        if category in {
            ProtectEventCategory.MOTION,
            ProtectEventCategory.SMART_DETECT,
            ProtectEventCategory.SENSOR,
            ProtectEventCategory.DEVICE_STATE,
        }:
            state_messages = self._get_state_messages(event)
            messages.extend(state_messages)

        return messages

    def _get_state_messages(self, event: ProtectEvent) -> list[MQTTMessage]:
        """Get state update messages for an event.

        Args:
            event: The Protect event.

        Returns:
            List of state update messages.
        """
        messages: list[MQTTMessage] = []
        prefix = self._config.topic_prefix
        category = event.category

        if category is None:
            return messages

        # Motion state
        if category == ProtectEventCategory.MOTION:
            state = 'ON' if event.event_type == ProtectEventType.MOTION else 'OFF'
            messages.append(MQTTMessage(
                topic=f'{prefix}/state/{event.device_id}/motion',
                payload=state,
                retain=self._config.retain_state,
                qos=self._config.qos,
            ))

        # Smart detection state
        elif category == ProtectEventCategory.SMART_DETECT:
            smart_types: list[str] = event.changed_data.get('smart_detect_types', [])
            for smart_type in smart_types:
                messages.append(MQTTMessage(
                    topic=f'{prefix}/state/{event.device_id}/smart_detect/{smart_type}',
                    payload='ON',
                    retain=False,  # Smart detects are momentary
                    qos=self._config.qos,
                ))

        # Sensor state
        elif category == ProtectEventCategory.SENSOR:
            if event.event_type == ProtectEventType.SENSOR_OPENED:
                state = 'ON'
            elif event.event_type == ProtectEventType.SENSOR_CLOSED:
                state = 'OFF'
            else:
                state = 'ON'  # Alarms, water leak, etc.

            messages.append(MQTTMessage(
                topic=f'{prefix}/state/{event.device_id}/sensor',
                payload=state,
                retain=self._config.retain_state,
                qos=self._config.qos,
            ))

        # Device connectivity state
        elif category == ProtectEventCategory.DEVICE_STATE:
            if event.event_type in {
                ProtectEventType.DEVICE_CONNECTED,
                ProtectEventType.CAMERA_CONNECTED,
            }:
                state = 'ON'
            elif event.event_type in {
                ProtectEventType.DEVICE_DISCONNECTED,
                ProtectEventType.CAMERA_DISCONNECTED,
                ProtectEventType.OFFLINE,
            }:
                state = 'OFF'
            else:
                return messages

            messages.append(MQTTMessage(
                topic=f'{prefix}/state/{event.device_id}/connectivity',
                payload=state,
                retain=self._config.retain_state,
                qos=self._config.qos,
            ))

        return messages

    async def _publish_loop(self) -> None:
        """Background task for publishing queued messages."""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )
                await self._publish_message(message)
                self._message_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Error in publish loop: {e}')
                if not self.is_connected:
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())
                    await asyncio.sleep(self._config.reconnect_interval)

    async def _publish_message(self, message: MQTTMessage) -> None:
        """Publish a single MQTT message.

        Args:
            message: The message to publish.
        """
        if not self._mqtt_client:
            logger.warning('Cannot publish: not connected')
            return

        try:
            await self._mqtt_client.publish(
                topic=message.topic,
                payload=message.encoded_payload(),
                qos=message.qos,
                retain=message.retain,
            )
            logger.debug(f'Published to {message.topic}')
        except Exception as e:
            logger.error(f'Failed to publish to {message.topic}: {e}')
            raise

    async def _publish_discovery(self) -> None:
        """Publish Home Assistant MQTT Discovery configs for all devices."""
        if not self._client.is_connected:
            logger.warning('Protect client not connected, skipping discovery')
            return

        # Discover cameras (including doorbells which are a camera subtype)
        for camera_id, camera in self._client.cameras.items():
            if camera_id not in self._discovered_devices:
                camera_name = camera.name or f'Camera {camera_id[:8]}'
                # Check if camera has doorbell feature
                has_chime = getattr(camera, 'has_chime', False)
                if has_chime:
                    await self._publish_doorbell_discovery(
                        device_id=camera_id,
                        name=camera_name,
                        model=getattr(camera, 'model', 'Doorbell'),
                        firmware=getattr(camera, 'firmware_version', ''),
                    )
                else:
                    await self._publish_camera_discovery(
                        device_id=camera_id,
                        name=camera_name,
                        model=getattr(camera, 'model', 'Camera'),
                        firmware=getattr(camera, 'firmware_version', ''),
                    )
                self._discovered_devices.add(camera_id)

        # Discover sensors
        for sensor_id, sensor in self._client.sensors.items():
            if sensor_id not in self._discovered_devices:
                sensor_name = sensor.name or f'Sensor {sensor_id[:8]}'
                await self._publish_sensor_discovery(
                    device_id=sensor_id,
                    name=sensor_name,
                    model=getattr(sensor, 'model', 'Sensor'),
                    firmware=getattr(sensor, 'firmware_version', ''),
                )
                self._discovered_devices.add(sensor_id)

        # Discover lights
        for light_id, light in self._client.lights.items():
            if light_id not in self._discovered_devices:
                light_name = light.name or f'Light {light_id[:8]}'
                await self._publish_light_discovery(
                    device_id=light_id,
                    name=light_name,
                    model=getattr(light, 'model', 'Light'),
                    firmware=getattr(light, 'firmware_version', ''),
                )
                self._discovered_devices.add(light_id)

        logger.info(f'Published discovery for {len(self._discovered_devices)} devices')

    async def _publish_camera_discovery(
        self,
        device_id: str,
        name: str,
        model: str,
        firmware: str,
    ) -> None:
        """Publish Home Assistant discovery for a camera.

        Args:
            device_id: Unique device identifier.
            name: Camera display name.
            model: Camera model.
            firmware: Firmware version.
        """
        device_info = DeviceDiscoveryInfo(
            identifiers=[f'unifi_protect_{device_id}'],
            name=name,
            model=model,
            sw_version=firmware,
        )

        prefix = self._config.topic_prefix
        discovery_prefix = self._config.discovery_prefix

        # Motion binary sensor
        motion_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_motion',
            name=f'{name} Motion',
            state_topic=f'{prefix}/state/{device_id}/motion',
            device=device_info,
            device_class=HADeviceClass.MOTION.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_motion',
            config=motion_config,
        )

        # Connectivity binary sensor
        connectivity_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_connectivity',
            name=f'{name} Connectivity',
            state_topic=f'{prefix}/state/{device_id}/connectivity',
            device=device_info,
            device_class=HADeviceClass.CONNECTIVITY.value,
            entity_category=HAEntityCategory.DIAGNOSTIC.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_connectivity',
            config=connectivity_config,
        )

        # Smart detection sensors (person, vehicle, package, animal)
        smart_types = ['person', 'vehicle', 'package', 'animal']
        for smart_type in smart_types:
            smart_config = EntityDiscoveryConfig(
                component='binary_sensor',
                object_id=f'{device_id}_{smart_type}',
                name=f'{name} {smart_type.title()} Detected',
                state_topic=f'{prefix}/state/{device_id}/smart_detect/{smart_type}',
                device=device_info,
                device_class=HADeviceClass.OCCUPANCY.value,
                icon=f'mdi:{self._smart_type_icon(smart_type)}',
            )

            await self._publish_discovery_config(
                discovery_prefix=discovery_prefix,
                component='binary_sensor',
                object_id=f'unifi_protect_{device_id}_{smart_type}',
                config=smart_config,
            )

    async def _publish_sensor_discovery(
        self,
        device_id: str,
        name: str,
        model: str,
        firmware: str,
    ) -> None:
        """Publish Home Assistant discovery for a sensor.

        Args:
            device_id: Unique device identifier.
            name: Sensor display name.
            model: Sensor model.
            firmware: Firmware version.
        """
        device_info = DeviceDiscoveryInfo(
            identifiers=[f'unifi_protect_{device_id}'],
            name=name,
            model=model,
            sw_version=firmware,
        )

        prefix = self._config.topic_prefix
        discovery_prefix = self._config.discovery_prefix

        # Door/window binary sensor
        door_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_sensor',
            name=f'{name}',
            state_topic=f'{prefix}/state/{device_id}/sensor',
            device=device_info,
            device_class=HADeviceClass.DOOR.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_sensor',
            config=door_config,
        )

        # Motion binary sensor
        motion_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_motion',
            name=f'{name} Motion',
            state_topic=f'{prefix}/state/{device_id}/motion',
            device=device_info,
            device_class=HADeviceClass.MOTION.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_motion',
            config=motion_config,
        )

        # Battery sensor (diagnostic)
        battery_config = EntityDiscoveryConfig(
            component='sensor',
            object_id=f'{device_id}_battery',
            name=f'{name} Battery',
            state_topic=f'{prefix}/state/{device_id}/battery',
            device=device_info,
            device_class='battery',
            entity_category=HAEntityCategory.DIAGNOSTIC.value,
            extra_config={
                'unit_of_measurement': '%',
                'state_class': 'measurement',
            },
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='sensor',
            object_id=f'unifi_protect_{device_id}_battery',
            config=battery_config,
        )

    async def _publish_light_discovery(
        self,
        device_id: str,
        name: str,
        model: str,
        firmware: str,
    ) -> None:
        """Publish Home Assistant discovery for a light.

        Args:
            device_id: Unique device identifier.
            name: Light display name.
            model: Light model.
            firmware: Firmware version.
        """
        device_info = DeviceDiscoveryInfo(
            identifiers=[f'unifi_protect_{device_id}'],
            name=name,
            model=model,
            sw_version=firmware,
        )

        prefix = self._config.topic_prefix
        discovery_prefix = self._config.discovery_prefix

        # Motion binary sensor
        motion_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_motion',
            name=f'{name} Motion',
            state_topic=f'{prefix}/state/{device_id}/motion',
            device=device_info,
            device_class=HADeviceClass.MOTION.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_motion',
            config=motion_config,
        )

        # Connectivity
        connectivity_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_connectivity',
            name=f'{name} Connectivity',
            state_topic=f'{prefix}/state/{device_id}/connectivity',
            device=device_info,
            device_class=HADeviceClass.CONNECTIVITY.value,
            entity_category=HAEntityCategory.DIAGNOSTIC.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_connectivity',
            config=connectivity_config,
        )

    async def _publish_doorbell_discovery(
        self,
        device_id: str,
        name: str,
        model: str,
        firmware: str,
    ) -> None:
        """Publish Home Assistant discovery for a doorbell.

        Args:
            device_id: Unique device identifier.
            name: Doorbell display name.
            model: Doorbell model.
            firmware: Firmware version.
        """
        device_info = DeviceDiscoveryInfo(
            identifiers=[f'unifi_protect_{device_id}'],
            name=name,
            model=model,
            sw_version=firmware,
        )

        prefix = self._config.topic_prefix
        discovery_prefix = self._config.discovery_prefix

        # Ring event sensor
        ring_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_ring',
            name=f'{name} Ring',
            state_topic=f'{prefix}/state/{device_id}/ring',
            device=device_info,
            device_class=HADeviceClass.OCCUPANCY.value,
            icon='mdi:bell-ring',
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_ring',
            config=ring_config,
        )

        # Motion (doorbell includes camera)
        motion_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_motion',
            name=f'{name} Motion',
            state_topic=f'{prefix}/state/{device_id}/motion',
            device=device_info,
            device_class=HADeviceClass.MOTION.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_motion',
            config=motion_config,
        )

        # Connectivity
        connectivity_config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id=f'{device_id}_connectivity',
            name=f'{name} Connectivity',
            state_topic=f'{prefix}/state/{device_id}/connectivity',
            device=device_info,
            device_class=HADeviceClass.CONNECTIVITY.value,
            entity_category=HAEntityCategory.DIAGNOSTIC.value,
        )

        await self._publish_discovery_config(
            discovery_prefix=discovery_prefix,
            component='binary_sensor',
            object_id=f'unifi_protect_{device_id}_connectivity',
            config=connectivity_config,
        )

    async def _publish_discovery_config(
        self,
        discovery_prefix: str,
        component: str,
        object_id: str,
        config: EntityDiscoveryConfig,
    ) -> None:
        """Publish a single discovery configuration.

        Args:
            discovery_prefix: Home Assistant discovery prefix.
            component: HA component type.
            object_id: Unique object ID.
            config: Entity discovery configuration.
        """
        topic = f'{discovery_prefix}/{component}/{object_id}/config'
        payload = config.to_discovery_payload(unique_id=object_id)

        message = MQTTMessage(
            topic=topic,
            payload=payload,
            retain=True,  # Discovery configs should be retained
            qos=self._config.qos,
        )

        await self._publish_message(message)

    def _smart_type_icon(self, smart_type: str) -> str:
        """Get MDI icon for a smart detection type.

        Args:
            smart_type: Smart detection type name.

        Returns:
            MDI icon name without 'mdi:' prefix.
        """
        icons = {
            'person': 'account',
            'vehicle': 'car',
            'package': 'package',
            'animal': 'paw',
            'face': 'face-recognition',
            'licensePlate': 'card-text',
        }
        return icons.get(smart_type, 'alert-circle')

    async def publish_device_state(
        self,
        device_id: str,
        state_type: str,
        value: str | int | float | bool,
    ) -> None:
        """Manually publish a device state update.

        Args:
            device_id: Device identifier.
            state_type: State type (motion, connectivity, battery, etc).
            value: State value.
        """
        prefix = self._config.topic_prefix
        payload = str(value) if isinstance(value, bool) else value

        message = MQTTMessage(
            topic=f'{prefix}/state/{device_id}/{state_type}',
            payload=str(payload),
            retain=self._config.retain_state,
            qos=self._config.qos,
        )

        if self.is_connected:
            await self._publish_message(message)
        else:
            self._message_queue.put_nowait(message)

    async def publish_availability(self, available: bool = True) -> None:
        """Publish bridge availability status.

        Args:
            available: Whether the bridge is available.
        """
        prefix = self._config.topic_prefix
        message = MQTTMessage(
            topic=f'{prefix}/status',
            payload='online' if available else 'offline',
            retain=True,
            qos=self._config.qos,
        )

        if self._mqtt_client:
            await self._publish_message(message)
