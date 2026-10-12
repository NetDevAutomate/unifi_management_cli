"""Payloads the live Network Integration API sends, through the network_api MCP tools.

The first live run of these tools (review follow-ups at d6d013f, Network 10.6.106) found that
one client with ``access.type: DEFAULT`` failed validation and emptied the whole
``get_clients`` result (issue 033), and that ``get_acl_rules`` and ``get_dns_policies`` asked
for paths the controller doesn't serve (issues 031 and 032). These tests serve fake pages
shaped like the controller's through ``httpx.MockTransport``, behind the tools' own read-only
guard, so nothing reaches a network.
"""

import httpx
import pytest
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.mcp.tools import network as network_tools


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
INTEGRATION = f'/proxy/network/integrations/v1/sites/{SITE_ID}'


class Pages(httpx.MockTransport):
    """A fake Integration API: one page per path, a 404 elsewhere; records each request."""

    def __init__(self, pages: dict[str, list[dict[str, Any]]]) -> None:
        self.calls: list[tuple[str, str]] = []
        self._pages = pages
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        data = self._pages.get(request.url.path)
        if data is None:
            return httpx.Response(404, json={'statusCode': 404, 'statusName': 'NOT_FOUND'})
        page = {'offset': 0, 'limit': 200, 'count': len(data), 'totalCount': len(data)}
        return httpx.Response(200, json={**page, 'data': data})


@pytest.fixture
def network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_NETWORK_HOST', '192.0.2.1')
    monkeypatch.setenv('UNIFI_NETWORK_API_KEY', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', SITE_ID)


def _serve(monkeypatch: pytest.MonkeyPatch, pages: dict[str, list[dict[str, Any]]]) -> Pages:
    """Put ``pages`` behind the network tools' guard and return the recording transport."""
    transport = Pages(pages)
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _config: transport)
    return transport


def _wired_client(client_id: str, access_type: str, mac: str) -> dict[str, Any]:
    """One wired client as the connected-clients list returns it (fake identifiers)."""
    return {
        'type': 'WIRED',
        'id': client_id,
        'name': client_id,
        'connectedAt': '2026-10-03T04:55:20Z',
        'ipAddress': '192.0.2.50',
        'macAddress': mac,
        'uplinkDeviceId': '00000000-0000-0000-0000-0000000000a1',
        'access': {'type': access_type},
    }


@pytest.mark.usefixtures('network_env')
async def test_get_clients_returns_default_and_user_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients = [
        _wired_client('c-default', 'DEFAULT', '02:00:00:00:00:71'),
        _wired_client('c-user', 'USER', '02:00:00:00:00:72'),
    ]
    transport = _serve(monkeypatch, {f'{INTEGRATION}/clients': clients})

    result = (await network_tools.get_clients())['clients']

    assert [c.get('id') for c in result] == ['c-default', 'c-user'], result
    assert [c['access']['type'] for c in result] == ['DEFAULT', 'USER']
    assert transport.calls == [('GET', f'{INTEGRATION}/clients')]


@pytest.mark.usefixtures('network_env')
async def test_get_clients_keeps_teleport_and_unknown_connection_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teleport = {
        'type': 'TELEPORT',
        'id': 'c-teleport',
        'name': 'c-teleport',
        'connectedAt': '2026-10-03T04:55:20Z',
        'access': {'type': 'DEFAULT'},
    }
    unknown = {**_wired_client('c-new', 'DEFAULT', '02:00:00:00:00:73'), 'type': 'SOMETHING_NEW'}
    wired = _wired_client('c-wired', 'DEFAULT', '02:00:00:00:00:74')
    _serve(monkeypatch, {f'{INTEGRATION}/clients': [teleport, unknown, wired]})

    result = (await network_tools.get_clients())['clients']

    # Sorted by id, so a page is stable between calls while the set is unchanged.
    assert [c.get('id') for c in result] == ['c-new', 'c-teleport', 'c-wired'], result
    assert [c['type'] for c in result] == ['SOMETHING_NEW', 'TELEPORT', 'WIRED']


# Issues 031 and 032: one record each, shaped as Ubiquiti's v10.6.102 reference documents it.
ACL_RULE = {
    'type': 'IPV4',
    'id': '00000000-0000-0000-0000-0000000000c1',
    'name': 'Block lab to NAS',
    'enabled': True,
    'action': 'BLOCK',
    'index': 0,
    'metadata': {'origin': 'USER_DEFINED'},
    'protocolFilter': ['TCP'],
}
DNS_POLICY = {
    'type': 'A_RECORD',
    'id': '00000000-0000-0000-0000-0000000000d1',
    'enabled': True,
    'domain': 'nas.lab.example',
    'ipv4Address': '192.0.2.5',
    'ttlSeconds': 3600,
    'metadata': {'origin': 'USER_DEFINED'},
}


