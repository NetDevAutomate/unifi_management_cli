"""UniFi Protect integration package.

This package provides async integration with UniFi Protect controllers
using the uiprotect library. It includes:

- Configuration management with Pydantic validation
- Async client wrapper with connection lifecycle management
- Device models for cameras, AI Ports, sensors, and more
- WebSocket event handling for real-time updates
- Smart detection analytics and reporting

Example:
    >>> from unifi_mapper.protect import ProtectConfig, UniFiProtectClient
    >>>
    >>> config = ProtectConfig.from_env()
    >>> async with UniFiProtectClient(config) as client:
    ...     for camera in client.cameras.values():
    ...         print(f"{camera.name}: {camera.state}")
"""

from unifi_mapper.protect.client import (
    AuthenticationError,
    ConnectionError,
    ConnectionState,
    ProtectClientError,
    UniFiProtectClient,
    create_client,
)
from unifi_mapper.protect.config import ProtectConfig
from unifi_mapper.protect.models import (
    BaseDevice,
    DeviceState,
    DeviceType,
    ProtectAIPort,
    ProtectCamera,
    ProtectChime,
    ProtectDevice,
    ProtectDoorlock,
    ProtectLight,
    ProtectNVR,
    ProtectSensor,
)
from unifi_mapper.protect.repository import (
    DeviceRepository,
    ProtectDeviceCache,
)
from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectAction,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    ProtectModelType,
)
from unifi_mapper.protect.analytics import (
    CorrelatedEventGroup,
    CorrelationCallback,
    CorrelationRule,
    DeviceHealth,
    DeviceHealthStatus,
    EventAggregation,
    EventAnalytics,
    EventCount,
    SmartDetectStats,
    SmartDetectType,
    TimeWindow,
)
from unifi_mapper.protect.aiport import (
    AICapability,
    AICapabilityType,
    AIDetectionCallback,
    AIDetectionEvent,
    AIPortInfo,
    AIPortManager,
    AIPortStatus,
    PairedCamera,
)


__all__ = [
    # Configuration
    'ProtectConfig',
    # Client
    'UniFiProtectClient',
    'create_client',
    'ConnectionState',
    # Exceptions
    'ProtectClientError',
    'ConnectionError',
    'AuthenticationError',
    # Device Models
    'DeviceType',
    'DeviceState',
    'BaseDevice',
    'ProtectCamera',
    'ProtectNVR',
    'ProtectSensor',
    'ProtectLight',
    'ProtectChime',
    'ProtectDoorlock',
    'ProtectAIPort',
    'ProtectDevice',
    # Repository
    'DeviceRepository',
    'ProtectDeviceCache',
    # Events
    'EventFilter',
    'EventHandler',
    'ProtectAction',
    'ProtectEvent',
    'ProtectEventCategory',
    'ProtectEventType',
    'ProtectModelType',
    # Analytics
    'CorrelatedEventGroup',
    'CorrelationCallback',
    'CorrelationRule',
    'DeviceHealth',
    'DeviceHealthStatus',
    'EventAggregation',
    'EventAnalytics',
    'EventCount',
    'SmartDetectStats',
    'SmartDetectType',
    'TimeWindow',
    # AI Port
    'AICapability',
    'AICapabilityType',
    'AIDetectionCallback',
    'AIDetectionEvent',
    'AIPortInfo',
    'AIPortManager',
    'AIPortStatus',
    'PairedCamera',
]
