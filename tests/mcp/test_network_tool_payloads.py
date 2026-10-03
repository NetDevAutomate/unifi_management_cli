"""Payloads the live Network Integration API sends, through the network_api MCP tools.

The first live run of these tools (review follow-ups at 7ef13c2, Network 10.6.106) found that
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

    result = await network_tools.get_clients()

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

    result = await network_tools.get_clients()

    assert [c.get('id') for c in result] == ['c-teleport', 'c-new', 'c-wired'], result
    assert [c['type'] for c in result] == ['TELEPORT', 'SOMETHING_NEW', 'WIRED']


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
