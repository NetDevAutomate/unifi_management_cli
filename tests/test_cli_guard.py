"""The CLI's async helpers run every command behind the read-only transport.

``_run_analysis`` and ``_run_gateway_ssh`` install one ``SharedControllerClient`` for the
command (``_guarded``), so every ``UniFiClient()`` the command opens borrows it and goes
through ``ReadOnlyAsyncTransport``, exactly as under the MCP server. A write is refused before
it leaves the host. Every read command runs through one of them (issue 064); the only direct
``asyncio.run`` sites left are the write paths, and the ratchet below stops their number from
growing.

Every test here runs under ``isolated_credentials`` (no live config can resolve) and patches
``typer_cli.load_env_from_config``.
"""

import ast
import asyncssh
import httpx
import importlib
import pytest
from collections.abc import Awaitable, Callable
from pathlib import Path
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.analysis import bandwidth_test
from unifi_mapper.cli import get_default_config_path
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import SharedControllerClient, UniFiClient
from unifi_mapper.core.utils.readonly import ReadOnlyViolation
from unifi_mapper.diagnostics import network_health
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('isolated_credentials')

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / 'src' / 'unifi_mapper'
TYPER_CLI = PACKAGE / 'typer_cli.py'
GUARD_HELPERS = frozenset({'_run_analysis', '_run_gateway_ssh'})
DIRECT_ASYNCIO_RUN_SITES = 7  # the write paths (issue 064); never raise it
API = '/proxy/network/api/s/default'


class LoginOnlyTransport(httpx.MockTransport):
    """A controller that answers only the token login and records every request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == 'GET' and request.url.path == '/api/system':
            return httpx.Response(200, json={})
        if request.method == 'GET' and request.url.path == f'{API}/self':
            return httpx.Response(200, json={'meta': {'rc': 'ok'}, 'data': []})
        raise AssertionError(f'unexpected request {request.method} {request.url.path}')


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> LoginOnlyTransport:
    """Every command's shared holder logs in over a login-only mock; nothing loads a config."""
    mock = LoginOnlyTransport()
    credentials = Credentials(host='192.0.2.1', api_token=FAKE_TOKEN)
    monkeypatch.setattr(
        typer_cli,
        '_shared_client_factory',
        lambda: SharedControllerClient(credentials, inner_transport=mock),
    )
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', 'FAKE-SSH-PW-NOT-REAL')  # pragma: allowlist secret
    return mock


def _put_through_a_fresh_client(seen: list[BaseException]) -> Callable[..., Awaitable[Any]]:
    async def _write(*_args: object, **_kwargs: object) -> Any:
        async with UniFiClient() as client:
            try:
                await client.put(client.build_path('rest/device/x'), {})
            except BaseException as e:
                seen.append(e)
                raise
        raise AssertionError('the PUT was not refused')

    return _write


@pytest.mark.parametrize(
    ('args', 'module', 'name'),
    [
        (['diagnose', 'health'], network_health, 'network_health_check'),
        (['diagnose', 'bandwidth', '192.0.2.10'], bandwidth_test, 'run_bandwidth_test'),
    ],
    ids=['_run_analysis', '_run_gateway_ssh'],
)
def test_a_write_through_either_helper_is_refused_before_the_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: LoginOnlyTransport,
    args: list[str],
    module: Any,
    name: str,
) -> None:
    seen: list[BaseException] = []
    monkeypatch.setattr(module, name, _put_through_a_fresh_client(seen))
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # the helper's error path, no traceback
    [error] = seen
    assert isinstance(error, ReadOnlyViolation)
    assert 'Error:' in result.stderr
    assert transport.calls == [('GET', '/api/system'), ('GET', f'{API}/self')]
    assert all(method != 'PUT' for method, _ in transport.calls)


