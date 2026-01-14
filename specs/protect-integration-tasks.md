# UniFi Protect Integration Tasks

## Overview

Integration plan for adding robust UniFi Protect functionality using the `uiprotect` Python library, replacing the current manual HTTP API implementation with a production-grade async client with WebSocket support.

## Current State

The project has a basic `ProtectMonitor` class (`src/unifi_mapper/monitors/protect_monitor.py`) that:
- Uses synchronous `requests` library for HTTP calls
- Polls the `/proxy/protect/api/bootstrap` endpoint
- Extracts AI Port and camera state
- Detects changes between polls
- No WebSocket support (polling only)

## Target State

A comprehensive Protect integration using `uiprotect` that provides:
- Async client with proper connection management
- Real-time WebSocket event streaming
- Full device type support (cameras, AI Ports, sensors, chimes, lights, door locks)
- Smart detection event handling
- Livestream access capability
- Proper error handling and reconnection logic

---

## Phase 1: Foundation Setup

### Task 1.1: Add uiprotect dependency
**Priority**: High | **Effort**: Low

```bash
uv add uiprotect
# or: pip install git+https://github.com/uilibs/uiprotect.git#egg=uiprotect
```

**Files to modify**:
- `pyproject.toml` - Add uiprotect dependency

---

### Task 1.2: Create Protect API client wrapper
**Priority**: High | **Effort**: Medium

Create an async wrapper around `uiprotect.ProtectApiClient` with:
- Connection management (connect/disconnect)
- Credential handling from config
- Bootstrap data caching
- Error handling and retry logic

**New file**: `src/unifi_mapper/protect/client.py`

```python
from uiprotect import ProtectApiClient
from uiprotect.data import Bootstrap

class UniFiProtectClient:
    """Async UniFi Protect API client wrapper."""

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def get_bootstrap(self) -> Bootstrap: ...
    async def refresh(self) -> None: ...

    @property
    def cameras(self) -> dict[str, Camera]: ...
    @property
    def ai_ports(self) -> dict[str, AIPort]: ...
    @property
    def sensors(self) -> dict[str, Sensor]: ...
```

---

### Task 1.3: Create configuration schema for Protect
**Priority**: High | **Effort**: Low

Add Protect-specific configuration to the existing config system:

**Modify**: `src/unifi_mapper/config.py`

```python
@dataclass
class ProtectConfig:
    host: str
    port: int = 443
    username: str
    password: str
    verify_ssl: bool = False
```

**Environment variables**:
```
PROTECT_HOST=192.168.1.1
PROTECT_PORT=443
PROTECT_USERNAME=admin
PROTECT_PASSWORD=secret
PROTECT_VERIFY_SSL=false
```

---

## Phase 2: Device Models & Data Layer

### Task 2.1: Create Pydantic models for Protect devices
**Priority**: High | **Effort**: Medium

Create type-safe models for all Protect device types:

**New file**: `src/unifi_mapper/protect/models.py`

```python
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class SmartDetectSettings(BaseModel):
    object_types: List[str] = []
    audio_types: List[str] = []
    sensitivity: int = 50

class CameraState(BaseModel):
    id: str
    name: str
    ip: str
    state: str  # CONNECTED, DISCONNECTED
    is_recording: bool
    is_third_party: bool
    is_paired_with_ai_port: bool
    ai_port_id: Optional[str]
    smart_detect_types: List[str]
    current_resolution: str
    video_codec: str
    last_motion: Optional[datetime]
    last_smart_detect: Optional[datetime]

class AIPortState(BaseModel):
    id: str
    name: str
    ip: str
    state: str
    firmware: str
    paired_cameras: List[str]
    camera_capacity: int
    camera_utilization: int
    smart_detect_types: List[str]
    is_recording: bool

class SmartDetectEvent(BaseModel):
    id: str
    camera_id: str
    camera_name: str
    event_type: str  # person, vehicle, animal, package, etc.
    score: float  # Confidence 0-100
    start: datetime
    end: Optional[datetime]
    thumbnail_id: Optional[str]
```

---

### Task 2.2: Create device repository/cache
**Priority**: Medium | **Effort**: Medium

Implement a device cache for efficient lookups:

**New file**: `src/unifi_mapper/protect/repository.py`

