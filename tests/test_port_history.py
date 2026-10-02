"""Tests for event/alarm/system-log history and counter sampling (no live controller)."""

import json
import os
import pytest
from pathlib import Path
from tests.fixtures_unifi import (
    NAS_MAC,
    NOW,
    OTHER_SWITCH_NAME,
    SITE,
    SWITCH_ID,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_switch,
    paged_events,
)
from unifi_mapper.diagnostic_reads import PortNotFound
from unifi_mapper.port_history import (
    EventMatcher,
    collect_events,
    read_counter_baselines,
    sample_port_counters,
)


pytestmark = pytest.mark.usefixtures('block_network')

KNOWN_NAMES = [SWITCH_NAME, OTHER_SWITCH_NAME, 'Test Gateway']


def _client(**routes):
    session = FakeSession(default_routes(**routes))
    return fake_client(session), session


def _events(client, **kwargs):
    kwargs.setdefault('port_idx', 5)
    kwargs.setdefault('known_device_names', KNOWN_NAMES)
    return collect_events(client, SITE, fake_switch(), now=lambda: NOW, **kwargs)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@pytest.fixture
def matcher() -> EventMatcher:
    return EventMatcher(fake_switch(), 5, [NAS_MAC], KNOWN_NAMES)


def test_switch_and_port_field_match(matcher):
    assert matcher.match({'sw': SWITCH_MAC.upper(), 'port': 5}) == (['switch', 'port'], 'mac')
    assert matcher.match({'device_id': SWITCH_ID, 'sw_port': '5'}) == (['switch', 'port'], 'id')


def test_port_text_needs_the_exact_number(matcher):
    assert matcher.match({'sw': SWITCH_MAC, 'msg': 'Port #5 is up'})[0] == ['switch', 'port']
    assert matcher.match({'sw': SWITCH_MAC, 'msg': 'Port 15 link down'})[0] == ['switch']
    assert matcher.match({'sw': SWITCH_MAC, 'msg': 'port 50 flapped'})[0] == ['switch']


def test_port_alone_without_the_switch_does_not_match(matcher):
    assert matcher.match({'sw': '02:00:00:00:00:99', 'port': 5}) == ([], None)


def test_a_longer_device_name_containing_ours_does_not_match(matcher):
    record = {'sw_name': OTHER_SWITCH_NAME, 'msg': f'Switch[{OTHER_SWITCH_NAME}] port 5 up'}
    assert matcher.match(record) == ([], None)
    assert matcher.match({'msg': f'Switch[{SWITCH_NAME}] rebooted'}) == (['switch'], 'name')


def test_client_mac_matches_anywhere_in_the_record(matcher):
    assert matcher.match({'params': {'client': {'mac': NAS_MAC.upper()}}}) == (['client'], None)


# ---------------------------------------------------------------------------
# Sources, paging and retention
# ---------------------------------------------------------------------------


def test_events_match_switch_port_and_client_newest_first():
    client, _ = _client()
    history = _events(client, client_macs=[NAS_MAC])
    keys = [m.key for m in history.matched]
    assert keys == [
        'DEVICE_PORT_SPEED',
        'EVT_LU_Disconnected',
        'EVT_SW_Lldp',
        'EVT_SW_PoeDisconnect',
        'ADMIN_CHANGED_DEVICE',
        'EVT_SW_Lost_Contact',
    ]
    by_key = {m.key: m for m in history.matched}
    assert by_key['EVT_SW_PoeDisconnect'].matched_on == ['switch', 'port']
    assert by_key['EVT_SW_Lldp'].matched_on == ['switch']  # 'Port 15' is not port 5
    assert by_key['EVT_LU_Disconnected'].matched_on == ['client']
    assert by_key['ADMIN_CHANGED_DEVICE'].source == 'system_log.admin-activity'
    assert 'EVT_SW_Connected' not in by_key  # the other switch
    assert history.matched_total == history.returned == 6 and history.truncated is False
    assert_no_secrets(history.to_json_dict())
    assert 'x_internal' not in by_key['EVT_SW_PoeDisconnect'].raw


def test_old_alarms_outside_the_window_are_dropped():
    client, _ = _client()
    history = _events(client, since_days=30)
    alarm_messages = [m.message for m in history.matched if m.source == 'alarms']
    assert alarm_messages == [f'Switch[{SWITCH_NAME}] was disconnected']


def test_retention_span_is_reported_for_ms_and_s_timestamps():
    client, _ = _client()
    source = _events(client).sources.stat_event
    assert source.records_returned == 5 and source.pages == 1 and source.truncated is False
    assert source.earliest == '2026-09-21T14:03:20+00:00'  # NOW - 600, given in ms
    assert source.latest == '2026-09-21T14:10:00+00:00'  # NOW - 200, given in ms


def test_stat_event_query_body_and_short_page_stop():
    client, session = _client()
    _events(client, since_days=10)
    [call] = [c for c in session.calls if c['path'].endswith('/stat/event')]
    assert call['json'] == {
        '_sort': '-time',
        'within': 240,
        'type': None,
        '_start': 0,
        '_limit': 1000,
    }


