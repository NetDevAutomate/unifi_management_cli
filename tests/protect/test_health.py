"""Tests for the Device Health Monitor module.

Tests cover:
- HealthThresholds configuration
- HealthChange event creation
- HealthHistoryEntry tracking
- DeviceHealthSummary statistics
- DeviceHealthMonitor lifecycle (start/stop)
- Health status calculation
- Health change detection and callbacks
- Fleet-wide health summaries
- Device statistics management
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_mapper.protect.analytics import DeviceHealth, DeviceHealthStatus
from unifi_mapper.protect.events import (
    EventHandler,
    ProtectAction,
    ProtectEvent,
    ProtectEventType,
    ProtectModelType,
)
from unifi_mapper.protect.health import (
    DeviceHealthMonitor,
    DeviceHealthSummary,
    HealthChange,
    HealthHistoryEntry,
    HealthThresholds,
    HealthTransition,
)


# ============================================================================
# Helper Functions
# ============================================================================


def create_mock_client(
    is_connected: bool = True,
    cameras: dict[str, Any] | None = None,
    sensors: dict[str, Any] | None = None,
    lights: dict[str, Any] | None = None,
    chimes: dict[str, Any] | None = None,
    doorlocks: dict[str, Any] | None = None,
    ai_ports: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock UniFiProtectClient for testing."""
    client = MagicMock()
    client.is_connected = is_connected
    client.cameras = cameras or {}
    client.sensors = sensors or {}
    client.lights = lights or {}
    client.chimes = chimes or {}
    client.doorlocks = doorlocks or {}
    client.ai_ports = ai_ports or {}
    return client


def create_mock_device(
    device_id: str = 'device-001',
    name: str = 'Test Device',
) -> MagicMock:
    """Create a mock device for testing."""
    device = MagicMock()
    device.id = device_id
    device.name = name
    return device


def create_protect_event(
    device_id: str = 'device-001',
    event_type: ProtectEventType | None = None,
    model_type: ProtectModelType | None = None,
    changed_data: dict[str, object] | None = None,
    timestamp: datetime | None = None,
) -> ProtectEvent:
    """Create a ProtectEvent for testing."""
    return ProtectEvent(
        action=ProtectAction.UPDATE,
        model_type=model_type or ProtectModelType.CAMERA,
        device_id=device_id,
        timestamp=timestamp or datetime.now(timezone.utc),
        event_type=event_type,
        changed_data=changed_data or {},
    )


# ============================================================================
# HealthThresholds Tests
# ============================================================================


class TestHealthThresholds:
    """Tests for HealthThresholds configuration."""

    def test_default_values(self) -> None:
        """Test default threshold values."""
        thresholds = HealthThresholds()

        assert thresholds.offline_timeout == timedelta(minutes=15)
        assert thresholds.warning_disconnect_count == 3
        assert thresholds.critical_disconnect_count == 10
        assert thresholds.low_battery_warning == 20
        assert thresholds.low_battery_critical == 10
        assert thresholds.stale_data_timeout == timedelta(hours=2)

    def test_custom_values(self) -> None:
        """Test custom threshold values."""
        thresholds = HealthThresholds(
            offline_timeout=timedelta(minutes=30),
            warning_disconnect_count=5,
            critical_disconnect_count=15,
            low_battery_warning=30,
            low_battery_critical=15,
            stale_data_timeout=timedelta(hours=4),
        )

        assert thresholds.offline_timeout == timedelta(minutes=30)
        assert thresholds.warning_disconnect_count == 5
        assert thresholds.critical_disconnect_count == 15
        assert thresholds.low_battery_warning == 30
        assert thresholds.low_battery_critical == 15
        assert thresholds.stale_data_timeout == timedelta(hours=4)


# ============================================================================
# HealthTransition Tests
# ============================================================================


class TestHealthTransition:
    """Tests for HealthTransition enum."""

    def test_all_transitions_exist(self) -> None:
        """Test that all expected transitions are defined."""
        assert HealthTransition.DEGRADED == 'degraded'
        assert HealthTransition.IMPROVED == 'improved'
        assert HealthTransition.RECOVERED == 'recovered'
        assert HealthTransition.FAILED == 'failed'

    def test_transition_values(self) -> None:
        """Test transition string values."""
        assert len(HealthTransition) == 4


# ============================================================================
# HealthChange Tests
# ============================================================================