```python
class ProtectDeviceRepository:
    """In-memory cache of Protect devices with change tracking."""

    def __init__(self, client: UniFiProtectClient): ...

    async def refresh(self) -> None: ...

    def get_camera(self, id: str) -> Optional[CameraState]: ...
    def get_ai_port(self, id: str) -> Optional[AIPortState]: ...
    def get_cameras_by_ai_port(self, ai_port_id: str) -> List[CameraState]: ...
    def get_third_party_cameras(self) -> List[CameraState]: ...

    def detect_changes(self, previous: 'ProtectDeviceRepository') -> List[DeviceChange]: ...
```

---

## Phase 3: Real-Time Events (WebSocket)

### Task 3.1: Implement WebSocket event handler
**Priority**: High | **Effort**: High

Create real-time event handling using uiprotect's WebSocket subscription:

**New file**: `src/unifi_mapper/protect/events.py`

```python
from uiprotect.data import WSSubscriptionMessage
from typing import Callable, Awaitable

EventCallback = Callable[[WSSubscriptionMessage], Awaitable[None]]

class ProtectEventHandler:
    """Handles real-time events from Protect WebSocket."""

    def __init__(self, client: UniFiProtectClient): ...

    async def start(self) -> None:
        """Start WebSocket subscription."""
        self.unsub = self.client.subscribe_websocket(self._handle_event)

    async def stop(self) -> None:
        """Stop WebSocket subscription."""
        if self.unsub:
            self.unsub()

    async def _handle_event(self, msg: WSSubscriptionMessage) -> None:
        """Process incoming WebSocket messages."""
        ...

    def on_motion(self, callback: EventCallback) -> None: ...
    def on_smart_detect(self, callback: EventCallback) -> None: ...
    def on_device_update(self, callback: EventCallback) -> None: ...
    def on_ring(self, callback: EventCallback) -> None: ...
```

---

### Task 3.2: Create event types and filters
**Priority**: Medium | **Effort**: Low

Define event types and filtering capabilities:

```python
class EventType(Enum):
    MOTION = "motion"
    SMART_DETECT = "smartDetectZone"
    RING = "ring"
    DEVICE_UPDATE = "update"
    DEVICE_ADD = "add"

class EventFilter:
    """Filter events by type, device, or smart detect category."""

    def __init__(
        self,
        event_types: Optional[List[EventType]] = None,
        camera_ids: Optional[List[str]] = None,
        smart_detect_types: Optional[List[str]] = None,  # person, vehicle, etc.
    ): ...
```

---

## Phase 4: Enhanced Monitor

### Task 4.1: Refactor ProtectMonitor to use uiprotect
**Priority**: High | **Effort**: High

Refactor the existing `ProtectMonitor` class to:
- Use async/await pattern
- Use `uiprotect.ProtectApiClient` instead of raw requests
- Add WebSocket support for real-time updates
- Remove polling in favor of event-driven updates

**Modify**: `src/unifi_mapper/monitors/protect_monitor.py`

Key changes:
```python
class ProtectMonitor:
    def __init__(self, config: ProtectConfig):
        self.client = UniFiProtectClient(config)
        self.event_handler = ProtectEventHandler(self.client)
        self.repository = ProtectDeviceRepository(self.client)

    async def start(self) -> None:
        """Start monitoring with WebSocket events."""
        await self.client.connect()
        await self.repository.refresh()
        await self.event_handler.start()

        # Register event callbacks
        self.event_handler.on_smart_detect(self._on_smart_detect)
        self.event_handler.on_motion(self._on_motion)
        self.event_handler.on_device_update(self._on_device_update)

    async def _on_smart_detect(self, event: SmartDetectEvent) -> None:
        """Handle smart detection events."""
        ...
```

---

### Task 4.2: Add TUI dashboard for real-time monitoring
**Priority**: Low | **Effort**: Medium

Create a rich TUI dashboard using `rich` library:

**New file**: `src/unifi_mapper/protect/dashboard.py`

Features:
- Live device status table
- Event log panel
- Smart detect statistics
- AI Port utilization graphs

---

## Phase 5: AI Detection Analytics

### Task 5.1: Create SmartDetect analytics module
**Priority**: Medium | **Effort**: Medium

Track and analyze smart detection patterns:

**New file**: `src/unifi_mapper/protect/analytics.py`

