"""Device stats, AP retry rates, config objects and config-change timelines (observability).

Ported from the prototype (a local archive, not in the repo) and adapted: documentation
values only, the house ``strip_secrets`` instead of the prototype's masking, and every handler driven
through the real read-only guard over ``tests/fake_controller.py``, so each test can assert
that only GETs left the host.
"""

import anyio
import asyncio
import json
import pytest
from datetime import UTC, datetime
from pathlib import Path
from tests.fake_controller import API, V2, FakeController, legacy, route_cli, serving
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics import observability
from unifi_mapper.diagnostics.observability import (
    config_objects_from_data,
    device_stats_from_data,
    find_recent_config_changes,
    get_ap_retry_rates,
    get_config_object,
    get_device_stats,
    merge_config_change_timeline,
    objectid_created,
    retry_rates_from_samples,
)
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.mcp.runner import ToolRunner
from unifi_mapper.typer_cli import app


runner = CliRunner()
FAKE_SYSLOG_KEY = 'FAKE-SYSLOG-KEY-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_COMMUNITY = 'FAKE-COMMUNITY-MUST-NOT-APPEAR'  # pragma: allowlist secret
FAKE_PSK = 'FAKE-PSK-MUST-NOT-APPEAR'  # pragma: allowlist secret
OID_2023 = '64b8f000' + '0' * 16  # 0x64b8f000 = 2023-07-20T08:27:44Z
OID_2024 = '65b8f000' + '0' * 16  # 0x65b8f000 = 2024-01-30T12:48:00Z


def _vap(essid: str, radio: str, tx_packets: Any, tx_retries: Any, **over: Any) -> dict:
    return {
        'essid': essid,
        'radio': radio,
        'channel': {'ng': 6, 'na': 36, '6e': 37}[radio],
        'num_sta': 4,
        'tx_packets': tx_packets,
        'tx_retries': tx_retries,
        'tx_dropped': 1,
        'rx_packets': 900,
        **over,
    }


def _ap(name: str = 'AP 1', mac: str = '02:00:00:00:01:01', vaps: Any = None, **over: Any) -> dict:
    dev = {
        'name': name,
        'mac': mac,
        'model': 'U6IW',
        'type': 'uap',
        'ip': '192.0.2.21',
        'version': '6.8.2',
        'state': 1,
        'uptime': 86400,
        'startup_timestamp': 1_790_000_000,
        'syslog_key': FAKE_SYSLOG_KEY,
        'x_authkey': FAKE_PSK,
        'system-stats': {'cpu': '12.5', 'mem': '43.0'},
        'sys_stats': {'loadavg_1': '0.85'},
        'radio_table_stats': [
            {'radio': 'ng', 'channel': 6, 'cu_total': 97, 'tx_power': 12, 'num_sta': 4},
            {'radio': 'na', 'channel': 36, 'cu_total': 15, 'tx_power': 20, 'num_sta': 2},
            {'radio': '6e', 'channel': 37, 'cu_total': 5, 'tx_power': 18, 'num_sta': 1},
        ],
        'vap_table': vaps
        if vaps is not None
        else [
            _vap('SSID A', 'ng', 10_000, 2_400),
            _vap('SSID B', 'na', 50_000, 1_000),
            _vap('SSID A', '6e', 4_000, 40),
        ],
    }
    dev.update(over)
    return dev


SWITCH = {
    'name': 'Switch A',
    'mac': '02:00:00:00:00:01',
    'type': 'usw',
    'model': 'USW',
    'state': 1,
}


# --- device_stats_from_data ---------------------------------------------------------------


def test_device_stats_reads_identity_and_coerces_string_system_stats() -> None:
    stats = device_stats_from_data(_ap())
    assert (stats['name'], stats['online'], stats['uptime_seconds']) == ('AP 1', True, 86400)
    assert stats['system'] == {'cpu_pct': 12.5, 'mem_pct': 43.0, 'loadavg_1': 0.85}
    bad = device_stats_from_data(_ap(**{'system-stats': {'cpu': 7, 'mem': 'n/a'}}))
    assert bad['system']['cpu_pct'] == 7.0 and bad['system']['mem_pct'] is None


