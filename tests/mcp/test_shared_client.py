"""The MCP server's shared, read-only-guarded async controller client (plan P3, P9).

Every request goes to an ``httpx.MockTransport`` that counts it, so nothing here can
reach a controller. With a holder installed, ``UniFiClient()`` borrows one logged-in
connection; with none (the CLI) each use logs in exactly as before.
"""

import anyio
import httpx
import json
import pytest
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from unifi_mapper.core.utils import client as client_mod
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import (
    SHARED_TIMEOUT,
    SharedControllerClient,
    UniFiClient,
    use_shared_controller_client,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import (
    ReadOnlySession,
    ReadOnlyViolation,
    configure_request_audit,
    request_allowed,
)
from unittest.mock import MagicMock


HOST = '192.0.2.1'
API = '/proxy/network/api/s/default'
TOKEN_CREDS = Credentials(host=HOST, api_token=FAKE_TOKEN)
PASSWORD_CREDS = Credentials(host=HOST, username='admin', password=FAKE_PW)


class CountingTransport(httpx.MockTransport):
    """A mock controller that records (method, path) and whether it was closed."""

    def __init__(self, *, token_ok: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        self._token_ok = token_ok
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if path == '/api/system':
            return httpx.Response(200, json={})
        if path == f'{API}/self':
            status = 200 if self._token_ok else 401
            return httpx.Response(status, json={'meta': {'rc': 'ok'}, 'data': []})
        if path in ('/api/auth/login', '/api/auth/logout'):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={'meta': {'rc': 'ok'}, 'data': [{'name': 'sw'}]})

    async def aclose(self) -> None:
        self.closed = True

    def count(self) -> Counter[tuple[str, str]]:
        return Counter(self.calls)


@pytest.fixture(autouse=True)
def _no_audit_sink() -> Iterator[None]:
    """Leave the process-wide audit sink cleared after every test."""
    yield
    configure_request_audit(None)


@pytest.fixture
def cli_transport(monkeypatch: pytest.MonkeyPatch) -> tuple[CountingTransport, list[dict]]:
    """Route the CLI path's own httpx.AsyncClient to a mock and record its kwargs."""
    transport = CountingTransport()
    built: list[dict] = []
    real = httpx.AsyncClient

    def _factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        built.append(dict(kwargs))
        kwargs['transport'] = transport
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_mod.httpx, 'AsyncClient', _factory)
    return transport, built


async def _two_tool_uses() -> None:
    for _ in range(2):
        async with UniFiClient() as client:
            assert await client.get_devices() == [{'name': 'sw'}]


async def test_two_borrowed_clients_log_in_once() -> None:
    transport = CountingTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        await _two_tool_uses()
    assert transport.count() == {
        ('GET', '/api/system'): 1,
        ('GET', f'{API}/self'): 1,
        ('GET', f'{API}/stat/device'): 2,
    }
    assert shared.is_connected  # released, not closed, by the borrowers
    await shared.aclose()


async def test_no_holder_logs_in_per_use_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch, cli_transport: tuple[CountingTransport, list[dict]]
) -> None:
    transport, built = cli_transport

    async def _creds() -> Credentials:
        return TOKEN_CREDS

    monkeypatch.setattr(client_mod, 'get_credentials', _creds)
    await _two_tool_uses()
    assert transport.count() == {
        ('GET', '/api/system'): 2,
        ('GET', f'{API}/self'): 2,
        ('GET', f'{API}/stat/device'): 2,
    }
    assert [b['timeout'] for b in built] == [httpx.Timeout(30.0)] * 2
    assert [b['transport'] for b in built] == [None, None]


async def test_explicit_credentials_bypass_the_holder(
    cli_transport: tuple[CountingTransport, list[dict]],
) -> None:
    own, _ = cli_transport
    shared_transport = CountingTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=shared_transport)
    with use_shared_controller_client(shared):
        async with UniFiClient(TOKEN_CREDS) as client:
            await client.get_devices()
    assert shared_transport.calls == []
    assert own.count()[('GET', f'{API}/self')] == 1


async def test_holder_is_restored_on_exit() -> None:
    outer = SharedControllerClient(TOKEN_CREDS, inner_transport=CountingTransport())
    inner = SharedControllerClient(TOKEN_CREDS, inner_transport=CountingTransport())
    with use_shared_controller_client(outer):
        with use_shared_controller_client(inner):
            assert client_mod._shared_holder is inner
        assert client_mod._shared_holder is outer
    assert client_mod._shared_holder is None


async def test_shared_client_uses_bounded_connect_timeout() -> None:
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=CountingTransport())
    owner = await shared.acquire()
    assert owner._client is not None
    assert owner._client.timeout == SHARED_TIMEOUT == httpx.Timeout(30.0, connect=10.0)
    await shared.aclose()


