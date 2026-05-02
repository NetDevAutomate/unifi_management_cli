"""Tests for STP preflight simulation."""

from __future__ import annotations

from unifi_mapper.analysis.stp_preflight import stp_preflight_simulate_add
from unifi_mapper.core.models.stp import STP_PRIORITY_CORE, STPTopology, SwitchSTPConfig


def test_preflight_simulates_added_flex_xg_switches() -> None:
    """Preflight should add planned switches and preserve preferred root."""
    topology = STPTopology(
        switches=[
            SwitchSTPConfig(
                device_id='root',
                name='Xray3 USW Flex XG 10G',
                mac='aa',
                model='USW-Flex-XG',
                current_priority=STP_PRIORITY_CORE,
                hierarchy_tier=0,
                connected_to_gateway=True,
            )
        ]
    )

    report = stp_preflight_simulate_add(
        topology,
        planned_models={'USW-Flex-XG': 2},
        uplink_targets=['Xray3 USW Flex XG 10G'],
    )

    assert report.simulated_switches_added == 2
    assert report.expected_root == 'Xray3 USW Flex XG 10G'
    assert 'USW-Flex-XG-1' in report.after_diagram
    assert report.required_priorities['Xray3 USW Flex XG 10G'] == STP_PRIORITY_CORE