def test_device_stats_lists_every_band_with_cumulative_retry_percentages() -> None:
    stats = device_stats_from_data(_ap())
    assert {r['radio'] for r in stats['radios']} == {'ng', 'na', '6e'}
    by_radio = {v['radio']: v for v in stats['vaps']}
    assert by_radio['ng']['retry_pct_cumulative'] == 24.0
    assert by_radio['6e']['retry_pct_cumulative'] == 1.0  # 6 GHz VAPs are rows like the rest
    assert any('cu_total' in note for note in stats['notes'])


def test_device_stats_tolerates_missing_tables_no_traffic_and_an_offline_device() -> None:
    bare = device_stats_from_data({'name': 'Switch A', 'mac': '02:00:00:00:00:01'})
    assert (bare['radios'], bare['vaps'], bare['notes']) == ([], [], [])
    idle = device_stats_from_data(_ap(vaps=[_vap('SSID A', 'ng', 0, 0)]))
    assert idle['vaps'][0]['retry_pct_cumulative'] is None
    assert device_stats_from_data(_ap(state=0))['online'] is False


# --- retry_rates_from_samples -------------------------------------------------------------


def test_retry_rates_flag_a_vap_above_the_threshold() -> None:
    later = _ap(vaps=[_vap('SSID A', 'ng', 11_000, 2_650)])  # 250 / 1000 = 25%
    result = retry_rates_from_samples([_ap()], [later], radio='ng')
    [row] = result['aps'][0]['vaps']
    assert (row['delta_tx_packets'], row['delta_tx_retries'], row['retry_pct']) == (
        1000,
        250,
        25.0,
    )
    assert row['unhealthy'] is True and result['healthy'] is False
    assert result['flagged'] == [
        {'ap': 'AP 1', 'ap_mac': '02:00:00:00:01:01', 'essid': 'SSID A', 'retry_pct': 25.0}
    ]


def test_retry_rates_below_the_threshold_are_healthy() -> None:
    later = _ap(vaps=[_vap('SSID A', 'ng', 11_000, 2_450)])  # 5%
    result = retry_rates_from_samples([_ap()], [later], radio='ng')
    assert result['aps'][0]['vaps'][0]['unhealthy'] is False and result['healthy'] is True


def test_retry_rates_count_from_zero_after_a_reboot_or_for_a_new_ap() -> None:
    rebooted = _ap(vaps=[_vap('SSID A', 'ng', 100, 30)], uptime=90)
    [row] = retry_rates_from_samples([_ap()], [rebooted], radio='ng')['aps'][0]['vaps']
    assert (row['delta_tx_packets'], row['delta_tx_retries'], row['retry_pct']) == (100, 30, 30.0)
    [new] = retry_rates_from_samples([], [_ap()], radio='ng')['aps'][0]['vaps']
    assert (new['delta_tx_packets'], new['retry_pct']) == (10_000, 24.0)


def test_retry_rates_read_string_counters_and_the_6ghz_band() -> None:
    earlier = _ap(vaps=[_vap('SSID A', '6e', '4000', '40')])
    later = _ap(vaps=[_vap('SSID A', '6e', '5000', '140')])
    [row] = retry_rates_from_samples([earlier], [later], radio='6e')['aps'][0]['vaps']
    assert row['retry_pct'] == 10.0


def test_retry_rates_filter_by_ssid_and_skip_non_aps() -> None:
    assert retry_rates_from_samples([_ap()], [_ap()], essid='No SSID', radio='ng')['aps'] == []
    assert retry_rates_from_samples([SWITCH], [SWITCH], radio='ng')['aps'] == []


# --- objectid_created and config objects ----------------------------------------------


def test_objectid_created_decodes_the_creation_time() -> None:
    assert objectid_created(OID_2023) == datetime(2023, 7, 20, 8, 27, 44, tzinfo=UTC)
    for not_an_id in ('abc123', 'zzzzzzzz00aabbccddeeff00', None, 12345):
        assert objectid_created(not_an_id) is None


def test_config_objects_strip_secrets_and_report_only_their_paths() -> None:
    setting = {'_id': OID_2023, 'key': 'snmp', 'community': FAKE_COMMUNITY, 'enabled': True}
    result = config_objects_from_data('setting', [setting])
    assert result['sanitised_paths'] == ['setting[0].community']
    assert result['objects'] == [
        {
            '_id': OID_2023,
            'key': 'snmp',
            'enabled': True,
            'created_utc': '2023-07-20T08:27:44+00:00',
        }
    ]
    assert FAKE_COMMUNITY not in json.dumps(result)


