"""One-shot client connectivity diagnosis (``diagnostics/client_connectivity.py``) and its CLI.

Ported from the prototype (a local archive, not in the repo) and adapted: documentation values
only; the HTTP probe takes the client's VLAN (resolved to its gateway interface by subnet), not
a VLAN ID passed as an interface name; every layer is bounded and the chain has a 120 s
budget; a failing layer is that layer's finding; no MCP tool (decision D1 in issue 060). SSH is
the shared fake (``tests/fake_ssh.py``) over the root ban; the controller is the fake behind
the real read-only guard.
"""

import asyncio
import asyncssh
import click
import json
import pytest
import shlex
import typer
from tests.fake_controller import API, FakeController, legacy, route_cli, serving
from tests.fake_ssh import FakeSSH
from tests.fixtures_unifi import FAKE_TOKEN
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics import client_connectivity
from unifi_mapper.diagnostics.client_connectivity import (
    CAPTIVE_PROBE_URL,
    CHAIN_BUDGET_SECONDS,
    build_verdict,
    diagnose_client_connectivity,
)
from unifi_mapper.typer_cli import app


runner = CliRunner()
FAKE_SSH_PW = 'FAKE-CONNECTIVITY-SSH-PASSWORD'  # pragma: allowlist secret

# --- build_verdict: the prototype's layers, documentation values -----------------------------------

PING_OK = {'reachable': True, 'loss_pct': 0.0, 'rtt_avg_ms': 5.0}
PING_DEAD = {'reachable': False, 'loss_pct': 100.0, 'rtt_avg_ms': None}
PING_LOSSY = {'reachable': True, 'loss_pct': 40.0, 'rtt_avg_ms': 80.0}
DNS_OK = {'resolved': True, 'addresses': ['203.0.113.10'], 'error': None}
DNS_FAIL = {'resolved': False, 'addresses': [], 'error': 'NXDOMAIN'}
HTTP_OK = {'ok': True, 'http_status': 200, 'interface': 'br30'}
HTTP_FAIL = {'ok': False, 'http_status': 0, 'interface': 'br30'}
FLOWS_HEALTHY = {'total_matching': 10, 'unreplied_count': 1}
FLOWS_BLACKHOLE = {'total_matching': 10, 'unreplied_count': 9}
AP_HEALTHY = {'name': 'AP 1', 'vaps': [{'essid': 'SSID A', 'retry_pct_cumulative': 3.0}]}
AP_SICK = {'name': 'AP 1', 'vaps': [{'essid': 'SSID A', 'retry_pct_cumulative': 24.0}]}


def _verdict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        'client_found': True,
        'ping': PING_OK,
        'ap_stats': AP_HEALTHY,
        'dns': DNS_OK,
        'http': HTTP_OK,
        'flows': FLOWS_HEALTHY,
    }
    base.update(overrides)
    return build_verdict(**base)


def test_all_healthy_mentions_the_stale_banner() -> None:
    result = _verdict()
    assert result['ok'] is True
    assert 'stale' in result['verdict'] and 'banner' in result['verdict'].lower()


def test_a_client_not_found() -> None:
    result = build_verdict(
        client_found=False, ping=None, ap_stats=None, dns=None, http=None, flows=None
    )
    assert result['ok'] is False and 'not found' in result['verdict'].lower()


def test_an_unreachable_client() -> None:
    result = _verdict(ping=PING_DEAD)
    assert result['ok'] is False
    assert any('unreachable' in f for f in result['findings'])


def test_high_loss_is_flagged() -> None:
    result = _verdict(ping=PING_LOSSY)
    assert result['ok'] is False
    assert any('40' in f and 'loss' in f for f in result['findings'])


def test_a_dns_failure() -> None:
    result = _verdict(dns=DNS_FAIL)
    assert result['ok'] is False
    assert any('DNS' in f and 'failed' in f for f in result['findings'])


def test_an_http_failure_names_the_interface() -> None:
    result = _verdict(http=HTTP_FAIL)
    assert result['ok'] is False
    assert any('br30' in f for f in result['findings'])


def test_unreplied_flows_are_a_blackhole() -> None:
    result = _verdict(flows=FLOWS_BLACKHOLE)
    assert result['ok'] is False
    assert any('UNREPLIED' in f for f in result['findings'])


def test_a_sick_ap_is_noted_with_the_interval_check() -> None:
    result = _verdict(ap_stats=AP_SICK)
    assert result['ok'] is True  # cumulative retries alone don't fail the verdict
    assert any('retries' in f.lower() and 'diagnose ap-retries' in f for f in result['findings'])


def test_probes_not_given_are_tolerated() -> None:
    result = _verdict(ping=None, dns=None, http=None, flows=None, ap_stats=None)
    assert result['ok'] is True  # nothing failed, nothing to report


