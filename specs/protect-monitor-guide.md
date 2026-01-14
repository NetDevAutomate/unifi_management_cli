# UniFi Protect Monitor Guide

Real-time monitoring tool for UniFi Protect devices with comprehensive AI analytics and debug capabilities.

## Overview

The Protect Monitor provides deep visibility into:
- **AI Ports**: Pairing status, smart detection capabilities, camera capacity
- **Cameras**: Connection state, recording status, stream routing (direct vs AI Port)
- **Smart Detection**: Person, vehicle, animal, face, license plate detection
- **Audio Detection**: Smoke alarm, CO detector, siren, baby cry, glass break, etc.
- **Events**: Real-time smart detection and motion events
- **Changes**: Instant alerts when any monitored field changes

## Quick Start

### From Project Root
```bash
# Basic monitoring (3 second poll interval)
python -m unifi_mapper.monitors.protect_monitor

# Fast polling (1 second)
python -m unifi_mapper.monitors.protect_monitor -i 1

# Log to file for later analysis
python -m unifi_mapper.monitors.protect_monitor -l /tmp/protect.log

# Quiet mode (only show changes, not full status)
python -m unifi_mapper.monitors.protect_monitor -q
```

### As a Python Module
```python
from unifi_mapper.monitors import ProtectMonitor

monitor = ProtectMonitor(
    base_url="https://192.168.125.254",
    username="Protect_Admin",
    password="your_password",
    poll_interval=3,
    log_file="/tmp/protect.log"  # Optional
)
monitor.run()
```

## CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `-u`, `--url` | UniFi controller URL | `https://192.168.125.254` |
| `--user` | Protect admin username | `Protect_Admin` |
| `--password` | Protect admin password | (configured) |
| `-i`, `--interval` | Poll interval in seconds | `3` |
| `-l`, `--log` | Log file path | None |
| `-q`, `--quiet` | Only show changes | False |

## Monitored Fields

### AI Port Fields
| Field | Description |
|-------|-------------|
| `state` | Connection state (CONNECTED, DISCONNECTED) |
| `isRecording` | Whether AI Port is actively recording |
| `pairedCameras` | List of paired camera IDs |
| `cameraId` | Active camera ID (if any) |
| `rtspClient` | RTSP client type (gstreamer, etc.) |
| `cameraCapacity` | Camera capacity info |
| `cameraUtilization` | Current utilization level |
| `smartDetectTypes` | Active detection types |
| `smartDetectAudioTypes` | Active audio detection types |
| `isSmartDetected` | Current smart detection state |
| `isMotionDetected` | Current motion detection state |
| `channels` | Video channel configurations |
| `sdCardState` | SD card status |

### Camera Fields
| Field | Description |
|-------|-------------|
| `state` | Connection state |
| `isRecording` | Recording status |
| `isPairedWithAiPort` | AI Port pairing flag |
| `aiportId` | Linked AI Port ID (critical for pairing verification) |
| `rtspUrl` | RTSP stream URL (shows if direct or via AI Port) |
| `rtspClient` | Stream client type |
| `errors` | Any stream errors |
| `smartDetectTypes` | Configured detection types |
| `isSmartDetected` | Current smart detection state |
| `currentResolution` | Active resolution |
| `videoCodec` | Active codec (h264, h265) |

## Understanding the Output

### Connection Status Icons
- 🟢 Connected
- 🔴 Disconnected
- 🔴 REC - Recording active
- ⚪ IDLE - Not recording

### AI Detection Icons
- 🏃 Motion detected
- 🤖 Smart detection active

### Stream Routing
- 🏠 DIRECT (127.0.0.1) - Stream goes directly to UDMPM
- 🔌 VIA AI PORT - Stream routed through AI Port for processing

### Pairing Status
The monitor tracks bidirectional pairing:
- **AI Port side**: `pairedCameras` array contains camera IDs
- **Camera side**: `aiportId` should contain the AI Port ID

⚠️ **Common Issue**: If `isPairedWithAiPort: True` but `aiportId: None`, the pairing is broken (one-way link).

## Example Output

