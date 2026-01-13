"""Tests for Device Statistics collection."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unifi_mapper.network.models import (
    CPUMemoryStats,
    DeviceStatistics,
    PortStatistics,
)
from unifi_mapper.network.statistics import (
    DeviceMetricsCollector,
    MetricsSnapshot,
    PortMetrics,
)
from unittest.mock import AsyncMock, MagicMock


class TestPortMetrics:
    """Tests for PortMetrics dataclass."""

    def test_error_rate_calculation(self) -> None:
        """Test error rate percentage calculation."""
        metrics = PortMetrics(
            port_idx=1,
            device_id='device-1',
            total_tx_packets=1000,
            total_rx_packets=1000,
            total_tx_errors=5,
            total_rx_errors=5,
        )
        # 10 errors out of 2000 packets = 0.5%
        assert metrics.error_rate_percent == 0.5

    def test_error_rate_zero_packets(self) -> None:
        """Test error rate with zero packets."""
        metrics = PortMetrics(port_idx=1, device_id='device-1')
        assert metrics.error_rate_percent == 0.0

    def test_drop_rate_calculation(self) -> None:
        """Test drop rate percentage calculation."""
        metrics = PortMetrics(
            port_idx=1,
            device_id='device-1',
            total_tx_packets=1000,
            total_rx_packets=1000,
            total_tx_dropped=10,
            total_rx_dropped=10,
        )
        # 20 drops out of 2000 packets = 1%
        assert metrics.drop_rate_percent == 1.0

    def test_link_flap_count(self) -> None:
        """Test link flap count property."""
        metrics = PortMetrics(
            port_idx=1,
            device_id='device-1',
            link_down_count=3,
        )
        assert metrics.link_flap_count == 3


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""

    def test_total_throughput(self) -> None:
        """Test total throughput calculation."""
        port1 = PortMetrics(
            port_idx=1,
            device_id='device-1',
            avg_tx_rate_bps=1000000,  # 1 Mbps
            avg_rx_rate_bps=2000000,  # 2 Mbps
        )
        port2 = PortMetrics(
            port_idx=2,
            device_id='device-1',
            avg_tx_rate_bps=500000,  # 0.5 Mbps
            avg_rx_rate_bps=500000,  # 0.5 Mbps
        )

        snapshot = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
            port_metrics={1: port1, 2: port2},
        )

        # Total: 1 + 2 + 0.5 + 0.5 = 4 Mbps
        assert snapshot.total_throughput_bps == 4000000

    def test_active_port_count(self) -> None:
        """Test active port counting."""
        port1 = PortMetrics(port_idx=1, device_id='device-1', last_link_up=True)
        port2 = PortMetrics(port_idx=2, device_id='device-1', last_link_up=False)
        port3 = PortMetrics(port_idx=3, device_id='device-1', last_link_up=True)

        snapshot = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
            port_metrics={1: port1, 2: port2, 3: port3},
        )

        assert snapshot.active_port_count == 2

    def test_get_top_ports_by_throughput(self) -> None:
        """Test getting top ports by throughput."""
        ports = {
            1: PortMetrics(port_idx=1, device_id='d', avg_tx_rate_bps=100, avg_rx_rate_bps=100),
            2: PortMetrics(port_idx=2, device_id='d', avg_tx_rate_bps=500, avg_rx_rate_bps=500),
            3: PortMetrics(port_idx=3, device_id='d', avg_tx_rate_bps=300, avg_rx_rate_bps=300),
            4: PortMetrics(port_idx=4, device_id='d', avg_tx_rate_bps=50, avg_rx_rate_bps=50),
        }

        snapshot = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
            port_metrics=ports,
        )

        top_3 = snapshot.get_top_ports_by_throughput(n=3)
        assert len(top_3) == 3
        assert top_3[0].port_idx == 2  # Highest throughput
        assert top_3[1].port_idx == 3
        assert top_3[2].port_idx == 1

    def test_get_error_ports(self) -> None:
        """Test getting ports with high error rates."""
        ports = {
            1: PortMetrics(
                port_idx=1,
                device_id='d',
                total_tx_packets=1000,
                total_rx_packets=1000,
                total_tx_errors=0,
                total_rx_errors=0,
            ),
            2: PortMetrics(
                port_idx=2,
                device_id='d',
                total_tx_packets=1000,
                total_rx_packets=1000,
                total_tx_errors=10,  # 0.5% error rate
                total_rx_errors=10,
            ),
            3: PortMetrics(
                port_idx=3,
                device_id='d',
                total_tx_packets=1000,
                total_rx_packets=1000,
                total_tx_errors=1,  # 0.05% error rate
                total_rx_errors=0,
            ),
        }

        snapshot = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
            port_metrics=ports,
        )

        # Threshold 0.1%
        error_ports = snapshot.get_error_ports(threshold_percent=0.1)
        assert len(error_ports) == 1
        assert error_ports[0].port_idx == 2


class TestDeviceMetricsCollector:
    """Tests for DeviceMetricsCollector."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.get_device_statistics = AsyncMock()
        return client

    def test_callback_registration(self, mock_client: MagicMock) -> None:
        """Test callback registration and removal."""
        collector = DeviceMetricsCollector(mock_client)

        callback = MagicMock()
        collector.on_snapshot(callback)
        assert callback in collector._callbacks

        collector.remove_callback(callback)
        assert callback not in collector._callbacks

    @pytest.mark.asyncio
    async def test_collect_once(self, mock_client: MagicMock) -> None:
        """Test single collection."""
        # Setup mock response
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            uptimeSeconds=3600,
            cpuMemory=CPUMemoryStats(
                cpuUtilizationPercent=25.0,
                memoryUtilizationPercent=50.0,
            ),
            ports=[
                PortStatistics(
                    portIdx=1,
                    linkUp=True,
                    txBytes=1000,
                    rxBytes=2000,
                    txRateBps=100,
                    rxRateBps=200,
                ),
            ],
        )

        collector = DeviceMetricsCollector(mock_client)
        snapshot = await collector.collect_once('device-1')

        assert snapshot.device_id == 'device-1'
        assert snapshot.uptime_seconds == 3600
        assert snapshot.cpu_percent == 25.0
        assert snapshot.memory_percent == 50.0
        assert 1 in snapshot.port_metrics

    @pytest.mark.asyncio
    async def test_collect_updates_metrics(self, mock_client: MagicMock) -> None:
        """Test that collection updates port metrics."""
        # First collection
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            ports=[
                PortStatistics(portIdx=1, linkUp=True, txRateBps=100, rxRateBps=200),
            ],
        )

        collector = DeviceMetricsCollector(mock_client)
        snapshot1 = await collector.collect_once('device-1')

        assert snapshot1.port_metrics[1].samples == 1
        assert snapshot1.port_metrics[1].avg_tx_rate_bps == 100
        assert snapshot1.port_metrics[1].avg_rx_rate_bps == 200

        # Second collection with different rates
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            ports=[
                PortStatistics(portIdx=1, linkUp=True, txRateBps=300, rxRateBps=400),
            ],
        )

        snapshot2 = await collector.collect_once('device-1')

        # Verify averaging
        assert snapshot2.port_metrics[1].samples == 2
        # Average: (100 + 300) / 2 = 200
        assert snapshot2.port_metrics[1].avg_tx_rate_bps == 200
        # Average: (200 + 400) / 2 = 300
        assert snapshot2.port_metrics[1].avg_rx_rate_bps == 300

    @pytest.mark.asyncio
    async def test_link_state_tracking(self, mock_client: MagicMock) -> None:
        """Test link state change tracking."""
        collector = DeviceMetricsCollector(mock_client)

        # First collection - link up
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            ports=[PortStatistics(portIdx=1, linkUp=True)],
        )
        await collector.collect_once('device-1')

        # Second collection - link down
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            ports=[PortStatistics(portIdx=1, linkUp=False)],
        )
        await collector.collect_once('device-1')

        # Third collection - link up again
        mock_client.get_device_statistics.return_value = DeviceStatistics(
            deviceId='device-1',
            ports=[PortStatistics(portIdx=1, linkUp=True)],
        )
        snapshot = await collector.collect_once('device-1')

        # Should have detected 2 link up events and 1 link down
        assert snapshot.port_metrics[1].link_up_count == 2
        assert snapshot.port_metrics[1].link_down_count == 1

    def test_reset_metrics(self, mock_client: MagicMock) -> None:
        """Test metrics reset."""
        collector = DeviceMetricsCollector(mock_client)

        # Add some data
        collector._port_metrics['device-1'] = {
            1: PortMetrics(port_idx=1, device_id='device-1', samples=10)
        }
        collector._snapshots['device-1'] = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
        )

        # Reset single device
        collector.reset_metrics('device-1')
        assert 'device-1' not in collector._port_metrics
        assert 'device-1' not in collector._snapshots

        # Reset all
        collector._port_metrics['device-2'] = {}
        collector.reset_metrics()
        assert len(collector._port_metrics) == 0

    def test_get_snapshot(self, mock_client: MagicMock) -> None:
        """Test getting stored snapshots."""
        collector = DeviceMetricsCollector(mock_client)

        # No snapshot yet
        assert collector.get_snapshot('device-1') is None

        # Add snapshot
        snapshot = MetricsSnapshot(
            timestamp=datetime.now(timezone.utc),
            device_id='device-1',
        )
        collector._snapshots['device-1'] = snapshot

        assert collector.get_snapshot('device-1') is snapshot

    def test_get_all_snapshots(self, mock_client: MagicMock) -> None:
        """Test getting all snapshots."""
        collector = DeviceMetricsCollector(mock_client)

        collector._snapshots = {
            'device-1': MetricsSnapshot(
                timestamp=datetime.now(timezone.utc),
                device_id='device-1',
            ),
            'device-2': MetricsSnapshot(
                timestamp=datetime.now(timezone.utc),
                device_id='device-2',
            ),
        }

        all_snapshots = collector.get_all_snapshots()
        assert len(all_snapshots) == 2
        assert 'device-1' in all_snapshots
        assert 'device-2' in all_snapshots
