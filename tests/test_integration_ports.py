"""Tests for the Integration API multi-device read behind the fleet link-speed audit."""

import pytest
from tests.fixtures_unifi import (
    INTEGRATION_DEVICE_ID,
    INTEGRATION_SITE_ID,
    OTHER_SWITCH_MAC,
    SITE,
    SWITCH_MAC,
    FakeSession,
    default_routes,
    fake_client,
)
from typing import Any
from unifi_mapper.diagnostic_reads import Collection
from unifi_mapper.port_diagnostics import (
    INTEGRATION_PAGE_SIZE,
    collect_integration_snapshot,
    fetch_integration_ports,
)


pytestmark = pytest.mark.usefixtures('block_network')

PLURAL = '/proxy/network/integrations'
SINGULAR = '/proxy/network/integration'
DEVICES_PATH = f'{PLURAL}/v1/sites/{INTEGRATION_SITE_ID}/devices'


def _paged_listing(pages: list[list[dict[str, Any]]]):
    def route(params: dict | None = None, **_: Any) -> dict[str, Any]:
        offset = int((params or {}).get('offset', 0))
        page = offset // INTEGRATION_PAGE_SIZE
        return {'data': pages[page] if page < len(pages) else []}

    return route


def _filler(page: int, count: int) -> list[dict[str, Any]]:
    return [
        {'id': f'filler-{page}-{i}', 'macAddress': f'02:00:00:00:{page + 0x10:02x}:{i % 256:02x}'}
        for i in range(count)
    ]


def _routes(pages: list[list[dict[str, Any]]]) -> dict:
    routes = default_routes()
    routes[('GET', rf'^{DEVICES_PATH}$')] = _paged_listing(pages)
    routes[('GET', rf'^{DEVICES_PATH}/[^/]+$')] = lambda path, **_: {
        'id': path.rsplit('/', 1)[-1],
        'interfaces': {'ports': [{'idx': 1, 'maxSpeedMbps': 10000}]},
        'x_secret_token': 'FAKE-API-TOKEN-MUST-NOT-APPEAR',  # pragma: allowlist secret
    }
    return routes


def _run(routes: dict, macs: list[Any], **client_kw: Any):
    session = FakeSession(routes)
    ctx = Collection()
    result = fetch_integration_ports(fake_client(session, **client_kw), SITE, macs, ctx)
    return result, session, ctx


def test_one_probe_per_base_one_sites_read_and_the_singular_base_first():
    result, session, ctx = _run(default_routes(), [SWITCH_MAC])
    paths = session.paths('GET')
    assert [p for p in paths if p.endswith('/v1/info')] == [
        f'{SINGULAR}/v1/info',
        f'{PLURAL}/v1/info',
    ]
    assert paths.count(f'{PLURAL}/v1/sites') == 1
    assert result.status == 'ok' and result.base_path_used == PLURAL
    assert result.application_version == '10.0.162'
    assert result.site_id == INTEGRATION_SITE_ID
    assert result.devices[SWITCH_MAC].device_id == INTEGRATION_DEVICE_ID
    device = result.devices[SWITCH_MAC].device
    assert device and device['interfaces']['ports'][0]['maxSpeedMbps'] == 10000
    assert result.missing_macs == []
    assert not ctx.errors


def test_paging_stops_once_every_mac_is_found():
    pages = [
        [*_filler(0, INTEGRATION_PAGE_SIZE - 1), {'id': 'dev-a', 'macAddress': SWITCH_MAC}],
        [{'id': 'dev-b', 'macAddress': OTHER_SWITCH_MAC.upper()}, *_filler(1, 199)],
        _filler(2, INTEGRATION_PAGE_SIZE),
    ]
    result, session, _ = _run(_routes(pages), [SWITCH_MAC, OTHER_SWITCH_MAC.replace(':', '-')])
    assert session.paths('GET').count(DEVICES_PATH) == 2
    assert {mac: d.device_id for mac, d in result.devices.items()} == {
        SWITCH_MAC: 'dev-a',
        OTHER_SWITCH_MAC: 'dev-b',
    }
    assert [p for p in session.paths('GET') if p.startswith(f'{DEVICES_PATH}/')] == [
        f'{DEVICES_PATH}/dev-a',
        f'{DEVICES_PATH}/dev-b',
    ]
    assert result.missing_macs == []


def test_paging_stops_on_a_short_page_and_reports_missing_macs():
    pages = [_filler(0, INTEGRATION_PAGE_SIZE), _filler(1, 3), _filler(2, INTEGRATION_PAGE_SIZE)]
    result, session, ctx = _run(_routes(pages), [SWITCH_MAC, 'not-a-mac', None])
    assert session.paths('GET').count(DEVICES_PATH) == 2
    assert result.status == 'ok' and result.devices == {}
    assert result.missing_macs == [SWITCH_MAC]
    assert not ctx.errors


def test_device_records_are_sanitised():
    pages = [[{'id': 'dev-a', 'macAddress': SWITCH_MAC}]]
    result, _, ctx = _run(_routes(pages), [SWITCH_MAC])
    device = result.devices[SWITCH_MAC].device
    assert device and 'x_secret_token' not in device
    assert 'integration.device.x_secret_token' in ctx.sanitised_paths


def test_a_failed_detail_read_keeps_the_device_id():
    routes = _routes([[{'id': 'dev-a', 'macAddress': SWITCH_MAC}]])
    routes[('GET', rf'^{DEVICES_PATH}/[^/]+$')] = (500, {'error': 'boom'})
    result, _, ctx = _run(routes, [SWITCH_MAC])
    assert result.devices[SWITCH_MAC].device_id == 'dev-a'
    assert result.devices[SWITCH_MAC].device is None
    assert [e.section for e in ctx.errors] == ['integration.device']


@pytest.mark.parametrize(
    ('client_kw', 'reason'),
    [
        ({'unifi_os': False}, 'controller is not UniFi OS'),
        (
            {'auth': 'username_password'},
            'the Integration API needs API-key (token) authentication',
        ),
    ],
)
def test_skipped_without_unifi_os_token_auth(client_kw, reason):
    result, session, _ = _run(default_routes(), [SWITCH_MAC], **client_kw)
    assert result.status == 'skipped' and result.reason == reason
    assert result.missing_macs == [SWITCH_MAC]
    assert not any('/v1/' in p for p in session.paths())


def test_unauthorised_probe_is_unavailable_with_its_base():
    routes = default_routes()
    routes = {(m, p): v for (m, p), v in routes.items() if 'integration' not in p}
    routes[('GET', rf'^{SINGULAR}/v1/info$')] = (401, {'error': 'unauthorised'})
    result, _, ctx = _run(routes, [SWITCH_MAC])
    assert result.status == 'unavailable' and result.base_path_used == SINGULAR
    assert [e.section for e in ctx.errors] == ['integration.info']


def test_no_base_answers_is_unavailable():
    routes = {(m, p): v for (m, p), v in default_routes().items() if 'integration' not in p}
    result, _, ctx = _run(routes, [SWITCH_MAC])
    assert result.status == 'unavailable'
    assert 'Integration API not found' in result.reason
    assert not ctx.errors


def test_snapshot_still_reports_a_missing_device_as_an_error():
    pages = [_filler(0, 3)]
    session = FakeSession(_routes(pages))
    snapshot = collect_integration_snapshot(
        fake_client(session), SITE, SWITCH_MAC, 5, Collection()
    )
    assert snapshot.status == 'error'
    assert snapshot.reason == 'device not found in the Integration API'
    assert snapshot.site_id == INTEGRATION_SITE_ID and snapshot.device_id is None
