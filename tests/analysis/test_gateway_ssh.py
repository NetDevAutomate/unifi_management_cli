"""The two CLI-only SSH commands check every value before it reaches a remote shell.

``diagnose latency-matrix`` and ``diagnose bandwidth`` run ``ping`` and ``iperf3`` on the
gateway, normally as root, with addresses from the controller or the command line. Every
address must parse with ``ipaddress`` (no IPv6 zone id, since ``ipaddress`` accepts any text
there), every number must be a bounded positive int, and the command line is shell-quoted
too. A bad bandwidth target is refused before anything connects; a bad latency target is
skipped and reported while the others are pinged.

The SSH password comes only from ``UNIFI_SSH_PASSWORD``: without it neither command makes
any request, and ``UNIFI_PASSWORD`` (the UniFi OS login) is never sent to root SSH.

Every session and command goes through ``gateway_ssh.gateway_session`` and
``run_gateway_command``: an argv list, shell-quoted, with a timeout each caller states.

Everything here is offline: ``asyncssh.connect`` and the controller client are fakes
(``tests/fake_ssh.py``; the root conftest bans a real connect), and the autouse fixture in
``tests/analysis/conftest.py`` isolates the environment.
"""

import ast
import asyncio
import asyncssh
import pytest
from collections.abc import Callable
from pathlib import Path
from tests.fake_ssh import FakeConnection, FakeSSH
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.analysis import bandwidth_test, latency_matrix
from unifi_mapper.analysis.gateway_ssh import (
    GATEWAY_KNOWN_HOSTS,
    SSH_CONNECT_SUGGESTION,
    SSH_CONNECT_TIMEOUT,
    SSH_PASSWORD_MISSING,
    SSH_PASSWORD_SUGGESTION,
    GatewayResult,
    as_text,
    check_exit_status,
    gateway_session,
    require_bounded_float,
    require_bounded_int,
    require_hostname,
    require_http_url,
    require_interface_name,
    require_ip,
    run_gateway_command,
    ssh_login,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
FAKE_SSH_PW = 'FAKE-SSH-PW-MUST-NOT-APPEAR'  # pragma: allowlist secret
INJECTED = '192.0.2.1; reboot'


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


# --- the session and command helpers -----------------------------------------------------

SRC = Path(__file__).resolve().parents[2] / 'src' / 'unifi_mapper'


class _Completed:
    """An ``SSHCompletedProcess`` with chosen output and exit status."""

    def __init__(self, stdout: object = '', stderr: object = '', exit_status: int | None = 0):
        self.stdout, self.stderr, self.exit_status = stdout, stderr, exit_status


class _ScriptedConnection:
    """Records each command and answers with one canned result, after ``delay`` seconds."""

    def __init__(self, result: _Completed | None = None, delay: float = 0.0) -> None:
        self.result = result or _Completed()
        self.delay = delay
        self.commands: list[str] = []

    async def run(self, command: str, check: bool = False) -> _Completed:
        self.commands.append(command)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(None, ''), (b'hello', 'hello'), (b'\xff\xfe', '\ufffd\ufffd'), ('text', 'text')],
)
def test_as_text_coerces_process_output(value: object, expected: str) -> None:
    assert as_text(value) == expected


def test_the_two_callers_share_as_text_instead_of_copies() -> None:
    assert not hasattr(latency_matrix, '_as_text')
    assert not hasattr(bandwidth_test, '_as_text')


def _asyncssh_connect_uses(tree: ast.AST) -> list[int]:
    """Line numbers that reach ``asyncssh.connect``: the attribute, or an import of the name."""
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == 'connect'
            and isinstance(node.value, ast.Name)
            and node.value.id == 'asyncssh'
        ):
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.ImportFrom)
            and (node.module or '').split('.')[0] == 'asyncssh'
            and any(alias.name in {'connect', '*'} for alias in node.names)
        ):
            lines.append(node.lineno)
    return lines


def test_asyncssh_connect_is_called_only_in_gateway_ssh() -> None:
    callers = [
        f'{path.relative_to(SRC)}:{line}'
        for path in sorted(SRC.rglob('*.py'))
        for line in _asyncssh_connect_uses(ast.parse(path.read_text(encoding='utf-8')))
    ]
    assert [c.split(':')[0] for c in callers] == ['analysis/gateway_ssh.py'], callers


