# AXIS Device Provisioning Guide

**Last updated**: 2026-04-06
**Audience**: Network engineers and homelab operators managing AXIS cameras and devices
**Prerequisites**: Python environment configured with `uv`, network access to AXIS devices

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Configuration](#3-configuration)
4. [Usage](#4-usage)
5. [Provisioning Workflow](#5-provisioning-workflow)
6. [What Gets Provisioned](#6-what-gets-provisioned)
7. [Firmware Limitations](#7-firmware-limitations)
8. [ONVIF Integration](#8-onvif-integration)
9. [Troubleshooting](#9-troubleshooting)
10. [Device Compatibility](#10-device-compatibility)
11. [Cross-References](#11-cross-references)

---

## 1. Overview

The AXIS provisioning system (`scripts/axis_provision.py`) automates the baseline configuration of AXIS network cameras and devices. Rather than logging in to each camera's web UI individually, you define the desired end state in a single YAML configuration file and the script reconciles each device to match.

The provisioner handles three categories of configuration:

- **User accounts** - Administrator accounts for ongoing management
- **ONVIF users** - Dedicated accounts for ONVIF-based NVR and VMS integrations
- **MQTT** - Broker connection and topic assignment for event-driven automation

The script is idempotent: running it against an already-configured device produces no changes and reports `up-to-date`. This makes it safe to run as a periodic check or after firmware upgrades.

The script uses the AXIS VAPIX API over HTTP with Digest authentication. It tries modern JSON-based APIs first and falls back to legacy CGI parameter APIs for older firmware. This dual-path approach means a single config file covers the full range of AXIS firmware generations.

---

## 2. Prerequisites

### Python Environment

The script runs in the project's `uv`-managed environment. Ensure the project dependencies are installed:

```bash
cd /path/to/unifi_management_cli
uv sync
```

Required packages (installed automatically via `uv sync`):

- `httpx` - Async HTTP client with Digest authentication support
- `pyyaml` - YAML config parsing

The ONVIF scripts (`onvif_probe.py`, `onvif_stream.py`) also need `onvif-zeep-async`. It is
a core dependency of the project, so `uv sync` installs it too; there is nothing to add.

For RTSP stream testing, `ffprobe` (part of `ffmpeg`) must be available on the system PATH:

```bash
brew install ffmpeg   # macOS
```

### Network Requirements

Each device must be reachable from the machine running the script:

- HTTP access to the device management port (default: 80)
- AXIS devices must have a working admin account whose credentials are in the config file
- If MQTT is being configured, the broker must be reachable from the device (not from the provisioning host)

### Config File Location

The default config path is `~/.config/axiscam/config.yaml`. Create the directory if it does not exist:

```bash
mkdir -p ~/.config/axiscam
```

---

## 3. Configuration

The configuration file defines all devices, the user accounts to provision, ONVIF user accounts, and the shared MQTT broker connection.

### Full Configuration Example

```yaml
# ~/.config/axiscam/config.yaml

# User accounts to ensure exist on every device
users:
  - name: camadmin
    password: "changeme-strong-password"
    role: administrator

# ONVIF user accounts for NVR/VMS integration
onvif:
  users:
    - name: onvifuser
      password: "changeme-onvif-password"

# Shared MQTT broker configuration
mqtt:
  broker: "mqtt://192.0.2.10:1883"
  username: "mqttuser"
  password: "changeme-mqtt-password"

# Device inventory
devices:
  - name: Camera_1
    address: 198.51.100.12
    port: 80
    username: root
    password: "current-device-password"
    serial: "ACCC8EXXXXXX"
    model: "P3245-V"
    vendor: AXIS
    mqtt:
      topic: "axis/camera-1"

  - name: Intercom
    address: 198.51.100.11
    port: 80
    username: root
    password: "current-device-password"
    serial: "ACCC8EYYYYYY"
    model: "A8207-VE"
    vendor: AXIS
    mqtt:
      topic: "axis/intercom"

  - name: NVR_S3008
    address: 198.51.100.20
    port: 80
    username: root
    password: "current-device-password"
    serial: "ACCC8EZZZZZ"
    model: "S3008"
    vendor: AXIS
    mqtt:
      topic: "axis/nvr-s3008"
```

### Configuration Fields Reference

#### Top-Level Keys

| Key | Required | Description |
|-----|----------|-------------|
| `users` | Yes | List of admin user accounts to provision on every device |
| `onvif.users` | No | List of ONVIF-specific user accounts |
| `mqtt` | Yes | Shared MQTT broker connection settings |
| `devices` | Yes | List of AXIS devices to manage |

#### User Account Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | - | Username to create |
| `password` | Yes | - | Account password |
| `role` | No | `administrator` | Role: `administrator`, `operator`, or `viewer` |

The `role` field maps to AXIS privilege levels: `administrator` grants full device access including configuration, `operator` grants PTZ control and live view, `viewer` grants live view only.

#### MQTT Fields

| Field | Required | Description |
|-------|----------|-------------|
| `broker` | Yes | Broker URL. Supports `mqtt://host:port` and `mqtts://host:port` (TLS) |
| `username` | Yes | MQTT broker authentication username |
| `password` | Yes | MQTT broker authentication password |

#### Device Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | Yes | - | Friendly name. Used with `--device` flag. Case-insensitive match |
| `address` | Yes | - | Device IP address or hostname |
| `port` | No | `80` | HTTP management port |
| `username` | Yes | - | Existing admin credential on the device |
| `password` | Yes | - | Existing admin password |
| `serial` | No | `""` | Device serial number. Used as the MQTT `clientId` |
| `model` | No | `""` | Model string for display and compatibility context |
| `vendor` | No | `"AXIS"` | Vendor identifier |
| `mqtt.topic` | No | `axis/{serial}` | Per-device MQTT base topic. Falls back to `axis/{serial}` if omitted |

---

## 4. Usage

All commands are run via `uv run` from the project root.

### Provision All Devices

```bash
uv run python scripts/axis_provision.py
```

Reads the default config at `~/.config/axiscam/config.yaml` and provisions every device listed.

### Dry Run (Preview Changes)

```bash
uv run python scripts/axis_provision.py --dry-run
```

Connects to each device and checks current state, but makes no changes. Reports what would be created or updated. Use this before running against devices in a production environment.

### Provision a Specific Device

```bash
uv run python scripts/axis_provision.py --device Camera_1
```

The `--device` value is matched case-insensitively against the `name` field in the config. Exits with an error if the name is not found.

### Enable Debug Logging

```bash
uv run python scripts/axis_provision.py --debug
```

Prints verbose output showing each API call, response status, and JSON payloads. Useful when diagnosing why a specific device is failing a provisioning step.

Debug and dry-run can be combined:

```bash
uv run python scripts/axis_provision.py --dry-run --debug --device Intercom
```

### Use a Custom Config Path

```bash
uv run python scripts/axis_provision.py --config /etc/axis/production.yaml
```

### CLI Flags Summary

| Flag | Argument | Description |
|------|----------|-------------|
| `--dry-run` | None | Preview mode: check state but make no changes |
| `--device` | `NAME` | Provision only this device (by name) |
| `--debug` | None | Enable verbose debug output for all API calls |
| `--config` | `PATH` | Override default config file path |

### Interpreting Output

Each provisioning task is reported with a status indicator:

```
Camera_1 (198.51.100.12) - P3245-V
  Serial: ACCC8EXXXXXX
  MQTT Topic: axis/camera-1
  o user:camadmin: User 'camadmin' already exists
  ✓ onvif:onvifuser: Created ONVIF user 'onvifuser'
  o mqtt: MQTT already configured: mqtt://192.0.2.10:1883 topic=axis/camera-1
  Status: success
```

| Icon | Meaning |
|------|---------|
| `o` | Already configured, no action taken |
| `-` | Skipped (feature not applicable to this device) |
| `✓` | Successfully created or updated |
| `✗` | Failed |

An overall `Status` line summarises the device result:

| Status | Meaning |
|--------|---------|
| `up-to-date` | All tasks already in desired state, no changes made |
| `success` | One or more tasks were created or updated successfully |
| `partial` | One or more tasks succeeded, one or more failed |
| `unreachable` | Could not connect to device |

---

## 5. Provisioning Workflow

The script processes each device independently and sequentially. Within a device, the provisioning steps run in order: connect, read current state, reconcile users, reconcile ONVIF users, reconcile MQTT.

```mermaid
sequenceDiagram
    participant Operator
    participant Script as axis_provision.py
    participant Device as AXIS Device (VAPIX)

    Operator->>Script: Run with config + flags

    Script->>Script: Load ~/.config/axiscam/config.yaml
    Script->>Script: Parse devices, users, ONVIF users, MQTT

    loop For each device
        Script->>Device: POST /axis-cgi/basicdeviceinfo.cgi (check connection)
        Device-->>Script: 200 OK or error

        alt Unreachable
            Script->>Script: Record status=unreachable, skip device
        else Connected
            Script->>Device: POST /axis-cgi/pwdgrp.cgi (get users - modern API)
            Device-->>Script: User list or error

            alt Modern API failed
                Script->>Device: GET /axis-cgi/pwdgrp.cgi?action=get (legacy API)
                Device-->>Script: User list (plain text format)
            end

            Script->>Device: POST /axis-cgi/onvifuser.cgi (get ONVIF users)
            Device-->>Script: ONVIF user list or error

            alt ONVIF JSON API unavailable
                Script->>Device: GET /axis-cgi/param.cgi?action=list&group=root.ONVIF
                Device-->>Script: ONVIF params or error
                Note over Script,Device: Falls through to endpoint probing<br/>and device capability checks
            end

            Script->>Device: POST /axis-cgi/mqtt/client.cgi (get MQTT status)
            Device-->>Script: MQTT config or error

            loop For each user in config
                alt User already exists
                    Script->>Script: Record action=none (already configured)
                else User missing
                    alt dry-run mode
                        Script->>Script: Record [DRY-RUN] message
                    else live mode
                        Script->>Device: POST /axis-cgi/user/management.cgi (createUser)
                        Device-->>Script: Success or error code 2100 (already exists)
                        alt Already exists (2100)
                            Script->>Device: POST /axis-cgi/user/management.cgi (updateUser)
                            Device-->>Script: Success or error
                        end
                        alt Modern API failed
                            Script->>Device: GET /axis-cgi/pwdgrp.cgi?action=add
                            Device-->>Script: Success or Error text
                        end
                    end
                end
            end

            loop For each ONVIF user in config
                alt ONVIF not supported
                    Script->>Script: Record action=skip
                else ONVIF user already exists
                    Script->>Script: Record action=none
                else ONVIF user missing
                    Script->>Device: POST /axis-cgi/onvifuser.cgi (addUser)
                    Device-->>Script: Success or error
                    alt Error 2100/2001 (already exists)
                        Script->>Device: POST /axis-cgi/onvifuser.cgi (updateUser)
                        Device-->>Script: Success or error
                    end
                    alt JSON API failed
                        Script->>Device: GET /axis-cgi/admin/pwdgrp.cgi?action=add (with operator:ptz)
                        Device-->>Script: Success or 403 (firmware restriction)
                    end
                end
            end

            alt MQTT already matches config
                Script->>Script: Record action=none
            else MQTT not configured or differs
                Script->>Device: POST /axis-cgi/mqtt/client.cgi (activateClient)
                Device-->>Script: Success or error
                alt MQTT JSON API unavailable
                    Script->>Device: GET /axis-cgi/param.cgi?action=update&root.MQTT.*
                    Device-->>Script: Success or Error text
                end
            end

            Script->>Script: Compute overall status
        end
    end

    Script->>Operator: Print per-device results and final summary
```

---

## 6. What Gets Provisioned

### User Accounts

The script ensures every account listed under `users` in the config exists on every device. It does not remove accounts that exist on the device but are not in the config.

API path (in order of preference):

1. `POST /axis-cgi/user/management.cgi` with `method: createUser` - modern JSON API
2. `POST /axis-cgi/user/management.cgi` with `method: updateUser` - if error code `2100` (already exists) returned
3. `GET /axis-cgi/pwdgrp.cgi?action=add` - legacy CGI fallback
4. `GET /axis-cgi/pwdgrp.cgi?action=update` - legacy update fallback

Roles map to AXIS privilege groups as follows:

| Config Role | AXIS Privilege | Access |
|-------------|----------------|--------|
| `administrator` | `admin` | Full device access including configuration |
| `operator` | `operator` | PTZ control, live view, event management |
| `viewer` | `viewer` | Live view only |

### ONVIF User Accounts

ONVIF users are dedicated accounts used by NVR and VMS systems (including UniFi Protect via third-party camera integration) to communicate via the ONVIF protocol. AXIS treats ONVIF user management separately from regular user management on modern firmware.

The script creates ONVIF users at `Operator` level, which grants access to live streams, PTZ control, and event subscriptions.

API path (in order of preference):

1. `POST /axis-cgi/onvifuser.cgi` with `method: addUser` (or `updateUser` on conflict) - modern JSON API
2. `POST /axis-cgi/useraccounts.cgi` with `method: addAccount` and viewer/operator/ptz privileges
3. `GET /axis-cgi/admin/pwdgrp.cgi?action=add` with `sgrp=operator:ptz` - admin-prefixed legacy path
4. `GET /axis-cgi/pwdgrp.cgi?action=add` with `sgrp=operator:ptz` - standard legacy path

If all methods fail with a 403 response, the script reports the firmware restriction and logs a manual action item. See [Section 7](#7-firmware-limitations) for detail.

### MQTT Configuration

The script configures the device's built-in MQTT client to connect to the shared broker defined in the config. Each device publishes to its own `mqtt_topic` (per-device override or the `axis/{serial}` default).

Parameters configured:

| Parameter | Source | Description |
|-----------|--------|-------------|
| Server host | `mqtt.broker` (hostname part) | MQTT broker IP or FQDN |
| Server port | `mqtt.broker` (port part, default 1883) | Broker port |
| Protocol | `tcp` or inferred from `mqtts://` prefix | Plain TCP or TLS |
| Client ID | `device.serial` | Unique per-device MQTT client identifier |
| Base topic | `device.mqtt.topic` | Per-device topic root |
| Auth username | `mqtt.username` | Broker authentication |
| Auth password | `mqtt.password` | Broker authentication |

API path (in order of preference):

1. `POST /axis-cgi/mqtt/client.cgi` with `method: activateClient` - modern JSON API
2. `GET /axis-cgi/param.cgi?action=update` with `root.MQTT.*` parameters - legacy fallback

MQTT configuration is skipped (reported as `up-to-date`) if the current broker host and base topic already match the config. Other MQTT parameters (port, credentials) are not checked for drift - if the broker host and topic match, the script assumes MQTT is correctly configured.

---

## 7. Firmware Limitations

### The Restriction

AXIS cameras running newer AXIS OS firmware versions (approximately 11.x and later, affecting models including the I8016-LVE, M3216-LVE, and similar modern network cameras) have restricted the legacy VAPIX CGI APIs for user management. On these devices, the `pwdgrp.cgi` endpoint returns HTTP 403 for user creation and modification requests that previously worked on older firmware.

This affects ONVIF user creation specifically. Standard user accounts can still be managed via the modern `user/management.cgi` JSON API, but ONVIF users on restricted firmware can only be created through the web UI.

```mermaid
flowchart TD
    A[Start: Configure ONVIF user] --> B{Try onvifuser.cgi JSON API}
    B -->|200 + no error| C[Done: User created via JSON API]
    B -->|200 + error 2100/2001| D[Try updateUser via JSON API]
    D -->|200 + no error| C
    D -->|error| E{Try useraccounts.cgi}
    B -->|4xx/5xx| E
    E -->|200 + no error| C
    E -->|error| F{Try admin/pwdgrp.cgi}
    F -->|200, no Error text| C
    F -->|403 or Error text| G{Try pwdgrp.cgi}
    G -->|200, no Error text| C
    G -->|403 or Error text| H[All API paths exhausted]
    H --> I[Report: Manual web UI setup required]
    I --> J[Operator action: System > ONVIF > Add account]
```

### Manual Workaround

When the script reports `ONVIF user 'X' requires manual setup via web UI (API restricted on this firmware)`, perform the following steps on the affected device:

1. Open a browser and navigate to `http://<device-address>/`
2. Log in with your administrator account
3. Go to **System** > **ONVIF**
4. Click **Add account**
5. Enter the username and password from your `onvif.users` config
6. Set the access level to **Operator**
7. Click **Save**

After the manual step, re-run the provisioner with `--dry-run` to confirm the ONVIF user is now detected:

```bash
uv run python scripts/axis_provision.py --dry-run --device Camera_1
```

If the ONVIF user created via the web UI is returned by the `onvifuser.cgi` API, the provisioner will detect it and report `action: none` on subsequent runs.

### Affected vs. Unaffected Devices

| Firmware Generation | User API | ONVIF via Script |
|--------------------|----------|-----------------|
| Older AXIS OS (pre-11.x) | Legacy `pwdgrp.cgi` | Fully automated |
| Newer AXIS OS (11.x+) | Modern `user/management.cgi` JSON API | Manual web UI required |
| NVR S3008 | Legacy `pwdgrp.cgi` | Fully automated |
| AXIS speakers (legacy) | Legacy `pwdgrp.cgi` | Fully automated |

The MQTT and standard user provisioning is not affected by this restriction. Only ONVIF-specific user creation via `pwdgrp.cgi` legacy paths is blocked on newer firmware.

This is an AXIS firmware design decision to migrate administration to the web interface and is not a bug in the provisioning script. There is no known supported API to work around it without AXIS providing a new API endpoint.

---

## 8. ONVIF Integration

### What ONVIF Provides

ONVIF (Open Network Video Interface Forum) is a standards-based protocol for IP cameras that enables NVR and VMS systems to discover cameras, manage media streams, subscribe to events, and control PTZ without vendor-specific integration. UniFi Protect uses ONVIF to integrate third-party cameras as "managed" devices.

The AXIS provisioner creates a dedicated ONVIF user account (separate from administrative accounts) as a security best practice. This account has operator-level privileges: it can authenticate ONVIF sessions and access streams, but cannot change device configuration.

### ONVIF Detection in the Provisioner

The provisioner uses a four-method detection chain to determine whether a device supports ONVIF and to retrieve existing ONVIF users:

```
Method 1: POST /axis-cgi/onvifuser.cgi (getUsers)
  - Modern firmware: returns JSON user list
  - If successful: return users and mark onvif_supported=True

Method 2: GET /axis-cgi/param.cgi?action=list&group=root.ONVIF
  - Legacy firmware: returns ONVIF parameter group
  - If present: query pwdgrp.cgi for digusers (digest auth users)

Method 3: Probe ONVIF service endpoints
  Endpoints tried:
    - /onvif/device_service
    - /onvif/media_service
    - /onvif-http/
    - /vapix/services
  - HTTP 200, 401, 405, or 500 = endpoint exists = ONVIF supported

Method 4: Device capability inspection
  - POST /axis-cgi/basicdeviceinfo.cgi (getAllProperties)
  - ProdType of "Network Camera", "PTZ Dome Camera", or "Dome Camera"
    implies ONVIF support regardless of endpoint probe results
```

If all four methods fail to confirm ONVIF support, the device is treated as non-ONVIF and ONVIF user provisioning is skipped (reported as `action: skip`).

### Testing ONVIF Connectivity

Two scripts are provided to validate ONVIF integration after provisioning. Both connect to
real cameras, so neither is part of the pytest suite.

#### Camera List and Credentials

Neither script keeps a camera address, name or password in the repository. Both read three
environment variables, through `scripts/onvif_config.py`:

| Variable | Value |
| --- | --- |
| `ONVIF_USERNAME` | The ONVIF account on the cameras (an `onvif.users` entry in the config above) |
| `ONVIF_PASSWORD` | That account's password |
| `ONVIF_CAMERAS` | Comma-separated `NAME=HOST[:PORT]` entries; the port defaults to 80. `HOST` is a name or an IPv4 address (IPv6 literals aren't supported) |

Keep them in a file outside the repository, for example `~/.config/axiscam/onvif.env`.
Create it with an editor rather than a shell command, so the password stays out of your
shell history:

```text
ONVIF_USERNAME=onvifuser
ONVIF_PASSWORD=<password>
ONVIF_CAMERAS='Intercom=198.51.100.11,Camera_1=198.51.100.12'
```

Then make it readable only by you, and pass it to each run with `uv run --env-file`:

```bash
chmod 600 ~/.config/axiscam/onvif.env
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_probe.py
```

If a variable is unset or empty, or an `ONVIF_CAMERAS` entry is malformed, the script exits
with status 1 before it connects to any camera, and the message names what to set (never the
password). `unifi-mapper` and `unifi-mcp` don't read these variables.

#### Basic ONVIF Probe (`onvif_probe.py`)

Tests connection, retrieves device information, enumerates capabilities, and lists media profiles with stream URIs, for every camera in `ONVIF_CAMERAS`.

Run:

```bash
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_probe.py
```

Expected successful output:

```
============================================================
Testing ONVIF: 198.51.100.12:80 as onvifuser
============================================================

Connection successful!
   Manufacturer: AXIS
   Model: P3245-V
   Firmware: 9.80.3.1
   Serial: ACCC8EXXXXXX

Capabilities:
   Media: True
   PTZ: False
   Events: True

Media Profiles (2):
   - profile_1_h264: 1920x1080
     Stream: rtsp://198.51.100.12/axis-media/media.amp?videocodec=h264&profile=1
   - profile_2_h264: 1280x720
     Stream: rtsp://198.51.100.12/axis-media/media.amp?videocodec=h264&profile=2
```

#### Stream and Snapshot Test (`onvif_stream.py`)

Provides four subcommands for stream validation. Each runs against every camera in `ONVIF_CAMERAS`, as the `ONVIF_USERNAME` account:

```bash
# Display device information (manufacturer, model, firmware, serial)
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_stream.py info

# List all stream URIs for each media profile
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_stream.py streams

# Capture a JPEG snapshot from each camera (saved to /tmp/)
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_stream.py snapshot

# Test RTSP connectivity using ffprobe (requires ffmpeg installed)
uv run --env-file ~/.config/axiscam/onvif.env python scripts/onvif_stream.py test-rtsp
```

#### AXIS XAddr Localhost Bug

AXIS cameras sometimes return `127.0.0.1` as the service address (`XAddr`) in ONVIF discovery responses. This causes connection failures when the ONVIF client tries to call a service using the returned localhost address.

The `onvif_stream.py` script corrects this automatically by replacing `127.0.0.1` with the camera's actual IP address after discovery:

```python
for service_name, xaddr in camera.xaddrs.items():
    if "127.0.0.1" in xaddr or "localhost" in xaddr:
        fixed_xaddr = xaddr.replace("127.0.0.1", config.ip)
        camera.xaddrs[service_name] = fixed_xaddr
```

If you write custom ONVIF integration code against AXIS cameras, apply the same XAddr correction.

#### RTSP Authenticated URIs

ONVIF `GetStreamUri` returns an RTSP URI without embedded credentials. To play the stream in VLC, ffplay, or pass it to UniFi Protect for testing, embed credentials in the URI:

```
# Bare URI from ONVIF:
rtsp://198.51.100.12/axis-media/media.amp?videocodec=h264

# With credentials embedded:
rtsp://onvifuser:<password>@198.51.100.12/axis-media/media.amp?videocodec=h264
```

The `streams` subcommand prints the bare URI and the authenticated form with the password
masked (`onvifuser:***@`), and `test-rtsp` prints the masked form. Error text, including the
ffprobe excerpt, is masked the same way, so neither command shows `ONVIF_PASSWORD`. To play a
stream, build the authenticated form by hand from the masked line. `test-rtsp` passes the
credentials to ffprobe on its command line, so other local users can see them in the process
list while it runs ([issue 057](../issues/057-onvif-test-rtsp-puts-the-password-on-argv.md)).

---

## 9. Troubleshooting

### Diagnostic Flowchart

```mermaid
flowchart TD
    A[Provisioning run has errors] --> B{Device status?}

    B -->|unreachable| C[Connection problem]
    B -->|partial| D[Some tasks failed]
    B -->|success or up-to-date| Z[No issue - check output for detail]

    C --> C1{Can you ping the device?}
    C1 -->|No| C2[Check network: VLAN, firewall, ARP table]
    C1 -->|Yes| C3{Does the management port respond?}
    C3 -->|No| C4[Check: is port 80 open? Try curl http://device-ip/]
    C3 -->|Yes| C5{Does Digest auth work?}
    C5 -->|No| C6[Check username/password in config matches device]
    C5 -->|Yes| C7[Run with --debug to inspect API response details]

    D --> D1{Which task failed?}
    D1 -->|user:name| E[User creation failed]
    D1 -->|onvif:name| F[ONVIF user failed]
    D1 -->|mqtt| G[MQTT configuration failed]

    E --> E1{Error message contains...}
    E1 -->|403 Forbidden| E2[Check admin privilege of existing credential]
    E1 -->|connection error| C
    E1 -->|unexpected| E3[Run with --debug for API call detail]

    F --> F1{Error message contains...}
    F1 -->|requires manual setup via web UI| F2[Firmware restriction - see Section 7]
    F1 -->|403 Forbidden| F3[Confirm admin credential has full access]
    F1 -->|ONVIF not supported| F4[Device does not support ONVIF - expected for some devices]
    F1 -->|other| F5[Run with --debug, check onvifuser.cgi responses]

    G --> G1{Error message contains...}
    G1 -->|not supported on this device| G2[Device lacks MQTT support - confirm firmware has MQTT feature]
    G1 -->|connection error| C
    G1 -->|other| G3[Run with --debug, check mqtt/client.cgi responses]
```

### Common Issues and Resolutions

**Device reports `unreachable` but the device is online**

The connectivity check (`basicdeviceinfo.cgi`) may fail if the admin credentials in the config no longer match the device - a failed authentication returns a non-200 status which the provisioner treats as an unreachable device. Run with `--debug` to distinguish authentication failure from network failure:

```bash
uv run python scripts/axis_provision.py --debug --device DeviceName
```

If the debug output shows `status=401`, the credential in the config is wrong. If it shows a connection exception, the device is genuinely unreachable.

**ONVIF probe script fails with `[Errno 111] Connection refused` on port 80**

The `onvif_probe.py` and `onvif_stream.py` scripts connect to port 80 by default. Some AXIS camera models redirect HTTP to HTTPS. Check whether the device is accessible on port 443 and, if so, give that camera's `ONVIF_CAMERAS` entry the port (`NAME=HOST:443`).

**ONVIF `GetStreamUri` returns `127.0.0.1` in the RTSP URI**

This is the AXIS XAddr localhost bug described in Section 8. The `onvif_stream.py` script corrects this automatically. In custom code, replace `127.0.0.1` with the camera IP before using any URI returned by ONVIF discovery or `GetStreamUri`.

**MQTT configuration succeeds but device does not connect to broker**

MQTT connectivity is from the camera to the broker, not from the provisioning host. Verify:

1. The broker address and port in the config are reachable from the camera's network segment
2. The broker allows connections from the device's IP (check broker ACLs)
3. The MQTT username/password are valid on the broker
4. If using `mqtts://`, the device trusts the broker's TLS certificate

Use `--debug` to confirm the API call succeeded (`MQTT client API: status=200` with no error in the response), which means configuration was accepted by the device.

**MQTT `existing_mqtt` check always triggers reconfiguration**

The MQTT idempotency check compares `current_host` and `current_topic` from the device's reported MQTT state. If the broker was configured via a different API path (e.g., directly through the web UI), the field names in the response may differ from what the script expects (`host` vs `server.host`, `basetopic` vs `baseTopic`). The script handles both field name variants, but if neither matches, it will reconfigure MQTT on every run. Run `--debug` to inspect the raw `getClientStatus` response and confirm the field names being returned.

**`Error: Config file not found`**

The default config path is `~/.config/axiscam/config.yaml`. Either create the file at that path or pass the path explicitly:

```bash
uv run python scripts/axis_provision.py --config /path/to/your/config.yaml
```

**`Error: Device 'Name' not found in config`**

The `--device` flag matches against the `name` field in the config (case-insensitive). Verify the name exactly matches a device entry. List available device names by checking the config file.

---

## 10. Device Compatibility

The following table summarises tested AXIS devices and their provisioning support levels. "Full" means all three provisioning tasks (user accounts, ONVIF users, MQTT) succeed automatically. "Partial" means one or more tasks require manual intervention.

| Device Model | Firmware Generation | User Accounts | ONVIF Users | MQTT | Notes |
|-------------|--------------------|----|------|------|-------|
| AXIS S3008 NVR | Older AXIS OS | Full | Full (via legacy API) | Full | Legacy CGI APIs available |
| AXIS P3245-V | Older AXIS OS | Full | Full (via legacy API) | Full | Legacy CGI APIs available |
| AXIS A8207-VE | Older AXIS OS | Full | Full (via legacy API) | Full | Intercom/door station |
| AXIS I8016-LVE | AXIS OS 11.x+ | Full | Manual (web UI) | Full | ONVIF API restricted |
| AXIS M3216-LVE | AXIS OS 11.x+ | Full | Manual (web UI) | Full | ONVIF API restricted |
| AXIS speakers (legacy) | Older firmware | Full | Skipped (no ONVIF) | Full | Non-camera devices, ONVIF not applicable |

Support levels:

- **Full** - Provisioning step completes automatically via script
- **Manual (web UI)** - Provisioning step requires manual completion in the device web UI (see Section 7)
- **Skipped** - Feature is not supported by the device; the script skips this step without error

This table reflects devices tested in this specific environment. Other AXIS models not listed here will follow the same pattern: devices running AXIS OS 11.x+ are likely to require manual ONVIF user creation, while devices on older firmware generations are likely to support full automation.

---

## 11. Cross-References

- [Architecture Overview](../architecture/architecture-overview.md) - System-level view of the UniFi Management CLI, including external integrations and the AXIS provisioning script's place in the broader toolset
- [Troubleshooting and Runbook](../operations/troubleshooting-and-runbook.md) - General troubleshooting procedures for the UniFi Management CLI, including authentication failures, API errors, and operational runbook procedures