def _many_events(count: int) -> list[dict]:
    return [
        {'_id': f'e{i}', 'key': 'EVT_SW_Ping', 'sw': SWITCH_MAC, 'time': (NOW - i) * 1000}
        for i in range(count)
    ]


def test_stat_event_paging_continues_until_a_short_page():
    client, session = _client(events=paged_events(_many_events(2500)))
    history = _events(client)
    source = history.sources.stat_event
    assert (source.pages, source.records_returned, source.truncated) == (3, 2500, False)
    starts = [c['json']['_start'] for c in session.calls if c['path'].endswith('/stat/event')]
    assert starts == [0, 1000, 2000]


def test_stat_event_paging_stops_at_max_pages_and_flags_truncation():
    client, _ = _client(events=paged_events(_many_events(3000)))
    source = _events(client, max_pages=2).sources.stat_event
    assert (source.pages, source.records_returned, source.truncated) == (2, 2000, True)


def test_a_controller_that_ignores_start_is_flagged_not_looped():
    records = _many_events(1000)
    client, session = _client(events={'data': records})
    source = _events(client).sources.stat_event
    assert source.truncated is True and source.records_returned == 1000
    assert len([c for c in session.calls if c['path'].endswith('/stat/event')]) == 2


def test_system_log_query_carries_the_class_filters_and_window():
    client, session = _client()
    _events(client, since_days=1)
    [call] = [c for c in session.calls if c['path'].endswith('/system-log/admin-activity')]
    body = call['json']
    assert body['pageNumber'] == 0 and body['pageSize'] == 100
    assert body['timestampTo'] - body['timestampFrom'] == 86_400_000
    assert 'ACCESSED_NETWORK_WEB' in body['activity_keys']
    assert 'DEVICE' in body['change_keys']


def test_system_log_permission_denied_is_unavailable_not_fatal():
    def system_log(path, **_):
        return (403, {'error': 'forbidden'}) if 'admin-activity' in path else {'data': []}

    client, _ = _client(system_log=system_log)
    history = _events(client)
    result = history.sources.system_log['admin-activity']
    assert result.status == 'unavailable' and result.http_status == 403
    assert history.sources.system_log['device-alert'].status == 'ok'
    assert any(e.section == 'events.system_log.admin-activity' for e in history.errors)


def test_max_events_keeps_the_newest():
    client, _ = _client(events=paged_events(_many_events(50)))
    history = _events(client, max_events=10)
    assert history.returned == 10 and history.truncated is True
    assert history.matched_total > 10
    stamps = [m.epoch_ms or 0 for m in history.matched]
    assert stamps == sorted(stamps, reverse=True)
    assert stamps[0] == NOW * 1000


@pytest.mark.parametrize(('since_days', 'max_events'), [(0, 10), (4000, 10), (30, 0)])
def test_event_bounds_are_validated(since_days, max_events):
    client, _ = _client()
    with pytest.raises(ValueError):
        _events(client, since_days=since_days, max_events=max_events)


# ---------------------------------------------------------------------------
# Counter sampling
# ---------------------------------------------------------------------------


def _device_route(samples: list[dict]):
    """Return successive device records, one per stat/device/{id} read."""
    reads = iter(samples)

    def route(**_):
        return {'data': [next(reads)]}

    return route


def _switch_at(last_seen: int, uptime: int, rx_errors: int, rx_bytes: int) -> dict:
    switch = fake_switch(last_seen=last_seen, uptime=uptime)
    port5 = switch['port_table'][4]
    port5.update({'rx_errors': rx_errors, 'rx_bytes': rx_bytes})
    return switch


class _Clock:
    def __init__(self, start: float) -> None:
        self.value = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _sample(client, tmp_path, clock, **kwargs):
    return sample_port_counters(
        client,
        SITE,
        fake_switch(),
        5,
        sleep=clock.sleep,
        now=clock.now,
        link_error_baseline_path=str(tmp_path / 'none.json'),
        port_counter_store_path=tmp_path / 'none-store.json',
        **kwargs,
    )


def test_counter_rates_use_the_device_inform_interval(tmp_path):
    client, _ = _client(
        device=_device_route(
            [_switch_at(NOW, 1000, 10, 1_000), _switch_at(NOW + 120, 1120, 22, 61_000)]
        )
    )
    clock = _Clock(NOW)
    trend = _sample(client, tmp_path, clock, samples=2, interval_seconds=100)
    assert clock.sleeps == [100]
    assert trend.verdict == 'ok'
    assert trend.rate_basis == 'device_last_seen' and trend.elapsed_seconds == 120
    assert trend.rates_per_minute['rx_errors'] == 6.0  # 12 errors over 2 minutes
    assert trend.rates_per_minute['rx_bytes'] == 30000.0
    assert len(trend.samples) == 2


def test_stale_device_gives_inconclusive_and_withholds_rates(tmp_path):
    client, _ = _client(
        device=_device_route([_switch_at(NOW, 1000, 10, 1), _switch_at(NOW, 1000, 10, 1)])
    )
    trend = _sample(client, tmp_path, _Clock(NOW), samples=2, interval_seconds=100)
    assert trend.verdict == 'inconclusive_not_informing'
    assert set(trend.rates_per_minute.values()) == {None}