def test_the_only_door_scan_sees_an_imported_connect() -> None:
    sample = (
        'import asyncssh\n'
        'from asyncssh import connect\n'
        'from asyncssh.connection import connect as dial\n'
        'from asyncssh import *\n'
        'from asyncssh import SSHClientConnection\n'
        'asyncssh.connect("192.0.2.1")\n'
    )
    assert _asyncssh_connect_uses(ast.parse(sample)) == [2, 3, 4, 6]


async def test_a_real_connect_fails_in_every_test() -> None:
    with pytest.raises(AssertionError, match='live SSH in a test'):
        await asyncssh.connect('192.0.2.1')


async def test_gateway_session_logs_in_with_the_ssh_login_and_closes(ssh: FakeSSH) -> None:
    async with gateway_session() as conn:
        assert conn is ssh.connections[0]
    [(host, kwargs)] = ssh.connects
    assert host == '192.0.2.1'  # Credentials.from_env().host, from UNIFI_URL
    assert kwargs == {
        'username': 'root',
        'password': FAKE_SSH_PW,
        'known_hosts': GATEWAY_KNOWN_HOSTS,
        'client_keys': [],
        'preferred_auth': 'keyboard-interactive,password',
    }
    assert GATEWAY_KNOWN_HOSTS is None  # issue 038: the one line that turns on checking


async def test_gateway_session_takes_an_explicit_host(ssh: FakeSSH) -> None:
    async with gateway_session('198.51.100.7'):
        pass
    assert [host for host, _ in ssh.connects] == ['198.51.100.7']


@pytest.mark.usefixtures('ui_login_only', 'no_ssh')
async def test_gateway_session_without_ssh_password_never_connects() -> None:
    with pytest.raises(ToolError) as exc:
        async with gateway_session('192.0.2.1'):
            pass
    _assert_ssh_password_missing(exc.value)


async def test_gateway_session_connect_failure_is_redacted_with_the_given_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError(f'auth failed for password={FAKE_SSH_PW}')

    monkeypatch.setattr(asyncssh, 'connect', _refused)
    with pytest.raises(ToolError) as exc:
        async with gateway_session('192.0.2.1', suggestion='check the thing'):
            pass
    assert exc.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert exc.value.message.startswith('SSH connection to 192.0.2.1 failed: auth failed for')
    assert FAKE_SSH_PW not in str(exc.value)
    assert exc.value.suggestion == 'check the thing'


async def test_gateway_session_suggests_the_ssh_settings_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError('Connection refused')

    monkeypatch.setattr(asyncssh, 'connect', _refused)
    with pytest.raises(ToolError) as exc:
        async with gateway_session('192.0.2.1'):
            pass
    assert exc.value.suggestion == SSH_CONNECT_SUGGESTION


async def test_run_gateway_command_quotes_every_argument() -> None:
    conn = _ScriptedConnection(_Completed(stdout='ok'))
    result = await run_gateway_command(conn, ['echo', 'a b', '; reboot', '$(id)'], timeout=5)
    assert conn.commands == ["echo 'a b' '; reboot' '$(id)'"]
    assert result == GatewayResult(stdout='ok', stderr='', exit_status=0)


async def test_run_gateway_command_normalises_output_and_a_missing_exit_status() -> None:
    conn = _ScriptedConnection(_Completed(stdout=b'out', stderr=b'err', exit_status=None))
    result = await run_gateway_command(conn, ['true'], timeout=5)
    assert result == GatewayResult(stdout='out', stderr='err', exit_status=-1)


async def test_run_gateway_command_times_out_naming_only_the_program_and_bound() -> None:
    conn = _ScriptedConnection(delay=1.0)
    with pytest.raises(ToolError) as exc:
        await run_gateway_command(conn, ['sleep', 'secret-arg-10'], timeout=0.05)
    assert exc.value.error_code == ErrorCodes.TIMEOUT
    assert exc.value.message == 'sleep timed out after 0.05s on the gateway'
    assert 'secret-arg-10' not in str(exc.value)


async def test_run_gateway_command_requires_a_timeout_and_a_program() -> None:
    conn = _ScriptedConnection()
    with pytest.raises(TypeError):
        await run_gateway_command(conn, ['true'])  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        await run_gateway_command(conn, [], timeout=1)
    assert conn.commands == []


@pytest.mark.parametrize('argv', ['reboot', b'reboot'])
async def test_run_gateway_command_refuses_a_string_for_argv(argv: object) -> None:
    # shlex.join('reboot') would run `r` with five one-letter arguments.
    conn = _ScriptedConnection()
    with pytest.raises(TypeError, match='argv must be a list'):
        await run_gateway_command(conn, argv, timeout=1)  # type: ignore[arg-type]
    assert conn.commands == []


