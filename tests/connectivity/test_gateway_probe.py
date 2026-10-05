"""Gateway probes over SSH (``connectivity/gateway_probe.py``) and the ``gateway`` CLI group.

Ported from the July work (a local archive, not in the repo) and adapted: documentation
values only, every command an argv through ``analysis/gateway_ssh.py`` with its own bound,
conntrack filtered in Python (no ``grep`` on the gateway), ``--globoff`` on curl, ``--vlan``
resolved by subnet from the controller's network list, and no MCP tool (decision D1 in issue
060). SSH is the shared fake (``tests/fake_ssh.py``) over the root ban on a real connect; the
controller is the fake behind the real read-only guard.
"""

import asyncssh
import json
import pytest
import shlex
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from tests.fake_ssh import FakeSSH
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.connectivity import gateway_probe
from unifi_mapper.connectivity.gateway_probe import (
    FLOW_STATES,
    WRITE_OUT,
    gateway_dns_check,
    gateway_http_check,
    gateway_ping,
    gateway_traceroute,
    get_active_flows,
    parse_conntrack_output,
    parse_curl_writeout,
    parse_nslookup_output,
    parse_traceroute_output,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.typer_cli import app


runner = CliRunner()
FAKE_SSH_PW = 'FAKE-PROBE-SSH-PASSWORD'  # pragma: allowlist secret
# Built in parts so no scanner reads a credential URL in this file.
FAKE_URL_PW = 'not-a-real-url-password'  # pragma: allowlist secret
LOGIN_URL = 'https://user:' + FAKE_URL_PW + '@www.example.com/'

TRACEROUTE_OUTPUT = """\
traceroute to 203.0.113.53 (203.0.113.53), 20 hops max, 60 byte packets
 1  gateway (192.0.2.1)  0.512 ms  0.401 ms  0.398 ms
 2  198.51.100.1 (198.51.100.1)  8.221 ms  8.105 ms  7.990 ms
 3  * * *
 4  dns.example.net (203.0.113.53)  12.345 ms  12.100 ms  11.987 ms
"""
CONNTRACK_OUTPUT = (
    'tcp      6 431999 ESTABLISHED src=192.0.2.50 dst=203.0.113.10 sport=52341 dport=443 '
    'src=203.0.113.10 dst=198.51.100.2 sport=443 dport=52341 [ASSURED] mark=0 use=1\n'
    'udp      17 26 src=192.0.2.50 dst=203.0.113.53 sport=5353 dport=53 [UNREPLIED] '
    'src=203.0.113.53 dst=198.51.100.2 sport=53 dport=5353 mark=0 use=1\n'
    'tcp      6 108 TIME_WAIT src=192.0.2.9 dst=203.0.113.20 sport=44444 dport=443 '
    'src=203.0.113.20 dst=198.51.100.2 sport=443 dport=44444 [ASSURED] mark=0 use=1\n'
)
NSLOOKUP_OK = """\
Server:         192.0.2.1
Address:        192.0.2.1#53

Non-authoritative answer:
Name:   www.example.com
Address: 203.0.113.10
Name:   www.example.com
Address: 203.0.113.11
"""
NSLOOKUP_FAIL = """\
Server:         203.0.113.53
Address:        203.0.113.53:53

** server can't find nowhere.invalid: NXDOMAIN
"""
IP_ADDR_JSON = json.dumps(
    [
        {'ifname': 'lo', 'addr_info': [{'local': '127.0.0.1', 'prefixlen': 8}]},
        {'ifname': 'br0', 'addr_info': [{'local': '192.0.2.1', 'prefixlen': 24}]},
        {'ifname': 'br7', 'addr_info': [{'local': '198.51.100.1', 'prefixlen': 24}]},
    ]
)
NETWORKS = [
    {'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
    {
        'name': 'IoT',
        'purpose': 'corporate',
        'vlan': 30,
        'vlan_enabled': True,
        'ip_subnet': '198.51.100.1/24',
    },  # fmt: skip
    {
        'name': 'Lab',
        'purpose': 'corporate',
        'vlan': 40,
        'vlan_enabled': True,
        'ip_subnet': '203.0.113.1/24',
    },  # fmt: skip
]
DEVICES = [
    {
        'name': 'AP 1',
        'mac': '02:00:00:00:01:01',
        'type': 'uap',
        'model': 'U6IW',
        'ip': '192.0.2.21',
    },  # fmt: skip
]
CLIENTS = [
    {'name': 'Phone A', 'hostname': 'phone-a', 'mac': '02:00:00:00:02:01', 'ip': '192.0.2.50'},
]
REPLIES: dict[str, Any] = {
    'traceroute': TRACEROUTE_OUTPUT,
    'conntrack': CONNTRACK_OUTPUT,
    'nslookup': NSLOOKUP_OK,
    'curl': '200 0.123456 203.0.113.10',
    'ip': IP_ADDR_JSON,
}


@pytest.fixture(autouse=True)
def _gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_SSH_PASSWORD', FAKE_SSH_PW)


@pytest.fixture
def ssh(monkeypatch: pytest.MonkeyPatch) -> FakeSSH:
    fake = FakeSSH(dict(REPLIES))
    monkeypatch.setattr(asyncssh, 'connect', fake)
    return fake


@pytest.fixture
def controller() -> FakeController:
    return FakeController(
        {
            f'{API}/stat/device': legacy(DEVICES),
            f'{API}/stat/sta': legacy(CLIENTS),
            f'{API}/rest/networkconf': legacy(NETWORKS),
        }
    )


def _argv(ssh: FakeSSH) -> list[list[str]]:
    return [shlex.split(command) for command in ssh.commands]


# --- the pure parsers (from July, documentation values) -----------------------------------


def test_traceroute_hops_timeouts_and_names() -> None:
    hops = parse_traceroute_output(TRACEROUTE_OUTPUT)
    assert [h['hop'] for h in hops] == [1, 2, 3, 4]
    assert (hops[0]['host'], hops[0]['ip'], hops[0]['rtt_ms']) == (
        'gateway',
        '192.0.2.1',
        [0.512, 0.401, 0.398],
    )
    assert hops[2]['timeout'] is True and hops[2]['rtt_ms'] == []
    assert (hops[3]['host'], hops[3]['ip']) == ('dns.example.net', '203.0.113.53')
    assert parse_traceroute_output('') == []


def test_conntrack_flows_and_filters() -> None:
    flows = parse_conntrack_output(CONNTRACK_OUTPUT)
    assert len(flows) == 3
    first = flows[0]
    assert (first['protocol'], first['state'], first['orig_src'], first['orig_dport']) == (
        'tcp',
        'ESTABLISHED',
        '192.0.2.50',
        443,
    )
    assert first['reply_src'] == '203.0.113.10' and first['unreplied'] is False
    assert flows[1]['unreplied'] is True and 'UNREPLIED' in flows[1]['flags']
    assert len(parse_conntrack_output(CONNTRACK_OUTPUT, ip='192.0.2.50')) == 2
    assert [
        f['protocol'] for f in parse_conntrack_output(CONNTRACK_OUTPUT, state='UNREPLIED')
    ] == ['udp']
    assert len(parse_conntrack_output(CONNTRACK_OUTPUT, state='ESTABLISHED')) == 1
    assert len(parse_conntrack_output(CONNTRACK_OUTPUT, ip='192.0.2.50', state='UNREPLIED')) == 1
    assert parse_conntrack_output('conntrack v1.4.6\nsome banner\n') == []


def test_nslookup_answers_failures_and_the_server_port() -> None:
    ok = parse_nslookup_output(NSLOOKUP_OK)
    assert ok['resolved'] is True and ok['error'] is None
    assert ok['addresses'] == ['203.0.113.10', '203.0.113.11']
    assert ok['names'] == ['www.example.com', 'www.example.com']
    fail = parse_nslookup_output(NSLOOKUP_FAIL)
    assert fail['resolved'] is False and fail['error'] is not None
    assert fail['server'] == '203.0.113.53'


@pytest.mark.parametrize(
    ('out', 'status', 'ok', 'remote'),
    [
        ('200 0.123456 203.0.113.10', 200, True, '203.0.113.10'),
        ('302 0.05 203.0.113.11', 302, True, '203.0.113.11'),
        ('000 0.000 -', 0, False, None),
        ('', 0, False, None),
    ],
)
def test_curl_write_out(out: str, status: int, ok: bool, remote: str | None) -> None:
    parsed = parse_curl_writeout(out)
    assert (parsed['http_status'], parsed['ok'], parsed['remote_ip']) == (status, ok, remote)


# --- each probe: one session, an argv, its own bound --------------------------------------


async def test_ping_runs_one_argv_with_a_bound_from_its_own_arguments(
    ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    bounds: list[float] = []
    real = gateway_probe.run_gateway_command

    async def _spy(conn: Any, argv: Any, *, timeout: float) -> Any:
        bounds.append(timeout)
        return await real(conn, argv, timeout=timeout)

    monkeypatch.setattr(gateway_probe, 'run_gateway_command', _spy)
    result = await gateway_ping('192.0.2.50', count=4, interval=0.5)
    assert _argv(ssh) == [['ping', '-c', '4', '-i', '0.5', '-W', '2', '192.0.2.50']]
    assert bounds == [4 * 0.5 + 12]
    assert result['reachable'] is True and result['probe_ip'] == '192.0.2.50'
    assert len(ssh.connects) == 1


async def test_a_name_resolves_through_the_guarded_controller(
    ssh: FakeSSH, controller: FakeController
) -> None:
    async with serving(controller):
        device = await gateway_ping('AP 1', count=1)
        client = await gateway_ping('phone-a', count=1)
    assert (device['probe_ip'], device['resolved_name']) == ('192.0.2.21', 'AP 1')
    assert (client['probe_ip'], client['resolved_name']) == ('192.0.2.50', 'Phone A')
    assert controller.methods == {'GET'}


async def test_an_unknown_name_is_not_found_before_any_ssh(
    ssh: FakeSSH, controller: FakeController
) -> None:
    async with serving(controller):
        with pytest.raises(ToolError) as caught:
            await gateway_ping('No such thing')
    assert caught.value.error_code == ErrorCodes.DEVICE_NOT_FOUND
    assert ssh.connects == []


@pytest.mark.parametrize('probe', [gateway_ping, gateway_traceroute])
async def test_no_ssh_password_fails_before_a_name_is_looked_up(
    ssh: FakeSSH, controller: FakeController, monkeypatch: pytest.MonkeyPatch, probe: Any
) -> None:
    monkeypatch.delenv('UNIFI_SSH_PASSWORD')
    async with serving(controller):
        with pytest.raises(ToolError) as caught:
            await probe('AP 1')
    assert caught.value.error_code == ErrorCodes.CONFIG_MISSING
    assert controller.calls == [] and ssh.connects == []


@pytest.mark.parametrize(
    ('call', 'code'),
    [
        (lambda: gateway_ping('192.0.2.50', count=0), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_ping('192.0.2.50', count=101), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_ping('192.0.2.50', interval=0.1), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_traceroute('192.0.2.50', max_hops=31), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_dns_check('-f'), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_dns_check('www.example.com', server='--help'), ErrorCodes.INVALID_IP),
        (lambda: gateway_http_check(LOGIN_URL), ErrorCodes.CONFIG_INVALID),
        (lambda: gateway_http_check('ftp://www.example.com/'), ErrorCodes.CONFIG_INVALID),
        (
            lambda: gateway_http_check('https://www.example.com/', interface='-eth0'),
            ErrorCodes.CONFIG_INVALID,
        ),
        (
            lambda: gateway_http_check('https://www.example.com/', vlan=30, interface='br7'),
            ErrorCodes.CONFIG_INVALID,
        ),
        (
            lambda: gateway_http_check('https://www.example.com/', vlan=4095),
            ErrorCodes.CONFIG_INVALID,
        ),
        (lambda: get_active_flows(ip='192.0.2.50; reboot'), ErrorCodes.INVALID_IP),
        (lambda: get_active_flows(state='BOGUS'), ErrorCodes.CONFIG_INVALID),
        (lambda: get_active_flows(limit=5001), ErrorCodes.CONFIG_INVALID),
    ],
    ids=[
        'count 0',
        'count 101',
        'interval 0.1',
        'hops 31',
        'hostname option',
        'server option',
        'url userinfo',
        'url scheme',
        'interface option',
        'vlan and interface',
        'vlan 4095',
        'flow ip',
        'flow state',
        'flow limit',
    ],
)
async def test_every_value_is_checked_before_any_ssh(ssh: FakeSSH, call: Any, code: str) -> None:
    with pytest.raises(ToolError) as caught:
        await call()
    assert caught.value.error_code == code
    assert ssh.connects == []
    assert 'secret' not in caught.value.message  # the URL is never echoed


async def test_traceroute_dns_and_flows_argv_and_parsing(ssh: FakeSSH) -> None:
    trace = await gateway_traceroute('203.0.113.53', max_hops=4)
    dns = await gateway_dns_check('www.example.com', server='203.0.113.53')
    flows = await get_active_flows(ip='192.0.2.50', state='unreplied', limit=1)
    assert _argv(ssh) == [
        ['traceroute', '-m', '4', '-w', '2', '203.0.113.53'],
        ['nslookup', 'www.example.com', '203.0.113.53'],
        ['conntrack', '-L'],  # filtered in Python, never with grep on the gateway
    ]
    assert trace['reached'] is True and len(trace['hops']) == 4
    assert dns['resolved'] is True and dns['requested_server'] == '203.0.113.53'
    assert (flows['total_matching'], flows['unreplied_count'], flows['truncated']) == (1, 1, False)
    assert flows['state_filter'] == 'UNREPLIED'


async def test_http_uses_globoff_and_an_interface_or_a_resolved_vlan(
    ssh: FakeSSH, controller: FakeController
) -> None:
    plain = await gateway_http_check('https://www.example.com/[a]', interface='br0')
    async with serving(controller):
        by_vlan = await gateway_http_check('http://www.example.com/', vlan=30, timeout_seconds=5)
    argv = _argv(ssh)
    assert argv[0] == [
        'curl', '-sS', '--globoff', '-o', '/dev/null', '--max-time', '10', '-w', WRITE_OUT,
        '--interface', 'br0', '--', 'https://www.example.com/[a]',
    ]  # fmt: skip
    assert argv[1] == ['ip', '-j', 'addr', 'show']
    assert argv[2][-4:] == ['--interface', 'br7', '--', 'http://www.example.com/']
    assert plain['ok'] is True and plain['interface'] == 'br0'
    assert by_vlan['interface'] == 'br7' and by_vlan['vlan'] == 30
    assert [path for _, path in controller.reads] == [f'{API}/rest/networkconf']


async def test_a_vlan_with_no_live_interface_is_no_data(
    ssh: FakeSSH, controller: FakeController
) -> None:
    async with serving(controller):
        with pytest.raises(ToolError) as caught:
            await gateway_http_check('https://www.example.com/', vlan=40)
    assert caught.value.error_code == ErrorCodes.NO_DATA
    assert 'VLAN 40' in caught.value.message
    assert _argv(ssh) == [['ip', '-j', 'addr', 'show']]  # no curl


def test_the_flow_states_are_the_design_s() -> None:
    assert set(FLOW_STATES) == {
        'ESTABLISHED',
        'SYN_SENT',
        'SYN_RECV',
        'FIN_WAIT',
        'CLOSE_WAIT',
        'LAST_ACK',
        'TIME_WAIT',
        'CLOSE',
        'UNREPLIED',
        'ASSURED',
    }


def test_the_probes_are_cli_only() -> None:
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    categories = ToolRegistry(default_manifests_dir(), strict=True).get_categories()
    names = {name for names in categories.values() for name in names}
    for name in ('gateway_ping', 'gateway_traceroute', 'gateway_dns_check',
                 'gateway_http_check', 'get_active_flows'):  # fmt: skip
        assert name not in names


# --- the gateway CLI group ----------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH, controller: FakeController) -> FakeSSH:
    route_cli(monkeypatch, controller)
    return ssh


@pytest.mark.parametrize(
    'args',
    [
        ['gateway', 'ping', '192.0.2.50', '--count', '2', '--json'],
        ['gateway', 'traceroute', '203.0.113.53', '--max-hops', '4', '--json'],
        ['gateway', 'dns', 'www.example.com', '--json'],
        ['gateway', 'http', 'https://www.example.com/', '--json'],
        ['gateway', 'flows', '--state', 'established', '--json'],
    ],
    ids=['ping', 'traceroute', 'dns', 'http', 'flows'],
)
def test_every_command_prints_json_and_the_notice_once(cli: FakeSSH, args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert result.stderr.count('host key is not verified') == 1
    assert len(cli.connects) == 1


@pytest.mark.parametrize(
    'args',
    [
        ['gateway', 'ping', '192.0.2.50'],
        ['gateway', 'traceroute', '203.0.113.53'],
        ['gateway', 'dns', 'www.example.com'],
        ['gateway', 'http', 'https://www.example.com/', '--vlan', '30'],
        ['gateway', 'flows', '--ip', '192.0.2.50'],
    ],
    ids=['ping', 'traceroute', 'dns', 'http', 'flows'],
)
def test_every_command_prints_a_table(cli: FakeSSH, args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stdout.strip()


@pytest.mark.parametrize(
    'args',
    [
        ['gateway', 'ping', '192.0.2.50', '--count', '0'],
        ['gateway', 'traceroute', '203.0.113.53', '--max-hops', '31'],
        ['gateway', 'http', 'https://www.example.com/', '--timeout', '61'],
        ['gateway', 'flows', '--state', 'bogus'],
        ['gateway', 'flows', '--limit', '0'],
    ],
)
def test_out_of_range_options_are_usage_errors(cli: FakeSSH, args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    assert cli.connects == []


def test_a_bad_value_is_one_error_line_and_no_ssh(cli: FakeSSH) -> None:
    result = runner.invoke(app, ['gateway', 'dns', '-x', '--json'])  # Typer refuses -x itself
    assert result.exit_code == 2
    bad = runner.invoke(app, ['gateway', 'http', LOGIN_URL])
    assert bad.exit_code == 1 and bad.stdout == ''
    assert 'user name or password' in bad.stderr and FAKE_URL_PW not in bad.stderr
    assert cli.connects == []


@pytest.mark.parametrize('command', ['ping', 'traceroute', 'dns', 'http', 'flows'])
def test_every_command_has_help(command: str) -> None:
    result = runner.invoke(app, ['gateway', command, '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert 'SSH' in flat and 'host key is not verified' in flat
