"""One shared, read-only-guarded sync controller session for the port-diagnostics tools (021).

Every sync tool (``get_switch_ports`` … ``inspect_switch_port``) borrows one process-wide
``UnifiApiClient`` through ``port_diagnostics_tools._readonly_sync_client()``: logged in once,
guarded straight after login, kept through a refresh, logged out by the server's shutdown
drain. Per-call attribution of ``request_audit`` survives the sharing through a
``contextvars.ContextVar`` set by the async handler before the thread hop. No test reaches a
network: ``UnifiApiClient`` is replaced by a factory of fake clients, each over a
``FakeSession``.
"""

from __future__ import annotations

import asyncio
import contextvars
import pytest
import requests
import threading
import time
from pathlib import Path
from tests.fixtures_unifi import (
    API,
    API_RE,
    BASE_URL,
    FAKE_TOKEN,
    NAS_MAC,
    SITE,
    SWITCH_NAME,
    FakeResponse,
    FakeSession,
    default_routes,
    fake_client,
)
from typing import Any
from unifi_mapper import api_client
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import ReadOnlySession, ReadOnlyViolation
from unifi_mapper.diagnostics import inspect_port
from unifi_mapper.diagnostics import port_diagnostics_tools as tools
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry


pytestmark = pytest.mark.usefixtures('block_network')

MANIFESTS = Path(server.__file__).parent / 'manifests'
DEVICES = f'{API}/stat/device'
PORTCONF = f'{API}/rest/portconf'
REAL_SESSION_REQUEST = requests.Session.request  # before block_network replaces it


@pytest.fixture(autouse=True)
def fresh_shared_session() -> Any:
    """No test inherits another's shared client; none leaves one behind."""
    tools._SHARED.reset()
    yield
    tools._SHARED.reset()


class Controller:
    """A fake controller: every client the factory builds, every login and logout."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.clients: list[Any] = []
        self.sessions: list[FakeSession] = []  # one per login, as _perform_login makes
        self.logins = 0
        self.logouts = 0
        self.login_result: bool | Exception = True
        self.pause = 0.0  # a sleep per request, to interleave worker threads

    def new_session(self) -> FakeSession:
        session = FakeSession(self.routes)
        if self.pause:
            inner = session._respond

            def slow(*args: Any, **kwargs: Any) -> FakeResponse:
                time.sleep(self.pause)
                return inner(*args, **kwargs)

            session._respond = slow  # type: ignore[method-assign]
        self.sessions.append(session)
        return session

    def factory(self, **_: Any) -> Any:
        client = fake_client(self.new_session())
        client.is_authenticated = False

        def login() -> bool:
            self.logins += 1
            if isinstance(self.login_result, Exception):
                raise self.login_result
            if self.login_result:
                client.session = self.new_session()  # a fresh session, as _perform_login does
                client.is_authenticated = True
            return self.login_result

        def logout() -> bool:
            self.logouts += 1
            client.session.close()
            client.is_authenticated = False
            return True

        client.login = login
        client.logout = logout
        self.clients.append(client)
        return client

    @property
    def calls(self) -> list[dict[str, Any]]:
        return [call for session in self.sessions for call in session.calls]


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch) -> Controller:
    monkeypatch.setenv('UNIFI_URL', BASE_URL)
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)  # pragma: allowlist secret
    fake = Controller(default_routes())
    monkeypatch.setattr(api_client, 'UnifiApiClient', fake.factory)
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(MANIFESTS))
    return fake


def _devices_route() -> Any:
    """The default ``stat/device`` route payload."""
    return default_routes()[('GET', r'^(?:/proxy/network)?/api/s/default/stat/device$')]


def _once_401(payload: Any) -> Any:
    """A route that answers 401 to the first request and ``payload`` afterwards."""
    seen = {'n': 0}

    def route(**_: Any) -> Any:
        seen['n'] += 1
        return (
            (401, {'meta': {'rc': 'error', 'msg': 'api.err.LoginRequired'}})
            if seen['n'] == 1
            else payload
        )

    return route


def _result(out: Any) -> dict[str, Any]:
    envelope = out.structuredContent
    assert envelope['ok'] is True, envelope
    return envelope['result']


# --- one client, logged in once -------------------------------------------------------------


async def test_the_sync_tools_share_one_client_logged_in_once(controller: Controller) -> None:
    for _ in range(3):
        _result(await server.execute_tool('get_switch_ports', {'switch': SWITCH_NAME}))
    _result(await server.execute_tool('inspect_switch_port', {'switch': SWITCH_NAME, 'port': 5}))
    assert len(controller.clients) == 1
    assert controller.logins == 1
    assert controller.logouts == 0  # the drain logs out, not the call
    (client,) = controller.clients
    assert isinstance(client.session, ReadOnlySession)


async def test_the_shared_client_keeps_the_client_settings_from_the_environment(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[dict[str, Any]] = []
    real = controller.factory

    def recording(**kwargs: Any) -> Any:
        built.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(api_client, 'UnifiApiClient', recording)
    monkeypatch.setenv('UNIFI_TIMEOUT', '42')
    monkeypatch.setenv('UNIFI_MAX_RETRIES', '7')
    monkeypatch.setenv('UNIFI_RETRY_DELAY', '2.5')
    with tools._readonly_sync_client():
        pass
    assert [(b['timeout'], b['max_retries'], b['retry_delay']) for b in built] == [(42, 7, 2.5)]


def test_a_changed_environment_retires_the_shared_client(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client is bound to the credentials and settings it was built from (one process
    sees one environment; tests and a reloaded config see the change on the next call)."""
    with tools._readonly_sync_client() as (first, _site):
        pass
    monkeypatch.setenv('UNIFI_TIMEOUT', '42')
    with tools._readonly_sync_client() as (second, _site):
        pass
    assert first is not second and len(controller.clients) == 2
    assert controller.logouts == 1  # the retired client was idle: logged out at once
    assert controller.sessions[1].closed is True


