"""CLI tests for the read-only fleet audits under `unifi-mapper analyze` (no live controller)."""

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
