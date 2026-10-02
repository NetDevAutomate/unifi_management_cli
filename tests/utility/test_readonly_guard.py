"""Tests for the transport-level read-only guard."""

import pytest
from types import SimpleNamespace
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
    'url', [f'{API}/cmd/devmgr', f'{API}/upd/device/0000000000000000000000a1', f'{API}/CMD/x']
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
        f'{API}/rest/device/0000000000000000000000a1',
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
        getattr(session, verb)(f'{API}/rest/device/0000000000000000000000a1', json={})
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
    client.session = MagicMock()  # what a re-login would do
    with pytest.raises(ReadOnlyViolation, match='no longer installed'):
        assert_guarded(client)
