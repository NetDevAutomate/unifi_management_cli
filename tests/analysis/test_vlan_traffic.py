"""Per-VLAN traffic sampling (``analysis/vlan_traffic.py``) and the ``vlan-traffic`` CLI group.

Ported from the July work (a local archive, not in the repo) and adapted: documentation values
and generic names; the sample is one fixed ``sh -c`` script through
``analysis/gateway_ssh.py`` with a 30 s bound; the network list comes through the read-only
guard; the store is under the XDG state directory unless ``--db`` names one, never in the
working directory. SSH is the shared fake over the root ban; the controller is the fake behind
the real read-only guard.
"""

import asyncssh
import json
import pytest
import shlex
import sqlite3
from pathlib import Path
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from tests.fake_ssh import FakeSSH
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.analysis import vlan_traffic
from unifi_mapper.analysis.vlan_traffic import (
    SAMPLE_SCRIPT,
    SAMPLE_TIMEOUT,
    parse_bridge_counters,
    sample_vlan_traffic,
    split_sample_output,
)
from unifi_mapper.analysis.vlan_traffic_store import default_db_path, open_store
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


runner = CliRunner()
FAKE_SSH_PW = 'FAKE-VLAN-SAMPLE-SSH-PASSWORD'  # pragma: allowlist secret

ADDRESSES = [
    {'ifname': 'br0', 'addr_info': [{'local': '192.0.2.1'}]},
    {'ifname': 'br7', 'addr_info': [{'local': '198.51.100.1'}]},
    {'ifname': 'br9', 'addr_info': [{'local': '203.0.113.1'}]},
]
NETWORKS = [
    {'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
    {'name': 'IoT', 'purpose': 'corporate', 'vlan': 30, 'ip_subnet': '198.51.100.1/24'},
    {'name': 'Lab', 'purpose': 'guest', 'vlan': 40, 'ip_subnet': '203.0.113.1/24'},
    {'name': 'Spare', 'purpose': 'corporate', 'vlan': 199, 'ip_subnet': '192.0.2.129/25'},
]
STDOUT = 'br0 1000 2000\nbr7 500 700\nbr9 300 400\n===ADDR===\n' + json.dumps(ADDRESSES)


# --- the parsers (July's) ------------------------------------------------------------------


def test_bridge_counters_parse_and_skip_malformed_lines() -> None:
    assert parse_bridge_counters('br0 1000 2000\nbr10 500 600\n') == {
        'br0': {'rx_bytes': 1000, 'tx_bytes': 2000},
        'br10': {'rx_bytes': 500, 'tx_bytes': 600},
    }
    text = 'br0 1000 2000\ngarbage line here\nbr10 not-a-number 5\n'
    assert parse_bridge_counters(text) == {'br0': {'rx_bytes': 1000, 'tx_bytes': 2000}}
    assert parse_bridge_counters('') == {}


@pytest.mark.parametrize(
    ('stdout', 'addresses'),
    [
        (
            'br0 1 2\n===ADDR===\n[{"ifname": "br0", "addr_info": []}]',
            [{'ifname': 'br0', 'addr_info': []}],
        ),
        ('br0 1 2\n', []),
        ('br0 1 2\n===ADDR===\nnot json', []),
        ('===ADDR===\n{"not": "a list"}', []),
    ],
    ids=['split', 'no marker', 'not json', 'not a list'],
)
def test_the_output_splits_at_the_marker(stdout: str, addresses: list[Any]) -> None:
    counters, parsed = split_sample_output(stdout)
    assert parsed == addresses
    assert counters.startswith('br0 1 2') or counters == ''


def test_the_script_is_a_constant_with_one_marker() -> None:
    assert SAMPLE_SCRIPT.count('===ADDR===') == 1 and '{' not in SAMPLE_SCRIPT
    assert SAMPLE_TIMEOUT == 30


# --- one sample ----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', FAKE_SSH_PW)


@pytest.fixture
def ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH({'sh': STDOUT})
    monkeypatch.setattr(asyncssh, 'connect', fake)
    return fake


def _controller() -> FakeController:
    return FakeController({f'{API}/rest/networkconf': legacy(NETWORKS)})


def _rows(path: Path) -> dict[int, tuple[int, int, str]]:
    with sqlite3.connect(path) as conn:
        query = 'SELECT vlan_id, rx_bytes, tx_bytes, iface FROM raw_samples'
        return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(query)}


