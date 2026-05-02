"""STP preflight simulation for planned switch additions."""

from __future__ import annotations

from pydantic import BaseModel, Field
from unifi_mapper.core.models.stp import (
    STP_PRIORITY_ACCESS_BASE,
    STP_PRIORITY_CORE,
    STPTopology,
    SwitchSTPConfig,
)


class STPPreflightReport(BaseModel):
    """Report from simulated STP switch addition."""

    simulated_switches_added: int
    expected_root: str
    required_priorities: dict[str, int] = Field(default_factory=dict)
    before_diagram: str = ''
    after_diagram: str = ''
    checklist: list[str] = Field(default_factory=lambda: [])


def stp_preflight_simulate_add(
    topology: STPTopology,
    planned_models: dict[str, int],
    uplink_targets: list[str],
) -> STPPreflightReport:
    """Simulate adding switches and return root/priority expectations."""
    simulated = topology.model_copy(deep=True)
    added = 0
    for model, count in planned_models.items():
        for index in range(1, count + 1):
            added += 1
            simulated.switches.append(
                SwitchSTPConfig(
                    device_id=f'sim-{model}-{index}',
                    name=f'{model}-{index}',
                    mac=f'sim-{added}',
                    model=model,
                    current_priority=STP_PRIORITY_ACCESS_BASE,
                    hierarchy_tier=2,
                    root_eligible=False,
                    root_eligibility_reason='Simulated planned switch',
                )
            )
    root = _expected_root(simulated)
    required = {root.name: STP_PRIORITY_CORE} if root else {}
    for switch in simulated.switches:
        if switch.name != (root.name if root else ''):
            required.setdefault(switch.name, switch.current_priority)
    return STPPreflightReport(
        simulated_switches_added=added,
        expected_root=root.name if root else '',
        required_priorities=required,
        before_diagram=_simple_mermaid(topology),
        after_diagram=_simple_mermaid(simulated),
        checklist=[
            'Preset planned switches to non-default access/distribution priorities before install.',
            'Confirm uplinks target: ' + ', '.join(uplink_targets),
            'Verify required trunk VLANs and LAG design before cabling.',
        ],
    )


def _expected_root(topology: STPTopology) -> SwitchSTPConfig | None:
    candidates = [
        switch
        for switch in topology.switches
        if switch.connected_to_gateway and switch.root_eligible
    ]
    if not candidates:
        candidates = [switch for switch in topology.switches if switch.connected_to_gateway]
    if not candidates:
        return None
    return sorted(candidates, key=lambda switch: (switch.root_preference, switch.name))[0]


def _simple_mermaid(topology: STPTopology) -> str:
    lines = ['```mermaid', 'graph TB']
    for switch in topology.switches:
        node_id = switch.device_id.replace('-', '_')
        lines.append(f'    {node_id}["{switch.name}<br/>{switch.current_priority}"]')
    lines.append('```')
    return '\n'.join(lines)
