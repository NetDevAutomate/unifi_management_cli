"""Tests for STP guard and TCN audits."""

from __future__ import annotations

from unifi_mapper.analysis.stp_guard import audit_stp_guard_recommendations
from unifi_mapper.core.models.stp import STPPortConfig, STPTopology, SwitchSTPConfig


def test_root_guard_recommended_on_core_downlink() -> None:
    """Core/downlink infrastructure ports should receive Root Guard recommendations."""
    topology = STPTopology(
        switches=[
            SwitchSTPConfig(
                device_id='core',
                name='Core',
                mac='aa',
                current_priority=4096,
                hierarchy_tier=0,
                port_states=[STPPortConfig(port_idx=1, connected_device_id='access')],
            ),
            SwitchSTPConfig(
                device_id='access',
                name='Access',
                mac='bb',
                current_priority=32768,
                hierarchy_tier=2,
            ),
        ]
    )

    report = audit_stp_guard_recommendations(topology)

    assert report.findings_count == 1
    assert report.findings[0].category == 'Root Guard'
    assert report.findings[0].severity == 'INFO'


def test_root_guard_warning_when_downstream_priority_can_hijack_root() -> None:
    """Downstream equal/lower priorities are more urgent Root Guard findings."""
    topology = STPTopology(
        switches=[
            SwitchSTPConfig(
                device_id='dist',
                name='Distribution',
                mac='aa',
                current_priority=8192,
                hierarchy_tier=1,
                port_states=[STPPortConfig(port_idx=4, connected_device_id='access')],
            ),
            SwitchSTPConfig(
                device_id='access',
                name='Access',
                mac='bb',
                current_priority=4096,
                hierarchy_tier=2,
            ),
        ]
    )

    report = audit_stp_guard_recommendations(topology)

    assert report.findings[0].severity == 'WARNING'


def test_tcn_monitor_flags_high_topology_change_count() -> None:
    """High STP topology-change counts should be visible in guard audit."""
    topology = STPTopology(
        switches=[
            SwitchSTPConfig(
                device_id='a',
                name='Switch A',
                mac='aa',
                hierarchy_tier=0,
                port_states=[STPPortConfig(port_idx=2, connected_device_id='b', stp_tc_count=12)],
            ),
            SwitchSTPConfig(device_id='b', name='Switch B', mac='bb', hierarchy_tier=1),
        ]
    )

    report = audit_stp_guard_recommendations(topology, tcn_threshold=10)

    assert any(finding.category == 'Topology Change' for finding in report.findings)
