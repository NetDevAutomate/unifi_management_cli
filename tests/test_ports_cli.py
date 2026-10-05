"""CLI tests for the read-only `ports` diagnostic commands (no live controller)."""

import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from tests.fixtures_unifi import (
    FAKE_PW,
    FAKE_TOKEN,
    NAS_MAC,
    OTHER_SWITCH_MAC,
    PROFILE_10G_NAME,
    PROFILE_AUTO_NAME,
    SITE,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_devices,
)
from typer.testing import CliRunner
from types import SimpleNamespace
from unifi_mapper import typer_cli
from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.core.utils.readonly import ReadOnlySession, install_read_only_guard
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()


def _plain(result) -> str:
    """The output with Rich panel borders removed and whitespace collapsed."""
    return ' '.join(result.output.replace('│', ' ').split())


PORT_COMMANDS = ('refresh', 'inspect', 'list', 'profile-diff', 'client', 'events', 'counters')


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Run `unifi-mapper` against an in-memory controller, from a temp working dir."""
    return _fake_cli(monkeypatch, tmp_path, default_routes())


def _fake_cli(monkeypatch, tmp_path, routes) -> SimpleNamespace:
    monkeypatch.chdir(tmp_path)
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

    return SimpleNamespace(session=session, client=client, run=run, opened=opened, tmp=tmp_path)


def _json(result) -> dict:
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert_no_secrets(data)
    return data


def test_ports_help_lists_every_subcommand_without_contacting_the_controller(cli):
    result = cli.run('ports', '--help')
    assert result.exit_code == 0
    for command in (*PORT_COMMANDS, 'diagnose'):
        assert command in result.stdout
    assert 'read-only port diagnostics' in result.stdout
    assert cli.opened == [] and cli.session.calls == []


def test_inspect_json_adds_override_and_negotiation_fields(cli):
    data = _json(cli.run('ports', 'inspect', SWITCH_NAME, '5', '--json'))
    assert data['port_idx'] == 5
    assert data['override']['portconf_id']
    assert data['link']['speed_caps'] is not None
    assert data['counters']['rx']['crc_errors'] == 3


def test_list_json(cli):
    data = _json(cli.run('ports', 'list', SWITCH_MAC, '--json'))
    assert data['schema_version'] == 1
    assert data['device']['name'] == SWITCH_NAME and data['device']['raw'] is None
    assert [p['port_idx'] for p in data['ports']] == [1, 2, 3, 4, 5]


def test_list_raw_includes_the_sanitised_device_record(cli):
    data = _json(cli.run('ports', 'list', SWITCH_NAME, '--json', '--raw'))
    assert data['device']['raw']['serial'] == 'aaaaaaaaaa0001'
    assert 'x_authkey' not in data['device']['raw']


def test_profile_diff_json(cli):
    data = _json(cli.run('ports', 'profile-diff', PROFILE_10G_NAME, PROFILE_AUTO_NAME, '--json'))
    assert [d['key'] for d in data['differences']] == ['autoneg']
    assert data['only_in_a'] == ['speed']


def test_profile_diff_unknown_profile_exits_1_and_lists_names(cli):
    result = cli.run('ports', 'profile-diff', 'Nope', PROFILE_AUTO_NAME)
    assert result.exit_code == 1
    assert PROFILE_10G_NAME in result.stderr


def test_client_json_checks_the_target_port(cli):
    data = _json(
        cli.run('ports', 'client', NAS_MAC, '--switch', SWITCH_NAME, '--port', '5', '--json')
    )
    assert data['resolved_macs'] == [NAS_MAC]
    assert data['records'][0]['matches_target'] is True


def test_client_port_without_switch_is_a_usage_error(cli):
    result = cli.run('ports', 'client', NAS_MAC, '--port', '5')
    assert result.exit_code == 2
    assert cli.opened == []


def test_events_json(cli):
    data = _json(cli.run('ports', 'events', SWITCH_NAME, '5', '--client', NAS_MAC, '--json'))
    assert data['match']['port'] == 5 and data['match']['client_macs'] == [NAS_MAC]
    assert data['matched_total'] >= 1
    assert set(data['sources']['system_log']) == {
        'device-alert',
        'admin-activity',
        'update-alert',
        'client-alert',
    }


def test_events_skips_device_rows_that_are_not_records(monkeypatch, tmp_path):
    devices = {'data': [*fake_devices(), 'not-a-record', None]}
    cli = _fake_cli(monkeypatch, tmp_path, default_routes(devices=devices))
    data = _json(cli.run('ports', 'events', SWITCH_NAME, '5', '--json'))
    assert data['matched_total'] >= 1


def test_counters_single_sample_json(cli):
    baseline = cli.tmp / 'baseline.json'
    # An explicit read-only baseline must exist (item 19), so the test writes it.
    baseline.write_text('{"timestamp": "2026-10-01T00:00:00", "devices": []}', encoding='utf-8')
    data = _json(
        cli.run(
            'ports',
            'counters',
            SWITCH_NAME,
            '5',
            '--samples',
            '1',
            '--link-error-baseline',
            str(baseline),
            '--json',
        )
    )
    assert data['verdict'] == 'single_sample'
    link = data['baselines']['link_error_tracking']
    assert link['found'] is True and link['device_present'] is False
    assert link['path'] == str(baseline)


def test_counters_rejects_a_flag_given_as_the_baseline_path(cli):
    # Regression: Click read `--json` as the baseline path and printed tables instead.
    result = cli.run('ports', 'counters', SWITCH_NAME, '5', '--link-error-baseline', '--json')
    assert result.exit_code == 2
    text = _plain(result)
    assert "Invalid value for '--link-error-baseline'" in text
    assert "expected a file path, got the option '--json'" in text
    assert cli.opened == []


@pytest.mark.parametrize('option', ['--link-error-baseline', '--history'])
def test_counters_rejects_an_explicit_missing_file(cli, option):
    missing = cli.tmp / 'missing.json'
    result = cli.run('ports', 'counters', SWITCH_NAME, '5', option, str(missing), '--json')
    assert result.exit_code == 2
    # Rich wraps long paths mid-word inside the error panel, so compare without whitespace.
    squashed = ''.join(_plain(result).split())
    assert f'filenotfound:{missing};omittheoptiontouse' in squashed
    assert cli.opened == []


def test_counters_rejects_a_flag_given_as_the_history_path(cli):
    result = cli.run('ports', 'counters', SWITCH_NAME, '5', '--history', '--json')
    assert result.exit_code == 2
    assert "'--history': expected a file path, got the option '--json'" in _plain(result)
    assert cli.opened == []


def test_counters_with_an_existing_history_file(cli):
    from unifi_mapper.analysis.counter_history import append_history, build_history_records

    history = cli.tmp / 'h.jsonl'
    append_history(
        build_history_records(fake_devices(), taken_at='T', epoch=1.0), path=history, now=1.0
    )
    data = _json(
        cli.run(
            'ports',
            'counters',
            SWITCH_NAME,
            '5',
            '--samples',
            '1',
            '--history',
            str(history),
            '--json',
        )
    )
    assert data['baselines']['history']['path'] == str(history)
    assert data['baselines']['history']['records'] == 1


def test_counters_without_the_option_reports_found_false(cli):
    data = _json(cli.run('ports', 'counters', SWITCH_NAME, '5', '--samples', '1', '--json'))
    link = data['baselines']['link_error_tracking']
    assert link['found'] is False and link['legacy'] is False
    assert link['path'].endswith('unifi_mapper/link-error-baseline.json')


def test_counters_json_includes_the_recorded_history(cli):
    from unifi_mapper.analysis.counter_history import (
        append_history,
        build_history_records,
        default_history_path,
    )

    without = _json(cli.run('ports', 'counters', SWITCH_NAME, '5', '--samples', '1', '--json'))
    assert without['baselines']['history']['found'] is False
    assert without['baselines']['history']['path'] == str(default_history_path())
    assert not default_history_path().exists()  # reading created nothing

    append_history(build_history_records(fake_devices(), taken_at='T', epoch=1.0), now=1.0)
    data = _json(cli.run('ports', 'counters', SWITCH_NAME, '5', '--samples', '1', '--json'))

    history = data['baselines']['history']
    assert history['found'] is True and history['records'] == 1
    assert history['points'][0]['rx_crc_errors'] == 3
    assert set(history['first_increase']) >= {'rx_errors', 'rx_crc_errors', 'link_down_count'}


def test_counters_table_prints_a_history_line(cli):
    result = cli.run('ports', 'counters', SWITCH_NAME, '5', '--samples', '1')
    assert result.exit_code == 0, result.output
    assert 'counter history' in result.stdout and 'analyze link-errors --record' in result.stdout


@pytest.mark.parametrize('args', [('--samples', '9'), ('--interval', '5')])
def test_counters_rejects_out_of_range_sampling(cli, args):
    result = cli.run('ports', 'counters', SWITCH_NAME, '5', *args)
    assert result.exit_code == 2 and cli.opened == []


def test_diagnose_writes_the_bundle_and_prints_a_summary(cli):
    out = cli.tmp / 'bundle.json'
    result = cli.run(
        'ports',
        'diagnose',
        SWITCH_NAME,
        '5',
        '--samples',
        '1',
        '--compare-profile',
        PROFILE_10G_NAME,
        '--compare-profile',
        PROFILE_AUTO_NAME,
        '-o',
        str(out),
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data['schema_version'] == 1
    assert data['profiles']['a']['name'] == PROFILE_10G_NAME
    assert data['request_audit']
    assert_no_secrets(data)
    assert 'bundle.json' in result.stdout


def test_diagnose_default_output_goes_under_reports(cli):
    result = cli.run('ports', 'diagnose', SWITCH_NAME, '5', '--samples', '1', '--json')
    data = _json(result)
    [written] = list((cli.tmp / 'reports').glob('port-diagnostics-usw-flex-xg-p5-*.json'))
    assert json.loads(written.read_text())['query'] == data['query']


def test_diagnose_needs_zero_or_two_compare_profiles(cli):
    result = cli.run('ports', 'diagnose', SWITCH_NAME, '5', '--compare-profile', 'A')
    assert result.exit_code == 2
    assert cli.opened == [] and cli.session.calls == []


def test_ambiguous_switch_exits_1_and_prints_the_candidates(cli):
    result = cli.run('ports', 'list', 'Flex XG')
    assert result.exit_code == 1
    assert SWITCH_MAC in result.stderr and OTHER_SWITCH_MAC in result.stderr


def test_missing_port_exits_1(cli):
    result = cli.run('ports', 'inspect', SWITCH_NAME, '9')
    assert result.exit_code == 1
    assert 'valid ports' in result.stderr


@pytest.mark.parametrize(
    ('args', 'expected'),
    [
        (('list', SWITCH_NAME), 'Ports'),
        (('profile-diff', PROFILE_10G_NAME, PROFILE_AUTO_NAME), 'Settings that differ'),
        (('client', 'ugreen-nas', '--switch', SWITCH_NAME, '--port', '5'), 'Client records'),
        (('events', SWITCH_NAME, '5'), 'Matched entries'),
        (('counters', SWITCH_NAME, '5', '--samples', '1'), 'Verdict'),
        (('inspect', SWITCH_NAME, '5'), 'Link state'),
    ],
)
def test_rich_output_renders(cli, args, expected):
    result = cli.run('ports', *args)
    assert result.exit_code == 0, result.output
    assert expected in result.stdout
    assert_no_secrets(result.stdout)


def test_every_command_is_read_only_at_the_transport(cli):
    for args in (
        ('list', SWITCH_NAME, '--json'),
        ('events', SWITCH_NAME, '5', '--json'),
        ('diagnose', SWITCH_NAME, '5', '--samples', '1', '--json'),
    ):
        assert cli.run('ports', *args).exit_code == 0
    assert isinstance(cli.client.session, ReadOnlySession)
    assert {c['method'] for c in cli.session.calls} <= {'GET', 'POST'}


# ---------------------------------------------------------------------------
# The real _readonly_client: config source and guard
# ---------------------------------------------------------------------------


class _LoginClient(UnifiApiClient):
    """A real client whose login succeeds against the fake transport."""

    instances: list['_LoginClient'] = []
    login_result = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _LoginClient.instances.append(self)

    def login(self) -> bool:
        if not self.login_result:
            return False
        self.is_authenticated = True
        self.is_unifi_os = True
        self.session = FakeSession(default_routes())
        return True


@pytest.fixture
def real_wrapper(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in ('UNIFI_URL', 'UNIFI_CONSOLE_API_TOKEN', 'UNIFI_SITE'):
        monkeypatch.setenv(key, 'placeholder')  # restored after the test
    config = tmp_path / 'prod.env'
    config.write_text(
        f'UNIFI_URL=https://192.0.2.1\nUNIFI_CONSOLE_API_TOKEN={FAKE_TOKEN}\nUNIFI_SITE=default\n'
    )
    # A stray ./.env pointing elsewhere must never be read.
    (tmp_path / '.env').write_text('UNIFI_URL=https://198.51.100.99\n')
    _LoginClient.instances = []
    _LoginClient.login_result = True
    monkeypatch.setattr('unifi_mapper.api_client.UnifiApiClient', _LoginClient)
    return config


def test_readonly_client_uses_only_the_config_file_and_installs_the_guard(real_wrapper):
    result = runner.invoke(
        app, ['--config', str(real_wrapper), 'ports', 'list', SWITCH_NAME, '--json']
    )
    assert result.exit_code == 0, result.output
    [client] = _LoginClient.instances
    assert client.base_url == 'https://192.0.2.1'
    assert isinstance(client.session, ReadOnlySession)
    assert client.is_authenticated is False  # logged out afterwards


def test_readonly_client_exits_1_when_login_fails(real_wrapper):
    _LoginClient.login_result = False
    result = runner.invoke(app, ['--config', str(real_wrapper), 'ports', 'list', SWITCH_NAME])
    assert result.exit_code == 1
    assert 'Could not authenticate' in result.stderr


# ---------------------------------------------------------------------------
# No CLI error prints a secret (issue 058)
# ---------------------------------------------------------------------------


@pytest.fixture
def password_wrapper(real_wrapper):
    """The real _readonly_client on a username-and-password config holding FAKE_PW."""
    real_wrapper.write_text(
        'UNIFI_URL=https://192.0.2.1\nUNIFI_USERNAME=admin\n'
        f'UNIFI_PASSWORD={FAKE_PW}\nUNIFI_SITE=default\n'
    )
    return real_wrapper


def test_an_unexpected_read_error_is_one_redacted_line(monkeypatch, password_wrapper):
    def _boom(*_args, **_kwargs):
        raise RuntimeError(f'boom, password={FAKE_PW}')

    monkeypatch.setattr('unifi_mapper.port_diagnostics.list_switch_ports', _boom)
    result = runner.invoke(app, ['--config', str(password_wrapper), 'ports', 'list', SWITCH_NAME])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # a clean exit, not a traceback
    assert '❌ Error: boom' in result.stderr
    assert FAKE_PW not in result.output


def test_a_login_failure_keeps_its_own_message_and_exits_once(password_wrapper):
    _LoginClient.login_result = False
    result = runner.invoke(app, ['--config', str(password_wrapper), 'ports', 'list', SWITCH_NAME])
    assert result.exit_code == 1
    assert 'Could not authenticate' in result.stderr
    assert result.stderr.count('❌') == 1
    assert 'Error: 1' not in result.stderr
    assert FAKE_PW not in result.output


def test_bundle_file_has_no_host_in_the_audit(cli):
    out = Path(cli.tmp) / 'b.json'
    assert (
        cli.run('ports', 'diagnose', SWITCH_NAME, '5', '--samples', '1', '-o', str(out)).exit_code
        == 0
    )
    audit = json.loads(out.read_text())['request_audit']
    assert all(set(entry) == {'method', 'path'} for entry in audit)
    assert not any('192.0.2.1' in entry['path'] for entry in audit)
