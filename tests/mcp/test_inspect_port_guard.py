"""inspect_switch_port runs behind the read-only guard and the opt-in request audit (issue 021).

Since the issue's step 1 it takes the same path as its sibling port-diagnostics tools:
``port_diagnostics_tools._readonly_sync_client()`` (one guarded login per call) under
``_mapped``, keeping its own error codes and its result shape.
"""

import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from tests.fixtures_unifi import (
    BASE_URL,
    FAKE_TOKEN,
    SITE,
    SWITCH_NAME,
    FakeSession,
    default_routes,
    fake_client,
)
from typing import Any
from unifi_mapper import api_client, port_inspect
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import ReadOnlySession, configure_request_audit
from unifi_mapper.diagnostics import inspect_port
from unifi_mapper.diagnostics import port_diagnostics_tools as sibling_tools


pytestmark = pytest.mark.usefixtures('block_network')


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Make ``_inspect_sync`` build an in-memory client; return the clients it built."""
    monkeypatch.setenv('UNIFI_URL', BASE_URL)
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)  # pragma: allowlist secret
    clients: list[Any] = []

    def factory(**_: Any) -> Any:
        client = fake_client(FakeSession(default_routes()))
        client.is_authenticated = False
        client.logged_out = False

        def login() -> bool:
            client.is_authenticated = True
            return True

        def logout() -> bool:
            client.logged_out = True
            return True

        client.login = login
        client.logout = logout
        clients.append(client)
        return client

    monkeypatch.setattr(api_client, 'UnifiApiClient', factory)
    return clients


def _unguarded(port: int) -> dict[str, Any]:
    client = fake_client(FakeSession(default_routes()))
    switch = port_inspect.resolve_switch(client, SITE, SWITCH_NAME)
    return port_inspect.inspect_port(client, SITE, switch, port).to_dict()


async def test_inspect_switch_port_installs_the_read_only_guard(made):
    result = await inspect_port.inspect_switch_port(SWITCH_NAME, 2)

    (client,) = made
    assert isinstance(client.session, ReadOnlySession)
    audit = client.session.audit
    assert audit, 'the guard recorded no requests'
    assert {entry['method'] for entry in audit} == {'GET'}
    assert client.logged_out is True
    assert result['port_idx'] == 2


async def test_inspect_switch_port_result_is_unchanged_by_the_guard(made, monkeypatch):
    from tests.analysis.test_link_settings import _FrozenDatetime

    monkeypatch.setattr(port_inspect, 'datetime', _FrozenDatetime)
    guarded = await inspect_port.inspect_switch_port(SWITCH_NAME, 5)
    assert guarded == _unguarded(5)


async def test_inspect_switch_port_requests_reach_the_request_audit(made, tmp_path: Path):
    sink = tmp_path / 'audit.jsonl'
    configure_request_audit(sink)
    try:
        await inspect_port.inspect_switch_port(SWITCH_NAME, 2)
    finally:
        configure_request_audit(None)

    lines = [json.loads(line) for line in sink.read_text().splitlines()]
    assert lines and {line['method'] for line in lines} == {'GET'}
    assert any(line['path'].endswith('/stat/device') for line in lines)
    assert all(set(line) == {'t', 'method', 'path'} for line in lines)


async def test_a_write_inside_inspect_is_refused_as_read_only_violation(made, monkeypatch):
    def writes(client: Any, site: str, switch: dict[str, Any], port: int) -> Any:
        client.session.put(f'{BASE_URL}/proxy/network/api/s/{site}/rest/device/x', json={})
        raise AssertionError('the guard let a PUT through')

    monkeypatch.setattr(port_inspect, 'inspect_port', writes)
    with pytest.raises(ToolError) as excinfo:
        await inspect_port.inspect_switch_port(SWITCH_NAME, 2)

    assert excinfo.value.error_code == ErrorCodes.READ_ONLY_VIOLATION
    (client,) = made
    assert client.logged_out is True
    assert all(entry['method'] == 'GET' for entry in client.session.audit)


async def test_existing_error_codes_are_kept(made):
    with pytest.raises(ToolError) as missing_switch:
        await inspect_port.inspect_switch_port('no such switch', 2)
    assert missing_switch.value.error_code == ErrorCodes.DEVICE_NOT_FOUND

    with pytest.raises(ToolError) as missing_port:
        await inspect_port.inspect_switch_port(SWITCH_NAME, 99)
    assert missing_port.value.error_code == ErrorCodes.INVALID_PORT


# --- issue 021 step 1: the sibling tools' client and error mapping -----------------------


async def test_inspect_switch_port_uses_the_siblings_readonly_sync_client(monkeypatch):
    """The one guarded, audited login path every sync port-diagnostics tool takes."""
    client = fake_client(FakeSession(default_routes()))
    entered: list[str] = []

    @contextmanager
    def recording_client():
        entered.append('in')
        try:
            yield client, SITE
        finally:
            entered.append('out')

    monkeypatch.setattr(sibling_tools, '_readonly_sync_client', recording_client)
    result = await inspect_port.inspect_switch_port(SWITCH_NAME, 2)

    assert entered == ['in', 'out']
    assert result['port_idx'] == 2


async def test_a_login_exception_is_controller_unreachable(monkeypatch):
    """Before, only ``login() -> False`` was mapped; an exception escaped as TOOL_FAILED."""
    monkeypatch.setenv('UNIFI_URL', BASE_URL)
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)  # pragma: allowlist secret

    def broken_login(self: Any) -> bool:
        raise RuntimeError('tls handshake failed')

    monkeypatch.setattr(api_client.UnifiApiClient, 'login', broken_login)
    with pytest.raises(ToolError) as excinfo:
        await inspect_port.inspect_switch_port(SWITCH_NAME, 2)

    assert excinfo.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert 'tls handshake failed' in excinfo.value.message


async def test_a_false_login_keeps_the_controller_unreachable_message(monkeypatch):
    monkeypatch.setenv('UNIFI_URL', BASE_URL)
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)  # pragma: allowlist secret
    monkeypatch.setattr(api_client.UnifiApiClient, 'login', lambda self: False)
    with pytest.raises(ToolError) as excinfo:
        await inspect_port.inspect_switch_port(SWITCH_NAME, 2)

    assert excinfo.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert excinfo.value.message.startswith('Could not authenticate to the UniFi controller at ')
