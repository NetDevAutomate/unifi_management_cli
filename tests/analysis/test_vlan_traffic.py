"""Per-VLAN traffic sampling (``analysis/vlan_traffic.py``) and the ``vlan-traffic`` CLI group.

Ported from the prototype (a local archive, not in the repo) and adapted: documentation values
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


# --- the parsers (the prototype's) ------------------------------------------------------------------


def test_bridge_counters_parse() -> None:
    assert parse_bridge_counters('br0 1000 2000\nbr10 500 600\n') == {
        'br0': {'rx_bytes': 1000, 'tx_bytes': 2000},
        'br10': {'rx_bytes': 500, 'tx_bytes': 600},
    }
    assert parse_bridge_counters('') == {}


SECRET_FIELD = 'password=FAKE-BRIDGE-LINE-PW'  # pragma: allowlist secret


@pytest.mark.parametrize(
    'line',
    [
        'br10 500 ',
        'br10  ',
        'br10 not-a-number 5',
        'br10 500 6x',
        'br10 -500 600',
        'br10 500 600 700',
        'garbage line here',
        f'br10 {SECRET_FIELD} 5',
    ],
    ids=[
        'empty tx field',
        'both fields empty',
        'non-numeric rx field',
        'non-numeric tx field',
        'negative',
        'four fields',
        'garbage',
        'secret-shaped field',
    ],
)
def test_a_bridge_line_without_two_integer_counters_is_an_error(line: str) -> None:
    """Review finding: the script exits with ``ip``'s status, so a ``cat`` that failed
    printed an empty counter, and the line was skipped: a partial sample, exit 0."""
    with pytest.raises(ToolError) as caught:
        parse_bridge_counters(f'br0 1000 2000\n{line}\nbr9 300 400\n')
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'without two integer counters' in caught.value.message
    assert 'FAKE-BRIDGE-LINE-PW' not in caught.value.message
    assert 'FAKE-BRIDGE-LINE-PW' not in (caught.value.suggestion or '')


def test_a_refused_bridge_line_is_redacted_in_the_message() -> None:
    with pytest.raises(ToolError) as caught:
        parse_bridge_counters(f'br10 {SECRET_FIELD} 5\n')
    assert 'FAKE-BRIDGE-LINE-PW' not in caught.value.message
    assert 'password=***redacted***' in caught.value.message


def test_blank_lines_hold_no_bridge() -> None:
    assert parse_bridge_counters('\nbr0 1 2\n  \n') == {'br0': {'rx_bytes': 1, 'tx_bytes': 2}}


@pytest.mark.parametrize(
    ('stdout', 'addresses'),
    [
        (
            'br0 1 2\n===ADDR===\n[{"ifname": "br0", "addr_info": []}]',
            [{'ifname': 'br0', 'addr_info': []}],
        ),
        ('br0 1 2\n===ADDR===\n[]', []),
        ('br0 1 2\n===ADDR===\n[{"ifname": "br0"}, "not an entry"]', [{'ifname': 'br0'}]),
    ],
    ids=['split', 'no addresses', 'a stray entry'],
)
def test_the_output_splits_at_the_marker(stdout: str, addresses: list[Any]) -> None:
    counters, parsed = split_sample_output(stdout)
    assert parsed == addresses
    assert counters.startswith('br0 1 2')


@pytest.mark.parametrize(
    'stdout',
    [
        'br0 1 2\n',
        'br0 1 2\n===ADDR===\nnot json',
        '===ADDR===\n{"not": "a list"}',
        'br0 1 2\n===ADDR===\n',
    ],
    ids=['no marker', 'not json', 'not a list', 'nothing after the marker'],
)
def test_output_without_a_parseable_address_list_is_an_error(stdout: str) -> None:
    """Review B4: read as "no addresses", a broken output looked like an empty sample."""
    with pytest.raises(ToolError) as caught:
        split_sample_output(stdout)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'address list' in caught.value.message


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


async def test_a_second_untagged_network_is_unresolved_not_overwritten(
    ssh: FakeSSH, tmp_path: Path
) -> None:
    """Two networks without a VLAN ID both derive VLAN 1 (issue 070).

    The store keys raw rows by ``(ts_utc, vlan_id)`` and writes with ``INSERT OR REPLACE``,
    so a second VLAN-1 row would silently replace the first. The first resolved network
    keeps the ID; the later one is listed under ``unresolved`` so the CLI's one line counts
    it, and is never stored under the other network's name.
    """
    networks = [
        {'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
        {'name': 'Second LAN', 'purpose': 'corporate', 'ip_subnet': '198.51.100.1/24'},
    ]
    controller = FakeController({f'{API}/rest/networkconf': legacy(networks)})
    path = tmp_path / 'store.sqlite3'
    async with serving(controller):
        result = await sample_vlan_traffic(path)
    assert [(row['vlan_id'], row['network_name']) for row in result['sampled']] == [(1, 'LAN')]
    assert result['unresolved'] == [
        {
            'vlan_id': 1,
            'network_name': 'Second LAN',
            'subnet': '198.51.100.0/24',
            'iface': 'br7',
            'reason': 'VLAN 1 already sampled from LAN (br0)',
        }
    ]
    assert _rows(path) == {1: (1000, 2000, 'br0')}


async def test_a_bridge_whose_counter_could_not_be_read_fails_the_sample(
    ssh: FakeSSH, tmp_path: Path
) -> None:
    """Review finding: a failed ``cat`` leaves an empty field under exit status 0; the
    sample is an error and stores nothing, never the other bridges' partial sample."""
    ssh.replies = {
        'sh': 'br0 1000 2000\nbr7 500 \nbr9 300 400\n===ADDR===\n' + json.dumps(ADDRESSES)
    }
    path = tmp_path / 'store.sqlite3'
    async with serving(_controller()):
        with pytest.raises(ToolError) as caught:
            await sample_vlan_traffic(path)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert 'without two integer counters' in caught.value.message
    assert not path.exists()


