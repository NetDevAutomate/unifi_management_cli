"""One-shot STP priority audit: what each switch's bridge priority is, and what it should be.

A read-only composite over :mod:`unifi_mapper.analysis.stp_optimizer`: it runs
``discover_stp_topology`` and ``calculate_optimal_priorities`` for the whole fleet and turns
the result into one verdict, so no priority logic is duplicated here. The gateway is listed
under ``skipped`` (its bridge runs with STP disabled, so its priority is not managed), never
among the switches or the remediation.

Scoping to one device never scopes the discovery: hierarchy tiers and the root come from the
whole fleet, so a scoped row always equals that switch's row in the fleet-wide report
(``scope_stp_audit``). Rebuilt from the July work (a local archive, not in the repo), where the
device was forwarded into the discovery and tiers were computed on a one-switch fleet.

Remediation is advice only: the change plan is written and applied with the CLI (``stp
optimize --plan`` then ``stp apply --plan``, which previews unless ``--no-dry-run``).
"""

from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.analysis.stp_optimizer import (
    calculate_optimal_priorities,
    discover_stp_topology,
    is_gateway_switch,
)
from unifi_mapper.core.models.capability import SwitchCapabilityClass
from unifi_mapper.core.models.stp import STPChange, STPTopology, SwitchSTPConfig
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostic_reads import normalise_mac


_TIER_LABELS = ('Core', 'Distribution', 'Access')
SKIPPED_REASON = 'gateway: its bridge runs with STP disabled, so its priority is not managed here'
REMEDIATION_COMMANDS = (
    'unifi-mapper stp optimize --plan PLAN.json',
    'unifi-mapper stp apply --plan PLAN.json',
)
REMEDIATION_NOTE = (
    'stp optimize --plan writes a reversible plan for every switch; stp apply previews it '
    'unless --no-dry-run is given.'
)
SCOPE_NOTE = (
    'priorities are computed for the whole fleet; `stp optimize --plan` plans every switch'
)


def _tier_label(tier: int) -> str:
    return _TIER_LABELS[tier] if 0 <= tier < len(_TIER_LABELS) else f'Access (Tier {tier})'


def _switch_row(switch: SwitchSTPConfig) -> dict[str, Any]:
    optimal = switch.optimal_priority
    if optimal is None:
        optimal = switch.current_priority
    return {
        'device_id': switch.device_id,
        'name': switch.name,
        'mac': switch.mac,
        'model': switch.model,
        'tier': switch.hierarchy_tier,
        'tier_label': _tier_label(switch.hierarchy_tier),
        'current_priority': switch.current_priority,
        'optimal_priority': optimal,
        'delta': optimal - switch.current_priority,
        'is_root': switch.is_root_bridge,
        'root_eligible': switch.root_eligible,
        'capability': switch.capability.value,
    }


def _skipped_row(switch: SwitchSTPConfig) -> dict[str, Any]:
    return {
        'device_id': switch.device_id,
        'name': switch.name,
        'mac': switch.mac,
        'model': switch.model,
        'reason': SKIPPED_REASON,
    }


def _tie_warning(rows: list[dict[str, Any]]) -> str | None:
    """Warn when two or more switches share the lowest optimal priority and none is core-class.

    A tie at the lowest priority means the root election is decided by MAC address rather
    than by design, unless one of the tied switches is aggregation- or core-distribution-class
    hardware, which is meant to hold it.
    """
    if not rows:
        return None
    lowest = min(row['optimal_priority'] for row in rows)
    tied = [row for row in rows if row['optimal_priority'] == lowest]
    if len(tied) < 2:
        return None
    core_classes = {
        SwitchCapabilityClass.AGGREGATION.value,
        SwitchCapabilityClass.CORE_DISTRIBUTION.value,
    }
    if any(row['capability'] in core_classes for row in tied):
        return None
    names = ', '.join(row['name'] for row in tied)
    return (
        f'{len(tied)} switches tie at the lowest optimal priority ({lowest}): {names}. None is '
        'an aggregation- or core-distribution-class switch, so the root election among them '
        'is decided by MAC address. Stagger their priorities or confirm the intended root.'
    )