class TestHealthChange:
    """Tests for HealthChange dataclass."""

    def test_create_health_change(self) -> None:
        """Test creating a health change event."""
        now = datetime.now(timezone.utc)
        change = HealthChange(
            device_id='device-001',
            device_name='Front Door Camera',
            device_type='camera',
            old_status=DeviceHealthStatus.HEALTHY,
            new_status=DeviceHealthStatus.WARNING,
            transition=HealthTransition.DEGRADED,
            timestamp=now,
            reason='3 disconnections',
        )

        assert change.device_id == 'device-001'
        assert change.device_name == 'Front Door Camera'
        assert change.device_type == 'camera'
        assert change.old_status == DeviceHealthStatus.HEALTHY
        assert change.new_status == DeviceHealthStatus.WARNING
        assert change.transition == HealthTransition.DEGRADED
        assert change.timestamp == now
        assert change.reason == '3 disconnections'
        assert change.health_snapshot is None

    def test_health_change_with_snapshot(self) -> None:
        """Test health change with health snapshot."""
        health = DeviceHealth(device_id='device-001')
        change = HealthChange(
            device_id='device-001',
            device_name='Camera',
            device_type='camera',
            old_status=DeviceHealthStatus.HEALTHY,
            new_status=DeviceHealthStatus.OFFLINE,
            transition=HealthTransition.FAILED,
            timestamp=datetime.now(timezone.utc),
            reason='Device offline',
            health_snapshot=health,
        )

        assert change.health_snapshot is not None
        assert change.health_snapshot.device_id == 'device-001'


# ============================================================================
# HealthHistoryEntry Tests
# ============================================================================


class TestHealthHistoryEntry:
    """Tests for HealthHistoryEntry dataclass."""

    def test_create_entry(self) -> None:
        """Test creating a history entry."""
        now = datetime.now(timezone.utc)
        entry = HealthHistoryEntry(
            timestamp=now,
            status=DeviceHealthStatus.HEALTHY,
        )

        assert entry.timestamp == now
        assert entry.status == DeviceHealthStatus.HEALTHY
        assert entry.issues == []
        assert entry.battery_level is None

    def test_entry_with_issues(self) -> None:
        """Test entry with issues."""
        entry = HealthHistoryEntry(
            timestamp=datetime.now(timezone.utc),
            status=DeviceHealthStatus.WARNING,
            issues=['Low battery', '3 disconnections'],
            battery_level=15,
        )

        assert len(entry.issues) == 2
        assert 'Low battery' in entry.issues
        assert entry.battery_level == 15


# ============================================================================
# DeviceHealthSummary Tests
# ============================================================================


class TestDeviceHealthSummary:
    """Tests for DeviceHealthSummary dataclass."""

    def test_create_summary(self) -> None:
        """Test creating a health summary."""
        summary = DeviceHealthSummary(device_id='device-001')

        assert summary.device_id == 'device-001'
        assert summary.device_name == ''
        assert summary.device_type == ''
        assert summary.current_health is None
        assert summary.uptime_percentage == 100.0
        assert summary.total_incidents == 0
        assert summary.last_incident is None
        assert summary.average_recovery_time is None
        assert summary.health_trend == 'stable'
        assert summary.history == []

    def test_summary_with_data(self) -> None:
        """Test summary with full data."""
        now = datetime.now(timezone.utc)
        health = DeviceHealth(device_id='device-001')
        history = [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY),
        ]

        summary = DeviceHealthSummary(
            device_id='device-001',
            device_name='Front Camera',
            device_type='camera',
            current_health=health,
            uptime_percentage=98.5,
            total_incidents=2,
            last_incident=now,
            average_recovery_time=timedelta(minutes=5),
            health_trend='improving',
            history=history,
        )

        assert summary.device_name == 'Front Camera'
        assert summary.uptime_percentage == 98.5
        assert summary.total_incidents == 2
        assert summary.average_recovery_time == timedelta(minutes=5)
        assert summary.health_trend == 'improving'
        assert len(summary.history) == 1


# ============================================================================
# DeviceHealthMonitor Lifecycle Tests
# ============================================================================