# Issue 064: the read commands that used to call ``asyncio.run`` directly, each with the
# module and name of its first controller read. The test replaces that read with a write and
# expects the guard to refuse it; a command still outside the guard would resolve credentials
# itself and never touch the shared transport. The write paths (``stp apply`` and the like)
# stay on their own plan, review and apply flow and are not listed.
MOVED_READ_COMMANDS: list[tuple[list[str], str, str]] = [
    (['analyze', 'port-profiles'], 'analysis.port_profile_validation', 'validate_port_profiles'),
    (['analyze', 'lag-candidates'], 'analysis.lag_monitoring', 'find_lag_candidates'),
    (['analyze', 'mtu'], 'analysis.mtu_audit', 'audit_mtu_consistency'),
    (['analyze', 'radio'], 'analysis.radio_optimization', 'analyze_radio_optimization'),
    (['analyze', 'sfp'], 'analysis.sfp_diagnostics', 'audit_sfp_diagnostics'),
    (
        ['analyze', 'vlan-coverage', '--required-vlans', '10'],
        'analysis.vlan_coverage',
        'audit_vlan_coverage',
    ),
    (
        ['analyze', 'uplink-transparency'],
        'analysis.uplink_transparency',
        'audit_uplink_transparency',
    ),
    (['analyze', 'power-budget'], 'analysis.power_budget', 'audit_power_budget'),
    (['analyze', 'traffic-matrix'], 'analysis.traffic_matrix', 'analyze_traffic_matrix'),
    (['analyze', 'link-errors', '--snapshot'], 'analysis.link_error_tracking', 'fetch_devices'),
    (['analyze', 'link-errors'], 'analysis.link_error_tracking', 'compare_link_errors'),
    (
        ['analyze', 'roaming', '--snapshot'],
        'analysis.roaming_analysis',
        'snapshot_client_associations',
    ),
    (['analyze', 'roaming'], 'analysis.roaming_analysis', 'analyze_roaming'),
    (['analyze', 'config-drift', '--snapshot'], 'analysis.config_drift', 'snapshot_config'),
    (['analyze', 'config-drift'], 'analysis.config_drift', 'detect_drift'),
    (['analyze', 'neighbours', '--snapshot'], 'analysis.neighbour_trend', 'snapshot_neighbours'),
    (['analyze', 'neighbours', '--diff'], 'analysis.neighbour_trend', 'detect_neighbour_trend'),
    (['analyze', 'neighbours'], 'analysis.neighbour_scan', 'scan_neighbours'),
    (
        ['diagnose', 'inter-vlan', '192.0.2.10', '192.0.2.20'],
        'connectivity.inter_vlan',
        'check_inter_vlan_routing',
    ),
    (['stp', 'analyze'], 'analysis.stp_optimizer', 'discover_stp_topology'),
    (['stp', 'optimize'], 'analysis.stp_optimizer', 'discover_stp_topology'),
    (
        ['stp', 'report', '--output', 'stp-report.md'],
        'analysis.stp_optimizer',
        'discover_stp_topology',
    ),
    (
        ['stp', 'snapshot', '--output', 'stp-snapshot.json'],
        'analysis.stp_optimizer',
        'discover_stp_topology',
    ),
    (['stp', 'diff', 'baseline.json'], 'analysis.stp_optimizer', 'discover_stp_topology'),
    (['stp', 'preflight'], 'analysis.stp_optimizer', 'discover_stp_topology'),
    (['stp', 'guard'], 'analysis.stp_optimizer', 'discover_stp_topology'),
    (
        ['stp', 'drift', '--intent', 'intent.yaml'],
        'analysis.stp_optimizer',
        'discover_stp_topology',
    ),
    (['stp', 'validate-10g'], 'analysis.stp_optimizer', 'validate_10g_expansion_readiness'),
    (['ports', 'refresh'], 'analysis.port_naming', 'analyse_port_names'),
    (['radio', 'snapshot'], 'analysis.radio_config', 'snapshot_radio_config'),
    (['radio', 'auto-channel'], 'analysis.channel_optimiser', 'analyze_channels'),
    (['radio', 'report'], 'analysis.channel_optimiser', 'analyze_channels'),
]


@pytest.mark.parametrize(
    ('args', 'module', 'name'),
    MOVED_READ_COMMANDS,
    ids=[' '.join(args) for args, _, _ in MOVED_READ_COMMANDS],
)
def test_a_write_through_a_moved_read_command_is_refused_before_the_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: LoginOnlyTransport,
    args: list[str],
    module: str,
    name: str,
) -> None:
    Path('baseline.json').write_text(
        '{}', encoding='utf-8'
    )  # stp diff reads it before the controller
    seen: list[BaseException] = []
    target = importlib.import_module(f'unifi_mapper.{module}')
    monkeypatch.setattr(target, name, _put_through_a_fresh_client(seen))
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)  # no traceback
    [error] = seen
    assert isinstance(error, ReadOnlyViolation), repr(error)
    assert transport.calls == [('GET', '/api/system'), ('GET', f'{API}/self')]
    assert all(method != 'PUT' for method, _ in transport.calls)


