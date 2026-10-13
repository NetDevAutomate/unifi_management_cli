"""T8: the ``unifi-mcp`` entry point, its flags and the advertised server version.

``--version`` and ``--help`` must exit 0 without building the catalog or starting stdio;
unknown arguments are warned about and ignored; no arguments starts the server. The
initialize handshake must report this package's version, not the SDK's. ``--config``
must name a readable file (else exit 2) and ``--check`` reports key names only.
"""

import json
import os
import pytest
import subprocess
import sys
import tomllib
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import InitializeResult
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from unifi_mapper.mcp import server


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def run_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Replace FastMCP.run with a recorder and make building the catalog fail loudly."""
    calls: list[tuple[object, ...]] = []

    def _fake_run(self: FastMCP, *args: object, **kwargs: object) -> None:
        calls.append((self, *args))

    def _no_catalog() -> None:
        raise AssertionError('the tool catalog must not be built for this path')

    monkeypatch.setattr(FastMCP, 'run', _fake_run)
    monkeypatch.setattr(server, 'get_registry', _no_catalog)
    # main() configures loguru and records --config/settings for the lifespan: keep both
    # process-wide effects inside the test.
    monkeypatch.setattr(server, '_configure_logging', lambda level: None)
    monkeypatch.setattr(server, '_config_path', None)
    monkeypatch.setattr(server, '_settings', None)
    return calls


def test_package_version_matches_pyproject() -> None:
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert server.package_version() == project['version']


def test_version_prints_versions_and_never_starts_server(
    run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(['--version'])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.strip() == server.version_string()
    assert f'{server.DIST_NAME} {server.package_version()}' in out
    assert 'mcp SDK ' in out
    assert run_calls == []


@pytest.mark.parametrize('flag', ['--help', '-h'])
def test_help_exits_zero_and_never_starts_server(
    flag: str, run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main([flag])
    assert exc.value.code == 0
    assert 'usage: unifi-mcp' in capsys.readouterr().out
    assert run_calls == []


def test_no_arguments_runs_server_once(
    run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    server.main([])
    assert len(run_calls) == 1
    assert run_calls[0][0] is server.mcp
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ''


def test_unknown_arguments_are_warned_and_tolerated(
    run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    server.main(['--bogus', 'extra'])
    assert len(run_calls) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'ignoring unknown arguments: --bogus extra' in captured.err


async def test_server_info_reports_package_version(monkeypatch: pytest.MonkeyPatch) -> None:
    results: list[InitializeResult] = []
    original = ClientSession.initialize

    async def _recording_initialize(self: ClientSession) -> InitializeResult:
        result = await original(self)
        results.append(result)
        return result

    monkeypatch.setattr(ClientSession, 'initialize', _recording_initialize)
    async with create_connected_server_and_client_session(server.mcp._mcp_server):
        pass
    [result] = results
    assert result.serverInfo.version == server.package_version()
    assert result.serverInfo.name == 'unifi-management'


def test_bare_import_does_not_import_connectivity() -> None:
    code = (
        'import sys\n'
        'import unifi_mapper\n'
        "assert 'unifi_mapper.connectivity.traceroute' not in sys.modules, 'eager import'\n"
        'from unifi_mapper import check_inter_vlan_routing, firewall_check, path_analysis, '
        'traceroute\n'
        'assert all(map(callable, (check_inter_vlan_routing, firewall_check, path_analysis, '
        'traceroute)))\n'
        "print('ok')\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(('UNIFI_', 'PROTECT_'))}
    proc = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == 'ok'


# --- T8 part 2: --config and --check -----------------------------------------------------


def _xdg_prod(values: str) -> Path:
    path = Path(os.environ['XDG_CONFIG_HOME']) / 'unifi_management_cli' / 'prod.env'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(values)
    return path


def test_config_missing_exits_2_without_starting(
    tmp_path: Path, run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / 'nope.env'
    with pytest.raises(SystemExit) as exc:
        server.main(['--config', str(missing)])
    assert exc.value.code == 2
    assert str(missing) in capsys.readouterr().err
    assert run_calls == []


def test_config_is_handed_to_the_lifespan(
    tmp_path: Path, run_calls: list[tuple[object, ...]]
) -> None:
    path = tmp_path / 'site.env'
    path.write_text('UNIFI_URL=https://192.0.2.1\n')
    server.main(['--config', str(path)])
    assert len(run_calls) == 1
    assert server._config_path == path


def test_check_prints_key_names_only_and_exits_0_when_ready(
    run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    path = _xdg_prod(
        f'UNIFI_URL=https://192.0.2.1\nUNIFI_CONSOLE_API_TOKEN={FAKE_TOKEN}\n'
        f'PROTECT_HOST=192.0.2.1\nPROTECT_USERNAME=viewer\nPROTECT_PASSWORD={FAKE_PW}\n'
    )
    with pytest.raises(SystemExit) as exc:
        server.main(['--check'])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert FAKE_TOKEN not in out and FAKE_PW not in out
    report = json.loads(out)
    assert (report['source'], report['path']) == ('xdg', str(path))
    controller = report['families']['controller']
    assert controller['ready'] and controller['source'] == 'file'
    assert 'UNIFI_CONSOLE_API_TOKEN' in controller['present']
    assert 'fallback_chain' not in controller
    assert report['families']['protect']['ready']
    # Issue 037: with only the controller's keys the network family is ready by derivation,
    # resolved later; --check stays offline (run_calls is empty below).
    network = report['families']['network_api']
    assert network['ready'] and network['missing'] == [] and network['present'] == []
    assert network['derived'] == [
        'host: derived from UNIFI_URL',
        'site id: resolved at first call',
        'key: console token (same origin)',
    ]
    assert report['tool_count'] > 0
    assert run_calls == []


def test_check_exits_1_when_nothing_is_configured(
    run_calls: list[tuple[object, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(['--check'])
    assert exc.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report['source'] == 'none'
    assert report['families']['controller']['fallback_chain'] == 'not probed'
    assert run_calls == []


def test_check_with_missing_config_exits_2(
    tmp_path: Path, run_calls: list[tuple[object, ...]]
) -> None:
    with pytest.raises(SystemExit) as exc:
        server.main(['--check', '--config', str(tmp_path / 'nope.env')])
    assert exc.value.code == 2


def test_invalid_setting_warns_once_and_uses_the_default(
    monkeypatch: pytest.MonkeyPatch,
    run_calls: list[tuple[object, ...]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    levels: list[str] = []
    monkeypatch.setattr(server, '_configure_logging', levels.append)
    os.environ['UNIFI_MCP_LOG_LEVEL'] = 'LOUD'
    os.environ['UNIFI_MCP_MAX_CONCURRENCY'] = '0'
    server.main([])
    err = capsys.readouterr().err
    assert err.count('UNIFI_MCP_LOG_LEVEL') == 1
    assert err.count('UNIFI_MCP_MAX_CONCURRENCY') == 1
    assert levels == ['WARNING']
    assert server._settings is not None and server._settings.max_concurrency == 4
    assert len(run_calls) == 1