@pytest.mark.usefixtures('network_env')
@pytest.mark.parametrize(
    ('tool', 'path', 'record'),
    [
        ('get_acl_rules', f'{INTEGRATION}/acl-rules', ACL_RULE),
        ('get_dns_policies', f'{INTEGRATION}/dns/policies', DNS_POLICY),
    ],
    ids=['get_acl_rules', 'get_dns_policies'],
)
async def test_acl_and_dns_tools_read_the_served_paths(
    tool: str, path: str, record: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _serve(monkeypatch, {path: [record]})

    result = await getattr(network_tools, tool)()

    assert [r.get('id') for r in result] == [record['id']], result
    assert transport.calls == [('GET', path)]


# --- get_clients paging (design 4.11) -------------------------------------------------------


# The fake's page size for a request that names no limit (the tool always names one).
FAKE_DEFAULT_PAGE = 200


class PagedClients(httpx.MockTransport):
    """The connected-clients list served in pages by its ``offset`` and ``limit`` parameters."""

    def __init__(self, clients: list[dict[str, Any]]) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._clients = clients
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path, request.url.query.decode()))
        if request.url.path != f'{INTEGRATION}/clients':
            return httpx.Response(404, json={'statusCode': 404, 'statusName': 'NOT_FOUND'})
        offset = int(request.url.params.get('offset', 0))
        limit = int(request.url.params.get('limit', FAKE_DEFAULT_PAGE))
        data = self._clients[offset : offset + limit]
        page = {'offset': offset, 'limit': limit, 'count': len(data)}
        return httpx.Response(200, json={**page, 'totalCount': len(self._clients), 'data': data})


def _many(count: int) -> list[dict[str, Any]]:
    # Served in reverse id order, so the tool's sort is visible.
    return [
        _wired_client(f'c-{i:03d}', 'DEFAULT', f'02:00:00:00:{i // 256:02x}:{i % 256:02x}')
        for i in reversed(range(count))
    ]


@pytest.fixture
def paged(monkeypatch: pytest.MonkeyPatch, network_env: None) -> PagedClients:
    transport = PagedClients(_many(250))  # two Integration API pages of 200
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _config: transport)
    return transport


async def test_get_clients_pages_a_list_read_in_full(paged: PagedClients) -> None:
    first = await network_tools.get_clients(limit=100)
    assert {key: first[key] for key in first if key != 'clients'} == {
        'total': 250,
        'returned': 100,
        'offset': 0,
        'limit': 100,
        'next_offset': 100,
        'truncated': True,
    }
    assert [c['id'] for c in first['clients'][:2]] == ['c-000', 'c-001']
    last = await network_tools.get_clients(limit=100, offset=200)
    assert (last['total'], last['returned'], last['next_offset'], last['truncated']) == (
        250,
        50,
        None,
        False,
    )
    assert [c['id'] for c in last['clients']][-1] == 'c-249'
    # Every Integration API page was read for each call, so total counts every client.
    assert [query for _, _, query in paged.calls] == [
        'offset=0&limit=200',
        'offset=200&limit=200',
    ] * 2
    assert {method for method, _, _ in paged.calls} == {'GET'}


async def test_get_clients_pages_are_disjoint_and_cover_the_list(paged: PagedClients) -> None:
    seen: list[str] = []
    offset: int | None = 0
    while offset is not None:
        page = await network_tools.get_clients(limit=60, offset=offset)
        seen += [c['id'] for c in page['clients']]
        offset = page['next_offset']
    assert seen == [f'c-{i:03d}' for i in range(250)]


async def test_an_offset_past_the_end_is_an_empty_last_page(paged: PagedClients) -> None:
    page = await network_tools.get_clients(offset=900)
    assert (page['returned'], page['next_offset'], page['truncated']) == (0, None, False)
    assert page['clients'] == [] and page['total'] == 250


async def test_a_failure_is_one_error_object(
    monkeypatch: pytest.MonkeyPatch, network_env: None
) -> None:
    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError('controller unreachable', request=request)

    transport = httpx.MockTransport(_down)
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _config: transport)
    result = await network_tools.get_clients()
    assert set(result) == {'error'}


@pytest.mark.parametrize(
    'params',
    [{'limit': 0}, {'limit': 1001}, {'offset': -1}, {'limit': 'ten'}],
    ids=['limit 0', 'limit 1001', 'negative offset', 'not a number'],
)
async def test_bad_bounds_are_refused_before_the_handler_runs(
    monkeypatch: pytest.MonkeyPatch, network_env: None, params: dict[str, Any]
) -> None:
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
    from unifi_mapper.mcp.runner import ToolRunner

    called: list[object] = []

    async def _never(**kwargs: object) -> dict[str, Any]:
        called.append(kwargs)
        return {}

    monkeypatch.setattr(network_tools, 'get_clients', _never)
    runner = ToolRunner(ToolRegistry(default_manifests_dir(), strict=True))
    out = await runner.run('get_clients', params)
    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == 'INVALID_PARAMETERS'
    assert called == []
