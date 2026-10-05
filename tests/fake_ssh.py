"""A fake ``asyncssh.connect`` shared by every package's SSH tests.

The root ``tests/conftest.py`` bans a real ``asyncssh.connect`` in every test
(``_no_live_ssh``). A test that needs SSH installs ``FakeSSH`` over the ban with
``monkeypatch.setattr(asyncssh, 'connect', FakeSSH())``; the later patch wins. Each
connection records every command it is asked to run and answers ``ping`` and ``iperf3`` with
canned output.
"""

import json
from typing import Any


PING_OK = (
    '3 packets transmitted, 3 received, 0% packet loss\n'
    'rtt min/avg/max/mdev = 0.100/0.200/0.300/0.050 ms\n'
)
IPERF3_OK = json.dumps(
    {
        'start': {'test_start': {'num_streams': 1}},
        'end': {
            'sum_sent': {'retransmits': 0},
            'sum_received': {'bits_per_second': 9.4e9, 'bytes': 11_750_000_000},
        },
    }
)


class FakeProcess:
    """What ``SSHClientConnection.run`` returns."""

    def __init__(self, stdout: str, exit_status: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ''
        self.exit_status = exit_status


class FakeConnection:
    """What ``asyncssh.connect`` returns: records every command it is asked to run."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def run(self, command: str, check: bool = False) -> FakeProcess:
        self.commands.append(command)
        return FakeProcess(IPERF3_OK if command.startswith('iperf3 ') else PING_OK)

    async def __aenter__(self) -> 'FakeConnection':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSSH:
    """Stands in for ``asyncssh.connect``; one connection per call."""

    def __init__(self) -> None:
        self.connects: list[tuple[str, dict[str, Any]]] = []
        self.connections: list[FakeConnection] = []

    async def __call__(self, host: str, **kwargs: Any) -> FakeConnection:
        self.connects.append((host, kwargs))
        self.connections.append(FakeConnection())
        return self.connections[-1]

    @property
    def commands(self) -> list[str]:
        return [cmd for conn in self.connections for cmd in conn.commands]
