"""Tests for STP change plan creation."""

from __future__ import annotations

from unifi_mapper.analysis.stp_change_plan import create_stp_change_plan
from unifi_mapper.core.models.stp import STPChange


def test_change_plan_orders_new_root_first_and_rolls_back_old_values() -> None:
    """STP plan should apply preferred root first and provide reverse changes."""
    changes = [
        STPChange(
            device_id='old-root',
            device_name='Old Root',
            current_priority=4096,
            new_priority=8192,
            hierarchy_tier=1,
            reason='Demote old root',
        ),
        STPChange(
            device_id='new-root',
            device_name='New Root',
            current_priority=8192,
            new_priority=4096,
            hierarchy_tier=0,
            reason='Preferred root',
        ),
    ]

    plan = create_stp_change_plan(changes)

    assert plan.expected_root_device_id == 'new-root'
    assert plan.apply_order == ['new-root', 'old-root']
    assert plan.changes[0].device_id == 'new-root'
    assert plan.rollback[0].device_id == 'old-root'
    assert plan.rollback[0].new_priority == 4096
