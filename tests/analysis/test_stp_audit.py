"""The one-shot STP priority audit (``analysis/stp_audit.py``) and its CLI command.

Rebuilt from the prototype (a local archive, not in the repo) and adapted: documentation values
only, the gateway reported under ``skipped``, remediation as CLI commands, and the fleet never
scoped before tiering. The end-to-end cases run the real discovery and priority calculation
through the read-only guard over ``tests/fake_controller.py``, so they also assert that only
GETs left the host.
"""

import inspect
import json
import pytest
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.analysis.stp_audit import (
    REMEDIATION_COMMANDS,
    SCOPE_NOTE,
    SKIPPED_REASON,
    audit_stp_priorities,
    build_stp_audit,
    scope_stp_audit,
)
from unifi_mapper.core.models.capability import SwitchCapabilityClass
from unifi_mapper.core.models.stp import STPChange, STPTopology, SwitchSTPConfig
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


runner = CliRunner()

GATEWAY_ID = '0000000000000000000000f1'
GATEWAY_MAC = '02:00:00:00:00:f1'


def _device(
    i: int, name: str, model: str, priority: int, links: dict[int, str], kind: str = 'usw'
) -> dict[str, Any]:
    """A controller device record whose LLDP table links each port to a neighbour's MAC."""
    return {
        '_id': f'{i:024x}',
        'mac': f'02:00:00:00:00:{i:02x}',
        'name': name,
        'model': model,
        'type': kind,
        'stp_priority': str(priority),
        'port_table': [{'port_idx': port, 'name': f'Port {port}'} for port in sorted(links)],
        'lldp_table': [
            {'local_port_idx': port, 'chassis_id': mac, 'port_id': 'Port 1'}
            for port, mac in sorted(links.items())
        ],
    }


def _mac(i: int) -> str:
    return f'02:00:00:00:00:{i:02x}'


def _fleet() -> list[dict[str, Any]]:
    """Two gateway-connected cores (A preferred, B), distribution D behind A, access C behind D."""
    gateway = _device(0xF1, 'Gateway', 'UDMPRO', 32768, {}, kind='udm')
    gateway['_id'] = GATEWAY_ID
    return [
        gateway,
        _device(0xA1, 'Switch A', 'USW-Flex-XG', 4096, {1: GATEWAY_MAC, 2: _mac(0xD1)}),
        _device(0xB1, 'Switch B', 'USW-Flex-XG', 32768, {1: GATEWAY_MAC}),
        _device(0xD1, 'Switch D', 'USW-Pro-24', 32768, {1: _mac(0xA1), 2: _mac(0xC1)}),
        _device(0xC1, 'Switch C', 'USW-Flex-Mini', 32768, {1: _mac(0xD1)}),
    ]


def _controller(devices: list[dict[str, Any]] | None = None) -> FakeController:
    return FakeController({f'{API}/stat/device': legacy(_fleet() if devices is None else devices)})


async def _audit(controller: FakeController, device: str | None = None) -> dict[str, Any]:
    async with serving(controller):
        return await audit_stp_priorities(device)


def _rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row['name']: row for row in report['switches']}


# --- the fleet is never scoped before tiering ---------------------------------------------


async def test_the_fleet_audit_tiers_every_switch_and_skips_the_gateway() -> None:
    controller = _controller()
    report = await _audit(controller)
    rows = _rows(report)
    assert set(rows) == {'Switch A', 'Switch B', 'Switch C', 'Switch D'}
    assert (rows['Switch A']['tier'], rows['Switch A']['optimal_priority']) == (0, 4096)
    assert (rows['Switch B']['tier'], rows['Switch B']['optimal_priority']) == (0, 8192)
    assert (rows['Switch D']['tier'], rows['Switch D']['optimal_priority']) == (1, 12288)
    assert (rows['Switch C']['tier'], rows['Switch C']['optimal_priority']) == (2, 16384)
    assert rows['Switch A']['is_root'] and rows['Switch A']['delta'] == 0
    assert rows['Switch B']['delta'] == 8192 - 32768
    assert report['current_root'] == 'Switch A' and report['current_root_priority'] == 4096
    assert [s['name'] for s in report['skipped']] == ['Gateway']
    assert {c['device_name'] for c in report['remediation']['changes']} == {
        'Switch B',
        'Switch C',
        'Switch D',
    }
    assert report['compliant'] is False and report['root_tie_break_warning'] is None
    assert controller.methods == {'GET'}
    assert [path for _, path in controller.reads] == [f'{API}/stat/device']