class TestDeviceHealthMonitorLifecycle:
    """Tests for DeviceHealthMonitor start/stop lifecycle."""

    def test_init(self) -> None:
        """Test monitor initialization."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        assert monitor.client is client
        assert monitor.is_running is False
        assert isinstance(monitor.thresholds, HealthThresholds)

    def test_init_with_custom_thresholds(self) -> None:
        """Test initialization with custom thresholds."""
        client = create_mock_client()
        thresholds = HealthThresholds(warning_disconnect_count=5)
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        assert monitor.thresholds.warning_disconnect_count == 5

    def test_init_with_custom_check_interval(self) -> None:
        """Test initialization with custom check interval."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client, check_interval=30.0)

        assert monitor._check_interval == 30.0  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_start_not_connected(self) -> None:
        """Test start fails when client not connected."""
        client = create_mock_client(is_connected=False)
        monitor = DeviceHealthMonitor(client)

        with pytest.raises(ValueError, match='Client must be connected'):
            await monitor.start()

    @pytest.mark.asyncio
    async def test_start_already_running(self) -> None:
        """Test start fails when already running."""
        client = create_mock_client()
        event_handler = MagicMock(spec=EventHandler)
        event_handler.subscribe = MagicMock(return_value=lambda: None)

        monitor = DeviceHealthMonitor(client, event_handler=event_handler)
        monitor._is_running = True  # type: ignore[reportPrivateUsage]

        with pytest.raises(RuntimeError, match='already running'):
            await monitor.start()

    @pytest.mark.asyncio
    async def test_start_success(self) -> None:
        """Test successful start."""
        client = create_mock_client()
        event_handler = MagicMock(spec=EventHandler)
        event_handler.subscribe = MagicMock(return_value=lambda: None)

        monitor = DeviceHealthMonitor(client, event_handler=event_handler)

        # Mock the check task to avoid infinite loop
        with patch.object(monitor, '_periodic_health_check', new_callable=AsyncMock):
            await monitor.start()

        assert monitor.is_running is True
        event_handler.subscribe.assert_called_once()

    def test_stop(self) -> None:
        """Test stopping the monitor."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)
        monitor._is_running = True  # type: ignore[reportPrivateUsage]
        unsubscribe_mock = MagicMock()
        monitor._unsubscribe = unsubscribe_mock  # type: ignore[reportPrivateUsage]

        monitor.stop()

        assert monitor.is_running is False
        unsubscribe_mock.assert_called_once()

    def test_clear(self) -> None:
        """Test clearing monitor data."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Add some data
        monitor._device_health['device-001'] = DeviceHealth(device_id='device-001')  # type: ignore[reportPrivateUsage]
        monitor._device_names['device-001'] = 'Test Device'  # type: ignore[reportPrivateUsage]

        monitor.clear()

        assert len(monitor._device_health) == 0  # type: ignore[reportPrivateUsage]
        assert len(monitor._device_names) == 0  # type: ignore[reportPrivateUsage]


# ============================================================================
# Health Calculation Tests
# ============================================================================


class TestHealthCalculation:
    """Tests for health status calculation."""

    def test_calculate_health_unknown_device(self) -> None:
        """Test health calculation for unknown device."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        health = monitor._calculate_health('unknown-device')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.UNKNOWN

    def test_calculate_health_healthy(self) -> None:
        """Test healthy status calculation."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Set up healthy device
        now = datetime.now(timezone.utc)
        monitor._device_last_seen['device-001'] = now  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.HEALTHY

    def test_calculate_health_offline(self) -> None:
        """Test offline status when device not seen recently."""
        client = create_mock_client()
        thresholds = HealthThresholds(offline_timeout=timedelta(minutes=5))
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        # Last seen 10 minutes ago
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        monitor._device_last_seen['device-001'] = old_time  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.OFFLINE
        assert len(health.issues) > 0

    def test_calculate_health_warning_disconnects(self) -> None:
        """Test warning status for disconnect count."""
        client = create_mock_client()
        thresholds = HealthThresholds(warning_disconnect_count=3)
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        # Recent activity but multiple disconnects
        now = datetime.now(timezone.utc)
        monitor._device_last_seen['device-001'] = now  # type: ignore[reportPrivateUsage]
        monitor._device_disconnect_count['device-001'] = 4  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.WARNING
        assert health.disconnect_count == 4

    def test_calculate_health_critical_disconnects(self) -> None:
        """Test critical status for high disconnect count."""
        client = create_mock_client()
        thresholds = HealthThresholds(critical_disconnect_count=10)
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        now = datetime.now(timezone.utc)
        monitor._device_last_seen['device-001'] = now  # type: ignore[reportPrivateUsage]
        monitor._device_disconnect_count['device-001'] = 15  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.CRITICAL

    def test_calculate_health_low_battery_warning(self) -> None:
        """Test warning status for low battery."""
        client = create_mock_client()
        thresholds = HealthThresholds(low_battery_warning=20)
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        now = datetime.now(timezone.utc)
        monitor._device_last_seen['device-001'] = now  # type: ignore[reportPrivateUsage]
        monitor._device_battery_levels['device-001'] = 15  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.WARNING
        assert health.battery_level == 15

    def test_calculate_health_critical_battery(self) -> None:
        """Test critical status for very low battery."""
        client = create_mock_client()
        thresholds = HealthThresholds(low_battery_critical=10)
        monitor = DeviceHealthMonitor(client, thresholds=thresholds)

        now = datetime.now(timezone.utc)
        monitor._device_last_seen['device-001'] = now  # type: ignore[reportPrivateUsage]
        monitor._device_battery_levels['device-001'] = 5  # type: ignore[reportPrivateUsage]

        health = monitor._calculate_health('device-001')  # type: ignore[reportPrivateUsage]

        assert health.status == DeviceHealthStatus.CRITICAL