# --- each caller's bound and error mapping -----------------------------------------------


def _recording_runner(calls: list[tuple[list[str], float]], error: ToolError | None = None):
    async def _run(conn: object, argv: list[str], *, timeout: float) -> GatewayResult:
        calls.append((list(argv), timeout))
        if error is not None:
            raise error
        return GatewayResult(stdout=PING_LINES, stderr='', exit_status=0)

    return _run


PING_LINES = '3 packets transmitted, 3 received, 0% packet loss\n'
TIMED_OUT = ToolError(message='x timed out', error_code=ErrorCodes.TIMEOUT)


@pytest.mark.parametrize(('count', 'timeout', 'bound'), [(3, 2, 11), (1, 1, 6), (100, 60, 6005)])
async def test_latency_bounds_each_ping_by_count_times_timeout_plus_five(
    monkeypatch: pytest.MonkeyPatch, count: int, timeout: int, bound: int
) -> None:
    calls: list[tuple[list[str], float]] = []
    monkeypatch.setattr(latency_matrix, 'run_gateway_command', _recording_runner(calls))
    target = {'ip': '192.0.2.10', 'name': 'Switch', 'type': 'device'}
    await latency_matrix._ping_single(object(), target, count, timeout)  # type: ignore[arg-type]
    assert calls == [(['ping', '-c', str(count), '-W', str(timeout), '192.0.2.10'], bound)]


async def test_latency_turns_a_ping_timeout_into_an_unreachable_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], float]] = []
    monkeypatch.setattr(latency_matrix, 'run_gateway_command', _recording_runner(calls, TIMED_OUT))
    target = {'ip': '192.0.2.10', 'name': 'Switch', 'type': 'device'}
    result = await latency_matrix._ping_single(object(), target, 3, 2)  # type: ignore[arg-type]
    assert (result.reachable, result.packet_loss, result.ip) == (False, 100.0, '192.0.2.10')


async def test_latency_connect_failure_names_the_host_with_its_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError('Connection refused')

    monkeypatch.setattr(asyncssh, 'connect', _refused)
    _controller(monkeypatch, [{'ip': '192.0.2.10', 'name': 'Switch'}], [])
    with pytest.raises(ToolError) as exc:
        await latency_matrix.run_latency_matrix(include_clients=False)
    assert exc.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert exc.value.message == 'SSH connection to 192.0.2.1 failed: Connection refused'
    assert exc.value.suggestion == SSH_CONNECT_SUGGESTION


@pytest.mark.parametrize(('duration', 'bound'), [(10, 25), (1, 16)])
async def test_bandwidth_bounds_iperf3_by_duration_plus_fifteen(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH, duration: int, bound: int
) -> None:
    calls: list[tuple[list[str], float]] = []
    monkeypatch.setattr(bandwidth_test, 'run_gateway_command', _recording_runner(calls))
    await bandwidth_test.run_bandwidth_test('192.0.2.10', duration)
    [(argv, timeout)] = calls
    assert argv[0] == 'iperf3' and timeout == bound


async def test_bandwidth_maps_a_timeout_to_todays_iperf3_error(
    monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH
) -> None:
    calls: list[tuple[list[str], float]] = []
    monkeypatch.setattr(bandwidth_test, 'run_gateway_command', _recording_runner(calls, TIMED_OUT))
    with pytest.raises(ToolError) as exc:
        await bandwidth_test.run_bandwidth_test('192.0.2.10', 10)
    assert exc.value.error_code == ErrorCodes.API_ERROR
    assert exc.value.message == 'iperf3 timed out after 25s'
    assert exc.value.suggestion == 'Ensure iperf3 server is running on 192.0.2.10 (iperf3 -s)'


async def test_bandwidth_connect_failure_names_the_host_with_its_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError('Connection refused')

    monkeypatch.setattr(asyncssh, 'connect', _refused)
    with pytest.raises(ToolError) as exc:
        await bandwidth_test.run_bandwidth_test('192.0.2.10')
    assert exc.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert exc.value.message == 'SSH connection to 192.0.2.1 failed: Connection refused'
    assert exc.value.suggestion == 'Check UNIFI_SSH_USERNAME/UNIFI_SSH_PASSWORD in config'


# --- the new value checks ----------------------------------------------------------------