# --- per-call request_audit ----------------------------------------------------------------


async def test_two_concurrent_calls_each_record_only_their_own_requests(
    controller: Controller,
) -> None:
    params = {'switch': SWITCH_NAME, 'port': 5}
    # The first call on a client builds UnifiApiClient's LLDP MAC cache (one extra
    # stat/device read); the reference is the second, warm, call.
    _result(await server.execute_tool('diagnose_switch_port', params))
    alone = _result(await server.execute_tool('diagnose_switch_port', params))
    controller.pause = 0.002  # interleave the two workers' requests
    before = len(controller.sessions[-1].calls)
    bundle, history = await asyncio.gather(
        server.execute_tool('diagnose_switch_port', params),
        server.execute_tool('get_client_history', {'client': NAS_MAC, 'switch': SWITCH_NAME}),
    )
    audit = _result(bundle)['request_audit']
    assert audit == alone['request_audit']  # exactly this call's requests, in its order
    assert _result(history)['records']
    during = controller.sessions[-1].calls[before:]  # both calls ran on the one session
    assert len(during) > len(audit)  # the other call's requests were there too, unrecorded
    assert controller.logins == 1


def test_the_session_audit_is_the_calling_calls_collector(controller: Controller) -> None:
    """What ``build_port_diagnostic_bundle`` ships (``list(install_read_only_guard(...))``)
    is the current call's collector; outside a call nothing is kept."""
    from unifi_mapper.core.utils.readonly import install_read_only_guard

    with tools._readonly_sync_client() as (api, site):
        audit = install_read_only_guard(api, site)
        api.session.get(f'{BASE_URL}{DEVICES}')  # no collector: dropped
        assert list(audit) == [] and len(audit) == 0 and not audit
        token = tools._request_audit.set([])
        try:
            api.session.get(f'{BASE_URL}{PORTCONF}')
            assert list(audit) == [{'method': 'GET', 'path': PORTCONF}]
            assert len(audit) == 1 and audit[0]['path'] == PORTCONF and bool(audit)
        finally:
            tools._request_audit.reset(token)
        assert list(audit) == []


def test_an_abandoned_worker_cannot_append_to_another_calls_collector_or_a_published_record(
    controller: Controller,
) -> None:
    """A worker the runner abandoned keeps its own copy of the context: its late request lands
    in its own collector, and a record already published (a list snapshot) does not change."""
    with tools._readonly_sync_client() as (api, _site):
        collector_a: list[dict[str, str]] = []
        token = tools._request_audit.set(collector_a)
        abandoned = contextvars.copy_context()  # what asyncio.to_thread hands the worker
        tools._request_audit.reset(token)

        collector_b: list[dict[str, str]] = []
        token = tools._request_audit.set(collector_b)
        try:
            api.session.get(f'{BASE_URL}{PORTCONF}')
            published = list(api.session.audit)
        finally:
            tools._request_audit.reset(token)

        late = threading.Thread(
            target=abandoned.run, args=(api.session.get, f'{BASE_URL}{DEVICES}')
        )
        late.start()
        late.join()

    assert collector_a == [{'method': 'GET', 'path': DEVICES}]
    assert collector_b == [{'method': 'GET', 'path': PORTCONF}]
    assert published == [{'method': 'GET', 'path': PORTCONF}]


