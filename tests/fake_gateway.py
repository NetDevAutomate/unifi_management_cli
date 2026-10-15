"""A real asyncssh gateway on one end of a Unix socket pair, shared by the SSH tests.

``tests/analysis/test_gateway_ssh_handshake.py`` proves that asyncssh itself refuses an
untrusted host key before any password (issue 038); ``tests/mcp/test_active_probes.py`` runs
the gateway probes through the MCP runner against the same server (issue 092). The server
counts every password it is offered and, given ``replies``, answers each command by its
program (its first word): stdout, or ``(stdout, stderr, exit status)``. A program the replies
do not name exits 127 with ``command not found``, so a test cannot pass on a command it never
scripted. The suite bans TCP, not ``AF_UNIX``, so no socket leaves the process.
"""

from __future__ import annotations

import asyncio
import asyncssh
import shlex
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path


# The real asyncssh.connect, bound at import: the root conftest's autouse fixture replaces the
# module attribute in every test, and a test connects through this one to its own socket.
REAL_CONNECT = asyncssh.connect
HOST = 'gateway.test'
USER = 'root'
PASSWORD = 'fixture-ssh-password-not-real'  # pragma: allowlist secret

# A reply: the stdout, or (stdout, stderr, exit status).
Reply = str | tuple[str, str, int]


class CountingServer(asyncssh.SSHServer):
    """Accepts ``USER`` with ``PASSWORD``; counts every password it is offered."""

    attempts: list[str]

    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        type(self).attempts.append(password)
        return username == USER and password == PASSWORD


@asynccontextmanager
async def serve(
    host_key: asyncssh.SSHKey,
    replies: dict[str, Reply] | None = None,
    commands: list[str] | None = None,
) -> AsyncIterator[tuple[socket.socket, list[str]]]:
    """A real asyncssh server on one end of a socket pair; yields the client end.

    Args:
        host_key: The key the server presents.
        replies: Program -> reply, for exec requests; None runs no command.
        commands: Receives every command line the client runs, in order.

    Yields:
        ``(client socket, passwords offered)``.
    """
    attempts: list[str] = []
    CountingServer.attempts = attempts
    seen = commands if commands is not None else []

    async def _process(process: asyncssh.SSHServerProcess[str]) -> None:
        command = process.command or ''
        seen.append(command)
        program = shlex.split(command)[0] if command.strip() else ''
        reply = (replies or {}).get(program, ('', f'sh: {program}: command not found\n', 127))
        stdout, stderr, status = (reply, '', 0) if isinstance(reply, str) else reply
        process.stdout.write(stdout)
        process.stderr.write(stderr)
        process.exit(status)

    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    conn_task = asyncio.ensure_future(
        asyncssh.run_server(
            server_sock,
            server_factory=CountingServer,
            server_host_keys=[host_key],
            process_factory=_process if replies is not None else None,
        )
    )
    try:
        yield client_sock, attempts
    finally:
        conn_task.cancel()
        try:
            conn = await conn_task
            conn.close()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the handshake may have failed
            pass
        server_sock.close()
        client_sock.close()


def write_known_hosts(path: Path, key: asyncssh.SSHKey | None, host: str = HOST) -> Path:
    """Write a known-hosts file trusting ``key`` for ``host`` (empty for None); return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{host} {key.export_public_key().decode().strip()}\n' if key else '')
    return path
