"""Issue 003: the Integration API base path the client uses.

Ubiquiti's Network API spec gives the server as ``/proxy/network/integration`` (singular);
Network 10.6.106 also answers on the undocumented plural ``/proxy/network/integrations``, which
is all the client used to try. The client now does what ``port_diagnostics`` does: one
``GET {base}/v1/info`` on the documented base, the plural on a 404, and every request after
that on the base that answered. These tests pin both paths with ``httpx.MockTransport``;
nothing reaches a network.
"""

import httpx
import pytest
from pydantic import SecretStr
from tests.fixtures_unifi import FAKE_TOKEN
from unifi_mapper.core.utils.readonly import ReadOnlyAsyncTransport, get_only_request_allowed
from unifi_mapper.network.client import (
    NetworkAuthenticationError,
    NetworkClientError,
    UniFiNetworkClient,
)
from unifi_mapper.network.config import INTEGRATION_BASES, NetworkConfig


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
DOCUMENTED = '/proxy/network/integration'
PLURAL = '/proxy/network/integrations'
INFO = {'applicationVersion': '10.6.106'}
EMPTY_PAGE = {'offset': 0, 'limit': 200, 'count': 0, 'totalCount': 0, 'data': []}


class Console(httpx.MockTransport):
    """A fake console whose Integration API answers only on ``bases``; records each request."""

    def __init__(self, *bases: str, info_status: int = 200) -> None:
        self.calls: list[tuple[str, str]] = []
        self._bases = bases
        self._info_status = info_status
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        base = next((b for b in self._bases if path.startswith(f'{b}/v1/')), None)
        if base is None:
            return httpx.Response(404, json={'statusCode': 404, 'statusName': 'NOT_FOUND'})
        if path == f'{base}/v1/info':
            return httpx.Response(self._info_status, json=INFO)
        return httpx.Response(200, json=EMPTY_PAGE)


def _client(transport: httpx.AsyncBaseTransport) -> UniFiNetworkClient:
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    return UniFiNetworkClient(config, transport=transport)


def test_the_documented_base_is_tried_first() -> None:
    assert INTEGRATION_BASES == (DOCUMENTED, PLURAL)
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    assert config.api_base_url == f'https://192.0.2.1:443{DOCUMENTED}/v1'


async def test_a_console_serving_the_documented_base_is_probed_once_and_used() -> None:
    console = Console(DOCUMENTED)
    async with _client(console) as client:
        assert client.base_path_used is None
        await client.list_devices()
        await client.list_clients()
        assert client.base_path_used == DOCUMENTED
    assert console.calls == [
        ('GET', f'{DOCUMENTED}/v1/info'),
        ('GET', f'{DOCUMENTED}/v1/sites/{SITE_ID}/devices'),
        ('GET', f'{DOCUMENTED}/v1/sites/{SITE_ID}/clients'),
    ]


async def test_a_console_serving_only_the_plural_base_is_used_after_one_404() -> None:
    console = Console(PLURAL)
    async with _client(console) as client:
        await client.list_devices()
        assert client.base_path_used == PLURAL
    assert console.calls == [
        ('GET', f'{DOCUMENTED}/v1/info'),
        ('GET', f'{PLURAL}/v1/info'),
        ('GET', f'{PLURAL}/v1/sites/{SITE_ID}/devices'),
    ]


async def test_a_console_serving_neither_base_fails_before_the_request_is_sent() -> None:
    console = Console()
    async with _client(console) as client:
        with pytest.raises(NetworkClientError) as failed:
            await client.list_devices()
        assert client.base_path_used is None
    assert failed.value.status_code == 404
    assert str(failed.value) == f'Integration API not found at {DOCUMENTED} or {PLURAL}'
    assert console.calls == [('GET', f'{DOCUMENTED}/v1/info'), ('GET', f'{PLURAL}/v1/info')]


async def test_a_rejected_probe_is_the_usual_authentication_error() -> None:
    console = Console(DOCUMENTED, info_status=401)
    async with _client(console) as client:
        with pytest.raises(NetworkAuthenticationError) as refused:
            await client.list_devices()
    assert refused.value.status_code == 401
    assert console.calls == [('GET', f'{DOCUMENTED}/v1/info')]


async def test_the_probe_is_a_get_the_read_only_guard_lets_through() -> None:
    console = Console(DOCUMENTED)
    guard = ReadOnlyAsyncTransport(console, policy=get_only_request_allowed)
    async with _client(guard) as client:
        await client.list_sites()
    assert console.calls == [('GET', f'{DOCUMENTED}/v1/info'), ('GET', f'{DOCUMENTED}/v1/sites')]