@pytest.mark.parametrize(
    'send',
    [
        lambda c: c.put(c.build_path('rest/device/abc'), {'name': 'x'}),
        lambda c: c._request('DELETE', c.build_path('rest/portconf/abc')),
        lambda c: c._request('PATCH', c.build_path('rest/device/abc')),
        lambda c: c.get(c.build_path('cmd/devmgr')),
        lambda c: c.get(c.build_path('upd/device/abc')),
        lambda c: c.post(c.build_path('cmd/devmgr'), {'cmd': 'force-provision'}),
        lambda c: c.post(c.build_path('rest/device'), {}),
    ],
    ids=['put', 'delete', 'patch', 'get-cmd', 'get-upd', 'post-cmd', 'post-rest'],
)
async def test_writes_are_refused_before_any_io(send) -> None:
    transport = CountingTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            before = len(transport.calls)
            with pytest.raises(ReadOnlyViolation):
                await send(client)
            assert len(transport.calls) == before
    await shared.aclose()


async def test_audit_sink_records_only_time_method_and_path(tmp_path: Path) -> None:
    audit = tmp_path / 'audit' / 'requests.jsonl'
    configure_request_audit(audit)
    transport = CountingTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            await client.get(client.build_path('stat/device'), mac='aa:bb')
    await shared.aclose()
    text = audit.read_text()
    assert FAKE_TOKEN not in text and HOST not in text and 'aa:bb' not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert all(set(line) == {'t', 'method', 'path'} for line in lines)
    assert [(e['method'], e['path']) for e in lines] == [
        ('GET', '/api/system'),
        ('GET', f'{API}/self'),
        ('GET', f'{API}/stat/device'),
    ]


async def test_password_login_is_allowed_but_not_audited(tmp_path: Path) -> None:
    audit = tmp_path / 'requests.jsonl'
    configure_request_audit(audit)
    transport = CountingTransport()
    shared = SharedControllerClient(PASSWORD_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            await client.get_devices()
    await shared.aclose()
    assert ('POST', '/api/auth/login') in transport.calls
    assert transport.calls[-1] == ('POST', '/api/auth/logout')  # aclose logs the owner out
    paths = [json.loads(line)['path'] for line in audit.read_text().splitlines()]
    assert '/api/auth/login' not in paths
    assert FAKE_PW not in audit.read_text()


def test_sync_guard_writes_to_the_same_sink(tmp_path: Path) -> None:
    audit = tmp_path / 'requests.jsonl'
    configure_request_audit(audit)
    session = ReadOnlySession(MagicMock(), 'default', [])
    session.get(f'https://{HOST}{API}/stat/device?x=1')
    [line] = [json.loads(line) for line in audit.read_text().splitlines()]
    assert (line['method'], line['path']) == ('GET', f'{API}/stat/device')
    configure_request_audit(None)
    session.get(f'https://{HOST}{API}/stat/sta')
    assert len(audit.read_text().splitlines()) == 1


def test_request_allowed_is_pure_policy() -> None:
    assert request_allowed('get', f'{API}/stat/device?x=1', 'default') == (
        True,
        f'{API}/stat/device',
    )
    assert request_allowed('POST', f'{API}/stat/event', 'default') == (True, f'{API}/stat/event')
    for method, url in [
        ('PUT', f'{API}/rest/device/x'),
        ('GET', f'{API}/cmd/devmgr'),
        ('POST', f'{API}/stat/event?x=1'),
        ('POST', '/proxy/network/api/s/other/stat/event'),
        ('GET', f'{API}/../cmd/devmgr'),
    ]:
        allowed, reason = request_allowed(method, url, 'default')
        assert not allowed and reason.startswith('refused')


async def test_aclose_closes_the_transport() -> None:
    transport = CountingTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    await shared.acquire()
    await shared.aclose()
    assert transport.closed
    assert not shared.is_connected
    await shared.aclose()  # idempotent


async def test_failed_connect_is_not_cached() -> None:
    transport = CountingTransport(token_ok=False)
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    for _ in range(2):
        with pytest.raises(ToolError) as exc:
            await shared.acquire()
        assert exc.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
    assert transport.count()[('GET', '/api/system')] == 2
    assert not shared.is_connected


async def test_borrower_failure_propagates_and_leaves_it_unconnected() -> None:
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=CountingTransport(token_ok=False))
    client = UniFiClient()
    with use_shared_controller_client(shared):
        with pytest.raises(ToolError):
            await client.connect()
    assert not client.is_connected


# ---------------------------------------------------------------------------
# A session lost after the first connect
# ---------------------------------------------------------------------------

