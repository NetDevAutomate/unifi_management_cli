# UniFi Protect and AXIS camera integration

The Protect library, its Home Assistant MQTT bridge and the Protect monitor, and the AXIS device
provisioning script, moved here from the README. The Protect MCP tools are unverified against a
live console ([issue 034](../issues/034-protect-has-no-live-account.md)); MQTT needs `aiomqtt`,
which the project does not declare ([issue 074](../issues/074-mqtt-needs-an-undeclared-dependency.md)).

# UniFi Protect Integration

Comprehensive async Python library for UniFi Protect with real-time event processing and Home Assistant integration.

> [!NOTE]
> Connect with a dedicated local, view-only Protect account, not the console's admin login.
> The MCP Protect tools use this library behind a read-only client and haven't been verified
> against a live console yet ([issue 034](../issues/034-protect-has-no-live-account.md)).

## Features

| Feature | Description |
|---------|-------------|
| Event Analytics | Real-time event correlation and smart detection tracking |
| AI Port Management | Smart detection subscriptions with paired camera tracking |
| Health Monitoring | Proactive device health tracking with configurable thresholds |
| MQTT Bridge | Home Assistant integration with automatic device discovery |

## Basic Usage

```python
from unifi_mapper.protect import ProtectConfig, UniFiProtectClient

config = ProtectConfig(
    host="192.0.2.1",
    username="protect-viewer",
    password="your_password",
    verify_ssl=False,
)

async with UniFiProtectClient(config) as client:
    for camera in client.cameras.values():
        print(f"{camera.name}: {camera.state}")
```

## MQTT Bridge for Home Assistant

The bridge needs the `aiomqtt` package, which the project does not declare yet
([issue 074](../issues/074-mqtt-needs-an-undeclared-dependency.md)), so `uv sync` leaves it
out and `bridge.start()` raises `ImportError`. Add it to your project with `uv add aiomqtt`,
or run a script with `uv run --with aiomqtt python your_script.py`, which changes no
project file.

```python
from unifi_mapper.protect import MQTTBridge, MQTTConfig

mqtt_config = MQTTConfig(
    host="192.0.2.100",
    port=1883,
    topic_prefix="unifi/protect",
    discovery_prefix="homeassistant",
)

async with UniFiProtectClient(protect_config) as client:
    bridge = MQTTBridge(client, mqtt_config)
    await bridge.start()
```

The bridge automatically creates Home Assistant entities for cameras, doorbells, sensors, and smart detections.

## Protect Monitor

A terminal monitor that polls Protect and prints AI-port pairing, cameras, smart and audio
detection, and stream and recording health, then each change as it is seen. It reads the
console from `PROTECT_HOST`, `PROTECT_USERNAME` and `PROTECT_PASSWORD` (the same view-only
account as above):

```bash
uv run python -m unifi_mapper.monitors.protect_monitor          # poll every 3 s
uv run python -m unifi_mapper.monitors.protect_monitor -i 1     # every second
uv run python -m unifi_mapper.monitors.protect_monitor -q       # changes only
uv run python -m unifi_mapper.monitors.protect_monitor -l ~/tmp/protect-monitor.log
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `-i`, `--interval SECONDS` | 3 | Seconds between polls |
| `-q`, `--quiet` | off | Print only changes, not the full status each poll |
| `-l`, `--log PATH` | none | Append each change and status message to this file |
| `-u`, `--url URL` | `$PROTECT_HOST` | The console's address |
| `--user NAME` | `$PROTECT_USERNAME` | The Protect account |
| `--password VALUE` | `$PROTECT_PASSWORD` | Its password. Prefer the variable: a password on the command line is visible to other processes and kept in shell history |

Stop it with Ctrl-C.

# AXIS Device Provisioning

> For the full provisioning guide including workflow diagrams, configuration reference, and troubleshooting, see [AXIS Provisioning Guide](../guides/axis-provisioning.md).

The `scripts/axis_provision.py` script automates AXIS camera and device configuration:

```bash
# Provision all devices from config
uv run python scripts/axis_provision.py

# Preview changes without applying
uv run python scripts/axis_provision.py --dry-run

# Provision specific device
uv run python scripts/axis_provision.py --device Camera_1

# Enable debug logging
uv run python scripts/axis_provision.py --debug
```

**Configuration:** `~/.config/axiscam/config.yaml`

## Firmware Limitations

Cameras with newer AXIS OS firmware (I8016-LVE, M3216-LVE, and similar models) have restricted the legacy VAPIX CGI APIs for user management. On these devices:

- **ONVIF users** must be created manually via the web UI: **System → ONVIF → Add account**
- **MQTT configuration** works via the modern JSON API and provisions correctly

This is an AXIS firmware decision to deprecate legacy APIs in favour of the web interface. The script cannot work around this limitation without AXIS providing a supported API for ONVIF user management.

Older devices (NVR S3008, speakers, legacy cameras) continue to work with full automated provisioning.
