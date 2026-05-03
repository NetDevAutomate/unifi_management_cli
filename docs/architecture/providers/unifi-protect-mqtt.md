# UniFi Protect and MQTT Provider Architecture

> **See also**: [C4 Architecture](../c4-architecture.md) | [Architecture Overview](../architecture-overview.md) | [Codebase Map](../codemap.md)

## Scope

The Protect provider is separate from the Network provider because UniFi Protect has different authentication, a different API model, and a real-time WebSocket event stream. The implementation lives under `src/unifi_mapper/protect/` with support code in `src/unifi_mapper/monitors/`.

The MQTT bridge turns Protect device state and events into Home Assistant-compatible MQTT discovery and state topics.

## Component Diagram

```mermaid
C4Component
    title Component Diagram - UniFi Protect and MQTT Provider

    Container_Boundary(protect, "Protect Provider") {
        Component(config, "protect/config.py / ProtectConfig", "Pydantic", "PROTECT_* environment config, SecretStr password, session/cache settings")
        Component(client, "protect/client.py / UniFiProtectClient", "asyncio + uiprotect", "Connection lifecycle, bootstrap cache, typed device properties, WebSocket subscription support")
        Component(events, "protect/events.py / EventHandler", "asyncio", "Normalises WebSocket messages into ProtectEvent records and dispatches filtered subscriptions")
        Component(models, "protect/models.py", "dataclasses", "Camera, NVR, sensor, event, and state records")
        Component(repository, "protect/repository.py", "Python", "Data access layer over ProtectApiClient/bootstrap data")
        Component(analytics, "protect/analytics.py", "Python", "Event aggregation, smart detection counts, motion statistics")
        Component(health, "protect/health.py", "asyncio", "Device health polling and transition detection")
        Component(aiport, "protect/aiport.py", "Python", "AI Port and third-party ONVIF camera support")
        Component(mqtt, "protect/mqtt.py / MQTTBridge", "asyncio + MQTT payload models", "Home Assistant discovery and state/event publishing")
        Component(monitor, "monitors/protect_monitor.py", "Python", "Long-running Protect monitoring entry point")
    }

    System_Ext(protect_controller, "UniFi Protect Controller", "REST + WebSocket")
    System_Ext(onvif_camera, "Third-party ONVIF Camera", "ONVIF via AI Port")
    System_Ext(mqtt_broker, "MQTT Broker", "MQTT")
    System_Ext(home_assistant, "Home Assistant", "MQTT discovery consumer")

    Rel(client, config, "Configured by")
    Rel(client, protect_controller, "Authenticates and loads bootstrap", "HTTPS")
    Rel(client, protect_controller, "Subscribes to real-time updates", "WSS")
    Rel(events, client, "Receives WebSocket messages")
    Rel(repository, client, "Reads bootstrap data")
    Rel(analytics, events, "Subscribes to filtered events")
    Rel(health, events, "Subscribes to state events")
    Rel(aiport, client, "Reads AI Port inventory")
    Rel(aiport, onvif_camera, "Represents third-party smart detection path")
    Rel(mqtt, events, "Subscribes to ProtectEvent stream")
    Rel(mqtt, mqtt_broker, "Publishes discovery, state, and event messages", "MQTT")
    Rel(home_assistant, mqtt_broker, "Consumes discovery and state topics", "MQTT")
    Rel(monitor, client, "Runs monitor lifecycle")
```

## PlantUML Class View

```plantuml
@startuml ProtectMqttClasses
enum ConnectionState {
  DISCONNECTED
  CONNECTING
  CONNECTED
  RECONNECTING
  ERROR
}

enum MQTTConnectionState {
  DISCONNECTED
  CONNECTING
  CONNECTED
  RECONNECTING
  FAILED
}

class ProtectConfig {
  +host: str
  +port: int
  +username: str
  +password: SecretStr
  +ws_timeout: int
  +cache_dir: Optional[Path]
  +from_env() ProtectConfig
  +to_client_kwargs() dict
}

class UniFiProtectClient {
  -_client: ProtectApiClient
  -_state: ConnectionState
  -_bootstrap: Bootstrap
  +connect() bool
  +disconnect() None
  +cameras: dict
  +ai_ports: dict
  +sensors: dict
  +lights: dict
  +api: ProtectApiClient
}

class EventHandler {
  +subscribe(callback, filter) Callable
  +unsubscribe(token) None
  -_dispatch(message) None
}

class MQTTConfig {
  +host: str
  +port: int
  +client_id: str
  +topic_prefix: str
  +discovery_prefix: str
  +qos: int
}

class MQTTBridge {
  +start() Coroutine
  +stop() Coroutine
  -_publish_event(event) Coroutine
  -_publish_discovery(device) Coroutine
}

UniFiProtectClient --> ProtectConfig : configured by
UniFiProtectClient --> ConnectionState : tracks
EventHandler --> UniFiProtectClient : subscribes to
MQTTBridge --> EventHandler : receives events from
MQTTBridge --> MQTTConfig : configured by
MQTTBridge --> MQTTConnectionState : tracks
@enduml
```

## Event Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant Controller as UniFi Protect Controller
    participant Client as UniFiProtectClient
    participant Handler as EventHandler
    participant Analytics as EventAnalytics
    participant Health as DeviceHealthMonitor
    participant MQTT as MQTTBridge
    participant Broker as MQTT Broker
    participant HA as Home Assistant

    Client->>Controller: authenticate
    Client->>Controller: load bootstrap
    Controller-->>Client: NVR, cameras, sensors, lights, AI Ports
    Client->>Controller: subscribe WebSocket
    Controller-->>Client: WS action/model/event update
    Client->>Handler: pass subscription message
    Handler->>Handler: map action, model type, event type, category
    Handler-->>Analytics: matching event callback
    Handler-->>Health: device-state event callback
    Handler-->>MQTT: MQTT bridge event callback
    MQTT->>Broker: publish unifi/protect/... state or event
    MQTT->>Broker: publish homeassistant/... discovery config
    Broker-->>HA: entity state and discovery payloads
```

## MQTT Topic Responsibilities

| Concept | Implementation | Responsibility |
| --- | --- | --- |
| Connection config | `MQTTConfig` | Broker host/port, credentials, QoS, retain behavior, topic prefixes, reconnect interval, SSL toggle. |
| Publish unit | `MQTTMessage` | Topic, payload, retain flag, QoS, JSON encoding. |
| HA device identity | `DeviceDiscoveryInfo` | Ubiquiti manufacturer metadata, identifiers, model, firmware, parent device. |
| HA entity config | `EntityDiscoveryConfig` | Component type, object ID, state topic, device class, templates, payloads, category, icon, extra config. |
| Bridge lifecycle | `MQTTBridge` | Subscribe to Protect events, publish Home Assistant discovery, publish state/event updates. |

## Current Implementation Notes

- Protect is async-first because real-time updates arrive through WebSocket subscriptions.
- `ProtectConfig` strips protocol prefixes from the host and keeps the password in `SecretStr`.
- `UniFiProtectClient` exposes the underlying `uiprotect` client through `.api` for advanced operations not wrapped by the local abstraction.
- AI Port support is part of the Protect provider, not the Network provider, because the device and smart-detection model belongs to Protect even when the camera is third-party ONVIF.
- The MQTT bridge is a downstream event consumer. It should not own Protect connection logic directly; it receives an already configured `UniFiProtectClient`.