class DevicesTransport(LoginOnlyTransport):
    """The login-only controller, plus an empty ``stat/device`` answer."""

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == 'GET' and request.url.path == f'{API}/stat/device':
            self.calls.append((request.method, request.url.path))
            return httpx.Response(200, json={'meta': {'rc': 'ok'}, 'data': []})
        return super()._handle(request)


def test_radio_optimize_reads_the_devices_through_the_shared_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``radio optimize`` opens its own ``UniFiClient()``; under the guard it borrows the holder."""
    mock = DevicesTransport()
    credentials = Credentials(host='192.0.2.1', api_token=FAKE_TOKEN)
    monkeypatch.setattr(
        typer_cli,
        '_shared_client_factory',
        lambda: SharedControllerClient(credentials, inner_transport=mock),
    )
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    result = runner.invoke(app, ['radio', 'optimize'])
    assert result.exit_code == 0, result.output
    assert 'No optimisations needed' in result.output
    assert mock.calls == [
        ('GET', '/api/system'),
        ('GET', f'{API}/self'),
        ('GET', f'{API}/stat/device'),
    ]


def _asyncio_runs(node: ast.AST) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == 'run'
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == 'asyncio'
    ]


def _cli_modules() -> list[Path]:
    """Return every module under src/unifi_mapper that builds a Typer app."""
    paths = PACKAGE.rglob('*.py')
    return sorted(p for p in paths if 'typer.Typer(' in p.read_text(encoding='utf-8'))


def test_new_commands_run_behind_the_read_only_transport() -> None:
    """Helpers run _guarded; no new direct asyncio.run in a CLI module (issue 064 ratchet)."""
    modules = _cli_modules()
    assert TYPER_CLI in modules
    for path in modules:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        if path != TYPER_CLI:
            assert _asyncio_runs(tree) == [], f'{path.name}: use _run_analysis/_run_gateway_ssh'
            continue
        helpers = [
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in GUARD_HELPERS
        ]
        assert {h.name for h in helpers} == GUARD_HELPERS
        for helper in helpers:
            (call,) = _asyncio_runs(helper)
            assert isinstance(call.args[0], ast.Call)
            assert getattr(call.args[0].func, 'id', None) == '_guarded', helper.name
        direct = len(_asyncio_runs(tree)) - len(helpers)
        assert direct <= DIRECT_ASYNCIO_RUN_SITES, 'route new commands through the guard helpers'


# Every module that reads the controller through UniFiClient must borrow the installed holder:
# a UniFiClient(...) with arguments would bypass it, an httpx.AsyncClient(...) the guard.
# Derived, so a module added later is scanned without being listed; client.py
# itself defines the client and the holder.
CLIENT_MODULE = PACKAGE / 'core' / 'utils' / 'client.py'
PROTOTYPE_CONTROLLER_MODULES = (
    'analysis/ap_health.py',
    'analysis/vlan_traffic.py',
    'connectivity/gateway_probe.py',
    'diagnostics/client_connectivity.py',
    'diagnostics/observability.py',
    'diagnostics/wan_health.py',
)


def _names_unifi_client(tree: ast.AST) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == 'UniFiClient')
        or (isinstance(n, ast.Attribute) and n.attr == 'UniFiClient')
        or (isinstance(n, ast.ImportFrom) and any(a.name == 'UniFiClient' for a in n.names))
        for n in ast.walk(tree)
    )


CONTROLLER_MODULES = sorted(
    path
    for path in PACKAGE.rglob('*.py')
    if path != CLIENT_MODULE and _names_unifi_client(ast.parse(path.read_text(encoding='utf-8')))
)


def _import_aliases(tree: ast.AST, name: str) -> set[str]:
    """The names ``from … import <name> [as alias]`` binds in the module, ``name`` included."""
    return {name} | {
        alias.asname
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for alias in n.names
        if alias.name == name and alias.asname
    }


def _own_clients(tree: ast.AST) -> list[int]:
    """Lines that build a client of their own: ``UniFiClient`` with arguments, or httpx's.

    Resolves ``from … import UniFiClient as X`` and ``from httpx import AsyncClient as Y``
    (issue 076 item 19), so an alias cannot hide a constructor from the scan.
    """
    unifi, httpx_clients = (
        _import_aliases(tree, 'UniFiClient'),
        _import_aliases(tree, 'AsyncClient'),
    )

    def own(call: ast.Call) -> bool:
        name = getattr(call.func, 'id', None) or getattr(call.func, 'attr', None)
        if name in httpx_clients:
            return True
        return name in unifi and bool(call.args or call.keywords)

    return [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and own(n)]


@pytest.mark.parametrize('path', CONTROLLER_MODULES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_controller_modules_only_borrow_the_guarded_client(path: Path) -> None:
    assert _own_clients(ast.parse(path.read_text(encoding='utf-8'))) == []


def test_the_scan_covers_every_prototype_controller_module() -> None:
    scanned = {str(path.relative_to(PACKAGE)) for path in CONTROLLER_MODULES}
    assert set(PROTOTYPE_CONTROLLER_MODULES) <= scanned
    assert len(scanned) > 40, f'only {len(scanned)} modules name UniFiClient: has it moved?'
    assert str(CLIENT_MODULE.relative_to(PACKAGE)) not in scanned


def test_the_own_client_scan_sees_arguments_and_raw_httpx() -> None:
    sample = (
        'UniFiClient()\nUniFiClient(creds)\nUniFiClient(credentials=c)\nhttpx.AsyncClient()\n'
        'client.UniFiClient(creds)\nclient.UniFiClient()\n'
    )
    assert _own_clients(ast.parse(sample)) == [2, 3, 4, 5]
    assert _names_unifi_client(ast.parse('from x import UniFiClient'))
    assert _names_unifi_client(ast.parse('c.UniFiClient()'))
    assert not _names_unifi_client(ast.parse('UniFiClientish = 1'))


def test_the_own_client_scan_resolves_import_aliases() -> None:
    """Issue 076 item 19: a constructor reached through an alias was not matched by name."""
    sample = (
        'from unifi_mapper.core.utils.client import UniFiClient as Client\n'  # 1
        'from httpx import AsyncClient as Http\n'  # 2
        'import httpx as h\n'  # 3
        'Client(creds)\n'  # 4: an own client through the alias
        'Client()\n'  # 5: borrows the holder
        'Http()\n'  # 6: raw httpx through the alias
        'h.AsyncClient()\n'  # 7
        'Other(creds)\n'  # 8: not a client
    )
    assert _own_clients(ast.parse(sample)) == [4, 6, 7]
    assert _names_unifi_client(ast.parse(sample))  # the aliased import still marks the module


def test_the_host_key_notice_prints_once_per_invocation(
    monkeypatch: pytest.MonkeyPatch, transport: LoginOnlyTransport
) -> None:
    async def _ok(*_args: object, reverse: bool = False, **_kwargs: object) -> dict:
        return {'status': 'OK', 'throughput_mbps': 1.0, 'throughput_gbps': 0.001}

    monkeypatch.setattr(bandwidth_test, 'run_bandwidth_test', _ok)
    for _ in range(2):  # a second in-process invocation prints it again, once
        result = runner.invoke(app, ['diagnose', 'bandwidth', '192.0.2.10', '--bidir'])
        assert result.exit_code == 0, result.output
        assert result.stderr.count(typer_cli.GATEWAY_SSH_NOTICE) == 1
        assert typer_cli.GATEWAY_SSH_NOTICE not in result.stdout
    assert 'host key is not verified' in typer_cli.GATEWAY_SSH_NOTICE
    assert '038' in typer_cli.GATEWAY_SSH_NOTICE


def test_an_analysis_command_prints_no_host_key_notice(
    monkeypatch: pytest.MonkeyPatch, transport: LoginOnlyTransport
) -> None:
    seen: list[BaseException] = []
    monkeypatch.setattr(network_health, 'network_health_check', _put_through_a_fresh_client(seen))
    result = runner.invoke(app, ['diagnose', 'health'])
    assert typer_cli.GATEWAY_SSH_NOTICE not in result.output


def test_this_module_cannot_see_a_live_config_or_ssh(tmp_path: Path) -> None:
    assert Path.cwd() == tmp_path
    assert not get_default_config_path().exists()


async def test_a_real_ssh_connect_fails_here() -> None:
    with pytest.raises(AssertionError, match='live SSH in a test'):
        await asyncssh.connect('192.0.2.1')