ROTATED_TOKEN = 'FAKE-ROTATED-TOKEN-MUST-NOT-APPEAR'  # pragma: allowlist secret


class SessionTransport(CountingTransport):
    """A mock controller that accepts one token at a time and can expire sessions."""

    def __init__(self, valid: str = FAKE_TOKEN) -> None:
        self.valid = valid
        self.expire_next = 0  # answer this many data requests with 401
        self.always_401 = False
        super().__init__()

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        token_ok = request.headers.get('X-API-KEY') == self.valid
        if path == f'{API}/self':
            self.calls.append((request.method, path))
            return httpx.Response(200 if token_ok else 401, json={'meta': {'rc': 'ok'}})
        if path.startswith(API) and (self.always_401 or self.expire_next or not token_ok):
            self.calls.append((request.method, path))
            self.expire_next = max(0, self.expire_next - 1)
            return httpx.Response(
                401, json={'meta': {'rc': 'error', 'msg': 'api.err.LoginRequired'}}
            )
        return super()._handle(request)


async def test_a_401_after_the_first_connect_makes_the_holder_reconnect() -> None:
    transport = SessionTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            assert await client.get_devices() == [{'name': 'sw'}]
        first = await shared.acquire()
        transport.expire_next = 1
        async with UniFiClient() as client:
            assert await client.get_devices() == [{'name': 'sw'}]
        second = await shared.acquire()

    assert second is not first and shared.is_connected
    assert transport.count()[('GET', f'{API}/self')] == 2  # one fresh login, not per borrower
    assert second._client is not None and second._client.headers.get('X-API-KEY') == FAKE_TOKEN
    assert first._client is not None and not first._client.is_closed  # kept for borrowers
    await shared.aclose()
    assert first._client is None and second._client is None  # both closed by aclose


async def test_a_rotated_token_is_picked_up_without_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {'creds': TOKEN_CREDS}

    async def _creds() -> Credentials:
        return current['creds']

    monkeypatch.setattr(client_mod, 'get_credentials', _creds)
    transport = SessionTransport()
    shared = SharedControllerClient(inner_transport=transport)  # credentials from the chain
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            await client.get_devices()
        # The token is rotated on the controller and in the credential store.
        transport.valid = ROTATED_TOKEN
        current['creds'] = Credentials(host=HOST, api_token=ROTATED_TOKEN)
        async with UniFiClient() as client:
            assert await client.get_devices() == [{'name': 'sw'}]
    owner = await shared.acquire()
    assert owner._client is not None and owner._client.headers['X-API-KEY'] == ROTATED_TOKEN
    await shared.aclose()


async def test_concurrent_borrowers_that_see_one_401_reconnect_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {'creds': TOKEN_CREDS}

    async def _creds() -> Credentials:
        return current['creds']

    monkeypatch.setattr(client_mod, 'get_credentials', _creds)
    transport = SessionTransport()
    shared = SharedControllerClient(inner_transport=transport)
    results: list[object] = []

    async def use() -> None:
        async with UniFiClient() as client:
            results.append(await client.get_devices())

    with use_shared_controller_client(shared):
        await shared.acquire()
        transport.valid = ROTATED_TOKEN  # every request on the old connection now gets 401
        current['creds'] = Credentials(host=HOST, api_token=ROTATED_TOKEN)
        async with anyio.create_task_group() as group:
            group.start_soon(use)
            group.start_soon(use)
    assert results == [[{'name': 'sw'}], [{'name': 'sw'}]]
    assert transport.count()[('GET', f'{API}/self')] == 2  # one reconnect for both borrowers
    await shared.aclose()


async def test_a_persistent_401_is_an_error_not_endless_reauthentication() -> None:
    transport = SessionTransport()
    shared = SharedControllerClient(TOKEN_CREDS, inner_transport=transport)
    with use_shared_controller_client(shared):
        async with UniFiClient() as client:
            transport.always_401 = True
            with pytest.raises(ToolError) as exc:
                await client.get_devices()
    assert exc.value.error_code == ErrorCodes.API_ERROR
    assert 'HTTP 401' in exc.value.message
    assert transport.count()[('GET', f'{API}/self')] == 2  # first login + one reconnect
    await shared.aclose()


async def test_cli_client_retries_a_401_once_then_reports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = SessionTransport()
    transport.always_401 = True
    real = httpx.AsyncClient

    def _factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs['transport'] = transport
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(client_mod.httpx, 'AsyncClient', _factory)
    async with UniFiClient(TOKEN_CREDS) as client:
        with pytest.raises(ToolError) as exc:
            await client.get_devices()
    assert 'HTTP 401' in exc.value.message
    assert transport.count()[('GET', f'{API}/stat/device')] == 2