# --- 401: one refresh, one replay -------------------------------------------------------------


async def test_a_401_triggers_exactly_one_refresh_and_one_replay(controller: Controller) -> None:
    controller.routes.update(default_routes(devices=_once_401(_devices_route())))
    out = _result(
        await server.execute_tool('diagnose_switch_port', {'switch': SWITCH_NAME, 'port': 5})
    )
    assert controller.logins == 2  # the first login and one refresh
    assert controller.logouts == 0
    paths = [c['path'] for c in controller.calls if c['path'] == DEVICES]
    assert len(paths) >= 2  # the refused request and its replay
    assert out['request_audit'][:2] == [{'method': 'GET', 'path': DEVICES}] * 2
    (client,) = controller.clients
    assert client.session.audit is not None and isinstance(client.session, ReadOnlySession)
    # The replayed request went to the fresh session the refresh logged in with.
    assert controller.sessions[-1].paths('GET')[0] == DEVICES


def test_a_second_401_is_returned_as_is_never_a_loop(controller: Controller) -> None:
    controller.routes.update(
        default_routes(devices=(401, {'meta': {'rc': 'error', 'msg': 'api.err.LoginRequired'}}))
    )
    with tools._readonly_sync_client() as (api, _site):
        response = api.session.get(f'{BASE_URL}{DEVICES}')
    assert response.status_code == 401
    assert controller.logins == 2  # one refresh for this request, not one per 401
    assert sum(1 for c in controller.calls if c['path'] == DEVICES) == 2  # one replay


def test_a_permanent_401_through_a_high_level_getter_costs_one_login_and_one_replay(
    controller: Controller,
) -> None:
    """One re-authentication owner on the shared path (0.4.0 council pass B, F-04).

    The guard refreshes and replays once at the session level. ``get_devices`` has its own
    401 branch that re-logs in and retries; stacked on the shared session that made a
    permanent 401 cost three logins and four requests. On the shared session the client's
    branch must stand down, so the advertised bound holds through the real getter.
    """
    controller.routes.update(
        default_routes(devices=(401, {'meta': {'rc': 'error', 'msg': 'api.err.LoginRequired'}}))
    )
    with tools._readonly_sync_client() as (api, site):
        result = api.get_devices(site)
    assert result == {}  # the getter's failure value, not a late success
    assert controller.logins == 2, 'the first login and ONE refresh'
    assert sum(1 for c in controller.calls if c['path'] == DEVICES) == 2, 'one request, one replay'


async def test_a_refresh_on_one_call_leaves_a_concurrent_call_unaffected(
    controller: Controller,
) -> None:
    controller.routes.update(default_routes(devices=_once_401(_devices_route())))
    controller.pause = 0.002
    a, b = await asyncio.gather(
        server.execute_tool('get_switch_ports', {'switch': SWITCH_NAME}),
        server.execute_tool(
            'diff_port_profiles',
            {
                'profile_a': 'Access Port VLAN 255 Management 10Gbps',
                'profile_b': 'Access Port VLAN 255 Management Auto',
            },
        ),
    )
    assert _result(a)['ports'] and _result(b)['differences'] is not None
    assert controller.logins == 2


def test_the_guard_is_on_the_shared_session_and_survives_refresh(controller: Controller) -> None:
    controller.routes.update(default_routes(devices=_once_401(_devices_route())))
    with tools._readonly_sync_client() as (api, _site):
        guard = api.session
        assert isinstance(guard, ReadOnlySession)
        with pytest.raises(ReadOnlyViolation):
            api.session.put(f'{BASE_URL}{API}/rest/device/x', json={})
        api.session.get(f'{BASE_URL}{DEVICES}')  # 401 -> refresh -> replay
        assert controller.logins == 2
        assert api.session is guard  # the same guard object, over the fresh session
        with pytest.raises(ReadOnlyViolation):
            api.session.put(f'{BASE_URL}{API}/rest/device/x', json={})
        assert controller.sessions[-1].paths('GET') == [DEVICES]  # requests go to the new one
        assert all(not c['method'] == 'PUT' for c in controller.calls)