@pytest.mark.parametrize(
    ('device', 'tier', 'priority'),
    [('Switch B', 0, 8192), ('Switch D', 1, 12288), ('Switch A', 0, 4096)],
)
async def test_a_scoped_row_equals_the_switch_s_fleet_row(
    device: str, tier: int, priority: int
) -> None:
    fleet = _rows(await _audit(_controller()))
    scoped = await _audit(_controller(), device)
    assert scoped['switches'] == [fleet[device]]
    # The prototype scoped the discovery: B became the only core (4096), D kept tier 2 (16384).
    assert (scoped['switches'][0]['tier'], scoped['switches'][0]['optimal_priority']) == (
        tier,
        priority,
    )
    assert scoped['current_root'] == 'Switch A'
    assert [s['name'] for s in scoped['skipped']] == ['Gateway']
    assert {c['device_name'] for c in scoped['remediation']['changes']} <= {device}
    assert scoped['notes'] == [SCOPE_NOTE]


async def test_a_name_an_upper_case_dashed_mac_and_an_id_give_the_same_row() -> None:
    by_name = await _audit(_controller(), 'switch d')
    by_mac = await _audit(_controller(), _mac(0xD1).upper().replace(':', '-'))
    by_id = await _audit(_controller(), f'{0xD1:024x}')
    assert by_name['switches'] == by_mac['switches'] == by_id['switches']
    assert [r['scope']['matched_by'] for r in (by_name, by_mac, by_id)] == ['name', 'mac', 'id']
    assert {r['scope']['device_id'] for r in (by_name, by_mac, by_id)} == {f'{0xD1:024x}'}


async def test_the_gateway_resolves_to_its_skipped_entry() -> None:
    report = await _audit(_controller(), 'Gateway')
    assert report['switches'] == [] and report['remediation']['changes'] == []
    assert [s['device_id'] for s in report['skipped']] == [GATEWAY_ID]
    assert report['scope']['device_id'] == GATEWAY_ID
    assert report['compliant'] is True  # nothing of its own to change
    assert report['summary'] == f'Skipped Gateway: {SKIPPED_REASON}.'


async def test_a_scoped_verdict_describes_the_switch_and_keeps_the_fleet_s() -> None:
    fleet = await _audit(_controller())
    in_line = await _audit(_controller(), 'Switch A')  # compliant, in a fleet that drifts
    assert fleet['compliant'] is False and 'fleet_compliant' not in fleet
    assert in_line['compliant'] is True
    assert in_line['summary'] == 'STP priorities are compliant across 1 switch(es).'
    assert (in_line['fleet_compliant'], in_line['fleet_summary']) == (
        fleet['compliant'],
        fleet['summary'],
    )
    drifting = await _audit(_controller(), 'Switch B')
    assert drifting['compliant'] is False
    assert drifting['summary'] == '1 of 1 switch(es) differ from the recommended priority.'


async def test_an_unknown_name_lists_every_switch_as_a_candidate() -> None:
    with pytest.raises(ToolError) as caught:
        await _audit(_controller(), 'No such switch')
    assert caught.value.error_code == ErrorCodes.DEVICE_NOT_FOUND
    for name in ('Switch A', 'Switch B', 'Switch C', 'Switch D'):
        assert name in caught.value.message
    assert caught.value.related_tools == ['discover_stp_topology']


