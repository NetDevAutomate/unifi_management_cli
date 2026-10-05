"""Self-test: an unmarked test cannot reach a controller (the root ``_no_live_network`` ban).

Every test runs with the real HTTP transports and TCP/UDP connects refused, so a missed stub
fails instead of reaching the live controller. In-memory transports still work.
"""

import httpx
import pytest
import requests
import socket


CONTROLLER = 'https://192.0.2.1/proxy/network/api/s/default/stat/device'


def test_httpx_sync_cannot_reach_a_controller() -> None:
    with pytest.raises(AssertionError, match='live network access in a test'):
        httpx.get(CONTROLLER)


async def test_httpx_async_cannot_reach_a_controller() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(AssertionError, match='live network access in a test'):
            await client.get(CONTROLLER)


def test_requests_cannot_reach_a_controller() -> None:
    with pytest.raises(AssertionError, match='live network access in a test'):
        requests.get(CONTROLLER, timeout=1)


@pytest.mark.parametrize('family', [socket.AF_INET, socket.AF_INET6])
def test_a_raw_socket_cannot_connect(family: socket.AddressFamily) -> None:
    address = ('192.0.2.1', 443) if family == socket.AF_INET else ('2001:db8::1', 443)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError, match='live network access in a test'):
            sock.connect(address)
        with pytest.raises(AssertionError, match='live network access in a test'):
            sock.connect_ex(address)


def test_unix_sockets_and_mock_transports_still_work() -> None:
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b'x')
        assert right.recv(1) == b'x'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'ok': True}))
    with httpx.Client(transport=transport) as client:
        assert client.get(CONTROLLER).json() == {'ok': True}