@pytest.mark.parametrize(
    'reply',
    [
        ('', 'sh: ip: not found', 127),
        ('br0 1000 2000\n===ADDR===\n', 'Error: unknown option -j', 255),
    ],
    ids=['ip missing', 'ip refused -j'],
)
async def test_a_script_that_fails_is_an_error_and_stores_nothing(
    ssh: FakeSSH, tmp_path: Path, reply: tuple[str, str, int]
) -> None:
    """Review B4: a failed script read as "Sampled 0 VLAN(s)", exit 0; the probes check it."""
    ssh.replies = {'sh': reply}
    path = tmp_path / 'store.sqlite3'
    async with serving(_controller()):
        with pytest.raises(ToolError) as caught:
            await sample_vlan_traffic(path)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert f'exit status {reply[2]}' in caught.value.message
    assert reply[1] in caught.value.message  # the last stderr line, redacted
    assert not path.exists()


async def test_the_failed_scripts_stderr_line_is_redacted(ssh: FakeSSH, tmp_path: Path) -> None:
    """Review finding: the failure cases held no secret-like text, so they would pass
    with the redaction removed; this one fails then."""
    stderr = 'fatal: login password=FAKE-VLAN-STDERR-PW'  # pragma: allowlist secret
    ssh.replies = {'sh': ('', stderr, 1)}
    async with serving(_controller()):
        with pytest.raises(ToolError) as caught:
            await sample_vlan_traffic(tmp_path / 'store.sqlite3')
    assert 'FAKE-VLAN-STDERR-PW' not in caught.value.message
    assert caught.value.message.endswith('fatal: login password=***redacted***')


async def test_a_script_without_the_address_list_is_an_error(ssh: FakeSSH, tmp_path: Path) -> None:
    ssh.replies = {'sh': 'br0 1000 2000\nbr7 500 700\n'}
    path = tmp_path / 'store.sqlite3'
    async with serving(_controller()):
        with pytest.raises(ToolError) as caught:
            await sample_vlan_traffic(path)
    assert caught.value.error_code == ErrorCodes.API_ERROR
    assert not path.exists()


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