async def test_a_sample_stores_each_resolved_vlan_and_lists_the_rest(
    ssh: FakeSSH, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bounds: list[float] = []
    real = vlan_traffic.run_gateway_command

    async def _spy(conn: Any, argv: Any, *, timeout: float) -> Any:
        bounds.append(timeout)
        return await real(conn, argv, timeout=timeout)

    monkeypatch.setattr(vlan_traffic, 'run_gateway_command', _spy)
    controller = _controller()
    path = tmp_path / 'store.sqlite3'
    async with serving(controller):
        result = await sample_vlan_traffic(path)
    assert {row['vlan_id'] for row in result['sampled']} == {1, 30, 40}
    assert [u['vlan_id'] for u in result['unresolved']] == [199]
    assert _rows(path) == {1: (1000, 2000, 'br0'), 30: (500, 700, 'br7'), 40: (300, 400, 'br9')}
    assert [shlex.split(c) for c in ssh.commands] == [['sh', '-c', SAMPLE_SCRIPT]]
    assert bounds == [SAMPLE_TIMEOUT]
    assert controller.methods == {'GET'}


async def test_a_resolved_interface_with_no_counters_is_skipped(
    ssh: FakeSSH, tmp_path: Path
) -> None:
    ssh.replies = {'sh': 'br7 500 700\n===ADDR===\n' + json.dumps(ADDRESSES)}
    path = tmp_path / 'store.sqlite3'
    async with serving(_controller()):
        result = await sample_vlan_traffic(path)
    assert [row['vlan_id'] for row in result['sampled']] == [30]
    assert {s['iface'] for s in result['skipped']} == {'br0', 'br9'}


async def test_an_unwritable_store_is_a_tool_error(ssh: FakeSSH, tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    open_store(path, writable=True).close()
    path.chmod(0o444)
    try:
        async with serving(_controller()):
            with pytest.raises(ToolError) as caught:
                await sample_vlan_traffic(path)
    finally:
        path.chmod(0o600)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'writable' in (caught.value.suggestion or '')


async def test_no_ssh_password_fails_before_the_controller_is_asked(
    ssh: FakeSSH, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('UNIFI_SSH_PASSWORD')
    controller = _controller()
    async with serving(controller):
        with pytest.raises(ToolError) as caught:
            await sample_vlan_traffic(tmp_path / 'store.sqlite3')
    assert caught.value.error_code == ErrorCodes.CONFIG_MISSING
    assert controller.calls == [] and ssh.connects == []


def test_the_sampler_has_no_mcp_tool_and_the_readers_do() -> None:
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    categories = ToolRegistry(default_manifests_dir(), strict=True).get_categories()
    names = {n for ns in categories.values() for n in ns}
    assert {'get_vlan_traffic_report', 'list_vlan_traffic_periods'} <= names
    assert 'trigger_vlan_traffic_sample' not in names and 'sample_vlan_traffic' not in names


# --- the CLI -------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH) -> FakeController:
    controller = _controller()
    route_cli(monkeypatch, controller)
    return controller


def test_sample_prints_one_line_and_the_notice_once(cli: FakeController, tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)])
    assert result.exit_code == 0, result.output
    assert len(result.stdout.strip().splitlines()) == 1
    assert 'Sampled 3 VLAN(s)' in result.stdout and '1 unresolved' in result.stdout
    assert result.stderr.count('host key') == 1
    assert set(_rows(path)) == {1, 30, 40}


def test_sample_without_db_writes_under_xdg_state_not_the_cwd(
    cli: FakeController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path / 'xdg'))
    result = runner.invoke(app, ['vlan-traffic', 'sample'])
    assert result.exit_code == 0, result.output
    assert list(cwd.iterdir()) == []
    assert default_db_path() == tmp_path / 'xdg' / 'unifi_mapper' / 'vlan-traffic.sqlite3'
    assert default_db_path().exists()


def test_rollup_prints_one_line(tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', 'rollup', '--db', str(path)])
    assert result.exit_code == 0, result.output
    assert len(result.stdout.strip().splitlines()) == 1 and 'Rolled' in result.stdout


@pytest.mark.parametrize('command', [['report', 'now'], ['coverage']])
def test_a_missing_store_exits_1_with_the_sample_hint(tmp_path: Path, command: list[str]) -> None:
    path = tmp_path / 'absent.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', *command, '--db', str(path)])
    assert result.exit_code == 1, result.output
    assert result.stdout == ''
    assert 'vlan-traffic sample' in ' '.join(result.stderr.split())
    assert not path.exists()


def test_report_and_coverage_print_json_and_tables(cli: FakeController, tmp_path: Path) -> None:
    path = tmp_path / 'store.sqlite3'
    assert runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)]).exit_code == 0
    report = runner.invoke(app, ['vlan-traffic', 'report', '1d', '--db', str(path), '--json'])
    assert report.exit_code == 0, report.output
    data = json.loads(report.stdout)
    assert data['methodology']['tier_used'] == 'raw'
    assert {v['vlan_id'] for v in data['vlans']} == {1, 30, 40}
    coverage = runner.invoke(app, ['vlan-traffic', 'coverage', '--db', str(path), '--json'])
    assert json.loads(coverage.stdout)['raw']['count'] == 1
    table = runner.invoke(app, ['vlan-traffic', 'report', '1d', '--db', str(path)])
    assert table.exit_code == 0 and 'IoT' in table.stdout
    assert runner.invoke(app, ['vlan-traffic', 'coverage', '--db', str(path)]).exit_code == 0


def test_an_unknown_period_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ['vlan-traffic', 'report', 'forever', '--db', str(tmp_path)])
    assert result.exit_code == 2


@pytest.mark.parametrize(
    'command', [['sample'], ['rollup'], ['report', 'now'], ['coverage']], ids=lambda c: c[0]
)
def test_a_db_that_is_a_directory_exits_2_naming_it(
    cli: FakeController, tmp_path: Path, command: list[str]
) -> None:
    """Design section 6.1 (review F8): ``--db`` naming a directory is refused, exit 2."""
    result = runner.invoke(app, ['vlan-traffic', *command, '--db', str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert '--db names a directory' in result.stderr and cli.calls == []


def test_the_db_path_is_expanded(
    cli: FakeController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', '~/vlan.sqlite3'])
    assert result.exit_code == 0, result.output
    assert set(_rows(tmp_path / 'vlan.sqlite3')) == {1, 30, 40}


@pytest.mark.parametrize('command', ['sample', 'rollup', 'report', 'coverage'])
def test_every_command_has_help(command: str) -> None:
    result = runner.invoke(app, ['vlan-traffic', command, '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert '--db' in flat
    if command == 'sample':
        assert 'SSH' in flat and 'host key is not verified' in flat
