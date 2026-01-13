"""AI Port management for UniFi Protect.

This module provides enhanced capabilities for managing UniFi AI Ports,
including paired camera tracking, smart detection configuration, and
AI-specific analytics.

Example:
    >>> from unifi_mapper.protect import UniFiProtectClient
    >>> from unifi_mapper.protect.aiport import AIPortManager
    >>>
    >>> async with UniFiProtectClient(config) as client:
    ...     manager = AIPortManager(client)
    ...     for aiport in manager.get_all_aiports():
    ...         print(f"{aiport.name}: {len(aiport.paired_cameras)} cameras")
    ...         for cap in manager.get_capabilities(aiport.id):
    ...             print(f"  - {cap.name}: {cap.enabled}")
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger  # type: ignore[import-untyped]

from unifi_mapper.protect.analytics import SmartDetectType
from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectEvent,
    ProtectEventCategory,
    UnsubscribeFunc,
)
from unifi_mapper.protect.models import DeviceState, ProtectAIPort, ProtectCamera


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


class AICapabilityType(str, Enum):
    """Types of AI detection capabilities."""

    PERSON = 'person'
    VEHICLE = 'vehicle'
    ANIMAL = 'animal'
    PACKAGE = 'package'
    FACE = 'face'
    LICENSE_PLATE = 'licensePlate'
    SMOKE = 'smoke'
    CARBON_MONOXIDE = 'cmonx'


class AIPortStatus(str, Enum):
    """Status of an AI Port."""

    ONLINE = 'online'
    OFFLINE = 'offline'
    PROCESSING = 'processing'
    IDLE = 'idle'
    ERROR = 'error'
    UPDATING = 'updating'


@dataclass
class AICapability:
    """Represents an AI detection capability.

    Attributes:
        capability_type: The type of AI detection.
        enabled: Whether this capability is enabled.
        available: Whether the AI Port supports this capability.
        confidence_threshold: Minimum confidence for detections (0.0-1.0).
        last_detection: Last time this type was detected.
        detection_count: Total detections of this type.
    """

    capability_type: AICapabilityType
    enabled: bool = False
    available: bool = True
    confidence_threshold: float = 0.5
    last_detection: datetime | None = None
    detection_count: int = 0

    @property
    def name(self) -> str:
        """Get human-readable capability name."""
        names = {
            AICapabilityType.PERSON: 'Person Detection',
            AICapabilityType.VEHICLE: 'Vehicle Detection',
            AICapabilityType.ANIMAL: 'Animal Detection',
            AICapabilityType.PACKAGE: 'Package Detection',
            AICapabilityType.FACE: 'Face Recognition',
            AICapabilityType.LICENSE_PLATE: 'License Plate Recognition',
            AICapabilityType.SMOKE: 'Smoke Detection',
            AICapabilityType.CARBON_MONOXIDE: 'Carbon Monoxide Detection',
        }
        return names.get(self.capability_type, self.capability_type.value)


@dataclass
class PairedCamera:
    """Represents a camera paired with an AI Port.

    Attributes:
        camera_id: The camera's unique identifier.
        camera_name: Human-readable camera name.
        aiport_id: The AI Port this camera is paired with.
        smart_detect_enabled: Whether smart detection is enabled.
        detection_zones: Number of configured smart detection zones.
        last_detection: Last smart detection from this camera.
    """

    camera_id: str
    camera_name: str = ''
    aiport_id: str = ''
    smart_detect_enabled: bool = False
    detection_zones: int = 0
    last_detection: datetime | None = None


@dataclass
class AIPortInfo:
    """Extended information about an AI Port.

    Attributes:
        aiport: The underlying ProtectAIPort model.
        status: Current operational status.
        paired_cameras: List of paired cameras with details.
        capabilities: List of AI capabilities and their status.
        total_detections: Total smart detections processed.
        detections_per_hour: Recent detection rate.
        processing_load: Estimated processing load (0.0-1.0).
        last_activity: Last activity timestamp.
    """

    aiport: ProtectAIPort
    status: AIPortStatus = AIPortStatus.IDLE
    paired_cameras: list[PairedCamera] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    capabilities: list[AICapability] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    total_detections: int = 0
    detections_per_hour: float = 0.0
    processing_load: float = 0.0
    last_activity: datetime | None = None

    @property
    def id(self) -> str:
        """Get the AI Port ID."""
        return self.aiport.id

    @property
    def name(self) -> str:
        """Get the AI Port name."""
        return self.aiport.name

    @property
    def camera_count(self) -> int:
        """Get the number of paired cameras."""
        return len(self.paired_cameras)

    @property
    def enabled_capabilities(self) -> list[AICapability]:
        """Get list of enabled AI capabilities."""
        return [c for c in self.capabilities if c.enabled]


@dataclass
class AIDetectionEvent:
    """Represents an AI detection event.

    Attributes:
        aiport_id: The AI Port that processed this detection.
        camera_id: The camera that captured this detection.
        detection_type: Type of detection (person, vehicle, etc.).
        timestamp: When the detection occurred.
        confidence: Detection confidence (0.0-1.0).
        zone_id: Smart detection zone ID, if applicable.
        event_id: Unique event identifier.
    """

    aiport_id: str
    camera_id: str
    detection_type: SmartDetectType
    timestamp: datetime
    confidence: float = 0.0
    zone_id: str | None = None
    event_id: str = ''


# Type aliases
AIDetectionCallback = Callable[[AIDetectionEvent], Any]


class AIPortManager:
    """Manager for UniFi AI Ports.

    Provides unified interface for monitoring AI Ports, tracking their
    paired cameras, managing capabilities, and receiving AI detection events.

    Attributes:
        client: The connected UniFiProtectClient instance.

    Example:
        >>> manager = AIPortManager(client)
        >>>
        >>> # Get all AI Ports with extended info
        >>> for info in manager.get_all_aiport_info():
        ...     print(f"{info.name}: {info.camera_count} cameras")
        ...     for cap in info.enabled_capabilities:
        ...         print(f"  - {cap.name}")
        >>>
        >>> # Subscribe to AI detections from specific AI Port
        >>> def on_detection(event: AIDetectionEvent) -> None:
        ...     print(f"Detected {event.detection_type.value} on {event.camera_id}")
        >>>
        >>> unsub = manager.subscribe_detections(on_detection, aiport_id='aiport-1')
    """

    def __init__(
        self,
        client: UniFiProtectClient,
        event_handler: EventHandler | None = None,
    ) -> None:
        """Initialize the AI Port manager.

        Args:
            client: A connected UniFiProtectClient instance.
            event_handler: Optional existing EventHandler.
        """
        self._client = client
        self._event_handler = event_handler or EventHandler(client)
        self._detection_callbacks: list[tuple[AIDetectionCallback, str | None]] = []
        self._unsubscribe: UnsubscribeFunc | None = None
        self._is_subscribed = False

        # Tracking
        self._detection_counts: dict[str, int] = {}  # aiport_id -> count
        self._last_detections: dict[str, datetime] = {}  # aiport_id -> timestamp
        self._recent_detections: list[AIDetectionEvent] = []

    @property
    def client(self) -> UniFiProtectClient:
        """Get the associated client."""
        return self._client

    @property
    def event_handler(self) -> EventHandler:
        """Get the underlying event handler."""
        return self._event_handler

    def get_all_aiports(self) -> list[ProtectAIPort]:
        """Get all AI Ports from the client.

        Returns:
            List of ProtectAIPort models.
        """
        if not self._client.is_connected:
            return []

        aiports: list[ProtectAIPort] = []
        for aiport in self._client.ai_ports.values():
            aiports.append(ProtectAIPort.from_uiprotect(aiport))
        return aiports

    def get_aiport(self, aiport_id: str) -> ProtectAIPort | None:
        """Get a specific AI Port by ID.

        Args:
            aiport_id: The AI Port identifier.

        Returns:
            ProtectAIPort if found, None otherwise.
        """
        if not self._client.is_connected:
            return None

        aiport = self._client.ai_ports.get(aiport_id)
        if aiport is not None:
            return ProtectAIPort.from_uiprotect(aiport)
        return None

    def get_aiport_info(self, aiport_id: str) -> AIPortInfo | None:
        """Get extended information for an AI Port.

        Args:
            aiport_id: The AI Port identifier.

        Returns:
            AIPortInfo with extended details, or None if not found.
        """
        aiport = self.get_aiport(aiport_id)
        if aiport is None:
            return None

        return self._build_aiport_info(aiport)

    def get_all_aiport_info(self) -> list[AIPortInfo]:
        """Get extended information for all AI Ports.

        Returns:
            List of AIPortInfo objects.
        """
        return [
            self._build_aiport_info(aiport)
            for aiport in self.get_all_aiports()
        ]

    def _build_aiport_info(self, aiport: ProtectAIPort) -> AIPortInfo:
        """Build extended AIPortInfo from a ProtectAIPort.

        Args:
            aiport: The base AI Port model.

        Returns:
            Extended AIPortInfo with additional context.
        """
        # Get raw aiport from client for more details
        raw_aiport = self._client.ai_ports.get(aiport.id)

        # Determine status
        status = self._determine_status(aiport)

        # Get paired cameras
        paired_cameras = self._get_paired_cameras(aiport, raw_aiport)

        # Get capabilities
        capabilities = self._get_capabilities(aiport)

        # Calculate detection stats
        total_detections = self._detection_counts.get(aiport.id, 0)
        last_activity = self._last_detections.get(aiport.id)

        # Estimate processing load based on camera count
        processing_load = min(1.0, len(paired_cameras) / 8.0)  # Assumes ~8 cameras max

        return AIPortInfo(
            aiport=aiport,
            status=status,
            paired_cameras=paired_cameras,
            capabilities=capabilities,
            total_detections=total_detections,
            processing_load=processing_load,
            last_activity=last_activity,
        )

    def _determine_status(self, aiport: ProtectAIPort) -> AIPortStatus:
        """Determine the current status of an AI Port.

        Args:
            aiport: The AI Port to check.

        Returns:
            The determined AIPortStatus.
        """
        if aiport.is_updating:
            return AIPortStatus.UPDATING

        if aiport.state == DeviceState.DISCONNECTED:
            return AIPortStatus.OFFLINE

        if aiport.state != DeviceState.CONNECTED:
            return AIPortStatus.ERROR

        # Check recent activity
        last_activity = self._last_detections.get(aiport.id)
        if last_activity is not None:
            time_since = datetime.now(timezone.utc) - last_activity
            if time_since < timedelta(seconds=30):
                return AIPortStatus.PROCESSING

        return AIPortStatus.ONLINE if aiport.camera_count > 0 else AIPortStatus.IDLE

    def _get_paired_cameras(
        self,
        aiport: ProtectAIPort,
        raw_aiport: Any | None,
    ) -> list[PairedCamera]:
        """Get paired cameras for an AI Port.

        Args:
            aiport: Our AI Port model.
            raw_aiport: Raw uiprotect AiPort object.

        Returns:
            List of PairedCamera objects.
        """
        paired: list[PairedCamera] = []

        if raw_aiport is None:
            return paired

        # Get paired camera IDs
        paired_ids: list[str] = getattr(raw_aiport, 'paired_cameras', [])

        for camera_id in paired_ids:
            camera = self._client.cameras.get(camera_id)
            if camera is not None:
                # Check smart detect settings
                smart_settings = getattr(camera, 'smart_detect_settings', None)
                smart_zones = getattr(camera, 'smart_detect_zones', [])

                paired.append(PairedCamera(
                    camera_id=camera_id,
                    camera_name=camera.name or 'Unknown',
                    aiport_id=aiport.id,
                    smart_detect_enabled=smart_settings is not None,
                    detection_zones=len(smart_zones) if smart_zones else 0,
                    last_detection=getattr(camera, 'last_smart_detect', None),
                ))

        return paired

    def _get_capabilities(self, aiport: ProtectAIPort) -> list[AICapability]:
        """Get AI capabilities for an AI Port.

        Args:
            aiport: The AI Port to check.

        Returns:
            List of AICapability objects.
        """
        return [
            AICapability(
                capability_type=AICapabilityType.PERSON,
                enabled=aiport.is_person_enabled,
                available=True,
            ),
            AICapability(
                capability_type=AICapabilityType.VEHICLE,
                enabled=aiport.is_vehicle_enabled,
                available=True,
            ),
            AICapability(
                capability_type=AICapabilityType.ANIMAL,
                enabled=aiport.is_animal_enabled,
                available=True,
            ),
            AICapability(
                capability_type=AICapabilityType.PACKAGE,
                enabled=aiport.is_package_enabled,
                available=True,
            ),
        ]

    def get_cameras_by_aiport(self, aiport_id: str) -> list[ProtectCamera]:
        """Get all cameras paired with a specific AI Port.

        Args:
            aiport_id: The AI Port identifier.

        Returns:
            List of ProtectCamera models.
        """
        info = self.get_aiport_info(aiport_id)
        if info is None:
            return []

        cameras: list[ProtectCamera] = []
        for paired in info.paired_cameras:
            camera = self._client.cameras.get(paired.camera_id)
            if camera is not None:
                cameras.append(ProtectCamera.from_uiprotect(camera))

        return cameras

    def get_capabilities(self, aiport_id: str) -> list[AICapability]:
        """Get AI capabilities for a specific AI Port.

        Args:
            aiport_id: The AI Port identifier.

        Returns:
            List of AICapability objects.
        """
        aiport = self.get_aiport(aiport_id)
        if aiport is None:
            return []
        return self._get_capabilities(aiport)

    def subscribe_detections(
        self,
        callback: AIDetectionCallback,
        aiport_id: str | None = None,
        detection_types: list[SmartDetectType] | None = None,
    ) -> UnsubscribeFunc:
        """Subscribe to AI detection events.

        Args:
            callback: Function to call when detections occur.
            aiport_id: Optional AI Port ID to filter by.
            detection_types: Optional detection types to filter by.

        Returns:
            Unsubscribe function.
        """
        self._detection_callbacks.append((callback, aiport_id))

        # Start event subscription if not already subscribed
        if not self._is_subscribed:
            self._start_subscription()

        def unsubscribe() -> None:
            self._detection_callbacks.remove((callback, aiport_id))
            if not self._detection_callbacks and self._is_subscribed:
                self._stop_subscription()

        return unsubscribe

    def _start_subscription(self) -> None:
        """Start listening for smart detection events."""
        smart_filter = EventFilter(
            categories=[ProtectEventCategory.SMART_DETECT],
        )

        self._unsubscribe = self._event_handler.subscribe(
            self._on_event,
            smart_filter,
        )
        self._is_subscribed = True
        logger.info('AI Port detection subscription started')

    def _stop_subscription(self) -> None:
        """Stop listening for smart detection events."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._is_subscribed = False
        logger.info('AI Port detection subscription stopped')

    def _on_event(self, event: ProtectEvent) -> None:
        """Handle incoming smart detection events.

        Args:
            event: The smart detection event.
        """
        # Find which AI Port processed this detection
        aiport_id = self._find_aiport_for_camera(event.device_id)
        if aiport_id is None:
            # Camera might not be paired with an AI Port
            return

        # Extract detection type
        detection_types = self._extract_detection_types(event)
        if not detection_types:
            return

        # Create detection events
        for detect_type in detection_types:
            detection = AIDetectionEvent(
                aiport_id=aiport_id,
                camera_id=event.device_id,
                detection_type=detect_type,
                timestamp=event.timestamp,
                event_id=event.update_id,
            )

            # Update tracking
            self._detection_counts[aiport_id] = (
                self._detection_counts.get(aiport_id, 0) + 1
            )
            self._last_detections[aiport_id] = event.timestamp

            # Store recent detection
            self._recent_detections.append(detection)
            if len(self._recent_detections) > 100:
                self._recent_detections = self._recent_detections[-100:]

            # Dispatch to callbacks
            self._dispatch_detection(detection)

    def _find_aiport_for_camera(self, camera_id: str) -> str | None:
        """Find the AI Port that a camera is paired with.

        Args:
            camera_id: The camera identifier.

        Returns:
            AI Port ID if found, None otherwise.
        """
        for aiport_id, aiport in self._client.ai_ports.items():
            paired_cameras: list[str] = getattr(aiport, 'paired_cameras', [])
            if camera_id in paired_cameras:
                return aiport_id
        return None

    def _extract_detection_types(
        self,
        event: ProtectEvent,
    ) -> list[SmartDetectType]:
        """Extract smart detection types from an event.

        Args:
            event: The event to extract from.

        Returns:
            List of SmartDetectType values.
        """
        types: list[SmartDetectType] = []

        smart_types_raw = event.changed_data.get('smartDetectTypes')
        if smart_types_raw is not None and isinstance(smart_types_raw, list):
            for item in smart_types_raw:  # type: ignore[reportUnknownVariableType]
                if isinstance(item, str):
                    try:
                        types.append(SmartDetectType(item))
                    except ValueError:
                        pass

        return types

    def _dispatch_detection(self, detection: AIDetectionEvent) -> None:
        """Dispatch a detection event to subscribers.

        Args:
            detection: The detection event to dispatch.
        """
        for callback, filter_aiport_id in self._detection_callbacks:
            # Apply AI Port filter if specified
            if filter_aiport_id is not None and detection.aiport_id != filter_aiport_id:
                continue

            try:
                callback(detection)
            except Exception as e:
                logger.error(f'Error in AI detection callback: {e}')

    def get_recent_detections(
        self,
        aiport_id: str | None = None,
        limit: int = 50,
    ) -> list[AIDetectionEvent]:
        """Get recent AI detection events.

        Args:
            aiport_id: Optional AI Port ID to filter by.
            limit: Maximum number of events to return.

        Returns:
            List of recent AIDetectionEvent objects (newest first).
        """
        detections = self._recent_detections.copy()

        if aiport_id is not None:
            detections = [d for d in detections if d.aiport_id == aiport_id]

        return detections[-limit:][::-1]

    def get_detection_stats(
        self,
        aiport_id: str | None = None,
    ) -> dict[str, Any]:
        """Get detection statistics.

        Args:
            aiport_id: Optional AI Port ID for specific stats.

        Returns:
            Dictionary with detection statistics.
        """
        if aiport_id is not None:
            total = self._detection_counts.get(aiport_id, 0)
            last = self._last_detections.get(aiport_id)
            aiport = self.get_aiport(aiport_id)

            return {
                'aiport_id': aiport_id,
                'aiport_name': aiport.name if aiport else 'Unknown',
                'total_detections': total,
                'last_detection': last.isoformat() if last else None,
            }

        # Aggregate stats for all AI Ports
        total_detections = sum(self._detection_counts.values())
        aiport_stats: list[dict[str, Any]] = []

        for ai_id in self._detection_counts:
            aiport = self.get_aiport(ai_id)
            aiport_stats.append({
                'aiport_id': ai_id,
                'aiport_name': aiport.name if aiport else 'Unknown',
                'detections': self._detection_counts[ai_id],
                'last_detection': (
                    self._last_detections.get(ai_id, datetime.min).isoformat()
                    if ai_id in self._last_detections else None
                ),
            })

        return {
            'total_detections': total_detections,
            'aiport_count': len(self.get_all_aiports()),
            'by_aiport': aiport_stats,
        }

    def clear_stats(self) -> None:
        """Clear all tracked detection statistics."""
        self._detection_counts.clear()
        self._last_detections.clear()
        self._recent_detections.clear()
        logger.debug('AI Port detection stats cleared')