def test_a_setting_that_names_a_secret_in_its_key_loses_its_value() -> None:
    setting = {'_id': OID_2023, 'key': 'api_token', 'value': FAKE_COMMUNITY}
    result = config_objects_from_data('setting', [setting])
    assert result['sanitised_paths'] == ['setting[0].value']
    assert FAKE_COMMUNITY not in json.dumps(result)


def test_config_objects_filter_by_name_and_index_paths_after_the_filter() -> None:
    wlans = [
        {'_id': OID_2023, 'name': 'SSID A', 'x_passphrase': FAKE_PSK},
        {'_id': 'not-an-id', 'name': 'SSID B', 'x_passphrase': FAKE_PSK},
    ]
    result = config_objects_from_data('wlanconf', wlans, name='ssid b')
    assert result['count'] == 1
    assert result['sanitised_paths'] == ['wlanconf[0].x_passphrase']
    assert result['objects'][0]['created_utc'] is None
    assert any(
        'get_networks' in note for note in config_objects_from_data('networkconf', [])['notes']
    )


# --- merge_config_change_timeline ---------------------------------------------------------

NOW = datetime(2024, 1, 31, 12, 48, 0, tzinfo=UTC)  # one day after OID_2024


def test_the_timeline_keeps_the_window_newest_first_across_kinds() -> None:
    newer = '65b94180' + '0' * 16  # 0x65b94180 = 2024-01-30T18:35:44Z
    rows = {
        'wlanconf': [{'_id': OID_2024, 'name': 'SSID A'}, {'_id': OID_2023, 'name': 'old'}],
        'networkconf': [{'_id': newer, 'name': 'VLAN 20'}, {'_id': 'bad', 'name': 'skipped'}],
        'setting': [],
    }
    result = merge_config_change_timeline(rows, since_hours=48, now=NOW)
    assert [c['name'] for c in result['changes']] == ['VLAN 20', 'SSID A']
    assert result['by_kind'] == {'networkconf': 1, 'wlanconf': 1}
    assert result['changes'][1]['age_hours'] == 24.0
    assert result['window'] == {'since_hours': 48, 'cutoff_utc': '2024-01-29T12:48:00+00:00'}


def test_the_timeline_clamps_a_future_object_s_age_to_zero() -> None:
    rows = {'apgroup': [{'_id': OID_2024, 'name': 'Group A'}]}
    early = datetime(2024, 1, 30, 12, 0, 0, tzinfo=UTC)  # before the object was created
    [change] = merge_config_change_timeline(rows, since_hours=24, now=early)['changes']
    assert (change['kind'], change['age_hours']) == ('apgroup', 0.0)


# --- the async handlers, through the real read-only guard ---------------------------------


def _devices_route(*device_lists: list[dict]) -> Any:
    """Serve each list in turn on successive stat/device reads (the last one repeats)."""
    served = iter(device_lists)
    current: list[list[dict]] = [device_lists[-1]]

    def _serve(_request: Any) -> dict:
        current[0] = next(served, current[0])
        return legacy(current[0])

    return _serve


async def test_get_device_stats_reads_once_and_strips_the_device_s_secrets() -> None:
    controller = FakeController({f'{API}/stat/device': legacy([_ap(), SWITCH])})
    async with serving(controller):
        stats = await get_device_stats('ap 1')
    assert stats['name'] == 'AP 1'
    assert controller.reads == [('GET', f'{API}/stat/device')]
    assert controller.methods == {'GET'}
    assert FAKE_SYSLOG_KEY not in json.dumps(stats) and FAKE_PSK not in json.dumps(stats)


@pytest.mark.parametrize('query', ['AP', 'No such device'])
async def test_get_device_stats_names_the_candidates_when_nothing_or_many_match(
    query: str,
) -> None:
    devices = [_ap(), _ap(name='AP 2', mac='02:00:00:00:01:02')]
    controller = FakeController({f'{API}/stat/device': legacy(devices)})
    async with serving(controller):
        with pytest.raises(ToolError) as exc:
            await get_device_stats(query)
    assert exc.value.error_code == ErrorCodes.DEVICE_NOT_FOUND
    assert exc.value.related_tools == ['find_device']
    assert 'AP 1' in exc.value.message


