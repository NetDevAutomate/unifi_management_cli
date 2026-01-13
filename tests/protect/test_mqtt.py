"""Tests for MQTT Bridge module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_mapper.protect.events import (
    ProtectAction,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    ProtectModelType,
)
from unifi_mapper.protect.mqtt import (
    DeviceDiscoveryInfo,
    EntityDiscoveryConfig,
    HADeviceClass,
    HAEntityCategory,
    MQTTBridge,
    MQTTConfig,
    MQTTConnectionState,
    MQTTMessage,
)


# ============================================================================
# Test Fixtures and Helpers
# ============================================================================


def create_mock_client(
    is_connected: bool = True,
    cameras: dict[str, Any] | None = None,
    sensors: dict[str, Any] | None = None,
    lights: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock UniFiProtectClient for testing."""
    client = MagicMock()
    client.is_connected = is_connected
    client.cameras = cameras or {}
    client.sensors = sensors or {}
    client.lights = lights or {}
    return client


def create_mock_camera(
    name: str = 'Test Camera',
    model: str = 'G4 Pro',
    firmware_version: str = '4.63.22',
    has_chime: bool = False,
) -> MagicMock:
    """Create a mock camera."""
    camera = MagicMock()
    camera.name = name
    camera.model = model
    camera.firmware_version = firmware_version
    camera.has_chime = has_chime
    return camera


def create_mock_sensor(
    name: str = 'Test Sensor',
    model: str = 'UP Sense',
    firmware_version: str = '2.1.5',
) -> MagicMock:
    """Create a mock sensor."""
    sensor = MagicMock()
    sensor.name = name
    sensor.model = model
    sensor.firmware_version = firmware_version
    return sensor


def create_mock_light(
    name: str = 'Test Light',
    model: str = 'UP Floodlight',
    firmware_version: str = '2.0.12',
) -> MagicMock:
    """Create a mock light."""
    light = MagicMock()
    light.name = name
    light.model = model
    light.firmware_version = firmware_version
    return light


def create_protect_event(
    event_type: ProtectEventType = ProtectEventType.MOTION,
    device_id: str = 'camera-123',
    model_type: ProtectModelType = ProtectModelType.CAMERA,
    changed_data: dict[str, Any] | None = None,
) -> ProtectEvent:
    """Create a ProtectEvent for testing."""
    return ProtectEvent(
        action=ProtectAction.UPDATE,
        model_type=model_type,
        device_id=device_id,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        changed_data=changed_data or {},
    )


# ============================================================================
# MQTTConfig Tests
# ============================================================================


