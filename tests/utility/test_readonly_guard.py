"""Tests for the transport-level read-only guard."""

import pytest
import re
import requests
from tests.fixtures_unifi import (
    BASE_URL,
    FAKE_PW,
    SITE,
    SWITCH_ID,
    FakeResponse,
    FakeSession,
    default_routes,
    fake_client,
    fake_devices,
)
from types import SimpleNamespace
from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.core.utils.readonly import (
    ReadOnlySession,
    ReadOnlyViolation,
    assert_guarded,
    install_read_only_guard,
)
from unittest.mock import MagicMock


BASE = 'https://192.0.2.1'
API = f'{BASE}/proxy/network/api/s/default'
V2 = f'{BASE}/proxy/network/v2/api/site/default'
STAT_DEVICE = {'method': 'GET', 'path': '/proxy/network/api/s/default/stat/device'}

pytestmark = pytest.mark.usefixtures('block_network')


@pytest.fixture
def inner() -> MagicMock:
    session = MagicMock()
    session.headers = {'Accept': 'application/json'}
    return session


@pytest.fixture
def guarded(inner: MagicMock) -> tuple[ReadOnlySession, list[dict[str, str]], MagicMock]:
    audit: list[dict[str, str]] = []
    return ReadOnlySession(inner, 'default', audit), audit, inner


def test_get_is_allowed_and_audited_without_host_or_query(guarded):
    session, audit, inner = guarded
    session.get(f'{API}/stat/device?x=1', timeout=5)
    inner.get.assert_called_once_with(f'{API}/stat/device?x=1', timeout=5)
    assert audit == [{'method': 'GET', 'path': '/proxy/network/api/s/default/stat/device'}]


@pytest.mark.parametrize(
    'url', [f'{API}/cmd/devmgr', f'{API}/upd/device/ab0000000000000000000001', f'{API}/CMD/x']
)
def test_get_under_cmd_or_upd_is_refused(guarded, url):
    session, audit, inner = guarded
    with pytest.raises(ReadOnlyViolation):
        session.get(url)
    inner.get.assert_not_called()
    assert audit == []


@pytest.mark.parametrize(
    'url',
    [
        f'{API}/stat/event',
        f'{API}/list/alarm',
        f'{V2}/system-log/device-alert',
        f'{V2}/system-log/admin-activity',
        f'{V2}/system-log/update-alert',
        f'{V2}/system-log/client-alert',
        f'{BASE}/api/s/default/stat/event',
        f'{BASE}/api/auth/logout',
        f'{BASE}/api/logout',
    ],
)
def test_post_to_allowlisted_query_endpoints_is_allowed(guarded, url):
    session, audit, inner = guarded
    session.post(url, json={'_limit': 1})
    inner.post.assert_called_once_with(url, data=None, json={'_limit': 1})
    assert audit[-1]['method'] == 'POST'


@pytest.mark.parametrize(
    'url',
    [
        f'{API}/rest/device/ab0000000000000000000001',
        f'{API}/rest/portconf/0000000000000000000000b1',
        f'{API}/rest/networkconf',
        f'{API}/upd/device/x',
        f'{API}/cmd/devmgr',
        f'{API}/set/setting/mgmt',
        f'{V2}/system-log/threat-alert',
        f'{API}/stat/event/../cmd/devmgr',
        f'{API}/stat/event/%2e%2e/cmd/devmgr',
        f'{API}/stat/event?cmd=restart',
        f'{BASE}/proxy/network/api/s/other-site/stat/event',
    ],
)
def test_post_outside_the_allowlist_is_refused(guarded, url):
    session, audit, inner = guarded
    with pytest.raises(ReadOnlyViolation):
        session.post(url, json={'cmd': 'restart'})
    inner.post.assert_not_called()
    assert audit == []


@pytest.mark.parametrize('verb', ['put', 'patch', 'delete'])
def test_write_verbs_are_refused(guarded, verb):
    session, audit, inner = guarded
    with pytest.raises(ReadOnlyViolation):
        getattr(session, verb)(f'{API}/rest/device/ab0000000000000000000001', json={})
    assert getattr(inner, verb).call_count == 0
    assert audit == []


@pytest.mark.parametrize('method', ['PUT', 'put', 'PATCH', 'DELETE', 'OPTIONS'])
def test_request_with_a_write_method_is_refused(guarded, method):
    session, _, inner = guarded
    with pytest.raises(ReadOnlyViolation):
        session.request(method, f'{API}/rest/portconf/0000000000000000000000b1')
    inner.request.assert_not_called()


