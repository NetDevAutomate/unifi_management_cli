# AXIS Provisioning Provider Architecture

> **See also**: [AXIS Provisioning Guide](../../guides/axis-provisioning.md) | [C4 Architecture](../c4-architecture.md) | [Codebase Map](../codemap.md)

## Scope

The AXIS provider covers helper scripts that provision AXIS cameras and related devices alongside the UniFi tooling. It is script-oriented rather than packaged as a first-class `unifi_mapper` provider module.

Primary responsibilities:

- Read desired camera/device configuration from YAML.
- Reconcile supported AXIS settings through VAPIX and modern JSON APIs.
- Configure MQTT where firmware exposes a supported API.
- Test ONVIF streams and snapshots where credentials are already available.
- Respect firmware limitations where AXIS has removed legacy VAPIX user-management endpoints.

## Component Diagram

```mermaid
C4Component
    title Component Diagram - AXIS Provisioning Provider

    Person(admin, "Operator", "Runs camera provisioning and stream-test scripts")

    Container_Boundary(scripts, "AXIS Scripts") {
        Component(axis_provision, "scripts/axis_provision.py", "Python", "Reads YAML desired state and reconciles supported AXIS settings")
        Component(onvif_stream, "scripts/onvif_stream.py", "Python / ONVIF", "Tests ONVIF profiles, stream URIs, and snapshots")
        Component(axis_config, "~/.config/axiscam/config.yaml", "YAML", "Desired device inventory, credentials, MQTT, and ONVIF settings")
    }

    System_Ext(axis_device, "AXIS Camera / Device", "VAPIX, JSON API, ONVIF")
    System_Ext(mqtt_broker, "MQTT Broker", "MQTT")
    System_Ext(operator_ui, "AXIS Web UI", "Manual ONVIF user fallback on newer firmware")

    Rel(admin, axis_provision, "Runs", "shell")
    Rel(admin, onvif_stream, "Runs", "shell")
    Rel(axis_provision, axis_config, "Reads desired state")
    Rel(axis_provision, axis_device, "Applies supported settings", "HTTPS VAPIX / JSON API")
    Rel(axis_provision, mqtt_broker, "Configures device MQTT target indirectly", "device-side MQTT")
    Rel(onvif_stream, axis_device, "Reads profiles and snapshot URI", "ONVIF / HTTP")
    Rel(admin, operator_ui, "Creates ONVIF users when firmware blocks API automation")
```

## PlantUML Flow

```plantuml
@startuml AxisProvisioningFlow
actor Operator
component "axis_provision.py" as Provision
database "config.yaml" as Config
component "AXIS Device" as Axis
component "MQTT Broker" as MQTT
component "AXIS Web UI" as UI

Operator --> Provision : run script
Provision --> Config : read desired state
Provision --> Axis : apply supported settings
Provision --> Axis : configure MQTT API where available
Axis --> MQTT : publish device events
Operator --> UI : create ONVIF account if firmware blocks API
@enduml
```

## Runtime Workflow

```mermaid
flowchart TD
    A([Start provisioning]) --> B[Load ~/.config/axiscam/config.yaml]
    B --> C[Iterate devices]
    C --> D{Firmware supports requested API?}
    D -->|Yes| E[Apply setting through VAPIX or JSON API]
    D -->|No| F[Report manual web UI step]
    E --> G{MQTT requested?}
    G -->|Yes| H[Configure MQTT target where supported]
    G -->|No| I[Skip MQTT]
    H --> J[Test/report result]
    I --> J
    F --> J
    J --> K{More devices?}
    K -->|Yes| C
    K -->|No| L([Provisioning report complete])
```

## Boundary Notes

- AXIS provisioning is intentionally outside the UniFi Network/Protect API clients.
- Newer AXIS OS firmware may require manual ONVIF user creation in the web UI. The script reports this limitation rather than attempting unsupported workarounds.
- MQTT configuration is device-side configuration; this repo does not act as the AXIS event bridge in the same way `protect/mqtt.py` bridges UniFi Protect events.