class TestMQTTConfig:
    """Tests for MQTTConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = MQTTConfig()

        assert config.host == 'localhost'
        assert config.port == 1883
        assert config.username is None
        assert config.password is None
        assert config.client_id == 'unifi-protect-bridge'
        assert config.topic_prefix == 'unifi/protect'
        assert config.discovery_prefix == 'homeassistant'
        assert config.retain_state is True
        assert config.qos == 1
        assert config.keepalive == 60
        assert config.reconnect_interval == 5.0
        assert config.ssl is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        from pydantic import SecretStr

        config = MQTTConfig(
            host='mqtt.example.com',
            port=8883,
            username='user',
            password=SecretStr('secret'),
            client_id='custom-client',
            topic_prefix='custom/prefix',
            discovery_prefix='ha',
            retain_state=False,
            qos=2,
            ssl=True,
        )

        assert config.host == 'mqtt.example.com'
        assert config.port == 8883
        assert config.username == 'user'
        assert config.password.get_secret_value() == 'secret'
        assert config.client_id == 'custom-client'
        assert config.topic_prefix == 'custom/prefix'
        assert config.discovery_prefix == 'ha'
        assert config.retain_state is False
        assert config.qos == 2
        assert config.ssl is True

    def test_port_validation(self) -> None:
        """Test port number validation."""
        # Valid port
        config = MQTTConfig(port=1883)
        assert config.port == 1883

        # Invalid port (too high)
        with pytest.raises(ValueError):
            MQTTConfig(port=70000)

        # Invalid port (too low)
        with pytest.raises(ValueError):
            MQTTConfig(port=0)

    def test_qos_validation(self) -> None:
        """Test QoS level validation."""
        for qos in [0, 1, 2]:
            config = MQTTConfig(qos=qos)
            assert config.qos == qos

        with pytest.raises(ValueError):
            MQTTConfig(qos=3)

        with pytest.raises(ValueError):
            MQTTConfig(qos=-1)


# ============================================================================
# MQTTMessage Tests
# ============================================================================


class TestMQTTMessage:
    """Tests for MQTTMessage."""

    def test_string_payload(self) -> None:
        """Test message with string payload."""
        message = MQTTMessage(
            topic='test/topic',
            payload='ON',
            retain=True,
            qos=1,
        )

        assert message.topic == 'test/topic'
        assert message.payload == 'ON'
        assert message.retain is True
        assert message.qos == 1
        assert message.encoded_payload() == b'ON'

    def test_dict_payload(self) -> None:
        """Test message with dictionary payload."""
        payload = {'status': 'active', 'value': 42}
        message = MQTTMessage(
            topic='test/topic',
            payload=payload,
        )

        encoded = message.encoded_payload()
        assert b'"status"' in encoded
        assert b'"active"' in encoded
        assert b'"value"' in encoded
        assert b'42' in encoded

    def test_default_values(self) -> None:
        """Test default message values."""
        message = MQTTMessage(topic='t', payload='p')

        assert message.retain is False
        assert message.qos == 1


# ============================================================================
# DeviceDiscoveryInfo Tests
# ============================================================================


class TestDeviceDiscoveryInfo:
    """Tests for DeviceDiscoveryInfo."""

    def test_basic_info(self) -> None:
        """Test basic device info."""
        info = DeviceDiscoveryInfo(
            identifiers=['device-123'],
            name='Test Device',
        )

        result = info.to_dict()

        assert result['identifiers'] == ['device-123']
        assert result['name'] == 'Test Device'
        assert result['manufacturer'] == 'Ubiquiti'
        assert 'model' not in result
        assert 'sw_version' not in result
        assert 'via_device' not in result

    def test_full_info(self) -> None:
        """Test full device info."""
        info = DeviceDiscoveryInfo(
            identifiers=['device-123'],
            name='Test Camera',
            manufacturer='Ubiquiti',
            model='G4 Pro',
            sw_version='4.63.22',
            via_device='nvr-456',
        )

        result = info.to_dict()

        assert result['identifiers'] == ['device-123']
        assert result['name'] == 'Test Camera'
        assert result['manufacturer'] == 'Ubiquiti'
        assert result['model'] == 'G4 Pro'
        assert result['sw_version'] == '4.63.22'
        assert result['via_device'] == 'nvr-456'


# ============================================================================
# EntityDiscoveryConfig Tests
# ============================================================================


class TestEntityDiscoveryConfig:
    """Tests for EntityDiscoveryConfig."""

    def test_binary_sensor_config(self) -> None:
        """Test binary sensor discovery config."""
        device_info = DeviceDiscoveryInfo(
            identifiers=['device-123'],
            name='Test Camera',
        )

        config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id='motion',
            name='Motion',
            state_topic='unifi/protect/state/device-123/motion',
            device=device_info,
            device_class=HADeviceClass.MOTION.value,
        )

        payload = config.to_discovery_payload('unifi_protect_device-123_motion')

        assert payload['unique_id'] == 'unifi_protect_device-123_motion'
        assert payload['name'] == 'Motion'
        assert payload['state_topic'] == 'unifi/protect/state/device-123/motion'
        assert payload['device_class'] == 'motion'
        assert payload['payload_on'] == 'ON'
        assert payload['payload_off'] == 'OFF'
        assert 'device' in payload

    def test_sensor_config(self) -> None:
        """Test sensor discovery config."""
        device_info = DeviceDiscoveryInfo(
            identifiers=['device-123'],
            name='Test Sensor',
        )

        config = EntityDiscoveryConfig(
            component='sensor',
            object_id='battery',
            name='Battery',
            state_topic='unifi/protect/state/device-123/battery',
            device=device_info,
            device_class='battery',
            entity_category=HAEntityCategory.DIAGNOSTIC.value,
            extra_config={
                'unit_of_measurement': '%',
                'state_class': 'measurement',
            },
        )

        payload = config.to_discovery_payload('unifi_protect_device-123_battery')

        assert payload['unique_id'] == 'unifi_protect_device-123_battery'
        assert payload['device_class'] == 'battery'
        assert payload['entity_category'] == 'diagnostic'
        assert payload['unit_of_measurement'] == '%'
        assert payload['state_class'] == 'measurement'
        # Sensor should not have payload_on/off
        assert 'payload_on' not in payload

    def test_icon_config(self) -> None:
        """Test entity with custom icon."""
        device_info = DeviceDiscoveryInfo(
            identifiers=['device-123'],
            name='Test',
        )

        config = EntityDiscoveryConfig(
            component='binary_sensor',
            object_id='person',
            name='Person Detected',
            state_topic='unifi/protect/state/device-123/person',
            device=device_info,
            icon='mdi:account',
        )

        payload = config.to_discovery_payload('test_id')

        assert payload['icon'] == 'mdi:account'


# ============================================================================
# HADeviceClass Tests
# ============================================================================


class TestHADeviceClass:
    """Tests for HADeviceClass enum."""

    def test_binary_sensor_classes(self) -> None:
        """Test binary sensor device classes."""
        assert HADeviceClass.MOTION.value == 'motion'
        assert HADeviceClass.DOOR.value == 'door'
        assert HADeviceClass.CONNECTIVITY.value == 'connectivity'
        assert HADeviceClass.BATTERY.value == 'battery'

    def test_sensor_classes(self) -> None:
        """Test sensor device classes."""
        assert HADeviceClass.TEMPERATURE.value == 'temperature'
        assert HADeviceClass.HUMIDITY.value == 'humidity'
        assert HADeviceClass.ILLUMINANCE.value == 'illuminance'


# ============================================================================
# MQTTBridge Tests
# ============================================================================


class TestMQTTBridgeInit:
    """Tests for MQTTBridge initialization."""

    def test_initial_state(self) -> None:
        """Test initial bridge state."""
        client = create_mock_client()
        config = MQTTConfig()

        bridge = MQTTBridge(client, config)

        assert bridge.state == MQTTConnectionState.DISCONNECTED
        assert bridge.is_connected is False
        assert bridge.config == config

    def test_connection_callback_subscription(self) -> None:
        """Test subscribing to connection state changes."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        states: list[MQTTConnectionState] = []

        def callback(state: MQTTConnectionState) -> None:
            states.append(state)

        unsub = bridge.subscribe_connection_state(callback)

        # Manually trigger state change
        bridge._notify_connection_state(MQTTConnectionState.CONNECTING)

        assert len(states) == 1
        assert states[0] == MQTTConnectionState.CONNECTING

        # Unsubscribe
        unsub()
        bridge._notify_connection_state(MQTTConnectionState.CONNECTED)

        # Should not receive after unsubscribe
        assert len(states) == 1