async def test_get_config_object_uses_the_v2_path_for_ap_groups_and_strips_settings() -> None:
    controller = FakeController(
        {
            f'{API}/rest/setting': legacy(
                [{'_id': OID_2023, 'key': 'snmp', 'community': FAKE_COMMUNITY, 'enabled': True}]
            ),
            f'{V2}/apgroups': [{'_id': OID_2024, 'name': 'Group A', 'device_macs': []}],
        }
    )
    async with serving(controller):
        setting = await get_config_object('setting')
        groups = await get_config_object('apgroup', name='group')
    assert setting['sanitised_paths'] == ['setting[0].community']
    assert groups['count'] == 1 and groups['objects'][0]['name'] == 'Group A'
    assert controller.reads == [('GET', f'{API}/rest/setting'), ('GET', f'{V2}/apgroups')]
    assert controller.methods == {'GET'}


async def test_find_recent_config_changes_reads_each_kind_once_and_none_for_no_kinds() -> None:
    controller = FakeController(
        {
            f'{API}/rest/wlanconf': legacy([{'_id': OID_2024, 'name': 'A'}]),
            f'{API}/rest/networkconf': legacy([]),
            f'{API}/rest/setting': legacy([]),
            f'{V2}/apgroups': [],
        }
    )
    async with serving(controller):
        everything = await find_recent_config_changes(since_hours=8760 * 100)
        nothing = await find_recent_config_changes(kinds=[])
    assert [c['name'] for c in everything['changes']] == ['A']
    assert [path for _, path in controller.reads] == [
        f'{API}/rest/wlanconf',
        f'{API}/rest/networkconf',
        f'{API}/rest/setting',
        f'{V2}/apgroups',
    ]
    assert nothing['count'] == 0  # and no request: the reads above are all there are
    assert controller.methods == {'GET'}


async def test_get_ap_retry_rates_reads_twice_around_the_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paused: list[float] = []

    async def _no_wait(seconds: float) -> None:
        paused.append(seconds)

    monkeypatch.setattr(observability, '_pause', _no_wait)
    later = _ap(vaps=[_vap('SSID A', 'ng', 11_000, 2_650)])
    controller = FakeController({f'{API}/stat/device': _devices_route([_ap()], [later])})
    async with serving(controller):
        result = await get_ap_retry_rates(interval_seconds=10)
    assert paused == [10]
    assert controller.reads == [('GET', f'{API}/stat/device')] * 2
    assert result['interval_seconds'] == 10 and result['flagged'][0]['retry_pct'] == 25.0
    assert controller.methods == {'GET'}


async def test_the_runner_deadline_ends_the_sampling_as_a_timeout_and_cancels_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue 012's reconciliation: the wait is cancellable, so the runner's deadline wins."""
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'FAKE-RUNNER-TOKEN')  # pragma: allowlist secret
    cancelled: list[float] = []

    async def _forever(seconds: float) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(seconds)
            raise

    monkeypatch.setattr(observability, '_pause', _forever)
    controller = FakeController({f'{API}/stat/device': legacy([_ap()])})
    tool_runner = ToolRunner(
        ToolRegistry(default_manifests_dir(), strict=True),
        settings=ServerSettings(tool_timeout=0.2),
    )
    async with serving(controller):
        with anyio.fail_after(5):
            out = await tool_runner.run('get_ap_retry_rates', {'interval_seconds': 10})
    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == 'TIMEOUT'
    assert cancelled == [10]
    assert controller.reads == [('GET', f'{API}/stat/device')]  # the second read never ran


def test_the_ported_handlers_are_coroutine_functions() -> None:
    import inspect

    for handler in (get_device_stats, get_ap_retry_rates, get_config_object):
        assert inspect.iscoroutinefunction(handler)
    assert inspect.iscoroutinefunction(find_recent_config_changes)


# --- the CLI commands ---------------------------------------------------------------------


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> FakeController:
    """Route every CLI command's guarded holder to a fake controller; load no config."""
    fake = FakeController(
        {
            f'{API}/stat/device': legacy([_ap(), SWITCH]),
            f'{API}/rest/wlanconf': legacy(
                [{'_id': OID_2024, 'name': 'SSID A', 'x_passphrase': FAKE_PSK}]
            ),
            f'{API}/rest/networkconf': legacy([]),
            f'{API}/rest/setting': legacy(
                [{'_id': OID_2023, 'key': 'snmp', 'community': FAKE_COMMUNITY}]
            ),
            f'{V2}/apgroups': [],
        }
    )
    route_cli(monkeypatch, fake)
    return fake