def _skipped_lines(skipped: list[dict[str, Any]]) -> list[str]:
    return [f'Skipped {row["name"]}: {row["reason"]}.' for row in skipped]


def _summary(rows: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> str:
    drift = sum(1 for row in rows if row['delta'] != 0)
    lines = (
        [f'STP priorities are compliant across {len(rows)} switch(es).']
        if drift == 0
        else [f'{drift} of {len(rows)} switch(es) differ from the recommended priority.']
    )
    return ' '.join(lines + _skipped_lines(skipped))


def build_stp_audit(topology: STPTopology, changes: list[STPChange]) -> dict[str, Any]:
    """Combine a discovered topology and its calculated changes into one audit verdict.

    Pure. ``changes`` must come from ``calculate_optimal_priorities(topology)``, which sets
    each switch's ``optimal_priority``.

    Args:
        topology: The fleet's topology from ``discover_stp_topology()``.
        changes: Its changes from ``calculate_optimal_priorities``.

    Returns:
        ``switches`` (per switch current, optimal, delta and tier), ``skipped`` (the
        gateway), ``current_root``, ``current_root_priority``, ``compliant``,
        ``root_tie_break_warning``, ``summary`` and ``remediation`` (``commands``,
        ``changes`` and ``note``), with no gateway in ``switches`` or ``remediation``.
    """
    gateways = [s for s in topology.switches if is_gateway_switch(s, topology)]
    gateway_ids = {s.device_id for s in gateways}
    rows = [_switch_row(s) for s in topology.switches if s.device_id not in gateway_ids]
    skipped = [_skipped_row(s) for s in gateways]
    plan = [c.model_dump(mode='json') for c in changes if c.device_id not in gateway_ids]
    return {
        'switches': rows,
        'skipped': skipped,
        'current_root': topology.root_bridge_name,
        'current_root_priority': topology.root_bridge_priority,
        'compliant': all(row['delta'] == 0 for row in rows),
        'root_tie_break_warning': _tie_warning(rows),
        'summary': _summary(rows, skipped),
        'remediation': {
            'commands': list(REMEDIATION_COMMANDS),
            'changes': plan,
            'note': REMEDIATION_NOTE,
        },
    }


def _describe(switches: list[SwitchSTPConfig]) -> str:
    return '; '.join(
        f'{s.name} ({s.mac or "no MAC"}, {s.model or "unknown model"})' for s in switches
    )


def _resolve(topology: STPTopology, device: str) -> tuple[SwitchSTPConfig, str]:
    """Find one switch by ID, then MAC (any notation), then exact name; first tier wins."""
    query = device.strip()
    query_mac = normalise_mac(query)
    tiers: list[tuple[str, list[SwitchSTPConfig]]] = [
        ('id', [s for s in topology.switches if s.device_id == query]),
        (
            'mac',
            [
                s
                for s in topology.switches
                if query_mac is not None and normalise_mac(s.mac) == query_mac
            ],
        ),
        ('name', [s for s in topology.switches if s.name.strip().casefold() == query.casefold()]),
    ]
    for matched_by, matches in tiers:
        if len(matches) == 1:
            return matches[0], matched_by
        if matches:
            raise ToolError(
                message=f'{device!r} matches more than one switch by {matched_by}: '
                f'{_describe(matches)}',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion='Give the switch ID or MAC address.',
                related_tools=['discover_stp_topology'],
            )
    raise ToolError(
        message=f'No switch matched {device!r}. Known switches: {_describe(topology.switches)}',
        error_code=ErrorCodes.DEVICE_NOT_FOUND,
        suggestion='Give a switch name, MAC address or ID from the list.',
        related_tools=['discover_stp_topology'],
    )


def scope_stp_audit(report: dict[str, Any], topology: STPTopology, device: str) -> dict[str, Any]:
    """Narrow a fleet-wide audit to one switch, keeping the fleet's root, warning and verdict.

    Pure. ``device`` is resolved against ``topology.switches`` by exact ``device_id``, then
    by MAC in any notation (only when both the query and the switch's MAC normalise, so a
    name never matches a switch with no MAC), then by exact name, case-insensitive; the first
    tier with a match wins. A gateway resolves to its ``skipped`` entry.

    ``compliant`` and ``summary`` describe the scoped switch (a gateway has nothing of its own
    to change, so it is compliant and its summary names the skip); the fleet's verdict is
    kept as ``fleet_compliant`` and ``fleet_summary``.

    Args:
        report: The fleet-wide result of :func:`build_stp_audit`.
        topology: The topology the report was built from.
        device: A switch name, MAC address or ID.

    Returns:
        The report with ``switches`` and ``remediation.changes`` filtered to that switch,
        ``compliant`` and ``summary`` for it, ``fleet_compliant`` and ``fleet_summary``,
        ``scope`` (``device``, ``device_id``, ``matched_by``) and a note that priorities are
        computed for the whole fleet.

    Raises:
        ToolError: ``DEVICE_NOT_FOUND`` naming the candidates (name, MAC, model) when nothing
            or more than one switch matches.
    """
    switch, matched_by = _resolve(topology, device)
    remediation = dict(report['remediation'])
    remediation['changes'] = [
        c for c in remediation['changes'] if c['device_id'] == switch.device_id
    ]
    rows = [row for row in report['switches'] if row['device_id'] == switch.device_id]
    skipped = [row for row in report['skipped'] if row['device_id'] == switch.device_id]
    return {
        **report,
        'switches': rows,
        'compliant': all(row['delta'] == 0 for row in rows),
        'summary': _summary(rows, skipped) if rows else ' '.join(_skipped_lines(skipped)),
        'fleet_compliant': report['compliant'],
        'fleet_summary': report['summary'],
        'remediation': remediation,
        'scope': {'device': device, 'device_id': switch.device_id, 'matched_by': matched_by},
        'notes': [SCOPE_NOTE],
    }


async def audit_stp_priorities(
    device: Annotated[
        str | None,
        Field(
            description='Only this switch: its name, MAC or ID (default the whole fleet)',
            min_length=1,
            max_length=128,
        ),
    ] = None,
) -> dict[str, Any]:
    """One-shot STP priority audit: current vs recommended, for the fleet or one switch.

    Read-only.

    When to use this tool:
    - "Are our switch STP priorities sane?" in one call, instead of chaining
      discover_stp_topology and calculate_optimal_priorities
    - Before an STP-affecting change, to see the current root and which switches drifted

    Runs the discovery and the priority calculation for the whole fleet (tiers need every
    switch), then reports each switch's current, recommended and delta priority, a warning
    when two non-core switches tie at the lowest priority (the root would be decided by MAC
    address), and the gateway under skipped (its bridge runs with STP disabled). With device,
    the same rows are narrowed to that switch: compliant and summary then describe it, and
    fleet_compliant and fleet_summary the fleet.

    Remediation is advice: write and apply the plan with the CLI (``unifi-mapper stp optimize
    --plan PLAN.json``, then ``unifi-mapper stp apply --plan PLAN.json``, which previews unless
    ``--no-dry-run``); STP writes never run over MCP.

    Args:
        device: Optional switch name, MAC address or ID to narrow the report to.

    Returns:
        switches, skipped, current_root, current_root_priority, compliant,
        root_tie_break_warning, summary, remediation and, when scoped, fleet_compliant,
        fleet_summary, scope and notes.

    Raises:
        ToolError: DEVICE_NOT_FOUND when device matches nothing or more than one switch;
            CONTROLLER_UNREACHABLE or API_ERROR from the discovery.
    """
    topology = await discover_stp_topology()  # never scoped: tiers need the whole fleet
    report = build_stp_audit(topology, await calculate_optimal_priorities(topology))
    return report if device is None else scope_stp_audit(report, topology, device)
