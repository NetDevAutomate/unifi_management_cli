"""Issue 035: the Integration API paths for device statistics and port actions.

Ubiquiti's Network API reference (v10.6.102) has ``/sites/{siteId}/devices/{deviceId}/statistics/latest``
and ``/sites/{siteId}/devices/{deviceId}/interfaces/ports/{portIdx}/actions``; the client read
``.../statistics`` (404 on Network 10.6.106) and posted to ``.../ports/{portIdx}/actions``.
These tests pin both with ``httpx.MockTransport`` in the style of ``test_client_paths.py``,
and show the GET-only guard refuses the port action before it is sent. Nothing reaches a
network.
"""

import httpx
import pytest
from pydantic import SecretStr
from tests.fixtures_unifi import FAKE_TOKEN
from unifi_mapper.core.utils.readonly import (
    ReadOnlyAsyncTransport,
    ReadOnlyViolation,
    get_only_request_allowed,
)
from unifi_mapper.network.client import UniFiNetworkClient
from unifi_mapper.network.config import NetworkConfig


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
DEVICE_ID = '00000000-0000-0000-0000-0000000000f2'
API = '/proxy/network/integration/v1'
PROBE = ('GET', f'{API}/info')
DEVICE = f'{API}/sites/{SITE_ID}/devices/{DEVICE_ID}'
STATISTICS_LATEST = f'{DEVICE}/statistics/latest'
PORT_5_ACTIONS = f'{DEVICE}/interfaces/ports/5/actions'


class Recorder(httpx.MockTransport):
    """A fake Integration API: records ``(method, path)`` and answers one object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if (request.method, request.url.path) == PROBE:
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        return httpx.Response(200, json={'uptimeSec': 86400})


def _client(transport: httpx.AsyncBaseTransport) -> UniFiNetworkClient:
    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    return UniFiNetworkClient(config, transport=transport)


async def test_device_statistics_read_the_latest_path() -> None:
    recorder = Recorder()
    async with _client(recorder) as client:
        stats = await client.get_device_statistics(DEVICE_ID)
    assert recorder.calls == [PROBE, ('GET', STATISTICS_LATEST)]
    assert stats.device_id == DEVICE_ID


async def test_port_actions_post_under_interfaces_and_the_guard_refuses_them() -> None:
    unguarded = Recorder()
    async with _client(unguarded) as client:
        await client.execute_port_action(DEVICE_ID, 5, 'POWER_CYCLE')
    assert unguarded.calls == [PROBE, ('POST', PORT_5_ACTIONS)]

    behind_guard = Recorder()
    guard = ReadOnlyAsyncTransport(behind_guard, policy=get_only_request_allowed)
    async with _client(guard) as client:
        with pytest.raises(ReadOnlyViolation) as refused:
            await client.execute_port_action(DEVICE_ID, 5, 'POWER_CYCLE')
    assert behind_guard.calls == [PROBE]
    assert str(refused.value) == f'refused POST {PORT_5_ACTIONS!r}: only GET and HEAD are allowed'
