"""asyncssh itself refuses an untrusted gateway host key before any password (issue 038).

``tests/analysis/test_gateway_ssh.py`` pins what ``gateway_session`` passes to
``asyncssh.connect`` with a stub, which proves the argument and the error mapping but not the
library's ordering. Here a real asyncssh server runs over a Unix socket pair (the suite bans TCP,
not ``AF_UNIX``), counts every password it is offered, and the real ``asyncssh.connect`` is called
with the arguments ``gateway_session`` uses (``gateway_connect_options``) and a temporary
known-hosts file. A missing or changed key must end the handshake with
``HostKeyNotVerifiable`` and zero passwords received; a trusted key authenticates.
"""

from __future__ import annotations

import asyncio
import asyncssh
import pytest
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.gateway_ssh import gateway_connect_options


REAL_CONNECT = asyncssh.connect  # bound before the autouse fixture replaces the module attribute
HOST = 'gateway.test'
USER = 'root'
PASSWORD = 'fixture-ssh-password-not-real'  # pragma: allowlist secret


class _CountingServer(asyncssh.SSHServer):
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
async def _server(host_key: asyncssh.SSHKey) -> AsyncIterator[tuple[socket.socket, list[str]]]:
    """A real asyncssh server on one end of a socket pair; yields the client end."""
    attempts: list[str] = []
    _CountingServer.attempts = attempts
    server_sock, client_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    conn_task = asyncio.ensure_future(
        asyncssh.run_server(
            server_sock, server_factory=_CountingServer, server_host_keys=[host_key]
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


def _known_hosts(tmp_path: Path, key: asyncssh.SSHKey | None) -> Path:
    path = tmp_path / 'known_hosts'
    path.write_text(f'{HOST} {key.export_public_key().decode().strip()}\n' if key else '')
    return path


async def _connect(sock: socket.socket, known_hosts: Path) -> Any:
    options = gateway_connect_options(USER, PASSWORD, known_hosts=str(known_hosts))
    return await REAL_CONNECT(HOST, sock=sock, **options)


@pytest.fixture(scope='module')
def keys() -> tuple[asyncssh.SSHKey, asyncssh.SSHKey]:
    return asyncssh.generate_private_key('ssh-ed25519'), asyncssh.generate_private_key(
        'ssh-ed25519'
    )


async def test_a_missing_host_key_ends_the_handshake_before_any_password(
    tmp_path: Path, keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey]
) -> None:
    gateway_key, _ = keys
    async with _server(gateway_key) as (sock, attempts):
        with pytest.raises(asyncssh.HostKeyNotVerifiable):
            await asyncio.wait_for(_connect(sock, _known_hosts(tmp_path, None)), 10)
    assert attempts == []


async def test_a_changed_host_key_ends_the_handshake_before_any_password(
    tmp_path: Path, keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey]
) -> None:
    gateway_key, impostor_key = keys
    async with _server(impostor_key) as (sock, attempts):
        with pytest.raises(asyncssh.HostKeyNotVerifiable):
            await asyncio.wait_for(_connect(sock, _known_hosts(tmp_path, gateway_key)), 10)
    assert attempts == []


async def test_a_trusted_host_key_authenticates_with_the_password(
    tmp_path: Path, keys: tuple[asyncssh.SSHKey, asyncssh.SSHKey]
) -> None:
    gateway_key, _ = keys
    async with _server(gateway_key) as (sock, attempts):
        conn = await asyncio.wait_for(_connect(sock, _known_hosts(tmp_path, gateway_key)), 10)
        conn.close()
        await conn.wait_closed()
    assert attempts == [PASSWORD]