def test_a_login_the_client_runs_itself_keeps_the_guard(controller: Controller) -> None:
    """``UnifiApiClient`` methods call ``self.login()`` when not authenticated; the login
    replaces ``client.session``, and the shared guard must come back on top."""
    with tools._readonly_sync_client() as (api, _site):
        guard = api.session
        api.is_authenticated = False
        api.login()
        assert api.session is guard and isinstance(api.session, ReadOnlySession)
        assert controller.logins == 2


# --- init failure, shutdown ------------------------------------------------------------------


def test_init_failure_resets_so_the_next_call_retries(controller: Controller) -> None:
    controller.login_result = False
    with pytest.raises(ToolError) as refused:
        with tools._readonly_sync_client():
            pass
    assert refused.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    controller.login_result = RuntimeError('tls handshake failed')
    with pytest.raises(ToolError) as raised:
        with tools._readonly_sync_client():
            pass
    assert raised.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert 'tls handshake failed' in raised.value.message
    controller.login_result = True
    with tools._readonly_sync_client() as (api, site):
        assert site == SITE and isinstance(api.session, ReadOnlySession)
    assert len(controller.clients) == 3 and controller.logins == 3


def test_shutdown_waits_for_active_workers_then_logs_out(controller: Controller) -> None:
    holding = threading.Event()
    release = threading.Event()

    def worker() -> None:
        with tools._readonly_sync_client():
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=worker)
    thread.start()
    assert holding.wait(5)
    drained: list[bool] = []
    drain = threading.Thread(
        target=lambda: drained.append(tools.shutdown_shared_sync_session(timeout=5))
    )
    drain.start()
    time.sleep(0.1)
    assert controller.logouts == 0 and drain.is_alive()  # never under an active worker
    release.set()
    thread.join(5)
    drain.join(5)
    assert drained == [True]
    assert controller.logouts == 1 and controller.sessions[-1].closed is True
    # A new call after the drain builds a new client.
    with tools._readonly_sync_client():
        pass
    assert len(controller.clients) == 2


def test_shutdown_leaves_a_still_active_worker_alone_after_its_bound(
    controller: Controller,
) -> None:
    holding = threading.Event()
    release = threading.Event()

    def worker() -> None:
        with tools._readonly_sync_client():
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=worker)
    thread.start()
    assert holding.wait(5)
    try:
        assert tools.shutdown_shared_sync_session(timeout=0.1) is False
        assert controller.logouts == 0  # not closed under the worker
    finally:
        release.set()
        thread.join(5)


def test_shutdown_with_no_client_is_a_no_op(controller: Controller) -> None:
    assert tools.shutdown_shared_sync_session(timeout=0.1) is True
    assert controller.logins == 0 and controller.logouts == 0


