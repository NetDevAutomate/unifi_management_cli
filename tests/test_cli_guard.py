"""The CLI's async helpers run every command behind the read-only transport.

``_run_analysis`` and ``_run_gateway_ssh`` install one ``SharedControllerClient`` for the
command (``_guarded``), so every ``UniFiClient()`` the command opens borrows it and goes
through ``ReadOnlyAsyncTransport``, exactly as under the MCP server. A write is refused before
it leaves the host. The rest of the CLI's direct ``asyncio.run`` sites are issue 064; the
ratchet below stops their number from growing.

Every test here runs under ``isolated_credentials`` (no live config can resolve) and patches
``typer_cli.load_env_from_config``.
"""

import ast
import asyncssh
import httpx
import pytest
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
I6_DIRECT_SITES = 47  # issue 064: lower this as each command group moves
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


def _put_through_a_fresh_client(seen: list[BaseException]):
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
        assert direct <= I6_DIRECT_SITES, 'route new commands through the guard helpers'


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