# ============================================================================
# Health Change Detection Tests
# ============================================================================


class TestHealthChangeDetection:
    """Tests for health change detection."""

    def test_determine_transition_degraded(self) -> None:
        """Test detecting degraded transition."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        transition = monitor._determine_transition(  # type: ignore[reportPrivateUsage]
            DeviceHealthStatus.HEALTHY,
            DeviceHealthStatus.WARNING,
        )

        assert transition == HealthTransition.DEGRADED

    def test_determine_transition_failed(self) -> None:
        """Test detecting failed transition."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        transition = monitor._determine_transition(  # type: ignore[reportPrivateUsage]
            DeviceHealthStatus.WARNING,
            DeviceHealthStatus.OFFLINE,
        )

        assert transition == HealthTransition.FAILED

    def test_determine_transition_improved(self) -> None:
        """Test detecting improved transition."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        transition = monitor._determine_transition(  # type: ignore[reportPrivateUsage]
            DeviceHealthStatus.CRITICAL,
            DeviceHealthStatus.WARNING,
        )

        assert transition == HealthTransition.IMPROVED

    def test_determine_transition_recovered(self) -> None:
        """Test detecting recovered transition."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        transition = monitor._determine_transition(  # type: ignore[reportPrivateUsage]
            DeviceHealthStatus.WARNING,
            DeviceHealthStatus.HEALTHY,
        )

        assert transition == HealthTransition.RECOVERED

    def test_health_change_callback(self) -> None:
        """Test health change callbacks are invoked."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Track callback invocations
        changes_received: list[HealthChange] = []

        def on_change(change: HealthChange) -> None:
            changes_received.append(change)

        monitor.subscribe_health_changes(on_change)

        # Set up device and trigger a change
        monitor._device_names['device-001'] = 'Test Device'  # type: ignore[reportPrivateUsage]
        monitor._device_types['device-001'] = 'camera'  # type: ignore[reportPrivateUsage]
        monitor._device_health['device-001'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-001',
            status=DeviceHealthStatus.HEALTHY,
        )

        # Simulate device going offline
        old_time = datetime.now(timezone.utc) - timedelta(hours=2)
        monitor._device_last_seen['device-001'] = old_time  # type: ignore[reportPrivateUsage]

        monitor._check_health_change('device-001')  # type: ignore[reportPrivateUsage]

        assert len(changes_received) == 1
        assert changes_received[0].device_id == 'device-001'
        assert changes_received[0].new_status == DeviceHealthStatus.OFFLINE

    def test_unsubscribe_callback(self) -> None:
        """Test unsubscribing from health changes."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        callback_count = 0

        def on_change(change: HealthChange) -> None:
            nonlocal callback_count
            callback_count += 1

        unsubscribe = monitor.subscribe_health_changes(on_change)
        unsubscribe()

        # Verify callback was removed
        assert on_change not in monitor._health_callbacks  # type: ignore[reportPrivateUsage]


# ============================================================================
# Event Handling Tests
# ============================================================================