def test_a_layer_that_could_not_run_makes_the_verdict_inconclusive() -> None:
    result = _verdict(dns=None, failed={'dns': '[TIMEOUT] nslookup timed out after 20s'})
    assert result['ok'] is False
    assert result['verdict'].startswith('Inconclusive')
    assert any(f.startswith('DNS could not run: [TIMEOUT]') for f in result['findings'])


def test_a_fault_outranks_a_layer_that_did_not_run() -> None:
    result = _verdict(ping=PING_DEAD, flows=None, not_run={'flows': 'budget'})
    assert result['verdict'].startswith('Connectivity fault found')
    assert any('conntrack flows not run: budget' in f for f in result['findings'])


# --- the chain: lookup -> AP -> ping -> DNS -> HTTP from the VLAN -> flows ----------------

IP_ADDR_JSON = json.dumps(
    [
        {'ifname': 'br0', 'addr_info': [{'local': '192.0.2.1', 'prefixlen': 24}]},
        {'ifname': 'br30', 'addr_info': [{'local': '198.51.100.1', 'prefixlen': 24}]},
    ]
)
NSLOOKUP_OK = (
    'Server:\t\t192.0.2.1\nAddress:\t192.0.2.1#53\n\n'
    'Name:\tcaptive.example.com\nAddress: 203.0.113.10\n'
)
CONNTRACK = (
    'tcp      6 431999 ESTABLISHED src=198.51.100.50 dst=203.0.113.10 sport=52341 dport=443 '
    'src=203.0.113.10 dst=192.0.2.2 sport=443 dport=52341 [ASSURED] mark=0 use=1\n'
)
REPLIES: dict[str, Any] = {
    'nslookup': NSLOOKUP_OK,
    'curl': '200 0.050000 203.0.113.10',
    'conntrack': CONNTRACK,
    'ip': IP_ADDR_JSON,
}
PROBE_URL = 'http://captive.example.com/hotspot-detect.html'
NETWORKS = [
    {'_id': 'net-lan', 'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
    {
        '_id': 'net-iot',
        'name': 'IoT',
        'purpose': 'corporate',
        'vlan': 30,
        'vlan_enabled': True,
        'ip_subnet': '198.51.100.1/24',
    },
]
DEVICES = [
    {
        'name': 'AP 1',
        'mac': '02:00:00:00:01:01',
        'type': 'uap',
        'model': 'U6IW',
        'x_authkey': 'FAKE-AP-AUTHKEY',  # pragma: allowlist secret
        'vap_table': [{'essid': 'SSID A', 'radio': 'ng', 'tx_packets': 1000, 'tx_retries': 30}],
    },
]
CLIENTS = [
    {
        'name': 'Phone A',
        'hostname': 'phone-a',
        'mac': '02:00:00:00:02:01',
        'ip': '198.51.100.50',
        'ap_mac': '02:00:00:00:01:01',
        'is_wired': False,
        'network': 'IoT',
        'network_id': 'net-iot',
    },
    {
        'name': 'Printer',
        'mac': '02:00:00:00:02:02',
        'ip': '192.0.2.60',
        'is_wired': True,
        'network': 'LAN',
        'network_id': 'net-lan',
    },
    {
        'name': 'Phone B',
        'mac': '02:00:00:00:02:03',
        'is_wired': False,
        'network': 'IoT',
        'network_id': 'net-iot',
    },  # no lease
    {
        'name': 'Tablet C',
        'mac': '02:00:00:00:02:04',
        'ip': '203.0.113.70',
        'is_wired': False,
    },  # no network the controller lists
]


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


def _controller(clients: list[dict[str, Any]] | None = None) -> FakeController:
    return FakeController(
        {
            f'{API}/stat/sta': legacy(CLIENTS if clients is None else clients),
            f'{API}/stat/device': legacy(DEVICES),
            f'{API}/rest/networkconf': legacy(NETWORKS),
        }
    )


async def _diagnose(controller: FakeController, query: str = 'Phone A') -> dict[str, Any]:
    async with serving(controller):
        return await diagnose_client_connectivity(query, probe_url=PROBE_URL)


def _argv(ssh: FakeSSH) -> list[list[str]]:
    return [shlex.split(command) for command in ssh.commands]


async def test_the_chain_runs_every_layer_in_order_through_reads_only(ssh: FakeSSH) -> None:
    controller = _controller()
    result = await _diagnose(controller)
    assert result['ok'] is True, result['findings']
    assert (result['client'], result['client_ip'], result['vlan']) == (
        'Phone A',
        '198.51.100.50',
        30,
    )
    assert result['ap'] == 'AP 1' and result['not_run'] == []
    programs = [argv[0] for argv in _argv(ssh)]
    assert programs == ['ping', 'nslookup', 'ip', 'curl', 'conntrack']
    ping, dns, _, curl, _ = _argv(ssh)
    assert ping[:3] == ['ping', '-c', '4'] and ping[-1] == '198.51.100.50'
    assert dns == ['nslookup', 'captive.example.com']
    assert curl[curl.index('--interface') + 1] == 'br30' and curl[-1] == PROBE_URL
    assert controller.methods == {'GET'}
    assert 'FAKE-AP-AUTHKEY' not in json.dumps(result)


async def test_a_failing_layer_never_hides_the_others(
    ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError('lookup broke: token=FAKE-LEAKED-VALUE')  # pragma: allowlist secret

    monkeypatch.setattr(client_connectivity, 'gateway_dns_check', _broken)
    result = await _diagnose(_controller())
    assert result['probes']['dns']['error'].startswith('lookup broke')
    assert 'FAKE-LEAKED-VALUE' not in json.dumps(result)
    assert [argv[0] for argv in _argv(ssh)] == ['ping', 'ip', 'curl', 'conntrack']
    assert result['ok'] is False and result['verdict'].startswith('Inconclusive')


async def test_a_conntrack_that_could_not_run_is_not_a_healthy_no_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review F7: an empty stdout from a conntrack the SSH user may not run read as "No live
    conntrack flows" (healthy); now that layer could not run and the verdict says so."""
    replies = {**REPLIES, 'conntrack': ('', 'conntrack v1.4: Operation not permitted', 1)}
    monkeypatch.setattr(asyncssh, 'connect', FakeSSH(replies))
    result = await _diagnose(_controller())
    assert result['probes']['flows']['error_code'] == ErrorCodes.API_ERROR
    assert 'No live conntrack flows' not in ' '.join(result['findings'])
    assert result['ok'] is False and result['verdict'].startswith('Inconclusive')


async def test_the_budget_ends_the_chain_and_names_what_did_not_run(
    ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _slow_ping(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(5)
        return PING_OK

    monkeypatch.setattr(client_connectivity, 'CHAIN_BUDGET_SECONDS', 0.2)
    monkeypatch.setattr(client_connectivity, 'gateway_ping', _slow_ping)
    result = await _diagnose(_controller())
    assert result['probes']['ping']['error_code'] == ErrorCodes.TIMEOUT
    assert result['not_run'] == ['dns', 'http', 'flows']
    assert all(result['probes'][layer] == {'not_run': 'budget'} for layer in result['not_run'])
    assert ssh.connects == []
    assert result['ok'] is False and 'budget' in result['verdict']


async def test_an_unknown_client_is_not_found_before_any_probe(ssh: FakeSSH) -> None:
    result = await _diagnose(_controller(), 'No such client')
    assert result['ok'] is False and 'not found' in result['verdict'].lower()
    assert ssh.connects == []


async def test_an_ambiguous_client_names_the_candidates(ssh: FakeSSH) -> None:
    with pytest.raises(ToolError) as caught:
        await _diagnose(_controller(), 'phone')
    assert caught.value.error_code == ErrorCodes.DEVICE_NOT_FOUND
    assert 'Phone A' in caught.value.message and 'Phone B' in caught.value.message
    assert ssh.connects == []


async def test_a_client_with_no_address_still_checks_dns_and_http(ssh: FakeSSH) -> None:
    result = await _diagnose(_controller(), 'Phone B')
    assert set(result['not_run']) == {'ping', 'flows'}
    assert result['probes']['ping'] == {'not_run': 'no IP address'}
    assert [argv[0] for argv in _argv(ssh)] == ['nslookup', 'ip', 'curl']  # from its VLAN
    assert result['probes']['http']['interface'] == 'br30'
    assert result['ok'] is False


async def test_a_client_on_the_untagged_lan_probes_from_its_interface(ssh: FakeSSH) -> None:
    result = await _diagnose(_controller(), 'Printer')
    assert result['vlan'] == 1 and result['wired'] is True and result['ap'] is None
    curl = next(argv for argv in _argv(ssh) if argv[0] == 'curl')
    assert curl[curl.index('--interface') + 1] == 'br0'


async def test_a_client_whose_network_is_unknown_gets_no_http_probe(ssh: FakeSSH) -> None:
    """Review F5: the gateway's default path is not the client's VLAN, so with the client's
    network unresolved the HTTP layer is not run (never a pass for a path not tested)."""
    result = await _diagnose(_controller(), 'Tablet C')
    assert result['vlan'] is None and result['not_run'] == ['http']
    assert result['probes']['http'] == {'not_run': 'client network unknown'}
    assert [argv[0] for argv in _argv(ssh)] == ['ping', 'nslookup', 'conntrack']  # no curl
    assert result['ok'] is False and result['verdict'].startswith('Inconclusive')
    assert 'No connectivity fault found' not in result['verdict']


@pytest.mark.parametrize(
    'url', ['http://203.0.113.10/hotspot-detect.html', 'http://[2001:db8::10]/hotspot.html']
)
async def test_a_probe_url_whose_host_is_an_address_gets_no_dns_layer(
    ssh: FakeSSH, url: str
) -> None:
    """Review R4-011: an address needs no lookup (an IPv6 one failed the hostname check, an
    IPv4 one asked for a reverse lookup that read as a DNS failure)."""
    async with serving(_controller()):
        result = await diagnose_client_connectivity('Phone A', probe_url=url)
    assert result['probes']['dns'] == {'not_run': 'probe URL host is an address'}
    assert 'nslookup' not in [argv[0] for argv in _argv(ssh)]
    assert result['verdict'].startswith('Inconclusive') and 'DNS' in result['verdict']


async def test_no_ssh_password_fails_before_the_controller_is_asked(
    ssh: FakeSSH, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv('UNIFI_SSH_PASSWORD')
    controller = _controller()
    with pytest.raises(ToolError) as caught:
        await _diagnose(controller)
    assert caught.value.error_code == ErrorCodes.CONFIG_MISSING
    assert controller.calls == [] and ssh.connects == []


@pytest.mark.parametrize(
    ('query', 'url'),
    [
        ('', PROBE_URL),
        ('x' * 129, PROBE_URL),
        ('Phone A', 'ftp://captive.example.com/'),
        ('Phone A', 'https://user:' + 'FAKE-URL-PW' + '@captive.example.com/'),
    ],
    ids=['empty', 'too long', 'not http', 'userinfo'],
)
async def test_bad_arguments_are_refused_before_anything_connects(
    ssh: FakeSSH, query: str, url: str
) -> None:
    controller = _controller()
    async with serving(controller):
        with pytest.raises(ToolError) as caught:
            await diagnose_client_connectivity(query, probe_url=url)
    assert caught.value.error_code == ErrorCodes.CONFIG_INVALID
    assert controller.calls == [] and ssh.connects == []


def test_the_defaults_are_the_design_s() -> None:
    assert CHAIN_BUDGET_SECONDS == 120
    assert CAPTIVE_PROBE_URL.startswith('http://')


def test_there_is_no_mcp_tool() -> None:
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    categories = ToolRegistry(default_manifests_dir(), strict=True).get_categories()
    assert 'diagnose_client_connectivity' not in {n for ns in categories.values() for n in ns}


# --- the CLI ------------------------------------------------------------------------------


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, ssh: FakeSSH) -> FakeController:
    controller = _controller()
    route_cli(monkeypatch, controller)
    return controller


def test_the_command_prints_json_and_the_notice_once(cli: FakeController) -> None:
    args = ['diagnose', 'client-connectivity', 'Phone A', '--probe-url', PROBE_URL, '--json']
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data['ok'] is True and data['client_ip'] == '198.51.100.50'
    assert result.stderr.count('host key') == 1
    assert cli.methods == {'GET'}


def test_a_fault_exits_1_and_prints_the_findings(cli: FakeController, ssh: FakeSSH) -> None:
    ssh.replies = {**REPLIES, 'curl': ('000 0.000 -', 'curl: (7) failed to connect', 7)}
    result = runner.invoke(app, ['diagnose', 'client-connectivity', 'Phone A'])
    assert result.exit_code == 1, result.output
    flat = ' '.join(result.stdout.split())
    assert 'Connectivity fault found' in flat and 'br30' in flat


def test_a_bad_probe_url_is_one_error_line(cli: FakeController, ssh: FakeSSH) -> None:
    url = 'https://user:' + 'FAKE-URL-PW' + '@captive.example.com/'
    result = runner.invoke(app, ['diagnose', 'client-connectivity', 'Phone A', '--probe-url', url])
    assert result.exit_code == 1 and result.stdout == ''
    assert 'FAKE-URL-PW' not in result.stderr
    assert ssh.connects == [] and cli.calls == []


def test_the_command_has_help() -> None:
    result = runner.invoke(app, ['diagnose', 'client-connectivity', '--help'])
    assert result.exit_code == 0
    flat = ' '.join(result.output.split())
    assert 'SSH' in flat and 'host key is verified' in flat and '120' in flat
    assert 'UNIFI_SSH_PASSWORD' in flat  # review finding: what it needs before it runs
    root = typer.main.get_command(app)
    assert isinstance(root, click.Group)
    group = root.commands['diagnose']
    assert isinstance(group, click.Group)
    params = group.commands['client-connectivity'].params
    option = next(p for p in params if p.name == 'probe_url')
    # review finding: the query is run as given, on the gateway's command line.
    assert 'no secret in its query' in (getattr(option, 'help', None) or '')
