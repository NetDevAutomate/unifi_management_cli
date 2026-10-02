"""T8 part 1: the ``unifi-mcp`` entry point, its flags and the advertised server version.

``--version`` and ``--help`` must exit 0 without building the catalog or starting stdio;
unknown arguments are warned about and ignored; no arguments starts the server. The
initialize handshake must report this package's version, not the SDK's.
"""

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
