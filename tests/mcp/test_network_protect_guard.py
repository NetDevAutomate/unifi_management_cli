"""Issue 024: the network_api and protect MCP tools run behind a read-only guard and audit.

network_api: every Integration API request goes through ``ReadOnlyAsyncTransport`` with the
GET-only policy (the Integration API has no read-only POST), so a write raises
``ReadOnlyViolation`` before any I/O and every GET reaches the opt-in request audit.

protect: ``ReadOnlyProtectApiClient`` overrides uiprotect's ``BaseApiClient.request``, the
method every uiprotect REST call goes through: GET and HEAD are audited and sent, the session
login is sent unaudited, and anything else is refused before any I/O.

Nothing here reaches a network: the network tests use ``httpx.MockTransport`` (so no
``block_network``, which patches ``httpx.AsyncClient.send``), and the Protect tests pass a
fake aiohttp session through uiprotect's documented ``session=`` argument.
"""

import httpx
import inspect
import json
import pytest
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from types import SimpleNamespace
from typing import Any
from uiprotect import ProtectApiClient
from unifi_mapper.core.utils.errors import ErrorCodes
from unifi_mapper.core.utils.readonly import (
    ReadOnlyAsyncTransport,
    ReadOnlyViolation,
    configure_request_audit,
    get_only_request_allowed,
)
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry
from unifi_mapper.mcp.runner import ToolRunner
from unifi_mapper.mcp.tools import network as network_tools
from unifi_mapper.mcp.tools import protect as protect_tools
from unifi_mapper.network import client as network_client
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.protect.client import ReadOnlyProtectApiClient, UniFiProtectClient
from unifi_mapper.protect.config import ProtectConfig
from unittest.mock import AsyncMock


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
NETWORK_HOST = '192.0.2.1'
PROTECT_HOST = '192.0.2.10'
INTEGRATION = f'/proxy/network/integrations/v1/sites/{SITE_ID}/'
NETWORK_TOOLS = [
    'get_firewall_zones',
    'get_firewall_policies',
    'get_acl_rules',
    'get_dns_policies',
    'get_clients',
    'get_networks',
]
PROTECT_TOOLS = ['get_cameras', 'get_nvr_info', 'get_sensors', 'get_lights', 'get_doorbells']


@pytest.fixture(autouse=True)
def _no_audit_sink() -> Iterator[None]:
    """Leave the process-wide audit sink cleared after every test."""
    yield
    configure_request_audit(None)