def test_request_get_passes_through(guarded):
    session, audit, inner = guarded
    session.request('get', f'{API}/stat/sysinfo')
    inner.request.assert_called_once_with('GET', f'{API}/stat/sysinfo')
    assert audit == [{'method': 'GET', 'path': '/proxy/network/api/s/default/stat/sysinfo'}]


def test_violation_is_a_permission_error(guarded):
    session, _, _ = guarded
    with pytest.raises(PermissionError):
        session.put(f'{API}/rest/device/x')


def test_audit_never_holds_bodies_or_headers(guarded):
    session, audit, _ = guarded
    session.post(f'{API}/stat/event', json={'secret_body': 'FAKE'})  # pragma: allowlist secret
    assert audit == [{'method': 'POST', 'path': '/proxy/network/api/s/default/stat/event'}]


def test_session_state_passes_through_and_bypass_attributes_do_not(guarded):
    session, _, inner = guarded
    session.headers.update({'X-Test': '1'})
    assert inner.headers['X-Test'] == '1'
    session.verify = False
    assert inner.verify is False
    session.close()
    inner.close.assert_called_once()
    with pytest.raises(AttributeError):
        _ = session.send
    with pytest.raises(AttributeError):
        _ = session.mount


def test_install_requires_an_authenticated_client(inner):
    client = SimpleNamespace(session=inner, is_authenticated=False, site='default')
    with pytest.raises(RuntimeError, match='after login'):
        install_read_only_guard(client)
    assert client.session is inner


def test_install_is_idempotent_and_returns_the_same_audit(inner):
    client = SimpleNamespace(session=inner, is_authenticated=True, site='default')
    first = install_read_only_guard(client)
    wrapped = client.session
    second = install_read_only_guard(client)
    assert isinstance(wrapped, ReadOnlySession)
    assert client.session is wrapped
    assert first is second
    client.session.get(f'{API}/stat/device')
    assert first == [{'method': 'GET', 'path': '/proxy/network/api/s/default/stat/device'}]


def test_assert_guarded_detects_a_replaced_session(inner):
    client = SimpleNamespace(session=inner, is_authenticated=True, site='default')
    install_read_only_guard(client)
    assert_guarded(client)
    client.session = MagicMock()  # a direct assignment that bypasses login
    with pytest.raises(ReadOnlyViolation, match='no longer installed'):
        assert_guarded(client)


# ---------------------------------------------------------------------------
# The guard survives a later login
# ---------------------------------------------------------------------------


class _RelogClient:
    """Mimics UnifiApiClient: ``_perform_login`` swaps in a fresh session, then logs in on it."""

    def __init__(self, session: object, fresh: MagicMock, outcome: str = 'ok') -> None:
        self.session = session
        self.fresh = fresh
        self.outcome = outcome
        self.site = 'default'
        self.is_authenticated = True

    def _perform_login(self) -> bool:
        self.session = self.fresh
        # Not on the POST allowlist: this only works because login runs before the re-wrap.
        self.session.post(f'{BASE}/api/auth/login', json={'username': 'fake-admin'})
        if self.outcome == 'raises':
            raise ConnectionError('controller unreachable')
        return self.outcome == 'ok'


def test_a_relogin_rewraps_the_new_session_with_the_same_audit(inner):
    fresh = MagicMock()
    client = _RelogClient(inner, fresh)
    audit = install_read_only_guard(client)
    client.session.get(f'{API}/stat/device')

    assert client._perform_login() is True

    fresh.post.assert_called_once()  # the login itself ran on the fresh, unwrapped session
    assert isinstance(client.session, ReadOnlySession)
    client.session.get(f'{API}/stat/device')
    fresh.get.assert_called_once()
    assert audit == [STAT_DEVICE, STAT_DEVICE]  # login traffic is not audited
    with pytest.raises(ReadOnlyViolation):
        client.session.put(f'{API}/rest/device/ab0000000000000000000001', json={})
    fresh.put.assert_not_called()