```
──────────────────────────────────────────────────────────────
🔌 AI PORT: AI Port (192.168.10.22)
──────────────────────────────────────────────────────────────
  Status: 🟢 CONNECTED | ⚪ IDLE
  Uptime: 10d 14h 23m | Last Seen: 15:42:31
  Firmware: 5.1.8 | Connection Host: 192.168.10.254

  📷 Camera Pairing:
     Paired Cameras: 1 / 1
     Camera IDs: ['6961c81a00be0503e400d5df']
     Active Camera ID: None
     RTSP Client: None
     Utilization: 1 | Capacity: {'state': 'ok', 'qualities': [...]}

  🤖 AI Detection:
     Active Types: ['person', 'vehicle', 'animal', 'face', 'licensePlate']
     Audio Types: None
     Smart Zones: 1 | Motion Zones: 1

  ⚙️ Capabilities:
     Supported: person, vehicle, animal, face, licensePlate
     Audio: alrmSmoke, alrmCmonx, alrmSiren, alrmBabyCry, alrmSpeak...
     Features: SmartDetect=True LineCross=True Tracking=True

  📺 Video: HD / h264
     High: 3840x2160 @ 24fps (8.0 Mbps)
     Medium: 1280x720 @ 24fps (2.0 Mbps)
     Low: 640x360 @ 24fps (0.3 Mbps)

  💾 SD Card: unmounted (insufficient_size)

──────────────────────────────────────────────────────────────
📷 CAMERA: AXIS I8016-LVE (192.168.10.11)
──────────────────────────────────────────────────────────────
  Status: 🟢 CONNECTED | 🔴 REC
  Type: AXIS I8016-LVE | Third-Party: True
  Last Seen: 15:42:35

  🔗 AI Port Pairing:
     isPairedWithAiPort: True
     aiportId: NOT SET ❌
     AI Capacity Points: 1

  📡 Stream:
     RTSP Client: gstreamer
     RTSP URL: 🏠 DIRECT (127.0.0.1) - Stream to UDMPM
     Has Audio: None

  🤖 AI Detection:
     Active Types: ['person', 'vehicle', 'animal', 'face', 'licensePlate']
     Smart Zones: 1 | Motion Zones: 1

  📺 Video: 4K / h265
     High: 3840x2160 @ 30fps
```

## Troubleshooting

### Authentication Failed
The Protect API requires specific login flags:
```python
{
    "username": "...",
    "password": "...",
    "remember": True,   # Required!
    "strict": True      # Required!
}
```

If login fails, ensure you have a local Protect admin account (not UniFi Cloud account).

### Broken AI Port Pairing
If cameras show:
- `isPairedWithAiPort: True`
- `aiportId: None`

This indicates a one-way pairing. The camera was likely added directly via ONVIF instead of through AI Port discovery. Solution:
1. Remove camera from Protect
2. Re-add through AI Port's camera discovery
3. Verify `aiportId` is set after re-pairing

### Stream Goes Direct Instead of Through AI Port
RTSP URL showing `127.0.0.1` means the camera streams directly to UDMPM, bypassing the AI Port. This works but AI features may be limited. The AI Port pairing in this case is for metadata/features, not stream routing.

## Smart Detection Types

### Video Detection
- `person` - Human detection
- `vehicle` - Car, truck, motorcycle
- `animal` - Pet and wildlife
- `face` - Facial recognition
- `licensePlate` - License plate recognition

### Audio Detection (AI Port)
- `alrmSmoke` - Smoke alarm
- `alrmCmonx` - CO detector
- `alrmSiren` - Siren
- `alrmBabyCry` - Baby crying
- `alrmSpeak` - Speech detection
- `alrmBurglar` - Burglar alarm
- `alrmCarHorn` - Car horn
- `alrmBark` - Dog barking
- `alrmGlassBreak` - Glass breaking

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/api/auth/login` | Authentication |
| `/proxy/protect/api/bootstrap` | Full device state |
| `/proxy/protect/api/events` | Recent events |

## See Also

- [Architecture and Codemap](architecture-and-codemap.md)
- [RSPAN Limitations](rspan-limitations-and-removal.md)