LEADING_DASH = ['-f', '--help', '-oProxyCommand=x']
# Built in parts so no scanner reads a credential URL in this file.
FAKE_URL_PW = 'hunter2-not-real'  # pragma: allowlist secret
LOGIN_URL = 'https://user:' + FAKE_URL_PW + '@example.com/'


@pytest.mark.parametrize(
    'value', ['gateway', 'host-name.example.com', 'a' * 63 + '.example', '192.0.2.1', 'x1']
)
def test_require_hostname_returns_a_hostname_unchanged(value: str) -> None:
    assert require_hostname(value) == value


@pytest.mark.parametrize(
    'value',
    [
        *LEADING_DASH,
        'host-',
        'a..b',
        '',
        'a' * 64,
        'my_host',
        'a b',
        'x;reboot',
        '$(reboot)',
        'example.com.',
        None,
        7,
    ],
)
def test_require_hostname_refuses_anything_else(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_hostname(value)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


def test_require_hostname_refuses_a_name_over_253_characters() -> None:
    name = '.'.join(['a' * 63] * 4)  # 255 characters, every label valid
    with pytest.raises(ToolError):
        require_hostname(name)
    assert require_hostname(name[:253].rstrip('.')) == name[:253].rstrip('.')


@pytest.mark.parametrize(
    'value',
    [
        'https://www.example.com/',
        'http://192.0.2.1:8080/status?x=1',
        'https://[2001:db8::1]:8443/',
        'http://gateway/',
    ],
)
def test_require_http_url_returns_a_url_unchanged(value: str) -> None:
    assert require_http_url(value) == value


@pytest.mark.parametrize(
    'value',
    [
        LOGIN_URL,
        'https://user@example.com/',
        'ftp://example.com/',
        'file:///etc/passwd',
        '-K/etc/passwd',
        'https://-f/',
        'https://example.com/a b',
        'https://example.com/\x00',
        'https://',
        'https://example.com:0/',
        'https://example.com:99999/',
        'https://[fe80::1%25br0]/',
        'https://[not-an-ip]/',
        'https://' + 'a' * 2050,
        '',
        None,
    ],
)
def test_require_http_url_refuses_anything_else_without_echoing_it(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_http_url(value)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID
    assert FAKE_URL_PW not in str(exc.value)
    if isinstance(value, str) and value:
        assert value not in exc.value.message


def test_require_http_url_says_why_a_url_with_a_login_is_refused() -> None:
    with pytest.raises(ToolError) as exc:
        require_http_url(LOGIN_URL)
    assert 'user name or password' in exc.value.message


@pytest.mark.parametrize('value', ['br0', 'eth8', 'br30', 'eth8.30', 'wg-site', 'a' * 15])
def test_require_interface_name_returns_a_name_unchanged(value: str) -> None:
    assert require_interface_name(value) == value


@pytest.mark.parametrize(
    'value', [*LEADING_DASH, 'Br0', '0eth', 'eth 0', 'br0;id', 'a' * 16, '', None]
)
def test_require_interface_name_refuses_anything_else(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_interface_name(value)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID


@pytest.mark.parametrize(('value', 'expected'), [(1, 1.0), (0.5, 0.5), (10, 10.0)])
def test_require_bounded_float_accepts_the_range(value: float, expected: float) -> None:
    assert require_bounded_float('interval', value, 0.5, 10) == expected


@pytest.mark.parametrize(
    'value',
    [
        *[0.49, 10.01, float('nan'), float('inf'), True, '1', None],
        pytest.param(10**400, id='huge-int'),
        pytest.param(-(10**400), id='huge-negative-int'),
    ],
)
def test_require_bounded_float_refuses_anything_else(value: object) -> None:
    with pytest.raises(ToolError) as exc:
        require_bounded_float('interval', value, 0.5, 10)
    assert exc.value.error_code == ErrorCodes.CONFIG_INVALID
    assert 'interval must be a number from 0.5 to 10' in exc.value.message


@pytest.mark.parametrize('check', [require_bounded_int, require_bounded_float])
def test_the_number_checks_redact_the_value_they_refuse(check: Callable[..., object]) -> None:
    refused = 'password=' + 'fake-value-for-the-echo'  # pragma: allowlist secret
    with pytest.raises(ToolError) as exc:
        check('ping count', refused, 1, 100)
    assert 'fake-value-for-the-echo' not in exc.value.message
    assert '***redacted***' in exc.value.message


# --- both SSH commands report a failure the same way (issue 050) -------------------------

SSH_COMMANDS = [['diagnose', 'bandwidth', '192.0.2.10'], ['diagnose', 'latency-matrix']]


@pytest.mark.parametrize('args', SSH_COMMANDS)
def test_cli_ssh_connect_failure_goes_to_stderr(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    async def _refused(host: str, **kwargs: Any) -> FakeConnection:
        raise OSError('Connection refused')

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr(asyncssh, 'connect', _refused)
    _controller(monkeypatch, [{'ip': '192.0.2.10', 'name': 'Switch'}], [])
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    stderr = _flat(result.stderr)
    assert '❌ [CONTROLLER_UNREACHABLE] SSH connection to 192.0.2.1 failed' in stderr
    assert 'SSH connection' not in result.stdout
    assert 'Error:' not in result.stdout


@pytest.mark.parametrize('args', SSH_COMMANDS)
def test_cli_ssh_unexpected_error_is_redacted_on_stderr(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError(f'agent died, password={FAKE_SSH_PW}')

    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    monkeypatch.setattr(bandwidth_test, 'run_bandwidth_test', _boom)
    monkeypatch.setattr(latency_matrix, 'run_latency_matrix', _boom)
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert '❌ Error: agent died' in _flat(result.stderr)
    assert 'agent died' not in result.stdout
    assert FAKE_SSH_PW not in result.output


# --- the latency matrix reads ping output through the shared parser ----------------------

BUSYBOX_PING = (
    '10 packets transmitted, 8 packets received, 20% packet loss\n'
    'round-trip min/avg/max = 2.100/5.500/12.300 ms\n'
)


def test_latency_reads_busybox_ping_output() -> None:
    target = {'ip': '192.0.2.10', 'name': 'AP 1', 'type': 'device'}
    result = latency_matrix._parse_ping_output(target, BUSYBOX_PING)
    assert (result.reachable, result.packet_loss) == (True, 20.0)
    assert (result.rtt_min, result.rtt_avg, result.rtt_max) == (2.1, 5.5, 12.3)
    assert result.rtt_mdev is None


def test_latency_counts_a_target_with_total_loss_as_unreachable() -> None:
    target = {'ip': '192.0.2.10', 'name': 'AP 1', 'type': 'device'}
    result = latency_matrix._parse_ping_output(
        target, '5 packets transmitted, 0 received, 100% packet loss\n'
    )
    assert (result.reachable, result.packet_loss, result.rtt_avg) == (False, 100.0, None)


# --- the connect itself is bounded (M2 council finding M2-MAJOR-001) ---------------------


async def test_a_stalled_connect_ends_as_unreachable_after_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stalled(host: str, **kwargs: Any) -> FakeConnection:
        await asyncio.sleep(60)
        raise AssertionError('not reached')

    monkeypatch.setattr(asyncssh, 'connect', _stalled)
    with pytest.raises(ToolError) as exc:
        async with gateway_session('192.0.2.1', connect_timeout=0.05):
            pass
    assert exc.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert exc.value.message == 'SSH connection to 192.0.2.1 timed out after 0.05s'
    assert exc.value.suggestion == SSH_CONNECT_SUGGESTION


def test_the_default_connect_bound_is_stated() -> None:
    assert SSH_CONNECT_TIMEOUT == 30


@pytest.mark.parametrize('check', [require_hostname, require_interface_name])
def test_a_refused_value_is_echoed_redacted(check: Callable[[object], str]) -> None:
    with pytest.raises(ToolError) as exc:
        check(f'token={FAKE_URL_PW}')
    assert FAKE_URL_PW not in exc.value.message
    assert 'token=' in exc.value.message


def test_a_result_code_passes_and_any_other_status_is_an_api_error() -> None:
    """Review F7: a program that could not run is an error, never an empty answer."""
    ok = GatewayResult(stdout='out', stderr='', exit_status=1)
    assert check_exit_status(ok, 'ping', (0, 1)) is ok
    for status, stderr, detail in (
        (2, 'first\nping: bad address', ': ping: bad address'),
        (-1, '', ''),  # ended by a signal: no status
        (127, f'sh: token={FAKE_URL_PW}', ': sh: token=***redacted***'),
    ):
        with pytest.raises(ToolError) as exc:
            check_exit_status(GatewayResult('', stderr, status), 'ping', (0, 1))
        assert exc.value.error_code == ErrorCodes.API_ERROR
        assert (
            exc.value.message
            == f'ping could not run on the gateway (exit status {status}){detail}'
        )
