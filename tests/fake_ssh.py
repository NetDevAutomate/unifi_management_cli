"""A fake ``asyncssh.connect`` shared by every package's SSH tests.

The root ``tests/conftest.py`` bans a real ``asyncssh.connect`` in every test
(``_no_live_ssh``). A test that needs SSH installs ``FakeSSH`` over the ban with
``monkeypatch.setattr(asyncssh, 'connect', FakeSSH())``; the later patch wins. Each
connection records every command it is asked to run and answers ``ping`` and ``iperf3`` with
canned output, or, given ``replies``, each program (the command's first word) with its own;
with ``replies`` a program they do not name is an ``AssertionError`` naming the command, so a
test cannot pass on a command it never scripted (issue 076 item 16).
"""

import json
import shlex
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

    def __init__(self, stdout: str, exit_status: int = 0, stderr: str = '') -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


# A reply: the stdout, or (stdout, stderr, exit status).
Reply = str | tuple[str, str, int]


class FakeConnection:
    """What ``asyncssh.connect`` returns: records every command it is asked to run.

    With ``replies`` (a dict, even an empty one) only the programs it names are answered;
    with None, ``ping`` and ``iperf3`` get the canned defaults.
    """

    def __init__(self, replies: dict[str, Reply] | None = None) -> None:
        self.commands: list[str] = []
        self.replies = replies

    async def run(self, command: str, check: bool = False) -> FakeProcess:
        self.commands.append(command)
        if self.replies is None:
            return FakeProcess(IPERF3_OK if command.startswith('iperf3 ') else PING_OK)
        program = shlex.split(command)[0]
        if program not in self.replies:
            raise AssertionError(f'the SSH fake has no reply for {program!r}: {command}')
        reply = self.replies[program]
        if isinstance(reply, tuple):
            return FakeProcess(reply[0], exit_status=reply[2], stderr=reply[1])
        return FakeProcess(reply)

    async def __aenter__(self) -> 'FakeConnection':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSSH:
    """Stands in for ``asyncssh.connect``; one connection per call."""

    def __init__(self, replies: dict[str, Reply] | None = None) -> None:
        self.connects: list[tuple[str, dict[str, Any]]] = []
        self.connections: list[FakeConnection] = []
        self.replies = replies

    async def __call__(self, host: str, **kwargs: Any) -> FakeConnection:
        self.connects.append((host, kwargs))
        self.connections.append(FakeConnection(self.replies))
        return self.connections[-1]

    @property
    def commands(self) -> list[str]:
        return [cmd for conn in self.connections for cmd in conn.commands]
