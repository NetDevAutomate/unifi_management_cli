"""T5 part 1: the stdio server as an MCP client sees it.

Subprocesses get an environment built from scratch (``isolated_env``), so they can't see
the real ~/.config, Keychain or 1Password; they run from ``tmp_path`` with a decoy CWD
``.env`` that must be ignored. The in-process print guard drives the real lifespan and
``stdio_server()`` over memory streams.
"""

import anyio
import json
import queue
import subprocess
import sys
import threading
import time
from mcp.server.stdio import stdio_server
from pathlib import Path
from tests.fixtures_unifi import FAKE_TOKEN
from tests.mcp.conftest import isolated_env
from typing import Any
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry


PRINTED = 'handler output that must not reach the protocol stream'
PROTOCOL = '2025-06-18'


def printing_handler() -> dict[str, str]:
    """A tool handler that prints, as some legacy helpers do."""
    print(PRINTED)
    return {'status': 'ok'}


def _server_env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / '.env').write_text(f'UNIFI_URL=https://192.0.2.1\nUNIFI_API_TOKEN={FAKE_TOKEN}\n')
    return isolated_env(tmp_path)


def _request(msg_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {'jsonrpc': '2.0', 'id': msg_id, 'method': method}
    if params is not None:
        body['params'] = params
    return json.dumps(body) + '\n'


INITIALIZE = _request(
    1,
    'initialize',
    {
        'protocolVersion': PROTOCOL,
        'capabilities': {},
        'clientInfo': {'name': 'smoke', 'version': '0'},
    },
)
INITIALIZED = json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n'


def test_check_under_isolated_env_reports_nothing_configured(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, '-m', 'unifi_mapper.mcp.server', '--check'],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_server_env(tmp_path),
        timeout=60,
    )
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert report['source'] == 'none'
    assert report['path'] is None
    assert not any(f['ready'] for f in report['families'].values())
    assert report['families']['controller']['fallback_chain'] == 'not probed'
    assert FAKE_TOKEN not in proc.stdout + proc.stderr
    assert all(Path(p).name != '.env' for p in report['tried'])


def _reader(stream: Any, lines: 'queue.Queue[str | None]') -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


def _next_line(lines: 'queue.Queue[str | None]', timeout: float = 30) -> str:
    line = lines.get(timeout=timeout)
    assert line is not None, 'server closed stdout early'
    return line


def test_stdio_handshake_stdout_purity_and_exit_on_eof(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, '-m', 'unifi_mapper.mcp.server'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
        env=_server_env(tmp_path),
    )
    assert proc.stdin and proc.stdout and proc.stderr
    lines: queue.Queue[str | None] = queue.Queue()
    seen: list[str] = []
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    try:
        proc.stdin.write(INITIALIZE)
        proc.stdin.flush()
        seen.append(_next_line(lines))
        init = json.loads(seen[-1])
        assert init['id'] == 1 and init['result']['serverInfo']['name'] == 'unifi-management'

        proc.stdin.write(INITIALIZED + _request(2, 'tools/list'))
        proc.stdin.flush()
        seen.append(_next_line(lines))
        listed = json.loads(seen[-1])
        assert listed['id'] == 2
        assert {t['name'] for t in listed['result']['tools']} >= {'search_tools', 'execute_tool'}

        closed_at = time.monotonic()
        proc.stdin.close()
        proc.wait(timeout=5)
        assert time.monotonic() - closed_at < 5
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    while (line := lines.get(timeout=5)) is not None:
        seen.append(line)
    stderr = proc.stderr.read()
    assert proc.returncode == 0, stderr
    for line in seen:
        assert json.loads(line)['jsonrpc'] == '2.0', line
    assert FAKE_TOKEN not in ''.join(seen) + stderr


class _MemoryStdin:
    """An async line iterator fed from a memory stream (what stdio_server reads)."""

    def __init__(self, receive: Any) -> None:
        self._receive = receive

    def __aiter__(self) -> '_MemoryStdin':
        return self

    async def __anext__(self) -> str:
        try:
            return await self._receive.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration from None


class _MemoryStdout:
    """Collects what stdio_server writes to the protocol stream."""

    def __init__(self, send: Any) -> None:
        self._send = send
        self._buffer = ''

    async def write(self, data: str) -> None:
        self._buffer += data
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            await self._send.send(line)

    async def flush(self) -> None:
        return None


async def test_print_in_a_handler_goes_to_stderr_not_the_protocol(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    manifests = tmp_path / 'manifests'
    manifests.mkdir()
    (manifests / 'fake.yaml').write_text(
        'category: fake\ntools:\n  shout:\n    module: tests.mcp.test_stdio_smoke\n'
        '    handler: printing_handler\n    description: prints\n'
    )
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(manifests))
    stdout_before = sys.stdout

    in_send, in_receive = anyio.create_memory_object_stream[str](10)
    out_send, out_receive = anyio.create_memory_object_stream[str](10)
    protocol_lines: list[str] = []

    async def _serve() -> None:
        async with stdio_server(
            stdin=_MemoryStdin(in_receive),  # type: ignore[arg-type]
            stdout=_MemoryStdout(out_send),  # type: ignore[arg-type]
        ) as (read, write):
            await server.mcp._mcp_server.run(
                read, write, server.mcp._mcp_server.create_initialization_options()
            )

    async def _next() -> dict[str, Any]:
        with anyio.fail_after(10):
            line = await out_receive.receive()
        protocol_lines.append(line)
        return json.loads(line)

    with anyio.fail_after(20):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_serve)
            await in_send.send(INITIALIZE)
            assert (await _next())['id'] == 1
            assert sys.stdout is sys.stderr  # the lifespan's guard is on while serving
            await in_send.send(INITIALIZED)
            call = {'name': 'execute_tool', 'arguments': {'tool_name': 'shout'}}
            await in_send.send(_request(3, 'tools/call', call))
            reply = await _next()
            assert reply['id'] == 3
            assert '"ok": true' in reply['result']['content'][0]['text']
            await in_send.aclose()

    assert sys.stdout is stdout_before
    captured = capsys.readouterr()
    assert PRINTED in captured.err
    assert PRINTED not in captured.out
    for line in protocol_lines:
        assert PRINTED not in line
        assert json.loads(line)['jsonrpc'] == '2.0'
