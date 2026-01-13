"""Device statistics collection and metrics aggregation.

This module provides tools for collecting and analyzing real-time
device statistics from UniFi Network devices.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from unifi_mapper.network.models import (
    DeviceStatistics,
    PortStatistics,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class PortMetrics:
    """Aggregated metrics for a single port over time."""

    port_idx: int
    device_id: str
    samples: int = 0
    # Throughput metrics (bytes/sec averaged over collection period)
    avg_tx_rate_bps: float = 0.0
    avg_rx_rate_bps: float = 0.0
    max_tx_rate_bps: int = 0
    max_rx_rate_bps: int = 0
    # Cumulative counters
    total_tx_bytes: int = 0
    total_rx_bytes: int = 0
    total_tx_packets: int = 0
    total_rx_packets: int = 0
    # Error tracking
    total_tx_errors: int = 0
    total_rx_errors: int = 0
    total_tx_dropped: int = 0
    total_rx_dropped: int = 0
    # State
    link_up_count: int = 0
    link_down_count: int = 0
    last_link_up: bool = False
    # PoE metrics
    poe_enabled: bool = False
    avg_poe_power_watts: float = 0.0
    max_poe_power_watts: float = 0.0

    @property
    def error_rate_percent(self) -> float:
        """Calculate error rate as percentage of total packets."""
        total_packets = self.total_tx_packets + self.total_rx_packets
        total_errors = self.total_tx_errors + self.total_rx_errors
        return (total_errors / total_packets * 100) if total_packets > 0 else 0.0

    @property
    def drop_rate_percent(self) -> float:
        """Calculate drop rate as percentage of total packets."""
        total_packets = self.total_tx_packets + self.total_rx_packets
        total_drops = self.total_tx_dropped + self.total_rx_dropped
        return (total_drops / total_packets * 100) if total_packets > 0 else 0.0

    @property
    def link_flap_count(self) -> int:
        """Number of times link state changed."""
        return self.link_down_count


@dataclass
class MetricsSnapshot:
    """Snapshot of metrics at a point in time."""

    timestamp: datetime
    device_id: str
    uptime_seconds: int = 0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    temperature_celsius: float | None = None
    port_metrics: dict[int, PortMetrics] = field(default_factory=dict)

    @property
    def total_throughput_bps(self) -> int:
        """Total throughput across all ports in bits per second."""
        total_tx = sum(p.avg_tx_rate_bps for p in self.port_metrics.values())
        total_rx = sum(p.avg_rx_rate_bps for p in self.port_metrics.values())
        return int(total_tx + total_rx)

    @property
    def active_port_count(self) -> int:
        """Number of ports with link up."""
        return sum(1 for p in self.port_metrics.values() if p.last_link_up)

    def get_top_ports_by_throughput(self, n: int = 5) -> list[PortMetrics]:
        """Get the N ports with highest throughput."""
        sorted_ports = sorted(
            self.port_metrics.values(),
            key=lambda p: p.avg_tx_rate_bps + p.avg_rx_rate_bps,
            reverse=True,
        )
        return sorted_ports[:n]

    def get_error_ports(self, threshold_percent: float = 0.1) -> list[PortMetrics]:
        """Get ports with error rate above threshold."""
        return [
            p for p in self.port_metrics.values()
            if p.error_rate_percent > threshold_percent
        ]


MetricsCallback = Callable[[MetricsSnapshot], None]


class DeviceMetricsCollector:
    """Collect and aggregate device statistics over time.

    This class provides continuous monitoring of device statistics
    with aggregation and analysis capabilities.

    Example:
        >>> collector = DeviceMetricsCollector(client)
        >>> collector.on_snapshot(lambda s: print(f"CPU: {s.cpu_percent}%"))
        >>> await collector.start_collection(['device-uuid-1', 'device-uuid-2'])
        >>> # Later...
        >>> snapshot = collector.get_snapshot('device-uuid-1')
    """

    def __init__(
        self,
        client: UniFiNetworkClient,
        interval_seconds: int = 30,
    ) -> None:
        """Initialize the metrics collector.

        Args:
            client: Network API client.
            interval_seconds: Collection interval in seconds.
        """
        self._client = client
        self._interval = interval_seconds
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._snapshots: dict[str, MetricsSnapshot] = {}
        self._port_metrics: dict[str, dict[int, PortMetrics]] = {}
        self._callbacks: list[MetricsCallback] = []
        self._device_ids: list[str] = []

    def on_snapshot(self, callback: MetricsCallback) -> None:
        """Register a callback for new snapshots.

        Args:
            callback: Function to call with new snapshots.
        """
        self._callbacks.append(callback)

    def remove_callback(self, callback: MetricsCallback) -> None:
        """Remove a snapshot callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def start_collection(self, device_ids: list[str]) -> None:
        """Start collecting metrics for devices.

        Args:
            device_ids: List of device UUIDs to monitor.
        """
        if self._running:
            log.warning("Collection already running")
            return

        self._device_ids = device_ids
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())
        log.info(f"Started metrics collection for {len(device_ids)} devices")

    async def stop_collection(self) -> None:
        """Stop collecting metrics."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("Stopped metrics collection")

    async def _collection_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                await self._collect_all()
            except Exception as e:
                log.error(f"Collection error: {e}")

            await asyncio.sleep(self._interval)

    async def _collect_all(self) -> None:
        """Collect metrics from all monitored devices."""
        tasks = [self._collect_device(device_id) for device_id in self._device_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _collect_device(self, device_id: str) -> None:
        """Collect metrics from a single device."""
        try:
            stats = await self._client.get_device_statistics(device_id)
            snapshot = self._process_statistics(device_id, stats)
            self._snapshots[device_id] = snapshot

            # Notify callbacks
            for callback in self._callbacks:
                try:
                    callback(snapshot)
                except Exception as e:
                    log.error(f"Callback error: {e}")

        except Exception as e:
            log.error(f"Failed to collect metrics for {device_id}: {e}")

    def _process_statistics(
        self,
        device_id: str,
        stats: DeviceStatistics,
    ) -> MetricsSnapshot:
        """Process raw statistics into a metrics snapshot."""
        now = datetime.now(timezone.utc)

        # Initialize port metrics storage if needed
        if device_id not in self._port_metrics:
            self._port_metrics[device_id] = {}

        # Process each port
        for port in stats.ports:
            self._update_port_metrics(device_id, port)

        snapshot = MetricsSnapshot(
            timestamp=now,
            device_id=device_id,
            uptime_seconds=stats.uptime_seconds,
            cpu_percent=stats.cpu_memory.cpu_utilization_percent if stats.cpu_memory else 0.0,
            memory_percent=stats.cpu_memory.memory_utilization_percent if stats.cpu_memory else 0.0,
            temperature_celsius=stats.temperature_celsius,
            port_metrics=self._port_metrics[device_id].copy(),
        )

        return snapshot

    def _update_port_metrics(
        self,
        device_id: str,
        port: PortStatistics,
    ) -> None:
        """Update aggregated port metrics."""
        port_store = self._port_metrics[device_id]

        if port.port_idx not in port_store:
            port_store[port.port_idx] = PortMetrics(
                port_idx=port.port_idx,
                device_id=device_id,
            )

        metrics = port_store[port.port_idx]
        metrics.samples += 1

        # Update throughput (rolling average)
        metrics.avg_tx_rate_bps = (
            (metrics.avg_tx_rate_bps * (metrics.samples - 1) + port.tx_rate_bps)
            / metrics.samples
        )
        metrics.avg_rx_rate_bps = (
            (metrics.avg_rx_rate_bps * (metrics.samples - 1) + port.rx_rate_bps)
            / metrics.samples
        )

        # Update max rates
        metrics.max_tx_rate_bps = max(metrics.max_tx_rate_bps, port.tx_rate_bps)
        metrics.max_rx_rate_bps = max(metrics.max_rx_rate_bps, port.rx_rate_bps)

        # Update cumulative counters
        metrics.total_tx_bytes = port.tx_bytes
        metrics.total_rx_bytes = port.rx_bytes
        metrics.total_tx_packets = port.tx_packets
        metrics.total_rx_packets = port.rx_packets
        metrics.total_tx_errors = port.tx_errors
        metrics.total_rx_errors = port.rx_errors
        metrics.total_tx_dropped = port.tx_dropped
        metrics.total_rx_dropped = port.rx_dropped

        # Track link state changes
        if port.link_up != metrics.last_link_up:
            if port.link_up:
                metrics.link_up_count += 1
            else:
                metrics.link_down_count += 1
        metrics.last_link_up = port.link_up

        # PoE metrics
        metrics.poe_enabled = port.poe_enabled
        if port.poe_enabled:
            metrics.avg_poe_power_watts = (
                (metrics.avg_poe_power_watts * (metrics.samples - 1) + port.poe_power_watts)
                / metrics.samples
            )
            metrics.max_poe_power_watts = max(metrics.max_poe_power_watts, port.poe_power_watts)

    def get_snapshot(self, device_id: str) -> MetricsSnapshot | None:
        """Get the latest metrics snapshot for a device.

        Args:
            device_id: Device UUID.

        Returns:
            Latest metrics snapshot or None if not available.
        """
        return self._snapshots.get(device_id)

    def get_all_snapshots(self) -> dict[str, MetricsSnapshot]:
        """Get all current metrics snapshots."""
        return self._snapshots.copy()

    async def collect_once(self, device_id: str) -> MetricsSnapshot:
        """Collect metrics once for a device.

        Args:
            device_id: Device UUID.

        Returns:
            Metrics snapshot.
        """
        stats = await self._client.get_device_statistics(device_id)
        return self._process_statistics(device_id, stats)

    def reset_metrics(self, device_id: str | None = None) -> None:
        """Reset accumulated metrics.

        Args:
            device_id: Specific device to reset, or None for all.
        """
        if device_id:
            self._port_metrics.pop(device_id, None)
            self._snapshots.pop(device_id, None)
        else:
            self._port_metrics.clear()
            self._snapshots.clear()
