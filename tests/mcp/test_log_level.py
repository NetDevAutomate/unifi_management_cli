"""The documented log level (``UNIFI_MCP_LOG_LEVEL``, default ``WARNING``) holds in every mode.

``--check`` and the direct surface build the tool catalog, which logs a DEBUG note for each
tool without a structured return type. By default nothing below WARNING may reach stderr,
and stdout must stay pure JSON (``--check``) or JSON-RPC (serving). The stderr warnings for
a malformed env-file line, a missing ``UNIFI_CONFIG`` file and an invalid level are plain
prints, not loguru records, so they must still show.

Each case runs ``main()`` in a subprocess, as the ``unifi-mcp`` console script does, in an
environment built from scratch (``isolated_env``): no real ~/.config, Keychain or 1Password.
"""

import json
import pytest
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from tests.fixtures_unifi import FAKE_TOKEN
from tests.mcp.conftest import isolated_env
from typing import Any


# What the unifi-mcp console script runs; `python -m` would add runpy's warning to stderr.
ENTRY = [sys.executable, '-c', 'from unifi_mapper.mcp.server import main; main()']
CATALOG_NOTE = 'has no structured return type; listing without outputSchema'
DEBUG = re.compile(r'\bDEBUG\b')
INITIALIZE = (
    json.dumps(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-06-18',
                'capabilities': {},
                'clientInfo': {'name': 'log-level', 'version': '0'},
            },
        }
    )
    + '\n'
)
INITIALIZED = json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'
LIST_TOOLS = json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}) + '\n'


def _debug_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if DEBUG.search(line)]


def _run(tmp_path: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ENTRY, *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=isolated_env(tmp_path, **env),
        timeout=60,
    )


def _reader(stream: Any, lines: 'queue.Queue[str | None]') -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


def _serve(tmp_path: Path, **env: str) -> tuple[list[dict[str, Any]], str]:
    """Serve the direct surface: initialize, list tools, close stdin; return replies, stderr."""
    proc = subprocess.Popen(
        [*ENTRY, '--surface', 'direct'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
        env=isolated_env(tmp_path, **env),
    )
    assert proc.stdin and proc.stdout and proc.stderr
    lines: queue.Queue[str | None] = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    replies: list[dict[str, Any]] = []
    try:
        for message in (INITIALIZE, INITIALIZED + LIST_TOOLS):
            proc.stdin.write(message)
            proc.stdin.flush()
            line = lines.get(timeout=30)
            assert line is not None, 'the server closed stdout early'
            replies.append(json.loads(line))
        proc.stdin.close()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    while (line := lines.get(timeout=5)) is not None:
        replies.append(json.loads(line))  # anything else on stdout must be JSON-RPC too
    return replies, proc.stderr.read()


def test_check_prints_json_and_no_debug_lines_by_default(tmp_path: Path) -> None:
    config = tmp_path / 'xdg' / 'unifi_management_cli' / 'prod.env'
    config.parent.mkdir(parents=True)
    config.write_text(
        f'UNIFI_URL=https://192.0.2.1\nnot a setting\nUNIFI_CONSOLE_API_TOKEN={FAKE_TOKEN}\n'
    )
    proc = _run(tmp_path, '--surface', 'direct', '--check')
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report['surface'] == 'direct'
    assert report['families']['controller']['ready']
    assert _debug_lines(proc.stderr) == []
    assert CATALOG_NOTE not in proc.stderr
    assert f'skipping malformed line 2 in {config}' in proc.stderr
    assert FAKE_TOKEN not in proc.stdout + proc.stderr


def test_check_keeps_its_warnings_and_falls_back_to_warning(tmp_path: Path) -> None:
    missing = tmp_path / 'gone.env'
    proc = _run(
        tmp_path,
        '--surface',
        'direct',
        '--check',
        UNIFI_CONFIG=str(missing),
        UNIFI_MCP_LOG_LEVEL='LOUD',
    )
    assert proc.returncode == 1, proc.stderr
    assert json.loads(proc.stdout)['source'] == 'none'
    assert f'UNIFI_CONFIG={missing} is not a readable file' in proc.stderr
    assert "UNIFI_MCP_LOG_LEVEL='LOUD' is not a log level; using WARNING" in proc.stderr
    assert _debug_lines(proc.stderr) == []


def test_check_at_debug_level_logs_the_catalog_notes(tmp_path: Path) -> None:
    proc = _run(tmp_path, '--surface', 'direct', '--check', UNIFI_MCP_LOG_LEVEL='DEBUG')
    assert proc.returncode == 1, proc.stderr
    assert json.loads(proc.stdout)['surface'] == 'direct'
    notes = [line for line in _debug_lines(proc.stderr) if CATALOG_NOTE in line]
    assert notes, proc.stderr
    assert all('unifi_mapper.mcp.catalog:build_tool' in line for line in notes)


@pytest.mark.parametrize('flag', ['--version', '--help'])
def test_version_and_help_print_no_log_lines(tmp_path: Path, flag: str) -> None:
    proc = _run(tmp_path, flag, UNIFI_MCP_LOG_LEVEL='DEBUG')
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()
    assert proc.stderr == ''


def test_serving_logs_nothing_below_warning_by_default(tmp_path: Path) -> None:
    replies, stderr = _serve(tmp_path)
    init, listed = replies[:2]
    assert init['id'] == 1 and init['result']['serverInfo']['name'] == 'unifi-management'
    assert listed['id'] == 2 and len(listed['result']['tools']) > 4  # the direct surface
    assert all(reply['jsonrpc'] == '2.0' for reply in replies)
    assert _debug_lines(stderr) == []
    assert CATALOG_NOTE not in stderr


def test_serving_at_debug_level_logs_the_catalog_notes(tmp_path: Path) -> None:
    replies, stderr = _serve(tmp_path, UNIFI_MCP_LOG_LEVEL='DEBUG')
    assert [reply['id'] for reply in replies[:2]] == [1, 2]
    assert any(CATALOG_NOTE in line for line in _debug_lines(stderr)), stderr
