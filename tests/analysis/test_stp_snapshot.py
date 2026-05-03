"""Tests for STP snapshot diffing."""

from __future__ import annotations

from unifi_mapper.analysis.stp_snapshot import diff_stp_snapshots, snapshot_stp_topology
from unifi_mapper.core.models.stp import STPPortConfig, STPTopology, SwitchSTPConfig


def test_snapshot_diff_reports_root_priority_and_port_changes() -> None:
    """Snapshot diff should capture root, priority, and port state changes."""
    before = snapshot_stp_topology(
        STPTopology(
            root_bridge_id='a',
            root_bridge_name='Switch A',
            switches=[
                SwitchSTPConfig(
                    device_id='a',
                    name='Switch A',
                    mac='aa',
                    current_priority=4096,
                    port_states=[STPPortConfig(port_idx=1, link_speed_mbps=1000, path_cost=20000)],
                )
            ],
        )
    )
    after = snapshot_stp_topology(
        STPTopology(
            root_bridge_id='b',
            root_bridge_name='Switch B',
            switches=[
                SwitchSTPConfig(
                    device_id='a',
                    name='Switch A',
                    mac='aa',
                    current_priority=8192,
                    port_states=[STPPortConfig(port_idx=1, link_speed_mbps=10000, path_cost=2000)],
                )
            ],
        )
    )

    diff = diff_stp_snapshots(before, after)

    assert any(change.change_type == 'root_bridge_changed' for change in diff.changes)
    assert any(change.change_type == 'priority_changed' for change in diff.changes)
    assert any(change.change_type == 'link_speed_changed' for change in diff.changes)
    assert any(change.change_type == 'path_cost_changed' for change in diff.changes)