def test_device_stats_prints_tables_or_json_without_secrets(controller: FakeController) -> None:
    table = runner.invoke(app, ['diagnose', 'device-stats', 'AP 1'])
    assert table.exit_code == 0, table.output
    assert 'AP 1' in table.stdout and 'SSID A' in table.stdout
    as_json = runner.invoke(app, ['diagnose', 'device-stats', 'AP 1', '--json'])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout)['system']['cpu_pct'] == 12.5
    for result in (table, as_json):
        assert FAKE_SYSLOG_KEY not in result.output and FAKE_PSK not in result.output
    assert controller.methods == {'GET'}


def test_an_unknown_device_is_one_error_line_on_stderr(controller: FakeController) -> None:
    result = runner.invoke(app, ['diagnose', 'device-stats', 'No such device', '--json'])
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'No device matched' in result.stderr


def test_ap_retries_waits_its_interval_and_prints_json(
    monkeypatch: pytest.MonkeyPatch, controller: FakeController
) -> None:
    paused: list[float] = []

    async def _no_wait(seconds: float) -> None:
        paused.append(seconds)

    monkeypatch.setattr(observability, '_pause', _no_wait)
    args = ['diagnose', 'ap-retries', '--interval', '10', '--radio', 'NA', '--json']
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert paused == [10]
    data = json.loads(result.stdout)
    assert data['radio'] == 'na' and data['interval_seconds'] == 10
    assert 'Reading every AP twice' in result.stderr


@pytest.mark.parametrize(
    'args',
    [
        ['diagnose', 'ap-retries', '--interval', '5'],
        ['diagnose', 'ap-retries', '--interval', '241'],
        ['diagnose', 'ap-retries', '--threshold', '101'],
        ['controller', 'config', 'rogueap'],
        ['controller', 'config-changes', '--since-hours', '0'],
    ],
)
def test_out_of_range_or_unknown_options_are_usage_errors(
    controller: FakeController, args: list[str]
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output
    assert controller.calls == []  # refused before connecting


def test_controller_config_strips_secrets_and_lists_their_paths(
    controller: FakeController,
) -> None:
    result = runner.invoke(app, ['controller', 'config', 'SETTING', '--json'])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data['sanitised_paths'] == ['setting[0].community']
    table = runner.invoke(app, ['controller', 'config', 'wlanconf'])
    assert table.exit_code == 0, table.output
    assert 'SSID A' in table.stdout and '1 secret key(s) removed' in table.stdout
    for output in (result.output, table.output):
        assert FAKE_COMMUNITY not in output and FAKE_PSK not in output
    assert controller.methods == {'GET'}


def test_controller_config_changes_searches_the_kinds_given(controller: FakeController) -> None:
    args = ['controller', 'config-changes', '--since-hours', '8760', '--kind', 'wlanconf']
    result = runner.invoke(app, [*args, '--kind', 'apgroup', '--json'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['window']['since_hours'] == 8760
    assert [path for _, path in controller.reads] == [f'{API}/rest/wlanconf', f'{V2}/apgroups']


@pytest.mark.parametrize(
    'command',
    [
        ['diagnose', 'device-stats'],
        ['diagnose', 'ap-retries'],
        ['controller', 'config'],
        ['controller', 'config-changes'],
    ],
)
def test_every_new_command_has_help(command: list[str]) -> None:
    result = runner.invoke(app, [*command, '--help'])
    assert result.exit_code == 0
    assert 'Read-only' in ' '.join(result.output.split())


def test_this_package_resolves_no_real_config(tmp_path: Path) -> None:
    from unifi_mapper.cli import get_default_config_path

    assert not get_default_config_path().exists()
    assert Path.cwd() == tmp_path
