"""Payloads the live Network Integration API sends, through the network_api MCP tools.

The first live run of these tools (review follow-ups at 7ef13c2, Network 10.6.106) found that
one client with ``access.type: DEFAULT`` failed validation and emptied the whole
``get_clients`` result (issue 033). These tests serve fake pages shaped like the controller's
through ``httpx.MockTransport``, behind the tools' own read-only guard, so nothing reaches a
network.
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
