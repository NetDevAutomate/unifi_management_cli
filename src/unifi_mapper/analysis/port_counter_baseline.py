"""Persistent baseline storage for UniFi port error counters."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import cast
from unifi_mapper.core.models.stp import STPPortConfig, SwitchSTPConfig


class PortCounterSnapshot(BaseModel):
    """A point-in-time snapshot of port error and drop counters."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    rx_errors: int = 0
    tx_errors: int = 0
    crc_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0


def default_baseline_path() -> Path:
    """Return the XDG state path used for persisted port counter baselines."""
    state_home = os.environ.get('XDG_STATE_HOME')
    if state_home:
        return Path(state_home) / 'unifi_mapper' / 'port-counters.json'
    return Path.home() / '.local' / 'state' / 'unifi_mapper' / 'port-counters.json'


def port_counter_key(device_id: str, port_idx: int) -> str:
    """Return the stable baseline key for a switch port."""
    return f'{device_id}:{port_idx}'


def snapshot_from_port(port: STPPortConfig) -> PortCounterSnapshot:
    """Build a counter snapshot from an STP port config."""
    return PortCounterSnapshot(
        rx_errors=port.rx_errors,
        tx_errors=port.tx_errors,
        crc_errors=port.crc_errors,
        rx_dropped=port.rx_dropped,
        tx_dropped=port.tx_dropped,
    )


def snapshots_from_switches(
    switches: list[SwitchSTPConfig],
) -> dict[str, PortCounterSnapshot]:
    """Build baseline snapshots for all ports on the supplied switches."""
    return {
        port_counter_key(switch.device_id, port.port_idx): snapshot_from_port(port)
        for switch in switches
        for port in switch.port_states
    }


def diff_snapshots(
    baseline: PortCounterSnapshot,
    current: PortCounterSnapshot,
) -> PortCounterSnapshot:
    """Return non-negative counter deltas between two snapshots."""
    return PortCounterSnapshot(
        timestamp=current.timestamp,
        rx_errors=max(0, current.rx_errors - baseline.rx_errors),
        tx_errors=max(0, current.tx_errors - baseline.tx_errors),
        crc_errors=max(0, current.crc_errors - baseline.crc_errors),
        rx_dropped=max(0, current.rx_dropped - baseline.rx_dropped),
        tx_dropped=max(0, current.tx_dropped - baseline.tx_dropped),
    )


class PortCounterBaselineStore:
    """JSON-backed storage for port counter baselines."""

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the store with an explicit or default state path."""
        self.path = path or default_baseline_path()

    def load(self) -> dict[str, PortCounterSnapshot]:
        """Load saved baselines, returning an empty mapping when none exists."""
        if not self.path.exists():
            return {}

        with self.path.open('r', encoding='utf-8') as file:
            raw_data: object = json.load(file)

        if not isinstance(raw_data, dict):
            return {}

        snapshots: dict[str, PortCounterSnapshot] = {}
        raw_snapshots = cast(dict[str, object], raw_data)
        for key, value in raw_snapshots.items():
            if isinstance(value, dict):
                snapshots[key] = PortCounterSnapshot.model_validate(value)
        return snapshots

    def save(self, snapshots: dict[str, PortCounterSnapshot]) -> None:
        """Persist baselines to disk, creating parent directories as needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            key: snapshot.model_dump(mode='json') for key, snapshot in sorted(snapshots.items())
        }
        with self.path.open('w', encoding='utf-8') as file:
            json.dump(payload, file, indent=2)
            file.write('\n')

    def diff_since_last(
        self,
        current: dict[str, PortCounterSnapshot],
    ) -> dict[str, PortCounterSnapshot]:
        """Compare current snapshots against the saved baseline."""
        baseline = self.load()
        return {
            key: diff_snapshots(baseline_snapshot, current_snapshot)
            for key, current_snapshot in current.items()
            if (baseline_snapshot := baseline.get(key)) is not None
        }