```python
class SmartDetectAnalytics:
    """Analyze smart detection events and patterns."""

    async def get_detection_summary(
        self,
        camera_id: Optional[str] = None,
        hours: int = 24
    ) -> DetectionSummary: ...

    async def get_hourly_breakdown(
        self,
        detection_type: str,
        days: int = 7
    ) -> List[HourlyStats]: ...

    async def get_camera_activity_ranking(self) -> List[CameraActivity]: ...
```

---

### Task 5.2: Add event export capabilities
**Priority**: Low | **Effort**: Low

Export events to various formats:

```python
class EventExporter:
    async def export_to_json(self, events: List[Event], path: Path) -> None: ...
    async def export_to_csv(self, events: List[Event], path: Path) -> None: ...
    async def export_thumbnails(self, events: List[Event], dir: Path) -> None: ...
```

---

## Phase 6: CLI Integration

### Task 6.1: Add Protect commands to Typer CLI
**Priority**: High | **Effort**: Medium

Add new CLI commands for Protect functionality:

**Modify**: `src/unifi_mapper/typer_cli.py`

```bash
# Device listing
unifi-mapper protect devices
unifi-mapper protect cameras
unifi-mapper protect ai-ports
unifi-mapper protect sensors

# Real-time monitoring
unifi-mapper protect monitor
unifi-mapper protect events --follow

# Smart detection
unifi-mapper protect smart-detect summary
unifi-mapper protect smart-detect events --type person --hours 24

# Snapshots
unifi-mapper protect snapshot <camera-name> -o snapshot.jpg
```

---

### Task 6.2: Add async CLI runner
**Priority**: Medium | **Effort**: Low

Set up async support for CLI commands:

```python
import asyncio
from functools import wraps

def async_command(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@app.command()
@async_command
async def monitor():
    """Start real-time Protect monitoring."""
    ...
```

---

## Phase 7: Integration & Testing

### Task 7.1: Create integration tests
**Priority**: Medium | **Effort**: Medium

**New file**: `tests/protect/test_client.py`

Test scenarios:
- Connection and authentication
- Bootstrap data retrieval
- WebSocket event handling
- Device state tracking
- Error handling and reconnection

---

### Task 7.2: Add mock fixtures for offline testing
**Priority**: Medium | **Effort**: Low

Create mock responses for testing without a live controller:

**New file**: `tests/protect/fixtures/`
- `bootstrap.json` - Sample bootstrap response
- `events.json` - Sample event data
- `cameras.json` - Sample camera configs

---

## Phase 8: Documentation

### Task 8.1: Update README with Protect features
**Priority**: High | **Effort**: Low

Add documentation for:
- Installation and configuration
- Available CLI commands
- Usage examples
- API reference links

---

### Task 8.2: Add architecture documentation
**Priority**: Low | **Effort**: Low

Document the Protect integration architecture:
- Component diagram
- Event flow diagram
- Configuration reference

---

## Dependencies

### Required Packages
```toml
[project.dependencies]
uiprotect = ">=7.0.0"  # UniFi Protect API client
```

### Optional Packages (for enhanced features)
```toml
[project.optional-dependencies]
protect-extras = [
    "pillow>=10.0.0",    # Thumbnail processing
    "av>=10.0.0",        # Video/audio processing (for talkback)
]
```

---

## Migration Notes

### Breaking Changes
- `ProtectMonitor` will become async-only
- Configuration format changes (new environment variables)
- Event callback signatures change

### Backward Compatibility
- Keep legacy synchronous wrapper for simple use cases
- Support both old and new config formats during transition

---

## Timeline Estimate

| Phase | Tasks | Priority |
|-------|-------|----------|
| Phase 1: Foundation | 1.1-1.3 | High |
| Phase 2: Models | 2.1-2.2 | High |
| Phase 3: Events | 3.1-3.2 | High |
| Phase 4: Monitor | 4.1-4.2 | High/Low |
| Phase 5: Analytics | 5.1-5.2 | Medium/Low |
| Phase 6: CLI | 6.1-6.2 | High/Medium |
| Phase 7: Testing | 7.1-7.2 | Medium |
| Phase 8: Docs | 8.1-8.2 | High/Low |

---

## References

- [uiprotect GitHub](https://github.com/uilibs/uiprotect)
- [uiprotect Documentation](https://uiprotect.readthedocs.io/)
- [hjdhjd/unifi-protect (TypeScript)](https://github.com/hjdhjd/unifi-protect) - Protocol reference
- [UniFi Protect API (unofficial)](https://github.com/hjdhjd/unifi-protect/blob/main/docs/ProtectApi.md)
