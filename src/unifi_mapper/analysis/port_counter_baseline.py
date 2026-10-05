"""Persistent baseline storage for UniFi port error counters."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.models.stp import STPPortConfig, SwitchSTPConfig


# Device types whose port_table carries switch-port counters (switches and gateways
# with built-in switch ports). Shared by the link-error baseline and counter history.
SWITCH_DEVICE_TYPES = ('usw', 'udm', 'udmpro')
STATE_DIR_NAME = 'unifi_mapper'


class PortCounterSnapshot(BaseModel):
    """A point-in-time snapshot of port error and drop counters."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    rx_errors: int = 0
    tx_errors: int = 0
    crc_errors: int = 0
    rx_dropped: int = 0
    tx_dropped: int = 0


def state_dir() -> Path:
    """Return the state root: ``$XDG_STATE_HOME/unifi_mapper`` or ``~/.local/state/unifi_mapper``.

    Read at call time, so a changed ``XDG_STATE_HOME`` (tests isolate it per test)
    takes effect immediately. A relative ``XDG_STATE_HOME`` (``~`` is not expanded) is
    ignored, as the XDG Base Directory spec says, so the root is never relative to the
    working directory. Nothing is created here.
    """
    state_home = os.environ.get('XDG_STATE_HOME')
    if state_home and Path(state_home).is_absolute():
        return Path(state_home) / STATE_DIR_NAME
    return Path.home() / '.local' / 'state' / STATE_DIR_NAME


def default_baseline_path() -> Path:
    """Return the XDG state path used for persisted port counter baselines."""
    return state_dir() / 'port-counters.json'


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


def _count(value: Any) -> int:
    """Return ``value`` as a non-negative counter, or 0 when it is missing or not a number."""
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def snapshots_from_devices(
    devices: list[dict[str, Any]],
    *,
    timestamp: str | None = None,
) -> dict[str, PortCounterSnapshot]:
    """Build baseline snapshots for every port of every switch-type device with an ``_id``.

    A device without ``_id`` (pending adoption) has no stable key and is skipped, as
    are ports without an integer ``port_idx``. CRC errors use the same source as the
    port diagnostics (``port_stats.rx_crc_errors``, then ``rx_crc_errors``).

    Args:
        devices: Raw ``stat/device`` rows.
        timestamp: ISO timestamp for every snapshot; defaults to now.

    Returns:
        Snapshots keyed by :func:`port_counter_key`.
    """
    # Imported here: diagnostic_reads imports port_inspect, which imports this package.
    from unifi_mapper.diagnostic_reads import crc_errors

    stamp = timestamp or datetime.now().isoformat()
    snapshots: dict[str, PortCounterSnapshot] = {}
    for device in devices:
        if not isinstance(device, dict) or device.get('type') not in SWITCH_DEVICE_TYPES:
            continue
        device_id = device.get('_id')
        if not device_id:
            continue
        for port in device.get('port_table') or []:
            if not isinstance(port, dict):
                continue
            port_idx = port.get('port_idx')
            if isinstance(port_idx, bool) or not isinstance(port_idx, int):
                continue
            snapshots[port_counter_key(str(device_id), port_idx)] = PortCounterSnapshot(
                timestamp=stamp,
                rx_errors=_count(port.get('rx_errors')),
                tx_errors=_count(port.get('tx_errors')),
                crc_errors=_count(crc_errors(port)[0]),
                rx_dropped=_count(port.get('rx_dropped')),
                tx_dropped=_count(port.get('tx_dropped')),
            )
    return snapshots


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
