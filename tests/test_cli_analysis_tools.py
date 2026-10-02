"""CLI tests for the read-only fleet audits under `unifi-mapper analyze` (no live controller)."""

import importlib
import json
import pytest
from contextlib import contextmanager
from tests.fixtures_unifi import (
    NOW,
    PROF_10G,
    PROF_TRUNK,
    PROFILE_10G_NAME,
    PROFILE_AUTO_NAME,
    SITE,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_other_switch,
    fake_peer,
    fake_port,
    fake_portconf,
    fake_switch,
)
from typer.testing import CliRunner
from types import SimpleNamespace
from unifi_mapper import typer_cli
from unifi_mapper.analysis import link_speed_audit
from unifi_mapper.analysis.link_speed_audit import MAX_LIMIT, collect_link_speed_audit
from unifi_mapper.analysis.port_profile_usage import collect_port_profile_usage
from unifi_mapper.core.models import (
    APClientDensity,
    ClientDensityReport,
    DeviceUplinkStatus,
    DHCPPoolReport,
    DHCPPoolStatus,
    PoEBudgetReport,
    PoEDeviceStatus,
    PoEPortDetail,
    UplinkInfo,
    UplinkRedundancyReport,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import ReadOnlySession, install_read_only_guard
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
AUTO_ONLY = {
    'data': [
        fake_switch(port_overrides=[{'port_idx': 2, 'portconf_id': PROF_TRUNK}]),
        fake_other_switch(),
        fake_peer(),
    ]
}


def _fake_cli(monkeypatch, tmp_path, routes) -> SimpleNamespace:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(link_speed_audit, '_now', lambda: NOW)
    session = FakeSession(routes)
    client = fake_client(session)
    install_read_only_guard(client)
    opened: list[bool] = []

    @contextmanager
    def fake_readonly_client():
        opened.append(True)
        yield client, SITE

    monkeypatch.setattr(typer_cli, '_readonly_client', fake_readonly_client)

    def run(*args: str):
        return runner.invoke(app, list(args))

    return SimpleNamespace(session=session, client=client, run=run, opened=opened)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    return _fake_cli(monkeypatch, tmp_path, default_routes())


def _expected(routes, **kw) -> dict:
    client = fake_client(FakeSession(routes))
    return collect_link_speed_audit(
        client, SITE, limit=MAX_LIMIT, now=lambda: NOW, **kw
    ).model_dump(mode='json')


# ---------------------------------------------------------------------------
# analyze link-speeds
# ---------------------------------------------------------------------------


def test_link_speeds_json_equals_the_model_dump_and_exits_2_on_high(cli):
    result = cli.run('analyze', 'link-speeds', '--json')
    assert result.exit_code == 2, result.output
    data = json.loads(result.stdout)
    assert_no_secrets(data)
    assert data == _expected(default_routes())
    assert data['validation_passed'] is False
    assert data['findings'][0]['code'] == 'FORCED_SPEED_MISMATCH'
    assert isinstance(cli.client.session, ReadOnlySession)
    assert {c['method'] for c in cli.session.calls} == {'GET'}


def test_link_speeds_exits_0_without_critical_or_high(monkeypatch, tmp_path):
    routes = default_routes(devices=AUTO_ONLY)
    cli = _fake_cli(monkeypatch, tmp_path, routes)
    result = cli.run('analyze', 'link-speeds', '--switch', SWITCH_NAME, '--json')
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data == _expected(routes, switch=SWITCH_NAME)
    assert [(f['port_idx'], f['code']) for f in data['findings']] == [(5, 'BELOW_PORT_CAPABILITY')]


def test_link_speeds_include_ok_and_short_switch_option(cli):
    result = cli.run('analyze', 'link-speeds', '-s', SWITCH_MAC, '--include-ok', '--json')
    assert result.exit_code == 2
    data = json.loads(result.stdout)
    assert {f['code'] for f in data['findings']} == {'OK', 'FORCED_SPEED_MISMATCH'}
    assert {f['switch_mac'] for f in data['findings']} == {SWITCH_MAC}


def test_link_speeds_table_output(cli):
    result = cli.run('analyze', 'link-speeds')
    assert result.exit_code == 2
    assert 'Link Speed Audit' in result.stdout
    assert 'Link Speed Findings' in result.stdout
    assert f'{SWITCH_NAME} port 5' in result.stdout
    assert 'Integration API: ok' in result.stdout


def test_link_speeds_unknown_switch_exits_1_listing_switches(cli):
    result = cli.run('analyze', 'link-speeds', '--switch', 'nope')
    assert result.exit_code == 1
    assert SWITCH_NAME in result.stderr


def test_link_speeds_help_does_not_contact_the_controller(cli):
    result = cli.run('analyze', 'link-speeds', '--help')
    assert result.exit_code == 0
    assert 'speed_caps' in result.stdout and '--include-ok' in result.stdout
    assert cli.opened == [] and cli.session.calls == []


# ---------------------------------------------------------------------------
# analyze port-profile-usage
# ---------------------------------------------------------------------------

UNUSED = {'_id': '0000000000000000000000b8', 'name': 'Spare', 'forward': 'disabled'}


def _usage_expected(routes, **kw) -> dict:
    client = fake_client(FakeSession(routes))
    return collect_port_profile_usage(client, SITE, limit=MAX_LIMIT, **kw).model_dump(mode='json')


def test_port_profile_usage_json_equals_the_model_dump(monkeypatch, tmp_path):
    from unifi_mapper.analysis import port_profile_usage

    monkeypatch.setattr(port_profile_usage, '_now', lambda: NOW)
    routes = default_routes(portconf={'data': [*fake_portconf(), UNUSED]})
    cli = _fake_cli(monkeypatch, tmp_path, routes)
    result = cli.run('analyze', 'port-profile-usage', '--json')
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert_no_secrets(data)
    assert data == _usage_expected(routes, now=lambda: NOW)
    assert {f['code'] for f in data['findings']} == {'FORCED_SPEED_PROFILE', 'UNUSED_PROFILE'}
    assert {c['method'] for c in cli.session.calls} == {'GET'}

    hidden = json.loads(cli.run('analyze', 'port-profile-usage', '--hide-unused', '--json').stdout)
    assert UNUSED['_id'] not in {p['id'] for p in hidden['profiles']}


def test_port_profile_usage_profile_option(cli):
    result = cli.run('analyze', 'port-profile-usage', '--profile', PROFILE_10G_NAME, '--json')
    assert result.exit_code == 0, result.output
    assert [p['id'] for p in json.loads(result.stdout)['profiles']] == [PROF_10G]


def test_port_profile_usage_exits_2_on_a_dangling_reference(monkeypatch, tmp_path):
    ports = [fake_port(1), fake_port(3, portconf_id='0000000000000000000000ff')]
    devices = {'data': [fake_switch(port_table=ports), fake_other_switch(), fake_peer()]}
    cli = _fake_cli(monkeypatch, tmp_path, default_routes(devices=devices))
    result = cli.run('analyze', 'port-profile-usage', '--json')
    assert result.exit_code == 2
    assert json.loads(result.stdout)['findings'][0]['code'] == 'DANGLING_PROFILE_REF'


def test_port_profile_usage_table_output(cli):
    result = cli.run('analyze', 'port-profile-usage')
    assert result.exit_code == 0, result.output
    assert 'Port Profile Usage' in result.stdout and 'Port Profiles' in result.stdout


def test_port_profile_usage_unknown_profile_exits_1_listing_names(cli):
    result = cli.run('analyze', 'port-profile-usage', '--profile', 'nope')
    assert result.exit_code == 1
    assert PROFILE_AUTO_NAME in result.stderr


@pytest.mark.parametrize(
    ('command', 'references'),
    [
        (
            'port-profile-usage',
            ('analyze port-profiles', 'ports profile-diff', 'analyze link-speeds'),
        ),
        ('link-speeds', ('analyze port-profile-usage',)),
        ('port-profiles', ('analyze port-profile-usage',)),
    ],
)
def test_help_texts_cross_reference(cli, command, references):
    result = cli.run('analyze', command, '--help')
    assert result.exit_code == 0
    text = ' '.join(result.stdout.split())
    for reference in references:
        assert reference in text, reference
    assert cli.opened == []


# ---------------------------------------------------------------------------
# analyze poe-budget | uplink-redundancy | client-density | dhcp-pools
# ---------------------------------------------------------------------------

POE_REPORT = PoEBudgetReport(
    timestamp='2026-10-02T12:00:00',
    devices_analyzed=1,
    total_budget=100.0,
    total_consumption=88.0,
    devices=[
        PoEDeviceStatus(
            device_id='sw-core',
            device_name='Core PoE',
            model='USW-Pro-24-PoE',
            poe_budget=100.0,
            poe_consumption=88.0,
            poe_available=12.0,
            utilization_percent=88.0,
            status='WARNING',
            high_draw_ports=[PoEPortDetail(port_idx=1, port_name='AP', poe_power=85.0)],
        )
    ],
    warnings=['Core PoE: PoE at 88%'],
)
UPLINK_REPORT = UplinkRedundancyReport(
    timestamp='2026-10-02T12:00:00',
    devices_analyzed=1,
    single_uplink_devices=1,
    redundant_devices=0,
    devices=[
        DeviceUplinkStatus(
            device_id='sw-edge',
            device_name='Edge',
            model='USW-Flex-XG',
            uplinks=[UplinkInfo(port_idx=1, speed_mbps=10000, is_up=True)],
            uplink_count=1,
            redundant=False,
            total_uplink_speed_mbps=10000,
            status='WARNING',
        )
    ],
    warnings=['Edge: single uplink — potential single point of failure'],
    recommendations=['Consider adding a redundant uplink to Edge'],
)
DENSITY_REPORT = ClientDensityReport(
    timestamp='2026-10-02T12:00:00',
    aps_analyzed=1,
    total_wireless_clients=31,
    access_points=[
        APClientDensity(
            device_id='ap-1',
            device_name='Office AP',
            model='U7-Pro',
            client_count=31,
            avg_signal_dbm=-60.0,
            status='WARNING',
        )
    ],
)
DHCP_REPORT = DHCPPoolReport(
    timestamp='2026-10-02T12:00:00',
    networks_analyzed=1,
    total_pool_size=34,
    total_active_clients=31,
    pools=[
        DHCPPoolStatus(
            network_id='net-iot',
            network_name='IoT',
            vlan_id=30,
            pool_start='10.0.30.10',
            pool_stop='10.0.30.43',
            pool_size=34,
            active_clients=31,
            utilization_percent=91.2,
            status='CRITICAL',
        )
    ],
)

# command -> (module, coroutine name, fixture report, a string the table must show)
EXPOSED_COMMANDS = {
    'poe-budget': ('poe_budget', 'check_poe_budget', POE_REPORT, 'PoE Budget per Switch'),
    'uplink-redundancy': (
        'uplink_redundancy',
        'check_uplink_redundancy',
        UPLINK_REPORT,
        'Uplinks per Switch',
    ),
    'client-density': (
        'client_density',
        'analyze_client_density',
        DENSITY_REPORT,
        'Clients per Access Point',
    ),
    'dhcp-pools': ('dhcp_pool', 'check_dhcp_pool_utilization', DHCP_REPORT, 'DHCP Pools'),
}


@pytest.fixture
def report_cli(monkeypatch, tmp_path):
    """Run the CLI with each analysis coroutine returning its fixture report."""
    monkeypatch.chdir(tmp_path)
    loaded: list[str] = []
    monkeypatch.setattr(typer_cli, 'load_env_from_config', loaded.append)
    calls: list[str] = []
    for module_name, coro_name, report, _ in EXPOSED_COMMANDS.values():

        async def _fake(report=report, coro_name=coro_name):
            calls.append(coro_name)
            return report

        module = importlib.import_module(f'unifi_mapper.analysis.{module_name}')
        monkeypatch.setattr(module, coro_name, _fake)

    def run(*args: str):
        return runner.invoke(app, list(args))

    return SimpleNamespace(run=run, calls=calls, loaded=loaded)


@pytest.mark.parametrize('command', sorted(EXPOSED_COMMANDS))
def test_exposed_analysis_json_equals_the_model_dump(report_cli, command):
    _, coro_name, report, _ = EXPOSED_COMMANDS[command]
    result = report_cli.run('analyze', command, '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == report.model_dump(mode='json')
    assert report_cli.calls == [coro_name]
    assert len(report_cli.loaded) == 1


@pytest.mark.parametrize('command', sorted(EXPOSED_COMMANDS))
def test_exposed_analysis_table_output(report_cli, command):
    result = report_cli.run('analyze', command)
    assert result.exit_code == 0, result.output
    assert EXPOSED_COMMANDS[command][3] in result.stdout


def test_poe_budget_table_shows_status_and_warnings(report_cli):
    result = report_cli.run('analyze', 'poe-budget')
    assert 'Core PoE' in result.stdout and 'WARNING' in result.stdout
    assert 'PoE at 88%' in result.stdout


def test_poe_budget_help_distinguishes_it_from_power_budget(report_cli):
    result = report_cli.run('analyze', 'poe-budget', '--help')
    assert result.exit_code == 0
    text = ' '.join(result.stdout.split())
    assert 'analyze power-budget' in text and 'OUTPUT' in text and 'INPUT' in text
    assert report_cli.calls == [] and report_cli.loaded == []


def test_exposed_analysis_tool_error_prints_red_and_exits_1(monkeypatch, report_cli):
    from unifi_mapper.analysis import dhcp_pool

    async def _down():
        raise ToolError(
            message='Cannot connect to UniFi controller',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
        )

    monkeypatch.setattr(dhcp_pool, 'check_dhcp_pool_utilization', _down)
    result = report_cli.run('analyze', 'dhcp-pools', '--json')
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'Cannot connect to UniFi controller' in result.stderr


def test_exposed_analysis_unexpected_error_is_redacted(monkeypatch, report_cli):
    from unifi_mapper.analysis import poe_budget

    async def _boom():
        raise RuntimeError('boom password=FAKE-SECRET-VALUE')  # pragma: allowlist secret

    monkeypatch.setattr(poe_budget, 'check_poe_budget', _boom)
    result = report_cli.run('analyze', 'poe-budget')
    assert result.exit_code == 1
    assert 'boom' in result.stderr
    assert 'FAKE-SECRET-VALUE' not in result.stderr