class TestEventHandling:
    """Tests for event processing."""

    def test_on_event_updates_last_seen(self) -> None:
        """Test event updates device last seen time."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        event = create_protect_event(device_id='device-001')
        monitor._on_event(event)  # type: ignore[reportPrivateUsage]

        assert 'device-001' in monitor._device_last_seen  # type: ignore[reportPrivateUsage]
        assert monitor._device_last_seen['device-001'] == event.timestamp  # type: ignore[reportPrivateUsage]

    def test_on_event_tracks_disconnection(self) -> None:
        """Test event tracks disconnection count."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        event = create_protect_event(
            device_id='device-001',
            event_type=ProtectEventType.DEVICE_DISCONNECTED,
        )

        monitor._on_event(event)  # type: ignore[reportPrivateUsage]

        assert monitor._device_disconnect_count['device-001'] == 1  # type: ignore[reportPrivateUsage]

        # Send another disconnect
        monitor._on_event(event)  # type: ignore[reportPrivateUsage]

        assert monitor._device_disconnect_count['device-001'] == 2  # type: ignore[reportPrivateUsage]

    def test_on_event_tracks_battery(self) -> None:
        """Test event tracks battery level."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        event = create_protect_event(
            device_id='device-001',
            changed_data={'batteryStatus': {'percentage': 75}},
        )

        monitor._on_event(event)  # type: ignore[reportPrivateUsage]

        assert monitor._device_battery_levels['device-001'] == 75  # type: ignore[reportPrivateUsage]

    def test_on_event_ignores_empty_device_id(self) -> None:
        """Test event with no device ID is ignored."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        event = ProtectEvent(
            action=ProtectAction.UPDATE,
            model_type=ProtectModelType.NVR,
            device_id='',
            timestamp=datetime.now(timezone.utc),
        )

        monitor._on_event(event)  # type: ignore[reportPrivateUsage]

        assert '' not in monitor._device_last_seen  # type: ignore[reportPrivateUsage]


# ============================================================================
# Query Methods Tests
# ============================================================================


