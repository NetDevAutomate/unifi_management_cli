"""The two CLI-only SSH commands check every value before it reaches a remote shell.

``diagnose latency-matrix`` and ``diagnose bandwidth`` run ``ping`` and ``iperf3`` on the
gateway, normally as root, with addresses from the controller or the command line. Every
address must parse with ``ipaddress`` (no IPv6 zone id, since ``ipaddress`` accepts any text
there), every number must be a bounded positive int, and the command line is shell-quoted
too. A bad bandwidth target is refused before anything connects; a bad latency target is
skipped and reported while the others are pinged.

The SSH password comes only from ``UNIFI_SSH_PASSWORD``: without it neither command makes
any request, and ``UNIFI_PASSWORD`` (the UniFi OS login) is never sent to root SSH.

Everything here is offline: ``asyncssh.connect`` and the controller client are fakes, and
the autouse fixture in ``tests/analysis/conftest.py`` isolates the environment.
"""

import asyncssh
import json
import pytest
from collections.abc import Callable
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.analysis import bandwidth_test, latency_matrix
from unifi_mapper.analysis.gateway_ssh import (
    SSH_PASSWORD_MISSING,
    SSH_PASSWORD_SUGGESTION,
    require_bounded_int,
    require_ip,
    ssh_login,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
FAKE_SSH_PW = 'FAKE-SSH-PW-MUST-NOT-APPEAR'  # pragma: allowlist secret
INJECTED = '192.0.2.1; reboot'
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


class FakeUniFiClient:
    """Stands in for the controller client the latency matrix reads targets from."""

    def __init__(self, devices: list[dict], clients: list[dict]) -> None:
        self._devices, self._clients = devices, clients

    async def __aenter__(self) -> 'FakeUniFiClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_devices(self) -> list[dict]:
        return self._devices

    async def get_clients(self) -> list[dict]:
        return self._clients


def _forbidden(what: str) -> Callable[..., Any]:
    def _fail(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError(f'{what} was called')

    return _fail


@pytest.fixture(autouse=True)
def controller_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', FAKE_SSH_PW)


@pytest.fixture
def ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH()
    monkeypatch.setattr(asyncssh, 'connect', fake)
    return fake


@pytest.fixture
def no_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncssh, 'connect', _forbidden('asyncssh.connect'))


@pytest.fixture
def no_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(latency_matrix, 'UniFiClient', _forbidden('UniFiClient'))


@pytest.fixture
def ui_login_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A UniFi OS username and password are configured, UNIFI_SSH_PASSWORD is not."""
    monkeypatch.setenv('UNIFI_USERNAME', 'admin')
    monkeypatch.setenv('UNIFI_PASSWORD', FAKE_PW)
    monkeypatch.delenv('UNIFI_SSH_PASSWORD')


def _controller(monkeypatch: pytest.MonkeyPatch, devices: list[dict], clients: list[dict]):
    monkeypatch.setattr(latency_matrix, 'UniFiClient', lambda: FakeUniFiClient(devices, clients))


def _assert_ssh_password_missing(error: ToolError) -> None:
    assert error.error_code == ErrorCodes.CONFIG_MISSING
    assert error.message == SSH_PASSWORD_MISSING
    assert error.message.startswith('UNIFI_SSH_PASSWORD is not set.')
    assert 'UNIFI_PASSWORD (the UniFi OS login) is never sent over SSH' in error.message
    assert error.suggestion == SSH_PASSWORD_SUGGESTION
    assert 'Enable SSH in UniFi OS' in error.suggestion
    assert 'UNIFI_SSH_USERNAME as well if the SSH user is not root' in error.suggestion
    assert FAKE_PW not in str(error)


def _flat(text: str) -> str:
    """Undo Rich's wrapping at the CliRunner's 80 columns."""
    return ' '.join(text.split())


# --- the checks --------------------------------------------------------------------------


@pytest.mark.parametrize('value', ['192.0.2.1', '2001:db8::1', '2001:DB8::1', '::1'])
def test_require_ip_returns_a_valid_address_unchanged(value: str) -> None:
    assert require_ip(value) == value


@pytest.mark.parametrize(
    'value',
    [
        INJECTED,
        '$(reboot)',
        '192.0.2.1 && reboot',
        '-c 1 192.0.2.1',
        ' 192.0.2.1',
        '192.0.2.1\n',
        '',
        'fe80::1%eth0; reboot',  # ipaddress parses this: the zone id is free text
        'fe80::1%br0',
        None,
        3221225985,  # ipaddress takes an int as an address; a command line mustn't
    ],
)
def test_require_ip_refuses_anything_else(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_ip(value)
    assert exc.value.error_code == ErrorCodes.INVALID_IP


@pytest.mark.parametrize('value', [1, 3, 100])
def test_require_bounded_int_accepts_the_range(value: int) -> None:
    assert require_bounded_int('ping count', value, 1, 100) == value


@pytest.mark.parametrize('value', [0, -1, 101, True, False, '3', '3; reboot', 3.0, None])
def test_require_bounded_int_refuses_anything_else(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_bounded_int('ping count', value, 1, 100)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID
    assert 'ping count must be a whole number from 1 to 100' in exc.value.message


# --- diagnose bandwidth ------------------------------------------------------------------


@pytest.mark.usefixtures('no_ssh')
async def test_bandwidth_refuses_an_injected_target_before_connecting() -> None:
    with pytest.raises(ToolError) as exc:
        await bandwidth_test.run_bandwidth_test(INJECTED)
    assert exc.value.error_code == ErrorCodes.INVALID_IP
    assert repr(INJECTED) in exc.value.message


@pytest.mark.usefixtures('no_ssh')
@pytest.mark.parametrize(('duration', 'parallel'), [(0, 1), (86401, 1), (10, 0), (10, 129)])
async def test_bandwidth_refuses_numbers_out_of_range_before_connecting(
    duration: int, parallel: int
) -> None:
    with pytest.raises(ToolError) as exc:
        await bandwidth_test.run_bandwidth_test('192.0.2.10', duration, parallel=parallel)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


@pytest.mark.parametrize(
    ('target', 'duration', 'parallel', 'reverse'),
    [('192.0.2.10', 10, 1, False), ('2001:db8::10', 5, 4, True)],
)
async def test_bandwidth_command_is_unchanged_for_valid_input(
    ssh: FakeSSH, target: str, duration: int, parallel: int, reverse: bool
) -> None:
    result = await bandwidth_test.run_bandwidth_test(target, duration, reverse, parallel)
    old = f'iperf3 -c {target} -t {duration} -P {parallel} -J' + (' -R' if reverse else '')
    assert ssh.commands == [old]
    assert result['status'] == 'OK' and result['target'] == target
    assert [host for host, _ in ssh.connects] == ['192.0.2.1']


def test_cli_bandwidth_refuses_an_injected_target_before_config_or_ssh(
    monkeypatch: pytest.MonkeyPatch, no_ssh: None
) -> None:
    monkeypatch.setattr(typer_cli, 'load_env_from_config', _forbidden('load_env_from_config'))
    result = runner.invoke(app, ['diagnose', 'bandwidth', INJECTED])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # a clean exit, not a traceback
    assert '[INVALID_IP]' in result.stderr
    assert f'{INJECTED!r} is not an IPv4 or IPv6 address' in result.stderr
    assert 'Bandwidth Test' not in result.output  # refused before anything ran


def test_cli_bandwidth_reports_an_ssh_failure_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError('Connection refused')

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr(asyncssh, 'connect', _refused)
    result = runner.invoke(app, ['diagnose', 'bandwidth', '192.0.2.10', '--bidir'])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert '[CONTROLLER_UNREACHABLE]' in result.stderr
    assert 'Download' not in result.output  # stopped at the first failure
    assert FAKE_SSH_PW not in result.output


# --- diagnose latency-matrix -------------------------------------------------------------


async def test_latency_skips_and_reports_invalid_targets_and_pings_the_rest(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH
) -> None:
    devices = [
        {'ip': INJECTED, 'name': 'Evil', 'mac': '02:00:00:00:00:01'},
        {'ip': '192.0.2.10', 'name': 'Switch', 'mac': '02:00:00:00:00:02'},
    ]
    clients = [
        {'ip': '2001:db8::10', 'name': 'NAS', 'mac': '02:00:00:00:00:51'},
        {'ip': 'fe80::1%br0; reboot', 'name': 'Zoned', 'mac': '02:00:00:00:00:52'},
    ]
    _controller(monkeypatch, devices, clients)
    report = await latency_matrix.run_latency_matrix()
    assert ssh.commands == ['ping -c 3 -W 2 192.0.2.10', 'ping -c 3 -W 2 2001:db8::10']
    assert [r.ip for r in report.results] == ['192.0.2.10', '2001:db8::10']
    assert report.targets_total == report.targets_reachable == 2
    skipped = {s.name: s for s in report.skipped_targets}
    assert sorted(skipped) == ['Evil', 'Zoned']
    assert skipped['Evil'].ip == INJECTED and skipped['Evil'].target_type == 'device'
    assert 'is not an IPv4 or IPv6 address' in skipped['Evil'].reason
    assert 'zone id' in skipped['Zoned'].reason and skipped['Zoned'].target_type == 'client'


@pytest.mark.usefixtures('no_ssh')
async def test_latency_with_no_valid_target_never_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller(monkeypatch, [{'ip': INJECTED, 'name': 'Evil'}], [])
    with pytest.raises(ToolError) as exc:
        await latency_matrix.run_latency_matrix()
    assert exc.value.error_code == ErrorCodes.NO_DATA
    assert '1 skipped: Evil' in exc.value.message


@pytest.mark.usefixtures('no_ssh', 'no_controller')
@pytest.mark.parametrize(('count', 'timeout'), [(0, 2), (101, 2), (3, 0), (3, 61), (True, 2)])
async def test_latency_refuses_numbers_out_of_range_before_any_request(
    count: int, timeout: int
) -> None:
    with pytest.raises(ToolError) as exc:
        await latency_matrix.run_latency_matrix(ping_count=count, timeout=timeout)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


@pytest.mark.parametrize('ip', ['192.0.2.10', '2001:db8::10'])
def test_ping_command_is_unchanged_for_valid_input(ip: str) -> None:
    assert latency_matrix._ping_command(ip, 5, 1) == f'ping -c 5 -W 1 {ip}'


def test_cli_latency_matrix_lists_the_skipped_targets(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH
) -> None:
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    _controller(
        monkeypatch,
        [{'ip': INJECTED, 'name': 'Evil'}, {'ip': '192.0.2.10', 'name': 'Switch'}],
        [],
    )
    result = runner.invoke(app, ['diagnose', 'latency-matrix', '--devices-only'])
    assert result.exit_code == 0, result.output
    assert 'Not pinged, no valid IP (1)' in result.output
    assert f'Evil: {INJECTED!r} is not an IPv4 or IPv6 address' in result.output
    assert ssh.commands == ['ping -c 3 -W 2 192.0.2.10']


# --- the SSH login: UNIFI_SSH_PASSWORD only ----------------------------------------------


def test_ssh_login_defaults_the_username_to_root() -> None:
    assert ssh_login() == ('root', FAKE_SSH_PW)


@pytest.mark.parametrize(('username', 'expected'), [('admin', 'admin'), ('', 'root')])
def test_ssh_login_takes_unifi_ssh_username(
    monkeypatch: pytest.MonkeyPatch, username: str, expected: str
) -> None:
    monkeypatch.setenv('UNIFI_SSH_USERNAME', username)
    assert ssh_login() == (expected, FAKE_SSH_PW)


@pytest.mark.usefixtures('ui_login_only')
@pytest.mark.parametrize('password', [None, ''])
def test_ssh_login_never_falls_back_to_the_ui_password(
    monkeypatch: pytest.MonkeyPatch, password: str | None
) -> None:
    if password is not None:
        monkeypatch.setenv('UNIFI_SSH_PASSWORD', password)
    with pytest.raises(ToolError) as exc:
        ssh_login()
    _assert_ssh_password_missing(exc.value)


@pytest.mark.usefixtures('ui_login_only', 'no_ssh')
async def test_bandwidth_without_ssh_password_never_connects() -> None:
    with pytest.raises(ToolError) as exc:
        await bandwidth_test.run_bandwidth_test('192.0.2.10')
    _assert_ssh_password_missing(exc.value)


@pytest.mark.usefixtures('ui_login_only', 'no_ssh', 'no_controller')
async def test_latency_without_ssh_password_makes_no_request() -> None:
    with pytest.raises(ToolError) as exc:
        await latency_matrix.run_latency_matrix()
    _assert_ssh_password_missing(exc.value)


@pytest.mark.parametrize(('username', 'expected'), [(None, 'root'), ('admin', 'admin')])
async def test_bandwidth_connects_with_exactly_the_ssh_login(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH, username: str | None, expected: str
) -> None:
    monkeypatch.setenv('UNIFI_USERNAME', 'ui-admin')
    monkeypatch.setenv('UNIFI_PASSWORD', FAKE_PW)
    if username is not None:
        monkeypatch.setenv('UNIFI_SSH_USERNAME', username)
    await bandwidth_test.run_bandwidth_test('192.0.2.10')
    [(host, kwargs)] = ssh.connects
    assert (host, kwargs['username'], kwargs['password']) == ('192.0.2.1', expected, FAKE_SSH_PW)


@pytest.mark.parametrize(('username', 'expected'), [(None, 'root'), ('admin', 'admin')])
async def test_latency_connects_with_exactly_the_ssh_login(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH, username: str | None, expected: str
) -> None:
    monkeypatch.setenv('UNIFI_USERNAME', 'ui-admin')
    monkeypatch.setenv('UNIFI_PASSWORD', FAKE_PW)
    if username is not None:
        monkeypatch.setenv('UNIFI_SSH_USERNAME', username)
    _controller(monkeypatch, [{'ip': '192.0.2.10', 'name': 'Switch'}], [])
    await latency_matrix.run_latency_matrix(include_clients=False)
    [(host, kwargs)] = ssh.connects
    assert (host, kwargs['username'], kwargs['password']) == ('192.0.2.1', expected, FAKE_SSH_PW)


@pytest.mark.usefixtures('ui_login_only', 'no_ssh', 'no_controller')
@pytest.mark.parametrize(
    'args', [['diagnose', 'bandwidth', '192.0.2.10'], ['diagnose', 'latency-matrix']]
)
def test_cli_without_ssh_password_says_what_to_set(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    output = _flat(result.output)
    assert f'[CONFIG_MISSING] {SSH_PASSWORD_MISSING}' in output
    assert SSH_PASSWORD_SUGGESTION in output
    assert FAKE_PW not in result.output