@pytest.fixture
def network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_NETWORK_HOST', NETWORK_HOST)
    monkeypatch.setenv('UNIFI_NETWORK_API_KEY', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', SITE_ID)


class Recorder(httpx.MockTransport):
    """A fake Integration API: records ``(method, path)`` and answers an empty page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        return httpx.Response(200, json={'data': []})


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch, network_env: None) -> Recorder:
    """Make the network tools' inner transport a recorder (the guard stays in front of it)."""
    rec = Recorder()
    monkeypatch.setattr(network_tools, '_inner_transport', lambda _config: rec)
    return rec


def _audit_lines(sink: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in sink.read_text().splitlines()] if sink.exists() else []


# --- the GET-only policy and the transport ------------------------------------------------


def test_get_only_policy_allows_reads_and_refuses_writes() -> None:
    url = f'https://{NETWORK_HOST}{INTEGRATION}firewall/zones?offset=0&limit=200'
    assert get_only_request_allowed('get', url) == (True, f'{INTEGRATION}firewall/zones')
    assert get_only_request_allowed('HEAD', f'{INTEGRATION}acls') == (True, f'{INTEGRATION}acls')
    for verb in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
        allowed, reason = get_only_request_allowed(verb, f'{INTEGRATION}networks')
        assert not allowed
        assert reason.startswith(f'refused {verb}') and 'only GET and HEAD' in reason, reason
    for tricky in (f'{INTEGRATION}../../../api/s/default/rest/x', f'{INTEGRATION}%2e%2e/x'):
        allowed, reason = get_only_request_allowed('GET', tricky)
        assert not allowed and reason.startswith('refused GET'), reason


def test_transport_takes_exactly_one_of_site_or_policy() -> None:
    inner = Recorder()
    with pytest.raises(ValueError):
        ReadOnlyAsyncTransport(inner)
    with pytest.raises(ValueError):
        ReadOnlyAsyncTransport(inner, 'default', policy=get_only_request_allowed)
    ReadOnlyAsyncTransport(inner, 'default')
    ReadOnlyAsyncTransport(inner, policy=get_only_request_allowed)


async def test_a_custom_policy_has_no_login_exemption() -> None:
    inner = Recorder()
    guarded = ReadOnlyAsyncTransport(inner, policy=get_only_request_allowed)
    async with httpx.AsyncClient(transport=guarded, base_url=f'https://{NETWORK_HOST}') as client:
        with pytest.raises(ReadOnlyViolation):
            await client.post('/api/auth/login', json={})
    assert inner.calls == []


# --- network_api ----------------------------------------------------------------------------


async def test_network_client_passes_its_transport(
    monkeypatch: pytest.MonkeyPatch, network_env: None
) -> None:
    seen: list[Any] = []

    class KwargsRecorder:
        def __init__(self, **kwargs: Any) -> None:
            seen.append(kwargs.get('transport'))

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(network_client.httpx, 'AsyncClient', KwargsRecorder)
    config = NetworkConfig.from_env()
    transport = Recorder()
    async with network_client.UniFiNetworkClient(config):
        pass
    async with network_client.UniFiNetworkClient(config, transport=transport):
        pass
    assert seen == [None, transport]


@pytest.mark.parametrize('tool', NETWORK_TOOLS)
async def test_each_network_tool_sends_only_audited_gets(
    tool: str, recorder: Recorder, tmp_path: Path
) -> None:
    sink = tmp_path / 'audit.jsonl'
    configure_request_audit(sink)

    assert await getattr(network_tools, tool)() == []

    assert recorder.calls, 'the tool sent no request'
    assert all(m == 'GET' and p.startswith(INTEGRATION) for m, p in recorder.calls), recorder.calls
    lines = _audit_lines(sink)
    assert [(line['method'], line['path']) for line in lines] == recorder.calls
    assert all(set(line) == {'t', 'method', 'path'} for line in lines)
    text = sink.read_text()
    assert FAKE_TOKEN not in text and NETWORK_HOST not in text and '?' not in text


NETWORK_WRITES: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = [
    ('delete_network', ('net-1',), {}),
    ('delete_acl_rule', ('acl-1',), {}),
    ('delete_dns_policy', ('dns-1',), {}),
    ('delete_traffic_matching_list', ('tml-1',), {}),
    ('create_network', ('lab',), {}),
    ('update_network', ('net-1',), {'name': 'lab'}),
    ('execute_device_action', ('dev-1', 'RESTART'), {}),
    ('authorize_guest', ('client-1',), {}),
]


@pytest.mark.parametrize(
    ('method', 'args', 'kwargs'), NETWORK_WRITES, ids=[w[0] for w in NETWORK_WRITES]
)
async def test_network_writes_are_refused_before_any_io(
    method: str, args: tuple[Any, ...], kwargs: dict[str, Any], recorder: Recorder, tmp_path: Path
) -> None:
    sink = tmp_path / 'audit.jsonl'
    configure_request_audit(sink)
    async with network_tools._read_only_client() as client:
        with pytest.raises(ReadOnlyViolation):
            await getattr(client, method)(*args, **kwargs)
    assert recorder.calls == []
    assert _audit_lines(sink) == []


async def test_a_write_inside_a_network_tool_is_read_only_violation(
    monkeypatch: pytest.MonkeyPatch, recorder: Recorder
) -> None:
    class WritingManager:
        def __init__(self, client: Any) -> None:
            self._client = client

        async def get_zones(self, refresh: bool = False) -> list[Any]:
            await self._client.delete_network('net-1')
            raise AssertionError('the guard let a DELETE through')

    monkeypatch.setattr(network_tools, 'FirewallManager', WritingManager)
    runner = ToolRunner(ToolRegistry(strict=True), settings=ServerSettings())

    out = await runner.run('get_firewall_zones', {})

    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == ErrorCodes.READ_ONLY_VIOLATION
    assert recorder.calls == []


# --- protect --------------------------------------------------------------------------------


class FakeResponse:
    """The parts of aiohttp.ClientResponse that uiprotect's request() path reads."""

    def __init__(self, body: bytes) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self.cookies: dict[str, Any] = {}
        self.content_type = 'application/json'
        self._body = body

    async def read(self) -> bytes:
        return self._body

    def release(self) -> None:
        return None


class FakeRequestContext:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    """Just enough of aiohttp.ClientSession for uiprotect: records ``(method, path)``."""

    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.closed = False
        self.cookie_jar = SimpleNamespace(clear=lambda: None)
        self.calls: list[tuple[str, str]] = []
        self._body = json.dumps(body if body is not None else {'id': 'nvr-1'}).encode()

    def request(self, method: str, url: Any, **_kwargs: Any) -> FakeRequestContext:
        self.calls.append((method.upper(), url.path))
        return FakeRequestContext(FakeResponse(self._body))

    async def close(self) -> None:
        self.closed = True


def _guarded_api(session: FakeSession, tmp_path: Path) -> ReadOnlyProtectApiClient:
    return ReadOnlyProtectApiClient(
        host=PROTECT_HOST,
        port=443,
        username='viewer',
        password=FAKE_PW,
        verify_ssl=False,
        session=session,
        store_sessions=False,
        config_dir=tmp_path / 'ufp',
        cache_dir=tmp_path / 'ufp-cache',
    )


@pytest.mark.usefixtures('block_network')
async def test_protect_guard_sends_reads_and_its_login_and_audits_only_the_reads(
    tmp_path: Path,
) -> None:
    sink = tmp_path / 'audit.jsonl'
    configure_request_audit(sink)
    session = FakeSession({'id': 'nvr-1'})

    assert await _guarded_api(session, tmp_path).api_request_obj('nvr') == {'id': 'nvr-1'}

    assert session.calls == [('POST', '/api/auth/login'), ('GET', '/proxy/protect/api/nvr')]
    lines = _audit_lines(sink)
    assert [(line['method'], line['path']) for line in lines] == [
        ('GET', '/proxy/protect/api/nvr')
    ]
    assert all(set(line) == {'t', 'method', 'path'} for line in lines)
    assert FAKE_PW not in sink.read_text() and PROTECT_HOST not in sink.read_text()


PROTECT_WRITES: list[tuple[str, Callable[[ReadOnlyProtectApiClient], Awaitable[Any]]]] = [
    ('reboot_nvr', lambda api: api.reboot_nvr()),
    ('patch_nvr', lambda api: api.api_request('nvr', method='patch', json={})),
    ('delete_camera', lambda api: api.api_request('cameras/x', method='delete')),
    (
        'public_api_patch',
        lambda api: api.api_request('/v1/chimes/x', method='patch', public_api=True),
    ),
]


@pytest.mark.usefixtures('block_network')
@pytest.mark.parametrize(
    'write', [w[1] for w in PROTECT_WRITES], ids=[w[0] for w in PROTECT_WRITES]
)
async def test_protect_guard_refuses_writes_before_any_io(
    write: Callable[[ReadOnlyProtectApiClient], Awaitable[Any]], tmp_path: Path
) -> None:
    sink = tmp_path / 'audit.jsonl'
    configure_request_audit(sink)
    session = FakeSession()

    with pytest.raises(ReadOnlyViolation):
        await write(_guarded_api(session, tmp_path))

    assert session.calls == []  # refused before the login, too
    assert _audit_lines(sink) == []


def test_protect_guard_signature_matches_uiprotect() -> None:
    """Canary for the uiprotect seam (pinned <9): the override must mirror request()."""

    def shape(fn: Any) -> list[tuple[str, Any, Any]]:
        return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()]

    assert ReadOnlyProtectApiClient.request is not ProtectApiClient.request
    assert shape(ReadOnlyProtectApiClient.request) == shape(ProtectApiClient.request)