class TestQueryMethods:
    """Tests for health query methods."""

    def test_get_device_health(self) -> None:
        """Test getting health for a specific device."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        health = DeviceHealth(device_id='device-001', status=DeviceHealthStatus.HEALTHY)
        monitor._device_health['device-001'] = health  # type: ignore[reportPrivateUsage]

        result = monitor.get_device_health('device-001')

        assert result is not None
        assert result.device_id == 'device-001'
        assert result.status == DeviceHealthStatus.HEALTHY

    def test_get_device_health_not_found(self) -> None:
        """Test getting health for unknown device."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        result = monitor.get_device_health('unknown')

        assert result is None

    def test_get_all_device_health(self) -> None:
        """Test getting health for all devices."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        monitor._device_health['device-001'] = DeviceHealth(device_id='device-001')  # type: ignore[reportPrivateUsage]
        monitor._device_health['device-002'] = DeviceHealth(device_id='device-002')  # type: ignore[reportPrivateUsage]

        result = monitor.get_all_device_health()

        assert len(result) == 2

    def test_get_devices_by_status(self) -> None:
        """Test filtering devices by status."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        monitor._device_health['device-001'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-001',
            status=DeviceHealthStatus.HEALTHY,
        )
        monitor._device_health['device-002'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-002',
            status=DeviceHealthStatus.WARNING,
        )
        monitor._device_health['device-003'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-003',
            status=DeviceHealthStatus.WARNING,
        )

        result = monitor.get_devices_by_status(DeviceHealthStatus.WARNING)

        assert len(result) == 2
        assert all(h.status == DeviceHealthStatus.WARNING for h in result)

    def test_get_unhealthy_devices(self) -> None:
        """Test getting unhealthy devices."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        monitor._device_health['device-001'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-001',
            status=DeviceHealthStatus.HEALTHY,
        )
        monitor._device_health['device-002'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-002',
            status=DeviceHealthStatus.WARNING,
        )
        monitor._device_health['device-003'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-003',
            status=DeviceHealthStatus.OFFLINE,
        )

        result = monitor.get_unhealthy_devices()

        assert len(result) == 2
        device_ids = [h.device_id for h in result]
        assert 'device-001' not in device_ids
        assert 'device-002' in device_ids
        assert 'device-003' in device_ids


# ============================================================================
# Device Summary Tests
# ============================================================================


class TestDeviceSummary:
    """Tests for device health summaries."""

    def test_get_device_summary(self) -> None:
        """Test getting a device summary."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Set up device data
        monitor._device_names['device-001'] = 'Test Camera'  # type: ignore[reportPrivateUsage]
        monitor._device_types['device-001'] = 'camera'  # type: ignore[reportPrivateUsage]
        monitor._device_health['device-001'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-001',
            status=DeviceHealthStatus.HEALTHY,
        )

        summary = monitor.get_device_summary('device-001')

        assert summary.device_id == 'device-001'
        assert summary.device_name == 'Test Camera'
        assert summary.device_type == 'camera'
        assert summary.current_health is not None

    def test_get_device_summary_with_history(self) -> None:
        """Test summary includes history."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        now = datetime.now(timezone.utc)
        monitor._device_history['device-001'] = [  # type: ignore[reportPrivateUsage]
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY),
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.WARNING),
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY),
        ]

        summary = monitor.get_device_summary('device-001')

        assert len(summary.history) == 3

    def test_calculate_health_trend_stable(self) -> None:
        """Test stable health trend calculation."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        now = datetime.now(timezone.utc)
        history = [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY)
            for _ in range(20)
        ]

        trend = monitor._calculate_health_trend(history)  # type: ignore[reportPrivateUsage]

        assert trend == 'stable'

    def test_calculate_health_trend_degrading(self) -> None:
        """Test degrading health trend calculation."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        now = datetime.now(timezone.utc)
        # First half healthy, second half warning
        history = [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY)
            for _ in range(10)
        ] + [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.WARNING)
            for _ in range(10)
        ]

        trend = monitor._calculate_health_trend(history)  # type: ignore[reportPrivateUsage]

        assert trend == 'degrading'

    def test_calculate_health_trend_improving(self) -> None:
        """Test improving health trend calculation."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        now = datetime.now(timezone.utc)
        # First half warning, second half healthy
        history = [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.WARNING)
            for _ in range(10)
        ] + [
            HealthHistoryEntry(timestamp=now, status=DeviceHealthStatus.HEALTHY)
            for _ in range(10)
        ]

        trend = monitor._calculate_health_trend(history)  # type: ignore[reportPrivateUsage]

        assert trend == 'improving'


# ============================================================================
# Fleet Summary Tests
# ============================================================================


class TestFleetSummary:
    """Tests for fleet-wide health summaries."""

    def test_get_fleet_summary_empty(self) -> None:
        """Test fleet summary with no devices."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        summary = monitor.get_fleet_summary()

        assert summary['total_devices'] == 0
        assert summary['healthy'] == 0
        assert summary['health_percentage'] == 100.0
        assert summary['devices_with_issues'] == []

    def test_get_fleet_summary_all_healthy(self) -> None:
        """Test fleet summary with all healthy devices."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        for i in range(5):
            monitor._device_health[f'device-{i}'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
                device_id=f'device-{i}',
                status=DeviceHealthStatus.HEALTHY,
            )

        summary = monitor.get_fleet_summary()

        assert summary['total_devices'] == 5
        assert summary['healthy'] == 5
        assert summary['warning'] == 0
        assert summary['health_percentage'] == 100.0
        assert summary['devices_with_issues'] == []

    def test_get_fleet_summary_mixed_status(self) -> None:
        """Test fleet summary with mixed health status."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        monitor._device_health['device-1'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-1',
            device_name='Camera 1',
            status=DeviceHealthStatus.HEALTHY,
        )
        monitor._device_health['device-2'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-2',
            device_name='Camera 2',
            status=DeviceHealthStatus.WARNING,
            issues=['Low battery'],
        )
        monitor._device_health['device-3'] = DeviceHealth(  # type: ignore[reportPrivateUsage]
            device_id='device-3',
            device_name='Sensor 1',
            status=DeviceHealthStatus.OFFLINE,
            issues=['Device offline'],
        )

        summary = monitor.get_fleet_summary()

        assert summary['total_devices'] == 3
        assert summary['healthy'] == 1
        assert summary['warning'] == 1
        assert summary['offline'] == 1
        assert abs(summary['health_percentage'] - 33.33) < 1.0
        assert len(summary['devices_with_issues']) == 2


# ============================================================================
# Statistics Reset Tests
# ============================================================================


class TestStatisticsReset:
    """Tests for statistics reset functionality."""

    def test_reset_device_stats(self) -> None:
        """Test resetting stats for a single device."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Set up device data
        monitor._device_disconnect_count['device-001'] = 10  # type: ignore[reportPrivateUsage]
        monitor._device_history['device-001'] = [  # type: ignore[reportPrivateUsage]
            HealthHistoryEntry(
                timestamp=datetime.now(timezone.utc),
                status=DeviceHealthStatus.WARNING,
            )
        ]

        monitor.reset_device_stats('device-001')

        assert monitor._device_disconnect_count['device-001'] == 0  # type: ignore[reportPrivateUsage]
        assert 'device-001' not in monitor._device_history  # type: ignore[reportPrivateUsage]

    def test_reset_all_stats(self) -> None:
        """Test resetting stats for all devices."""
        client = create_mock_client()
        monitor = DeviceHealthMonitor(client)

        # Set up device data
        for i in range(3):
            device_id = f'device-{i}'
            monitor._device_disconnect_count[device_id] = i + 1  # type: ignore[reportPrivateUsage]
            monitor._device_history[device_id] = []  # type: ignore[reportPrivateUsage]

        monitor.reset_all_stats()

        for i in range(3):
            device_id = f'device-{i}'
            assert monitor._device_disconnect_count[device_id] == 0  # type: ignore[reportPrivateUsage]

        assert len(monitor._device_history) == 0  # type: ignore[reportPrivateUsage]


