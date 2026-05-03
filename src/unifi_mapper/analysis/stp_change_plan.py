"""STP change plan and rollback bundle helpers."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from unifi_mapper.core.models.stp import STP_PRIORITY_CORE, STPChange


class STPChangePlan(BaseModel):
    """A reversible STP priority change plan."""

    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    expected_root_device_id: str = ''
    changes: list[STPChange] = Field(default_factory=lambda: [])
    rollback: list[STPChange] = Field(default_factory=lambda: [])
    apply_order: list[str] = Field(default_factory=list)
    preflight_checks: list[str] = Field(default_factory=list)
    postflight_checks: list[str] = Field(default_factory=list)


def create_stp_change_plan(changes: list[STPChange]) -> STPChangePlan:
    """Create a convergence-aware STP plan with rollback changes."""
    ordered = sorted(changes, key=_apply_sort_key)
    rollback = [
        STPChange(
            device_id=change.device_id,
            device_name=change.device_name,
            current_priority=change.new_priority,
            new_priority=change.current_priority,
            hierarchy_tier=change.hierarchy_tier,
            reason=f'Rollback {change.device_name} to priority {change.current_priority}',
        )
        for change in reversed(ordered)
    ]
    expected_root = next(
        (change.device_id for change in ordered if change.new_priority == STP_PRIORITY_CORE),
        '',
    )
    return STPChangePlan(
        expected_root_device_id=expected_root,
        changes=ordered,
        rollback=rollback,
        apply_order=[change.device_id for change in ordered],
        preflight_checks=[
            'Confirm controller reachable and all target switches online.',
            'Confirm expected root is gateway-connected before applying.',
            'Run stp validate-10g and save output before changes.',
        ],
        postflight_checks=[
            'Re-run stp analyze and confirm expected root bridge.',
            'Check blocked ports and path costs after convergence.',
            'Re-run stp validate-10g after the maintenance window.',
        ],
    )


def _apply_sort_key(change: STPChange) -> tuple[int, int, str]:
    if change.new_priority == STP_PRIORITY_CORE:
        phase = 0
    elif change.new_priority > change.current_priority:
        phase = 1
    elif change.hierarchy_tier == 1:
        phase = 2
    else:
        phase = 3
    return (phase, change.new_priority, change.device_name)