class TestMQTTBridgeEventConversion:
    """Tests for event conversion to MQTT messages."""

    def test_motion_event_conversion(self) -> None:
        """Test converting motion event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.MOTION,
            device_id='camera-123',
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Should have event message + state message
        assert len(messages) >= 1

        # Check event message
        event_msg = messages[0]
        assert 'event/camera-123/motion' in event_msg.topic

    def test_smart_detect_event_conversion(self) -> None:
        """Test converting smart detection event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.SMART_DETECT,
            device_id='camera-123',
            changed_data={'smart_detect_types': ['person', 'vehicle']},
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Should have event message + smart detect state messages
        assert len(messages) >= 1

        # Find smart detect messages
        smart_topics = [m.topic for m in messages if 'smart_detect' in m.topic]
        assert len(smart_topics) >= 1

    def test_sensor_opened_event_conversion(self) -> None:
        """Test converting sensor opened event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.SENSOR_OPENED,
            device_id='sensor-123',
            model_type=ProtectModelType.SENSOR,
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Find state message
        state_msgs = [m for m in messages if '/state/' in m.topic and '/sensor' in m.topic]
        assert len(state_msgs) == 1
        assert state_msgs[0].payload == 'ON'

    def test_sensor_closed_event_conversion(self) -> None:
        """Test converting sensor closed event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.SENSOR_CLOSED,
            device_id='sensor-123',
            model_type=ProtectModelType.SENSOR,
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Find state message
        state_msgs = [m for m in messages if '/state/' in m.topic and '/sensor' in m.topic]
        assert len(state_msgs) == 1
        assert state_msgs[0].payload == 'OFF'

    def test_device_connected_event_conversion(self) -> None:
        """Test converting device connected event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.DEVICE_CONNECTED,
            device_id='camera-123',
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Find connectivity state message
        conn_msgs = [m for m in messages if 'connectivity' in m.topic]
        assert len(conn_msgs) == 1
        assert conn_msgs[0].payload == 'ON'

    def test_device_disconnected_event_conversion(self) -> None:
        """Test converting device disconnected event to MQTT messages."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.DEVICE_DISCONNECTED,
            device_id='camera-123',
        )

        messages = bridge._event_to_mqtt_messages(event)

        # Find connectivity state message
        conn_msgs = [m for m in messages if 'connectivity' in m.topic]
        assert len(conn_msgs) == 1
        assert conn_msgs[0].payload == 'OFF'

    def test_event_without_type_skipped(self) -> None:
        """Test that events without event_type are skipped."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.CAMERA,
            device_id='camera-123',
            timestamp=datetime.now(timezone.utc),
            event_type=None,
        )

        messages = bridge._event_to_mqtt_messages(event)
        assert len(messages) == 0


class TestMQTTBridgeDiscovery:
    """Tests for Home Assistant discovery publishing."""

    @pytest.mark.asyncio
    async def test_camera_discovery_payload(self) -> None:
        """Test camera discovery payload generation."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        # Mock publish_message
        bridge._publish_message = AsyncMock()

        await bridge._publish_camera_discovery(
            device_id='camera-123',
            name='Front Door',
            model='G4 Pro',
            firmware='4.63.22',
        )

        # Should publish multiple discovery configs (motion, connectivity, smart detects)
        assert bridge._publish_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_sensor_discovery_payload(self) -> None:
        """Test sensor discovery payload generation."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._publish_message = AsyncMock()

        await bridge._publish_sensor_discovery(
            device_id='sensor-123',
            name='Entry Door',
            model='UP Sense',
            firmware='2.1.5',
        )

        # Should publish door/window, motion, and battery discovery
        assert bridge._publish_message.call_count >= 3

    @pytest.mark.asyncio
    async def test_doorbell_discovery_payload(self) -> None:
        """Test doorbell discovery payload generation."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._publish_message = AsyncMock()

        await bridge._publish_doorbell_discovery(
            device_id='doorbell-123',
            name='Front Doorbell',
            model='G4 Doorbell Pro',
            firmware='4.60.15',
        )

        # Should publish ring, motion, and connectivity discovery
        assert bridge._publish_message.call_count >= 3

    @pytest.mark.asyncio
    async def test_discovery_skips_when_not_connected(self) -> None:
        """Test that discovery is skipped when client not connected."""
        client = create_mock_client(is_connected=False)
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._publish_message = AsyncMock()

        await bridge._publish_discovery()

        # Should not publish anything
        bridge._publish_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_discovery_publishes_for_all_devices(self) -> None:
        """Test that discovery is published for all devices."""
        cameras = {
            'cam-1': create_mock_camera(name='Camera 1'),
            'cam-2': create_mock_camera(name='Camera 2', has_chime=True),
        }
        sensors = {
            'sensor-1': create_mock_sensor(name='Sensor 1'),
        }
        lights = {
            'light-1': create_mock_light(name='Light 1'),
        }

        client = create_mock_client(
            cameras=cameras,
            sensors=sensors,
            lights=lights,
        )
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._publish_message = AsyncMock()

        await bridge._publish_discovery()

        # Should have discovered all 4 devices
        assert len(bridge._discovered_devices) == 4
        assert 'cam-1' in bridge._discovered_devices
        assert 'cam-2' in bridge._discovered_devices
        assert 'sensor-1' in bridge._discovered_devices
        assert 'light-1' in bridge._discovered_devices


