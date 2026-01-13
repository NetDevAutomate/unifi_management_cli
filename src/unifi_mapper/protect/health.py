"""Device health monitoring for UniFi Protect.

This module provides proactive device health monitoring with status change
subscriptions, configurable thresholds, health history tracking, and
recovery detection.

Example:
    >>> from unifi_mapper.protect import UniFiProtectClient
    >>> from unifi_mapper.protect.health import DeviceHealthMonitor
    >>>
    >>> async with UniFiProtectClient(config) as client:
    ...     monitor = DeviceHealthMonitor(client)
    ...     monitor.subscribe_health_changes(lambda c: print(f"Health changed: {c}"))
    ...     await monitor.start()
    ...     # ... monitoring runs in background ...
    ...     monitor.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger  # type: ignore[import-untyped]

from unifi_mapper.protect.analytics import DeviceHealth, DeviceHealthStatus
from unifi_mapper.protect.events import (
    EventFilter,
    EventHandler,
    ProtectEvent,
    ProtectEventCategory,
    ProtectEventType,
    UnsubscribeFunc,
)


if TYPE_CHECKING:
    from unifi_mapper.protect.client import UniFiProtectClient


class HealthTransition(str, Enum):
    """Types of health status transitions."""

    DEGRADED = 'degraded'     # Health worsened
    IMPROVED = 'improved'     # Health got better
    RECOVERED = 'recovered'   # Device back to healthy
    FAILED = 'failed'        # Device went offline/critical


@dataclass
class HealthThresholds:
    """Configurable thresholds for health status determination.

    Attributes:
        offline_timeout: Time without activity before marking offline.
        warning_disconnect_count: Disconnects to trigger warning.
        critical_disconnect_count: Disconnects to trigger critical.
        low_battery_warning: Battery % for warning.
        low_battery_critical: Battery % for critical.
        stale_data_timeout: Time before data considered stale.
    """

    offline_timeout: timedelta = field(default_factory=lambda: timedelta(minutes=15))
    warning_disconnect_count: int = 3
    critical_disconnect_count: int = 10
    low_battery_warning: int = 20
    low_battery_critical: int = 10
    stale_data_timeout: timedelta = field(default_factory=lambda: timedelta(hours=2))


@dataclass
class HealthChange:
    """Represents a health status change event.

    Attributes:
        device_id: The device identifier.
        device_name: Human-readable device name.
        device_type: Type of device (camera, sensor, etc.).
        old_status: Previous health status.
        new_status: New health status.
        transition: Type of transition that occurred.
        timestamp: When the change was detected.
        reason: Human-readable reason for the change.
        health_snapshot: Full health state at time of change.
    """

    device_id: str
    device_name: str
    device_type: str
    old_status: DeviceHealthStatus
    new_status: DeviceHealthStatus
    transition: HealthTransition
    timestamp: datetime
    reason: str
    health_snapshot: DeviceHealth | None = None


@dataclass
class HealthHistoryEntry:
    """A single entry in a device's health history.

    Attributes:
        timestamp: When this status was recorded.
        status: The health status at this time.
        issues: Any issues present at this time.
        battery_level: Battery level if applicable.
    """

    timestamp: datetime
    status: DeviceHealthStatus
    issues: list[str] = field(default_factory=lambda: [])  # type: ignore[arg-type]
    battery_level: int | None = None


@dataclass
class DeviceHealthSummary:
    """Summary of a device's health over time.

    Attributes:
        device_id: The device identifier.
        device_name: Human-readable device name.
        device_type: Type of device.
        current_health: Current health state.
        uptime_percentage: Percentage of time healthy (0-100).
        total_incidents: Number of health incidents.
        last_incident: Timestamp of most recent incident.
        average_recovery_time: Average time to recover from issues.
        health_trend: Current health trend direction.
        history: Recent health history entries.
    """

    device_id: str
    device_name: str = ''
    device_type: str = ''
    current_health: DeviceHealth | None = None
    uptime_percentage: float = 100.0
    total_incidents: int = 0
    last_incident: datetime | None = None
    average_recovery_time: timedelta | None = None
    health_trend: str = 'stable'  # 'improving', 'degrading', 'stable'
    history: list[HealthHistoryEntry] = field(default_factory=lambda: [])  # type: ignore[arg-type]


# Type alias for health change callbacks
HealthChangeCallback = Callable[[HealthChange], Any]


class DeviceHealthMonitor:
    """Proactive device health monitoring with subscriptions.

    This monitor tracks device health over time, detects status changes,
    and provides notifications when devices degrade or recover.

    Attributes:
        client: The connected UniFiProtectClient instance.
        thresholds: Configurable health thresholds.

    Example:
        >>> monitor = DeviceHealthMonitor(client)
        >>> monitor.subscribe_health_changes(on_health_change)
        >>> await monitor.start()
        >>> # ... runs in background ...
        >>> summary = monitor.get_device_summary('device-123')
        >>> print(f"Uptime: {summary.uptime_percentage}%")
        >>> monitor.stop()
    """

    # Configuration constants
    DEFAULT_CHECK_INTERVAL = 60.0  # seconds
    MAX_HISTORY_ENTRIES = 1000
    MAX_HISTORY_PER_DEVICE = 100

    def __init__(
        self,
        client: UniFiProtectClient,
        event_handler: EventHandler | None = None,
        thresholds: HealthThresholds | None = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
    ) -> None:
        """Initialize the health monitor.

        Args:
            client: A connected UniFiProtectClient instance.
            event_handler: Optional existing EventHandler.
            thresholds: Health thresholds. Uses defaults if not provided.
            check_interval: Seconds between health checks.
        """
        self._client = client
        self._event_handler = event_handler or EventHandler(client)
        self._thresholds = thresholds or HealthThresholds()
        self._check_interval = check_interval
        self._unsubscribe: UnsubscribeFunc | None = None
        self._check_task: asyncio.Task[None] | None = None
        self._is_running = False

        # Health state tracking
        self._device_health: dict[str, DeviceHealth] = {}
        self._device_history: dict[str, list[HealthHistoryEntry]] = {}
        self._device_names: dict[str, str] = {}
        self._device_types: dict[str, str] = {}
        self._device_last_seen: dict[str, datetime] = {}
        self._device_disconnect_count: dict[str, int] = {}
        self._device_battery_levels: dict[str, int] = {}

        # Incident tracking
        self._incident_start: dict[str, datetime] = {}
        self._recovery_times: dict[str, list[timedelta]] = {}
        self._total_healthy_time: dict[str, timedelta] = {}
        self._monitoring_start: dict[str, datetime] = {}

        # Change subscriptions
        self._health_callbacks: list[HealthChangeCallback] = []

    @property
    def client(self) -> UniFiProtectClient:
        """Get the associated client."""
        return self._client

    @property
    def thresholds(self) -> HealthThresholds:
        """Get the health thresholds."""
        return self._thresholds

    @property
    def is_running(self) -> bool:
        """Check if monitoring is active."""
        return self._is_running

    async def start(self) -> None:
        """Start health monitoring.

        Raises:
            ValueError: If client is not connected.
            RuntimeError: If monitor is already running.
        """
        if self._is_running:
            raise RuntimeError('Health monitor is already running')

        if not self._client.is_connected:
            raise ValueError('Client must be connected to start monitoring')

        # Subscribe to relevant events
        event_filter = EventFilter(
            categories=[
                ProtectEventCategory.DEVICE_STATE,
                ProtectEventCategory.MOTION,
                ProtectEventCategory.SENSOR,
            ],
        )
        self._unsubscribe = self._event_handler.subscribe(
            self._on_event,
            event_filter=event_filter,
        )

        # Initialize device tracking from current state
        await self._initialize_devices()

        # Start periodic health check task
        self._check_task = asyncio.create_task(self._periodic_health_check())
        self._is_running = True
        logger.info('Device health monitor started')

    def stop(self) -> None:
        """Stop health monitoring."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

        if self._check_task is not None:
            self._check_task.cancel()
            self._check_task = None

        self._is_running = False
        logger.info('Device health monitor stopped')

    def clear(self) -> None:
        """Clear all health tracking data."""
        self._device_health.clear()
        self._device_history.clear()
        self._device_names.clear()
        self._device_types.clear()
        self._device_last_seen.clear()
        self._device_disconnect_count.clear()
        self._device_battery_levels.clear()
        self._incident_start.clear()
        self._recovery_times.clear()
        self._total_healthy_time.clear()
        self._monitoring_start.clear()
        logger.debug('Health monitor data cleared')

    async def _initialize_devices(self) -> None:
        """Initialize device tracking from current client state."""
        now = datetime.now(timezone.utc)
        device_count = 0

        # Track cameras
        for device_id, camera in self._client.cameras.items():
            name = getattr(camera, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'camera'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        # Track sensors
        for device_id, sensor in self._client.sensors.items():
            name = getattr(sensor, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'sensor'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        # Track lights
        for device_id, light in self._client.lights.items():
            name = getattr(light, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'light'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        # Track chimes
        for device_id, chime in self._client.chimes.items():
            name = getattr(chime, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'chime'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        # Track doorlocks
        for device_id, doorlock in self._client.doorlocks.items():
            name = getattr(doorlock, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'doorlock'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        # Track AI ports
        for device_id, aiport in self._client.ai_ports.items():
            name = getattr(aiport, 'name', None) or device_id
            self._device_names[device_id] = str(name)
            self._device_types[device_id] = 'ai_port'
            self._device_last_seen[device_id] = now
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()
            health = self._calculate_health(device_id)
            self._device_health[device_id] = health
            self._record_history(device_id, health)
            device_count += 1

        logger.info(f'Initialized health tracking for {device_count} devices')

    def _on_event(self, event: ProtectEvent) -> None:
        """Handle incoming events for health tracking.

        Args:
            event: The received event.
        """
        device_id = event.device_id
        if not device_id:
            return

        # Update last seen
        self._device_last_seen[device_id] = event.timestamp

        # Extract device info from event if available
        if event.model_type:
            self._device_types[device_id] = event.model_type.value

        # Track disconnections
        if event.event_type in (
            ProtectEventType.DEVICE_DISCONNECTED,
            ProtectEventType.CAMERA_DISCONNECTED,
            ProtectEventType.OFFLINE,
        ):
            self._device_disconnect_count[device_id] = (
                self._device_disconnect_count.get(device_id, 0) + 1
            )

        # Track battery levels
        if 'batteryStatus' in event.changed_data:
            battery = event.changed_data.get('batteryStatus', {})
            if isinstance(battery, dict) and 'percentage' in battery:
                self._device_battery_levels[device_id] = battery['percentage']

        # Check for health changes
        self._check_health_change(device_id)

    async def _periodic_health_check(self) -> None:
        """Periodically check health of all devices."""
        while self._is_running:
            try:
                await asyncio.sleep(self._check_interval)

                if not self._is_running:
                    break

                # Check all tracked devices
                for device_id in list(self._device_last_seen.keys()):
                    self._check_health_change(device_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'Error in periodic health check: {e}')

    def _check_health_change(self, device_id: str) -> None:
        """Check if a device's health status has changed.

        Args:
            device_id: The device to check.
        """
        old_health = self._device_health.get(device_id)
        new_health = self._calculate_health(device_id)

        # Store new health state
        self._device_health[device_id] = new_health

        # Check for status change
        old_status = old_health.status if old_health else DeviceHealthStatus.UNKNOWN
        new_status = new_health.status

        if old_status != new_status:
            transition = self._determine_transition(old_status, new_status)
            self._handle_status_change(
                device_id, old_status, new_status, transition, new_health
            )

        # Record history periodically
        self._record_history(device_id, new_health)

    def _calculate_health(self, device_id: str) -> DeviceHealth:
        """Calculate current health for a device.

        Args:
            device_id: The device identifier.

        Returns:
            DeviceHealth for the device.
        """
        health = DeviceHealth(
            device_id=device_id,
            device_name=self._device_names.get(device_id, ''),
        )

        # Get tracking data
        health.last_seen = self._device_last_seen.get(device_id)
        health.disconnect_count = self._device_disconnect_count.get(device_id, 0)
        health.battery_level = self._device_battery_levels.get(device_id)

        # Calculate uptime percentage
        health.uptime_percentage = self._calculate_uptime(device_id)

        # Determine status using thresholds
        issues: list[str] = []
        now = datetime.now(timezone.utc)

        if health.last_seen is None:
            health.status = DeviceHealthStatus.UNKNOWN
        else:
            time_since_seen = now - health.last_seen

            # Check offline threshold
            if time_since_seen > self._thresholds.offline_timeout:
                health.status = DeviceHealthStatus.OFFLINE
                issues.append(f'Offline for {time_since_seen}')

            # Check critical conditions
            elif health.disconnect_count >= self._thresholds.critical_disconnect_count:
                health.status = DeviceHealthStatus.CRITICAL
                issues.append(f'{health.disconnect_count} disconnections (critical)')
            elif health.battery_level is not None and health.battery_level <= self._thresholds.low_battery_critical:
                health.status = DeviceHealthStatus.CRITICAL
                issues.append(f'Critical battery: {health.battery_level}%')

            # Check warning conditions
            elif health.disconnect_count >= self._thresholds.warning_disconnect_count:
                health.status = DeviceHealthStatus.WARNING
                issues.append(f'{health.disconnect_count} disconnections')
            elif health.battery_level is not None and health.battery_level <= self._thresholds.low_battery_warning:
                health.status = DeviceHealthStatus.WARNING
                issues.append(f'Low battery: {health.battery_level}%')

            # Healthy
            else:
                health.status = DeviceHealthStatus.HEALTHY

        health.issues = issues
        return health

    def _calculate_uptime(self, device_id: str) -> float:
        """Calculate uptime percentage for a device.

        Args:
            device_id: The device identifier.

        Returns:
            Uptime percentage (0-100).
        """
        start_time = self._monitoring_start.get(device_id)
        if start_time is None:
            return 100.0

        now = datetime.now(timezone.utc)
        total_time = now - start_time
        if total_time.total_seconds() <= 0:
            return 100.0

        healthy_time = self._total_healthy_time.get(device_id, timedelta())
        return min(100.0, (healthy_time.total_seconds() / total_time.total_seconds()) * 100)

    def _determine_transition(
        self,
        old_status: DeviceHealthStatus,
        new_status: DeviceHealthStatus,
    ) -> HealthTransition:
        """Determine the type of health transition.

        Args:
            old_status: Previous status.
            new_status: New status.

        Returns:
            The type of transition.
        """
        # Define status severity (lower is better)
        severity = {
            DeviceHealthStatus.HEALTHY: 0,
            DeviceHealthStatus.WARNING: 1,
            DeviceHealthStatus.CRITICAL: 2,
            DeviceHealthStatus.OFFLINE: 3,
            DeviceHealthStatus.UNKNOWN: 2,
        }

        old_severity = severity.get(old_status, 2)
        new_severity = severity.get(new_status, 2)

        if new_status == DeviceHealthStatus.HEALTHY:
            return HealthTransition.RECOVERED
        elif new_status in (DeviceHealthStatus.OFFLINE, DeviceHealthStatus.CRITICAL):
            return HealthTransition.FAILED
        elif new_severity > old_severity:
            return HealthTransition.DEGRADED
        else:
            return HealthTransition.IMPROVED

    def _handle_status_change(
        self,
        device_id: str,
        old_status: DeviceHealthStatus,
        new_status: DeviceHealthStatus,
        transition: HealthTransition,
        health: DeviceHealth,
    ) -> None:
        """Handle a health status change.

        Args:
            device_id: The device that changed.
            old_status: Previous status.
            new_status: New status.
            transition: Type of transition.
            health: Current health state.
        """
        now = datetime.now(timezone.utc)

        # Track incident timing
        if transition == HealthTransition.FAILED:
            self._incident_start[device_id] = now
        elif transition == HealthTransition.RECOVERED:
            incident_start = self._incident_start.pop(device_id, None)
            if incident_start:
                recovery_time = now - incident_start
                if device_id not in self._recovery_times:
                    self._recovery_times[device_id] = []
                self._recovery_times[device_id].append(recovery_time)

        # Build reason string
        reason = f'{old_status.value} -> {new_status.value}'
        if health.issues:
            reason += f': {", ".join(health.issues)}'

        # Create change event
        change = HealthChange(
            device_id=device_id,
            device_name=self._device_names.get(device_id, ''),
            device_type=self._device_types.get(device_id, 'unknown'),
            old_status=old_status,
            new_status=new_status,
            transition=transition,
            timestamp=now,
            reason=reason,
            health_snapshot=health,
        )

        # Log the change
        log_level = 'warning' if transition in (HealthTransition.FAILED, HealthTransition.DEGRADED) else 'info'
        getattr(logger, log_level)(
            f'Health change for {change.device_name or device_id}: '
            f'{change.old_status.value} -> {change.new_status.value} '
            f'({change.transition.value})'
        )

        # Notify subscribers
        for callback in self._health_callbacks:
            try:
                callback(change)
            except Exception as e:
                logger.error(f'Error in health change callback: {e}')

    def _record_history(self, device_id: str, health: DeviceHealth) -> None:
        """Record a health history entry.

        Args:
            device_id: The device identifier.
            health: Current health state.
        """
        if device_id not in self._device_history:
            self._device_history[device_id] = []

        entry = HealthHistoryEntry(
            timestamp=datetime.now(timezone.utc),
            status=health.status,
            issues=health.issues.copy(),
            battery_level=health.battery_level,
        )

        history = self._device_history[device_id]
        history.append(entry)

        # Trim history
        if len(history) > self.MAX_HISTORY_PER_DEVICE:
            self._device_history[device_id] = history[-self.MAX_HISTORY_PER_DEVICE:]

        # Update healthy time tracking
        if health.status == DeviceHealthStatus.HEALTHY:
            # Approximate: add check interval to healthy time
            current = self._total_healthy_time.get(device_id, timedelta())
            self._total_healthy_time[device_id] = current + timedelta(
                seconds=self._check_interval
            )

    def subscribe_health_changes(
        self,
        callback: HealthChangeCallback,
    ) -> UnsubscribeFunc:
        """Subscribe to health status changes.

        Args:
            callback: Function to call when health changes.

        Returns:
            Unsubscribe function.
        """
        self._health_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._health_callbacks:
                self._health_callbacks.remove(callback)

        return unsubscribe

    def get_device_health(self, device_id: str) -> DeviceHealth | None:
        """Get current health for a device.

        Args:
            device_id: The device identifier.

        Returns:
            DeviceHealth or None if not tracked.
        """
        return self._device_health.get(device_id)

    def get_all_device_health(self) -> list[DeviceHealth]:
        """Get current health for all tracked devices.

        Returns:
            List of DeviceHealth for all devices.
        """
        return list(self._device_health.values())

    def get_devices_by_status(
        self,
        status: DeviceHealthStatus,
    ) -> list[DeviceHealth]:
        """Get all devices with a specific health status.

        Args:
            status: The status to filter by.

        Returns:
            List of devices with that status.
        """
        return [
            health for health in self._device_health.values()
            if health.status == status
        ]

    def get_unhealthy_devices(self) -> list[DeviceHealth]:
        """Get all devices that are not healthy.

        Returns:
            List of devices with warning, critical, or offline status.
        """
        return [
            health for health in self._device_health.values()
            if health.status != DeviceHealthStatus.HEALTHY
        ]

    def get_device_summary(self, device_id: str) -> DeviceHealthSummary:
        """Get a summary of device health over time.

        Args:
            device_id: The device identifier.

        Returns:
            DeviceHealthSummary with statistics.
        """
        summary = DeviceHealthSummary(
            device_id=device_id,
            device_name=self._device_names.get(device_id, ''),
            device_type=self._device_types.get(device_id, ''),
            current_health=self._device_health.get(device_id),
        )

        # Get history
        history = self._device_history.get(device_id, [])
        summary.history = history[-50:]  # Last 50 entries

        # Calculate uptime
        summary.uptime_percentage = self._calculate_uptime(device_id)

        # Count incidents (non-healthy periods)
        incidents = 0
        last_incident: datetime | None = None
        in_incident = False

        for entry in history:
            is_incident = entry.status != DeviceHealthStatus.HEALTHY
            if is_incident and not in_incident:
                incidents += 1
                last_incident = entry.timestamp
                in_incident = True
            elif not is_incident:
                in_incident = False

        summary.total_incidents = incidents
        summary.last_incident = last_incident

        # Calculate average recovery time
        recovery_times = self._recovery_times.get(device_id, [])
        if recovery_times:
            total_seconds = sum(rt.total_seconds() for rt in recovery_times)
            summary.average_recovery_time = timedelta(
                seconds=total_seconds / len(recovery_times)
            )

        # Determine health trend
        summary.health_trend = self._calculate_health_trend(history)

        return summary

    def _calculate_health_trend(
        self,
        history: list[HealthHistoryEntry],
    ) -> str:
        """Calculate the health trend from history.

        Args:
            history: List of health history entries.

        Returns:
            'improving', 'degrading', or 'stable'.
        """
        if len(history) < 10:
            return 'stable'

        # Compare first half to second half
        mid = len(history) // 2
        first_half = history[:mid]
        second_half = history[mid:]

        def unhealthy_ratio(entries: list[HealthHistoryEntry]) -> float:
            if not entries:
                return 0.0
            unhealthy = sum(
                1 for e in entries if e.status != DeviceHealthStatus.HEALTHY
            )
            return unhealthy / len(entries)

        first_ratio = unhealthy_ratio(first_half)
        second_ratio = unhealthy_ratio(second_half)

        # Significant change threshold
        threshold = 0.1

        if second_ratio < first_ratio - threshold:
            return 'improving'
        elif second_ratio > first_ratio + threshold:
            return 'degrading'
        return 'stable'

    def get_fleet_summary(self) -> dict[str, Any]:
        """Get a summary of health across all devices.

        Returns:
            Dictionary with fleet-wide health statistics.
        """
        devices = list(self._device_health.values())

        if not devices:
            return {
                'total_devices': 0,
                'healthy': 0,
                'warning': 0,
                'critical': 0,
                'offline': 0,
                'unknown': 0,
                'health_percentage': 100.0,
                'devices_with_issues': [],
            }

        # Count by status
        status_counts: dict[DeviceHealthStatus, int] = {}
        for health in devices:
            status_counts[health.status] = status_counts.get(health.status, 0) + 1

        # Identify devices with issues
        devices_with_issues = [
            {
                'device_id': h.device_id,
                'device_name': h.device_name,
                'status': h.status.value,
                'issues': h.issues,
            }
            for h in devices
            if h.status != DeviceHealthStatus.HEALTHY
        ]

        healthy_count = status_counts.get(DeviceHealthStatus.HEALTHY, 0)
        health_percentage = (healthy_count / len(devices)) * 100 if devices else 100.0

        return {
            'total_devices': len(devices),
            'healthy': healthy_count,
            'warning': status_counts.get(DeviceHealthStatus.WARNING, 0),
            'critical': status_counts.get(DeviceHealthStatus.CRITICAL, 0),
            'offline': status_counts.get(DeviceHealthStatus.OFFLINE, 0),
            'unknown': status_counts.get(DeviceHealthStatus.UNKNOWN, 0),
            'health_percentage': health_percentage,
            'devices_with_issues': devices_with_issues,
        }

    def reset_device_stats(self, device_id: str) -> None:
        """Reset statistics for a specific device.

        Args:
            device_id: The device to reset.
        """
        self._device_disconnect_count[device_id] = 0
        self._device_history.pop(device_id, None)
        self._recovery_times.pop(device_id, None)
        self._incident_start.pop(device_id, None)

        # Reset monitoring start
        now = datetime.now(timezone.utc)
        self._monitoring_start[device_id] = now
        self._total_healthy_time[device_id] = timedelta()

        logger.debug(f'Reset health stats for device {device_id}')

    def reset_all_stats(self) -> None:
        """Reset statistics for all devices."""
        now = datetime.now(timezone.utc)

        for device_id in list(self._device_disconnect_count.keys()):
            self._device_disconnect_count[device_id] = 0
            self._monitoring_start[device_id] = now
            self._total_healthy_time[device_id] = timedelta()

        self._device_history.clear()
        self._recovery_times.clear()
        self._incident_start.clear()

        logger.info('Reset health stats for all devices')