def _protect_config(tmp_path: Path) -> ProtectConfig:
    return ProtectConfig(
        host=PROTECT_HOST,
        username='viewer',
        password=FAKE_PW,
        cache_dir=tmp_path / 'ufp-cache',
        store_sessions=False,
    )


@pytest.mark.usefixtures('block_network')
async def test_read_only_protect_client_uses_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bootstrap = SimpleNamespace(nvr=None, cameras={}, aiports={})
    monkeypatch.setattr(ProtectApiClient, 'get_bootstrap', AsyncMock(return_value=bootstrap))

    guarded = UniFiProtectClient(_protect_config(tmp_path), read_only=True)
    await guarded.connect()
    assert isinstance(guarded.api, ReadOnlyProtectApiClient)
    await guarded.disconnect()

    plain = UniFiProtectClient(_protect_config(tmp_path))
    await plain.connect()
    assert type(plain.api) is ProtectApiClient
    await plain.disconnect()


@pytest.mark.parametrize('tool', PROTECT_TOOLS)
async def test_every_protect_tool_opens_a_read_only_client(
    tool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[dict[str, Any]] = []

    class RecordingClient:
        def __init__(self, _config: Any, **kwargs: Any) -> None:
            opened.append(kwargs)
            self.cameras: dict[str, Any] = {}
            self.sensors: dict[str, Any] = {}
            self.lights: dict[str, Any] = {}
            self.nvr = None

        async def __aenter__(self) -> 'RecordingClient':
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(protect_tools, 'UniFiProtectClient', RecordingClient)
    monkeypatch.setattr(protect_tools, '_get_config', lambda: SimpleNamespace())

    await getattr(protect_tools, tool)()

    assert opened == [{'read_only': True}]


@pytest.mark.usefixtures('block_network')
async def test_a_write_inside_a_protect_tool_is_read_only_violation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv('PROTECT_HOST', PROTECT_HOST)
    monkeypatch.setenv('PROTECT_USERNAME', 'viewer')
    monkeypatch.setenv('PROTECT_PASSWORD', FAKE_PW)
    monkeypatch.setenv('PROTECT_STORE_SESSIONS', 'false')
    monkeypatch.setenv('PROTECT_CACHE_DIR', str(tmp_path / 'ufp-cache'))

    async def writes(self: ProtectApiClient) -> Any:
        await self.reboot_nvr()
        raise AssertionError('the guard let a POST through')

    monkeypatch.setattr(ProtectApiClient, 'get_bootstrap', writes)
    protect_tools._get_config.cache_clear()
    try:
        runner = ToolRunner(ToolRegistry(strict=True), settings=ServerSettings())
        out = await runner.run('get_nvr_info', {})
    finally:
        protect_tools._get_config.cache_clear()

    assert out.structuredContent is not None
    assert out.structuredContent['error_code'] == ErrorCodes.READ_ONLY_VIOLATION