class TestMQTTBridgeLifecycle:
    """Tests for bridge lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_without_aiomqtt_raises(self) -> None:
        """Test that start raises ImportError without aiomqtt."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        with patch.dict('sys.modules', {'aiomqtt': None}):
            with pytest.raises(ImportError, match='aiomqtt is required'):
                await bridge.start()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self) -> None:
        """Test stopping bridge when not running does nothing."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        # Should not raise
        await bridge.stop()

        assert bridge.state == MQTTConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_publish_device_state(self) -> None:
        """Test manually publishing device state."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._mqtt_client = MagicMock()
        bridge._mqtt_client.publish = AsyncMock()
        bridge._state = MQTTConnectionState.CONNECTED

        await bridge.publish_device_state('device-123', 'motion', 'ON')

        bridge._mqtt_client.publish.assert_called_once()
        call_kwargs = bridge._mqtt_client.publish.call_args.kwargs
        assert 'device-123' in call_kwargs['topic']
        assert 'motion' in call_kwargs['topic']

    @pytest.mark.asyncio
    async def test_publish_availability(self) -> None:
        """Test publishing availability status."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._mqtt_client = MagicMock()
        bridge._mqtt_client.publish = AsyncMock()

        await bridge.publish_availability(available=True)

        bridge._mqtt_client.publish.assert_called_once()
        call_kwargs = bridge._mqtt_client.publish.call_args.kwargs
        assert b'online' in call_kwargs['payload']

    @pytest.mark.asyncio
    async def test_publish_availability_offline(self) -> None:
        """Test publishing offline availability status."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        bridge._mqtt_client = MagicMock()
        bridge._mqtt_client.publish = AsyncMock()

        await bridge.publish_availability(available=False)

        call_kwargs = bridge._mqtt_client.publish.call_args.kwargs
        assert b'offline' in call_kwargs['payload']


