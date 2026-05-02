"""Tests for port counter baseline persistence."""

from __future__ import annotations

from pathlib import Path
from unifi_mapper.analysis.port_counter_baseline import (
    PortCounterBaselineStore,
    PortCounterSnapshot,
    default_baseline_path,
    diff_snapshots,
    port_counter_key,
    snapshots_from_switches,
)
from unifi_mapper.core.models.stp import STPPortConfig, SwitchSTPConfig


def test_default_baseline_path_uses_xdg_state_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Default path honors XDG_STATE_HOME."""
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))

    assert default_baseline_path() == tmp_path / 'unifi_mapper' / 'port-counters.json'


def test_missing_baseline_loads_empty(tmp_path: Path) -> None:
    """Missing baseline file returns no snapshots."""
    store = PortCounterBaselineStore(tmp_path / 'missing' / 'port-counters.json')

    assert store.load() == {}


def test_save_creates_parent_dirs_and_loads_snapshots(tmp_path: Path) -> None:
    """Store writes JSON and loads it back as snapshot models."""
    path = tmp_path / 'state' / 'port-counters.json'
    store = PortCounterBaselineStore(path)
    snapshots = {
        'switch1:1': PortCounterSnapshot(
            timestamp='2026-05-02T10:00:00',
            rx_errors=1,
            tx_errors=2,
            crc_errors=3,
            rx_dropped=4,
            tx_dropped=5,
        )
    }

    store.save(snapshots)

    assert path.exists()
    assert store.load() == snapshots


def test_diff_snapshots_clamps_counter_resets() -> None:
    """Negative deltas caused by reboot/reset are clamped to zero."""
    baseline = PortCounterSnapshot(rx_errors=10, tx_errors=2, crc_errors=3)
    current = PortCounterSnapshot(rx_errors=8, tx_errors=9, crc_errors=3)

    delta = diff_snapshots(baseline, current)

    assert delta.rx_errors == 0
    assert delta.tx_errors == 7
    assert delta.crc_errors == 0


def test_diff_since_last_uses_saved_keys(tmp_path: Path) -> None:
    """Deltas are computed for ports that exist in the previous baseline."""
    store = PortCounterBaselineStore(tmp_path / 'port-counters.json')
    store.save(
        {
            'switch1:1': PortCounterSnapshot(rx_errors=1, rx_dropped=10),
        }
    )

    current = {
        'switch1:1': PortCounterSnapshot(rx_errors=4, rx_dropped=15),
        'switch1:2': PortCounterSnapshot(rx_errors=100),
    }

    deltas = store.diff_since_last(current)

    assert list(deltas) == ['switch1:1']
    assert deltas['switch1:1'].rx_errors == 3
    assert deltas['switch1:1'].rx_dropped == 5


def test_snapshots_from_switches_use_device_port_keys() -> None:
    """Switch port snapshots are keyed as device_id:port_idx."""
    switch = SwitchSTPConfig(
        device_id='switch1',
        name='Switch',
        mac='00:00:00:00:00:01',
        port_states=[
            STPPortConfig(port_idx=1, rx_errors=7),
        ],
    )

    snapshots = snapshots_from_switches([switch])

    assert port_counter_key('switch1', 1) in snapshots
    assert snapshots['switch1:1'].rx_errors == 7