async def test_the_server_lifespan_drains_the_shared_session(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    drained: list[float] = []
    monkeypatch.setattr(
        tools, 'shutdown_shared_sync_session', lambda timeout=0.0: drained.append(timeout) or True
    )
    async with server.lifespan(server._build_fastmcp('execute_tool', ToolRegistry(MANIFESTS))):
        pass
    assert len(drained) == 1 and drained[0] > 0


# --- inspect_switch_port rides the same session -----------------------------------------------


async def test_inspect_switch_port_uses_the_shared_session_and_its_collector(
    controller: Controller,
) -> None:
    result = await inspect_port.inspect_switch_port(SWITCH_NAME, 2)
    assert result['port_idx'] == 2
    assert len(controller.clients) == 1 and controller.logins == 1
    (client,) = controller.clients
    assert isinstance(client.session, ReadOnlySession)
    assert {c['method'] for c in controller.calls} == {'GET'}


# --- the underlying requests.Session under concurrent reads -----------------------------------


class _CannedAdapter(requests.adapters.BaseAdapter):
    """Answers every request from memory, after a short pause, counting them."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self._lock = threading.Lock()

    def send(self, request: Any, **_: Any) -> requests.Response:
        time.sleep(0.001)
        with self._lock:
            self.count += 1
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"meta": {"rc": "ok"}, "data": []}'
        response.headers['Content-Type'] = 'application/json'
        response.request = request
        response.url = request.url
        return response

    def close(self) -> None:
        return None


def test_concurrent_reads_through_one_requests_session_stay_attributed(
    controller: Controller, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guarded shared session over a real ``requests.Session``: sixteen worker threads
    each read thirty paths and each collector holds exactly its own thirty, in order."""
    # block_network replaces Session.request; the real one is wanted here, over an in-memory
    # adapter (no HTTPAdapter, no socket: those stay blocked).
    monkeypatch.setattr(requests.Session, 'request', REAL_SESSION_REQUEST)
    adapter = _CannedAdapter()
    with tools._readonly_sync_client() as (api, _site):
        real = requests.Session()
        real.mount('https://', adapter)
        api.session.headers.update({'User-Agent': 'test'})  # the client's per-request update
        monkeypatch.setattr(tools._SHARED._record, 'raw', real)
        collectors: dict[int, list[dict[str, str]]] = {}
        failures: list[BaseException] = []

        def worker(n: int) -> None:
            collector: list[dict[str, str]] = []
            collectors[n] = collector
            token = tools._request_audit.set(collector)
            try:
                for i in range(30):
                    api.session.headers.update({'Accept': 'application/json'})
                    response = api.session.get(f'{BASE_URL}{API}/stat/sta/{n}-{i}', timeout=1)
                    assert response.status_code == 200
            except BaseException as e:  # noqa: BLE001 - reported below
                failures.append(e)
            finally:
                tools._request_audit.reset(token)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
    assert failures == []
    assert adapter.count == 16 * 30
    for n, collector in collectors.items():
        assert [c['path'] for c in collector] == [f'{API}/stat/sta/{n}-{i}' for i in range(30)]


# --- council pass B, verify item (a): a login in flight never exposes a raw session, and a
# worker's own login waits for the refresh instead of logging in beside it


def _real_client_record(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The shared record around a real UnifiApiClient (its real login and _perform_login)."""
    monkeypatch.setenv('UNIFI_URL', BASE_URL)
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)  # pragma: allowlist secret
    monkeypatch.setattr(
        api_client, 'UnifiApiClient', lambda **_: fake_client(FakeSession(default_routes()))
    )
    return tools._SHARED.acquire()


def _blocking_login_session(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[FakeSession, threading.Event, threading.Event, list[int]]:
    """A second session whose auth GET blocks until released; every Session() is counted."""
    second = FakeSession({**default_routes(), ('GET', rf'^{API_RE}/self$'): {'data': []}})
    in_login, finish = threading.Event(), threading.Event()
    inner = second._respond

    def blocking(*args: Any, **kwargs: Any) -> Any:
        in_login.set()
        assert finish.wait(5)
        return inner(*args, **kwargs)

    second._respond = blocking  # type: ignore[method-assign]
    built: list[int] = []

    def session_factory() -> FakeSession:
        built.append(1)
        return second

    monkeypatch.setattr(api_client.requests, 'Session', session_factory)
    monkeypatch.setattr(api_client.requests, 'get', lambda *_a, **_k: FakeResponse(200, {}))
    return second, in_login, finish, built


def test_the_shared_client_s_session_stays_guarded_while_a_refresh_logs_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _real_client_record(monkeypatch)
    second, in_login, finish, _ = _blocking_login_session(monkeypatch)
    before = record.raw

    refresher = threading.Thread(target=tools._SHARED.refresh, args=(record, record.generation))
    refresher.start()
    assert in_login.wait(5)
    seen_during_login = record.api.session
    raw_during_login = record.raw
    finish.set()
    refresher.join(5)

    assert seen_during_login is record.guarded, 'a worker must never pick up the raw session'
    assert raw_during_login is before, 'the old session serves until the new one is logged in'
    assert record.raw is second and record.api.session is record.guarded
    tools._SHARED.release(record)


def test_a_worker_s_own_login_waits_for_the_refresh_instead_of_logging_in_beside_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _real_client_record(monkeypatch)
    _, in_login, finish, built = _blocking_login_session(monkeypatch)
    api = record.api

    refresher = threading.Thread(target=tools._SHARED.refresh, args=(record, record.generation))
    refresher.start()
    assert in_login.wait(5)
    # A worker whose getter finds is_authenticated False calls login() itself.
    worker = threading.Thread(target=api.get_devices, args=(SITE,))
    worker.start()
    time.sleep(0.05)  # long enough for an unserialised login to have started
    finish.set()
    refresher.join(5)
    worker.join(5)

    assert len(built) == 1, 'one login per expiry: the worker must wait for the refresh'
    assert api.is_authenticated is True
    tools._SHARED.release(record)