@pytest.mark.parametrize('outcome', ['fails', 'raises'])
def test_a_failed_relogin_still_leaves_the_new_session_guarded(inner, outcome):
    fresh = MagicMock()
    client = _RelogClient(inner, fresh, outcome=outcome)
    install_read_only_guard(client)
    if outcome == 'raises':
        with pytest.raises(ConnectionError):
            client._perform_login()
    else:
        assert client._perform_login() is False
    assert isinstance(client.session, ReadOnlySession)
    with pytest.raises(ReadOnlyViolation):
        client.session.delete(f'{API}/rest/portconf/0000000000000000000000b1')
    fresh.delete.assert_not_called()


def test_a_second_install_keeps_the_same_login_wrapper(inner):
    client = _RelogClient(inner, MagicMock())
    install_read_only_guard(client)
    wrapper = client._perform_login
    install_read_only_guard(client)
    assert client._perform_login is wrapper


def test_a_mock_client_keeps_its_configured_login(inner):
    client = MagicMock(session=inner, is_authenticated=True, site='default')
    client.login.return_value = 'configured'
    install_read_only_guard(client)
    assert client.login() == 'configured'
    assert isinstance(client.session, ReadOnlySession)


def test_reinstalling_after_a_direct_session_swap_does_not_stack_login_wrappers(inner):
    client = _RelogClient(inner, MagicMock())
    first = install_read_only_guard(client)
    client.session = MagicMock()  # bypasses login, so the guard is gone
    second = install_read_only_guard(client)
    assert second is not first

    client._perform_login()
    client.session.get(f'{API}/stat/device')

    assert second == [STAT_DEVICE]
    assert first == []


def test_a_401_from_stat_device_is_retried_through_the_same_guard():
    responses = iter([(401, {'meta': {'rc': 'error', 'msg': 'api.err.LoginRequired'}})])

    def devices(**_: object) -> object:
        return next(responses, {'data': fake_devices()})

    session = FakeSession(default_routes(devices=devices))
    client = fake_client(session)
    audit = install_read_only_guard(client, SITE)

    assert client.get_devices(SITE)['data']

    assert isinstance(client.session, ReadOnlySession)
    assert audit == [STAT_DEVICE, STAT_DEVICE]


@pytest.mark.parametrize(
    ('auth', 'login_method', 'login_path'),
    [
        ('token', 'GET', '/proxy/network/api/s/default/self'),
        ('username_password', 'POST', '/api/auth/login'),
    ],
)
def test_the_real_client_is_guarded_again_after_logout_and_login(
    monkeypatch, auth, login_method, login_path
):
    first = FakeSession(default_routes())
    if auth == 'token':
        client = fake_client(first)
    else:
        client = UnifiApiClient(
            base_url=BASE_URL, site=SITE, username='fake-admin', password=FAKE_PW, max_retries=1
        )
        client.is_authenticated, client.is_unifi_os, client.session = True, True, first
    audit = install_read_only_guard(client, SITE)
    assert client.get_devices(SITE)['data']

    second = FakeSession(
        {**default_routes(), (login_method, rf'^{re.escape(login_path)}$'): {'data': []}}
    )
    monkeypatch.setattr(requests, 'Session', lambda: second)
    monkeypatch.setattr(requests, 'get', lambda *_a, **_k: FakeResponse(200, {}))  # OS probe
    client.logout()
    assert client.is_authenticated is False and first.closed

    assert client.get_devices(SITE)['data']  # logs in again on `second`, then reads

    assert client.is_authenticated is True
    assert login_path in second.paths(login_method)
    assert isinstance(client.session, ReadOnlySession)
    assert audit == [STAT_DEVICE, STAT_DEVICE]
    with pytest.raises(ReadOnlyViolation):
        client.session.put(f'{API}/rest/device/{SWITCH_ID}', json={})
    assert second.paths('PUT') == []


# --- issue 029: a raw path starting with // is judged as sent, not after urlsplit drops a segment


@pytest.mark.parametrize(
    'path',
    [
        '//evil/proxy/network/api/s/default/stat/event',
        '//evil/proxy/network/integrations/v1/sites',
    ],
)
def test_a_network_path_reference_is_refused_not_collapsed(path):
    from unifi_mapper.core.utils.readonly import get_only_request_allowed, request_allowed

    for verb in ('POST', 'GET'):
        allowed, detail = request_allowed(verb, path, 'default')
        assert allowed is False
        assert 'network-path reference' in detail
    allowed, detail = get_only_request_allowed('GET', path)
    assert allowed is False and 'network-path reference' in detail