def test_sample_exits_1_when_the_script_fails(
    cli: FakeController, ssh: FakeSSH, tmp_path: Path
) -> None:
    ssh.replies = {'sh': ('', 'sh: ip: not found', 127)}
    path = tmp_path / 'store.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)])
    assert result.exit_code == 1, result.output
    assert result.stdout == ''
    assert 'could not run on the gateway' in ' '.join(result.stderr.split())
    assert not path.exists()


def test_sample_exits_1_when_a_bridge_counter_is_missing(
    cli: FakeController, ssh: FakeSSH, tmp_path: Path
) -> None:
    """Review finding: before, the other bridges were stored and the run exited 0."""
    ssh.replies = {'sh': 'br0 1000 2000\nbr7  \n===ADDR===\n' + json.dumps(ADDRESSES)}
    path = tmp_path / 'store.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)])
    assert result.exit_code == 1, result.output
    assert result.stdout == ''
    assert 'without two integer counters' in ' '.join(result.stderr.split())
    assert not path.exists()


def test_sample_exits_1_when_nothing_was_sampled(
    cli: FakeController, ssh: FakeSSH, tmp_path: Path
) -> None:
    """A schedule must notice a sample that stored nothing."""
    ssh.replies = {'sh': 'br0 1000 2000\n===ADDR===\n[]'}
    path = tmp_path / 'store.sqlite3'
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)])
    assert result.exit_code == 1, result.output
    assert 'Sampled 0 VLAN(s)' in result.stdout and '4 unresolved' in result.stdout
    assert 'Nothing was stored' in ' '.join(result.stderr.split())
    assert not path.exists()


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


def test_a_weekly_report_reads_the_newest_samples(cli: FakeController, tmp_path: Path) -> None:
    """Issue 069: the documented `vlan-traffic report 1w` read a tier that held no recent
    data, so it always came back empty; it reads the raw samples now."""
    path = tmp_path / 'store.sqlite3'
    assert runner.invoke(app, ['vlan-traffic', 'sample', '--db', str(path)]).exit_code == 0
    report = runner.invoke(app, ['vlan-traffic', 'report', '1w', '--db', str(path), '--json'])
    assert report.exit_code == 0, report.output
    data = json.loads(report.stdout)
    assert data['methodology']['tier_used'] == 'raw'
    assert {v['vlan_id'] for v in data['vlans']} == {1, 30, 40}


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
    # Review finding: the column is the share of samples that gave a rate, not coverage.
    assert 'Valid samples' in table.stdout and 'Coverage' not in table.stdout
    assert {v['valid_sample_pct'] for v in data['vlans']} == {0.0}  # one sample each
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
    """Design section 6.1: ``--db`` naming a directory is refused, exit 2."""
    result = runner.invoke(app, ['vlan-traffic', *command, '--db', str(tmp_path)])
    assert result.exit_code == 2, result.output
    assert '--db names a directory' in result.stderr and cli.calls == []


def test_the_db_path_is_expanded(
    cli: FakeController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / 'cwd'  # an unexpanded '~/…' would land here, never in the source tree
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv('HOME', str(tmp_path))
    result = runner.invoke(app, ['vlan-traffic', 'sample', '--db', '~/vlan.sqlite3'])
    assert result.exit_code == 0, result.output
    assert set(_rows(tmp_path / 'vlan.sqlite3')) == {1, 30, 40}
    assert list(cwd.iterdir()) == []


@pytest.mark.parametrize('command', ['sample', 'rollup', 'report', 'coverage'])
def test_every_command_has_help(command: str) -> None:
    result = runner.invoke(app, ['vlan-traffic', command, '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert '--db' in flat
    if command == 'sample':
        assert 'SSH' in flat and 'host key is not verified' in flat
