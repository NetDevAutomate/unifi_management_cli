"""Tests for the shared read helpers behind the port diagnostics (no live controller)."""

import pytest
from tests.fixtures_unifi import API, FAKE_AUTHKEY, NOW, FakeSession, fake_client
from unifi_mapper.core.utils.readonly import ReadOnlyViolation, install_read_only_guard
from unifi_mapper.diagnostic_reads import (
    Collection,
    DiagnosticModel,
    epoch_ms,
    fetch,
    int_or_none,
    iso_from_ms,
    iso_from_seconds,
    rows,
)
from unittest.mock import MagicMock


pytestmark = pytest.mark.usefixtures('block_network')


def _client(routes: dict):
    client = fake_client(FakeSession(routes))
    install_read_only_guard(client)
    return client


def test_fetch_returns_data_for_a_good_read():
    client = _client({('GET', r'/stat/sysinfo$'): {'meta': {'rc': 'ok'}, 'data': [{'v': 1}]}})
    result = fetch(client, f'{API}/stat/sysinfo')
    assert result.ok and result.status == 200 and rows(result.data) == [{'v': 1}]


def test_fetch_never_raises_on_http_errors_and_redacts_the_body():
    body = {'error': 'denied', 'token': FAKE_AUTHKEY}
    client = _client({('GET', r'/stat/sysinfo$'): (403, body)})
    result = fetch(client, f'{API}/stat/sysinfo')
    assert not result.ok and result.status == 403
    assert result.error and FAKE_AUTHKEY not in result.error


def test_fetch_treats_rc_error_as_a_failure():
    client = _client({('GET', r'/stat/sysinfo$'): {'meta': {'rc': 'error', 'msg': 'api.err.X'}}})
    result = fetch(client, f'{API}/stat/sysinfo')
    assert not result.ok and 'api.err.X' in (result.error or '')


def test_fetch_turns_transport_exceptions_into_results():
    client = _client({})
    client.session._inner.get = MagicMock(side_effect=ConnectionError('reset by peer'))
    result = fetch(client, f'{API}/stat/sysinfo')
    assert not result.ok and result.status is None
    assert 'ConnectionError' in (result.error or '')


def test_fetch_never_swallows_a_guard_refusal():
    client = _client({})
    with pytest.raises(ReadOnlyViolation):
        fetch(client, f'{API}/rest/device/x', method='POST', json_body={})
    with pytest.raises(ReadOnlyViolation):
        fetch(client, f'{API}/rest/device/x', method='PUT')


def test_collection_records_failures_by_path_without_the_host():
    client = _client({})
    ctx = Collection()
    ctx.fetch(client, f'{API}/stat/sysinfo', section='controller')
    [error] = ctx.errors
    assert error.section == 'controller'
    assert error.error.startswith(f'GET {API}/stat/sysinfo: HTTP 404')
    assert '192.0.2.1' not in error.error


def test_collection_clean_records_removed_paths():
    ctx = Collection()
    assert ctx.clean({'a': 1, 'x_b': FAKE_AUTHKEY}, 'root') == {'a': 1}
    assert ctx.sanitised_paths == ['root.x_b']


def test_final_pass_strips_anything_a_section_missed():
    class Report(DiagnosticModel):
        payload: dict

    data = Report(payload={'x_late': FAKE_AUTHKEY, 'ok': 1}).to_json_dict()
    assert data['payload'] == {'ok': 1}
    assert data['sanitised_paths'] == ['final:payload.x_late']
    assert data['schema_version'] == 1


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (NOW, NOW * 1000),
        (NOW * 1000, NOW * 1000),
        (str(NOW), NOW * 1000),
        ('2026-09-21T14:13:20Z', NOW * 1000),
        ('2026-09-21T14:13:20', NOW * 1000),
        (None, None),
        (True, None),
        (0, None),
        ('not a time', None),
    ],
)
def test_epoch_ms_normalises_seconds_milliseconds_and_iso(value, expected):
    assert epoch_ms(value) == expected


def test_out_of_range_timestamps_render_as_none_not_a_crash():
    assert iso_from_ms(10**20) is None
    assert iso_from_seconds(10**18) is None
    assert iso_from_seconds('junk') is None


def test_int_or_none_handles_controller_strings():
    assert int_or_none('86400') == 86400
    assert int_or_none('7.9') == 7
    assert int_or_none(None) is None and int_or_none(True) is None and int_or_none('x') is None