async def test_an_ambiguous_name_lists_only_the_matches() -> None:
    devices = _fleet()
    devices[4]['name'] = 'Switch D'  # C now shares D's name
    with pytest.raises(ToolError) as caught:
        await _audit(_controller(devices), 'Switch D')
    assert caught.value.error_code == ErrorCodes.DEVICE_NOT_FOUND
    assert 'more than one switch by name' in caught.value.message
    assert _mac(0xC1) in caught.value.message and _mac(0xD1) in caught.value.message
    assert 'Switch A' not in caught.value.message


# --- the pure cores -----------------------------------------------------------------------


def _switch(
    device_id: str,
    name: str,
    *,
    mac: str = '02:00:00:00:00:01',
    capability: SwitchCapabilityClass = SwitchCapabilityClass.ACCESS,
    tier: int = 2,
    current: int = 32768,
    optimal: int | None = None,
) -> SwitchSTPConfig:
    return SwitchSTPConfig(
        device_id=device_id,
        name=name,
        mac=mac,
        model='USW-Flex-Mini',
        capability=capability,
        hierarchy_tier=tier,
        current_priority=current,
        optimal_priority=current if optimal is None else optimal,
    )


def _change(switch: SwitchSTPConfig) -> STPChange:
    assert switch.optimal_priority is not None
    return STPChange(
        device_id=switch.device_id,
        device_name=switch.name,
        current_priority=switch.current_priority,
        new_priority=switch.optimal_priority,
        hierarchy_tier=switch.hierarchy_tier,
        reason='test change',
    )


def test_a_switch_with_no_mac_never_matches_a_name_query() -> None:
    nameless = _switch('a1', 'Switch E', mac='')
    named = _switch('a2', 'Switch F', mac='02:00:00:00:00:02')
    topology = STPTopology(switches=[nameless, named])
    report = scope_stp_audit(build_stp_audit(topology, []), topology, 'Switch F')
    assert [row['device_id'] for row in report['switches']] == ['a2']
    assert report['scope']['matched_by'] == 'name'


@pytest.mark.parametrize(
    ('capability', 'gateway_id'),
    [(SwitchCapabilityClass.GATEWAY, None), (SwitchCapabilityClass.UNKNOWN, 'gw')],
)
def test_either_gateway_test_alone_moves_it_to_skipped(
    capability: SwitchCapabilityClass, gateway_id: str | None
) -> None:
    gateway = _switch('gw', 'Gateway', capability=capability, current=8192, optimal=12288)
    access = _switch('a1', 'Switch A', current=16384)
    topology = STPTopology(gateway_id=gateway_id, switches=[gateway, access])
    report = build_stp_audit(topology, [_change(gateway)])
    assert [row['name'] for row in report['switches']] == ['Switch A']
    assert [row['name'] for row in report['skipped']] == ['Gateway']
    assert 'STP disabled' in report['skipped'][0]['reason']
    assert report['remediation']['changes'] == []  # a gateway change never surfaces
    assert 'Skipped Gateway' in report['summary']


def test_a_tie_among_access_switches_at_the_lowest_priority_warns() -> None:
    switches = [_switch(f'a{i}', f'Switch {i}', optimal=16384) for i in range(3)]
    report = build_stp_audit(STPTopology(switches=switches), [_change(s) for s in switches])
    warning = report['root_tie_break_warning']
    assert warning is not None and '16384' in warning
    assert all(f'Switch {i}' in warning for i in range(3))
    assert report['summary'].startswith('3 of 3 switch(es) differ')


def test_a_core_switch_tied_with_an_access_switch_warns_naming_the_access_switch() -> None:
    """Issue 076 item 5: the warning was skipped when any tied switch was core-class, so a
    core switch and an access switch tied at the lowest priority left the root to MAC order
    unwarned."""
    core = _switch('c1', 'Switch A', capability=SwitchCapabilityClass.AGGREGATION, current=4096)
    access = _switch('a1', 'Switch B', current=4096)
    report = build_stp_audit(STPTopology(switches=[core, access]), [])
    warning = report['root_tie_break_warning']
    assert warning is not None and '4096' in warning
    assert 'Switch A' in warning and 'Switch B' in warning
    assert 'Switch B is not an aggregation- or core-distribution-class switch' in warning
    assert 'decided by MAC address' in warning