@pytest.mark.parametrize(
    ('second', 'reason'),
    [
        (_switch_at(NOW + 100, 50, 10, 1), 'uptime'),
        (_switch_at(NOW + 100, 1100, 2, 1), 'rx_errors'),
    ],
)
def test_reboot_or_cleared_counters_give_counter_reset(tmp_path, second, reason):
    client, _ = _client(device=_device_route([_switch_at(NOW, 1000, 10, 1), second]))
    trend = _sample(client, tmp_path, _Clock(NOW), samples=2, interval_seconds=100)
    assert trend.verdict == 'counter_reset' and reason in trend.verdict_reason
    assert set(trend.rates_per_minute.values()) == {None}


def test_single_sample_never_sleeps(tmp_path):
    client, _ = _client()
    clock = _Clock(NOW)
    trend = _sample(client, tmp_path, clock, samples=1)
    assert clock.sleeps == [] and trend.verdict == 'single_sample'
    assert trend.samples[0].counters['rx_crc_errors'] == 3


@pytest.mark.parametrize(('samples', 'interval'), [(0, 100), (6, 100), (2, 29), (2, 301)])
def test_sampling_bounds_are_validated(tmp_path, samples, interval):
    client, _ = _client()
    with pytest.raises(ValueError):
        _sample(client, tmp_path, _Clock(NOW), samples=samples, interval_seconds=interval)


def test_sampling_a_missing_port_fails(tmp_path):
    client, _ = _client()
    with pytest.raises(PortNotFound):
        sample_port_counters(
            client, SITE, fake_switch(), 9, samples=1, sleep=lambda _: None, now=lambda: NOW
        )


# ---------------------------------------------------------------------------
# Baselines are read, never written
# ---------------------------------------------------------------------------


def _write_link_baseline(path: Path, *, device_present: bool = True) -> None:
    devices = []
    if device_present:
        devices.append(
            {
                'device_id': SWITCH_ID,
                'name': SWITCH_NAME,
                'uptime': 90000,
                'ports': [
                    {
                        'port_idx': 5,
                        'rx_errors': 4,
                        'tx_errors': 0,
                        'rx_dropped': 1,
                        'tx_dropped': 0,
                        'rx_bytes': 100,
                        'tx_bytes': 200,
                    }
                ],
            }
        )
    path.write_text(json.dumps({'timestamp': '2026-05-03T22:02:00', 'devices': devices}))


def test_link_error_baseline_is_compared_without_being_modified(tmp_path):
    path = tmp_path / 'link-error-baseline.json'
    _write_link_baseline(path)
    before_bytes, before_mtime = path.read_bytes(), os.stat(path).st_mtime_ns
    current = {'rx_errors': 7, 'tx_errors': 0, 'rx_dropped': 1, 'tx_dropped': 0}
    current.update({'rx_bytes': 5000, 'tx_bytes': 10000})
    view = read_counter_baselines(
        fake_switch(), 5, current, 86400, str(path), tmp_path / 'store.json'
    ).link_error_tracking
    assert path.read_bytes() == before_bytes
    assert os.stat(path).st_mtime_ns == before_mtime
    assert view.found and view.device_present and view.port_present
    assert view.baseline_timestamp == '2026-05-03T22:02:00'
    assert view.deltas['rx_errors'] == 3
    assert view.reboot_detected is True  # uptime 86400 < 90000


def test_a_device_missing_from_the_baseline_is_reported(tmp_path):
    path = tmp_path / 'link-error-baseline.json'
    _write_link_baseline(path, device_present=False)
    view = read_counter_baselines(fake_switch(), 5, {}, None, str(path)).link_error_tracking
    assert view.found is True and view.device_present is False and view.deltas == {}


def test_port_counter_store_defaults_to_xdg_state_and_is_only_read(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    view = read_counter_baselines(fake_switch(), 5, {}, None, str(tmp_path / 'x.json'))
    store = view.port_counter_baseline
    assert store.path == str(tmp_path / 'unifi_mapper' / 'port-counters.json')
    assert store.found is False and store.key == f'{SWITCH_ID}:5'
    assert not (tmp_path / 'unifi_mapper').exists()  # nothing was created


def test_port_counter_store_delta_is_computed_from_the_saved_snapshot(tmp_path):
    store = tmp_path / 'port-counters.json'
    store.write_text(
        json.dumps({f'{SWITCH_ID}:5': {'timestamp': '2026-09-01T00:00:00', 'rx_errors': 2}})
    )
    before = store.read_bytes()
    view = read_counter_baselines(
        fake_switch(), 5, {'rx_errors': 7, 'rx_crc_errors': 3}, None, str(tmp_path / 'x'), store
    ).port_counter_baseline
    assert store.read_bytes() == before
    assert view.found and view.baseline_timestamp == '2026-09-01T00:00:00'
    assert view.delta['rx_errors'] == 5 and view.delta['crc_errors'] == 3