class TestSmartTypeIcons:
    """Tests for smart detection type icon mapping."""

    def test_smart_type_icons(self) -> None:
        """Test smart type to MDI icon mapping."""
        client = create_mock_client()
        config = MQTTConfig()
        bridge = MQTTBridge(client, config)

        assert bridge._smart_type_icon('person') == 'account'
        assert bridge._smart_type_icon('vehicle') == 'car'
        assert bridge._smart_type_icon('package') == 'package'
        assert bridge._smart_type_icon('animal') == 'paw'
        assert bridge._smart_type_icon('face') == 'face-recognition'
        assert bridge._smart_type_icon('licensePlate') == 'card-text'
        assert bridge._smart_type_icon('unknown') == 'alert-circle'


class TestTopicPrefixConfiguration:
    """Tests for topic prefix configuration."""

    def test_custom_topic_prefix(self) -> None:
        """Test using custom topic prefix."""
        client = create_mock_client()
        config = MQTTConfig(topic_prefix='my/custom/prefix')
        bridge = MQTTBridge(client, config)

        event = create_protect_event(
            event_type=ProtectEventType.MOTION,
            device_id='camera-123',
        )

        messages = bridge._event_to_mqtt_messages(event)

        assert len(messages) >= 1
        assert messages[0].topic.startswith('my/custom/prefix')

    def test_custom_discovery_prefix(self) -> None:
        """Test using custom discovery prefix."""
        client = create_mock_client()
        config = MQTTConfig(discovery_prefix='custom_ha')
        bridge = MQTTBridge(client, config)

        assert config.discovery_prefix == 'custom_ha'