def test_a_tie_among_core_class_switches_only_does_not_warn() -> None:
    cores = [
        _switch('c1', 'Switch A', capability=SwitchCapabilityClass.AGGREGATION, current=4096),
        _switch(
            'c2', 'Switch B', capability=SwitchCapabilityClass.CORE_DISTRIBUTION, current=4096
        ),
    ]
    report = build_stp_audit(STPTopology(switches=cores), [])
    assert report['root_tie_break_warning'] is None


def test_a_compliant_fleet_proposes_nothing_but_still_names_the_commands() -> None:
    core = _switch('c1', 'Switch A', capability=SwitchCapabilityClass.AGGREGATION, current=4096)
    access = _switch('a1', 'Switch B', current=16384)
    report = build_stp_audit(STPTopology(switches=[core, access]), [])
    assert report['compliant'] is True
    assert report['summary'] == 'STP priorities are compliant across 2 switch(es).'
    assert report['remediation']['changes'] == []
    assert report['remediation']['commands'] == list(REMEDIATION_COMMANDS)
    assert '--no-dry-run' in report['remediation']['note']


def test_an_empty_topology_is_compliant() -> None:
    report = build_stp_audit(STPTopology(switches=[]), [])
    assert report['switches'] == [] and report['skipped'] == []
    assert report['compliant'] is True and report['root_tie_break_warning'] is None
    assert report['summary']


def test_the_remediation_names_cli_commands_never_an_mcp_write() -> None:
    assert REMEDIATION_COMMANDS == (
        'unifi-mapper stp optimize --plan PLAN.json',
        'unifi-mapper stp apply --plan PLAN.json',
    )
    switch = _switch('a1', 'Switch A', optimal=16384)
    change = build_stp_audit(STPTopology(switches=[switch]), [_change(switch)])['remediation']
    assert set(change) == {'commands', 'changes', 'note'}
    assert set(change['changes'][0]) == set(STPChange.model_fields)


def test_the_handler_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(audit_stp_priorities)


# --- the CLI command ----------------------------------------------------------------------


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> FakeController:
    fake = _controller()
    route_cli(monkeypatch, fake)
    return fake


def test_the_command_prints_a_table_with_the_skipped_gateway(controller: FakeController) -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities'])
    assert result.exit_code == 0, result.output
    flat = ' '.join(result.stdout.split())
    assert 'Current root: Switch A (priority 4096)' in flat
    assert 'Skipped Gateway' in flat and 'stp optimize --plan PLAN.json' in flat
    assert controller.methods == {'GET'}


def test_the_command_prints_the_scoped_row_as_json(controller: FakeController) -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities', '--device', 'Switch D', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [(r['name'], r['tier'], r['optimal_priority']) for r in data['switches']] == [
        ('Switch D', 1, 12288)
    ]
    assert data['notes'] == [SCOPE_NOTE]


def test_a_scoped_table_prints_the_switch_s_verdict_then_the_fleet_s(
    controller: FakeController,
) -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities', '--device', 'Switch A'])
    assert result.exit_code == 0, result.output
    flat = ' '.join(result.stdout.split())
    assert 'STP priorities are compliant across 1 switch(es).' in flat
    assert 'Fleet: 3 of 4 switch(es) differ from the recommended priority.' in flat


def test_an_unknown_device_is_one_error_line_on_stderr(controller: FakeController) -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities', '--device', 'Nope', '--json'])
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'No switch matched' in result.stderr


@pytest.mark.parametrize('device', ['', 'x' * 129], ids=['empty', 'too long'])
def test_a_device_the_mcp_tool_would_refuse_is_a_usage_error(
    controller: FakeController, device: str
) -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities', '--device', device])
    assert result.exit_code == 2, result.output
    assert controller.calls == []  # refused before connecting


def test_the_command_has_help_that_says_read_only() -> None:
    result = runner.invoke(app, ['stp', 'audit-priorities', '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert 'Read-only' in flat and 'name, MAC or ID' in flat