# ============================================================================
# Device Initialization Tests
# ============================================================================


class TestDeviceInitialization:
    """Tests for device initialization from client state."""

    @pytest.mark.asyncio
    async def test_initialize_devices_cameras(self) -> None:
        """Test initialization with cameras."""
        camera = create_mock_device('cam-001', 'Front Camera')
        client = create_mock_client(cameras={'cam-001': camera})

        event_handler = MagicMock(spec=EventHandler)
        event_handler.subscribe = MagicMock(return_value=lambda: None)

        monitor = DeviceHealthMonitor(client, event_handler=event_handler)

        with patch.object(monitor, '_periodic_health_check', new_callable=AsyncMock):
            await monitor.start()

        assert 'cam-001' in monitor._device_names  # type: ignore[reportPrivateUsage]
        assert monitor._device_names['cam-001'] == 'Front Camera'  # type: ignore[reportPrivateUsage]
        assert monitor._device_types['cam-001'] == 'camera'  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_initialize_devices_sensors(self) -> None:
        """Test initialization with sensors."""
        sensor = create_mock_device('sensor-001', 'Door Sensor')
        client = create_mock_client(sensors={'sensor-001': sensor})

        event_handler = MagicMock(spec=EventHandler)
        event_handler.subscribe = MagicMock(return_value=lambda: None)

        monitor = DeviceHealthMonitor(client, event_handler=event_handler)

        with patch.object(monitor, '_periodic_health_check', new_callable=AsyncMock):
            await monitor.start()

        assert 'sensor-001' in monitor._device_names  # type: ignore[reportPrivateUsage]
        assert monitor._device_types['sensor-001'] == 'sensor'  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_initialize_devices_multiple_types(self) -> None:
        """Test initialization with multiple device types."""
        camera = create_mock_device('cam-001', 'Camera 1')
        sensor = create_mock_device('sensor-001', 'Sensor 1')
        light = create_mock_device('light-001', 'Light 1')

        client = create_mock_client(
            cameras={'cam-001': camera},
            sensors={'sensor-001': sensor},
            lights={'light-001': light},
        )

        event_handler = MagicMock(spec=EventHandler)
        event_handler.subscribe = MagicMock(return_value=lambda: None)

        monitor = DeviceHealthMonitor(client, event_handler=event_handler)

        with patch.object(monitor, '_periodic_health_check', new_callable=AsyncMock):
            await monitor.start()

        assert len(monitor._device_names) == 3  # type: ignore[reportPrivateUsage]
        assert monitor._device_types['cam-001'] == 'camera'  # type: ignore[reportPrivateUsage]
        assert monitor._device_types['sensor-001'] == 'sensor'  # type: ignore[reportPrivateUsage]
        assert monitor._device_types['light-001'] == 'light'  # type: ignore[reportPrivateUsage]
