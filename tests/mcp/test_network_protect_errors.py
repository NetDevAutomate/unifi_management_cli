"""Issue 011: a failed Network or Protect read is an error result, never a success value.

Until this change the eleven handlers in ``mcp/tools/network.py`` and ``mcp/tools/protect.py``
caught every exception and returned ``{'error': ...}`` (or a list holding one), so
``execute_tool`` answered ``ok: true`` with ``isError: false``. Now a client failure the
wrapper can name (connection, authentication, an API status) is a ``ToolError`` with that
domain code, and anything else reaches the runner as ``TOOL_FAILED``, like every other tool.

Nothing here reaches a network: the network tests serve ``httpx.MockTransport`` behind the
tools' own guard; the Protect tests replace ``UniFiProtectClient`` with a fake.
"""

import httpx
import pytest
from tests.fixtures_unifi import FAKE_PW, FAKE_TOKEN
from types import SimpleNamespace
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry
from unifi_mapper.mcp.runner import ToolRunner
from unifi_mapper.mcp.tools import network as network_tools
from unifi_mapper.mcp.tools import protect as protect_tools
from unifi_mapper.protect.client import AuthenticationError, ConnectionError


SITE_ID = '550e8400-e29b-41d4-a716-446655440000'
NETWORK_TOOLS = [
    'get_firewall_zones',
    'get_firewall_policies',
    'get_acl_rules',
    'get_dns_policies',
    'get_clients',
    'get_networks',
]
PROTECT_TOOLS = ['get_cameras', 'get_nvr_info', 'get_sensors', 'get_lights', 'get_doorbells']


@pytest.fixture
def network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_NETWORK_HOST', '192.0.2.1')
    monkeypatch.setenv('UNIFI_NETWORK_API_KEY', FAKE_TOKEN)
    monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', SITE_ID)


@pytest.fixture
def protect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('PROTECT_HOST', '192.0.2.10')
    monkeypatch.setenv('PROTECT_USERNAME', 'viewer')
    monkeypatch.setenv('PROTECT_PASSWORD', FAKE_PW)
    monkeypatch.setattr(protect_tools, '_get_config', lambda: SimpleNamespace())


def _serve_status(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    def _handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={'statusCode': status, 'message': 'no'})

    monkeypatch.setattr(
        network_tools, '_inner_transport', lambda _config: httpx.MockTransport(_handle)
    )


def _serve_exception(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _handle(request: httpx.Request) -> httpx.Response:
        raise exc

    monkeypatch.setattr(
        network_tools, '_inner_transport', lambda _config: httpx.MockTransport(_handle)
    )


def _runner() -> ToolRunner:
    return ToolRunner(ToolRegistry(strict=True), settings=ServerSettings())


async def _envelope(tool: str) -> tuple[dict[str, Any], bool]:
    out = await _runner().run(tool, {})
    assert out.structuredContent is not None
    return out.structuredContent, bool(out.isError)


# --- network_api ----------------------------------------------------------------------------


@pytest.mark.usefixtures('network_env')
@pytest.mark.parametrize('tool', NETWORK_TOOLS)
async def test_an_unreachable_network_api_is_controller_unreachable(
    tool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_exception(monkeypatch, httpx.ConnectError('controller unreachable'))

    envelope, is_error = await _envelope(tool)

    assert is_error is True
    assert envelope['ok'] is False
    assert envelope['error_code'] == ErrorCodes.CONTROLLER_UNREACHABLE
    assert 'controller unreachable' in envelope['message']


@pytest.mark.usefixtures('network_env')
@pytest.mark.parametrize(
    ('status', 'code'),
    [
        (401, ErrorCodes.AUTHENTICATION_FAILED),
        (403, ErrorCodes.AUTHENTICATION_FAILED),
        (500, ErrorCodes.API_ERROR),
    ],
)
async def test_a_network_api_status_maps_to_its_domain_code(
    status: int, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_status(monkeypatch, status)

    envelope, is_error = await _envelope('get_networks')

    assert is_error is True
    assert envelope['error_code'] == code


@pytest.mark.usefixtures('network_env')
async def test_an_unnamed_network_failure_is_tool_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not a NetworkClientError: the client does not wrap it, so neither does the tool.
    _serve_exception(monkeypatch, httpx.RemoteProtocolError('peer closed connection'))

    envelope, is_error = await _envelope('get_networks')

    assert is_error is True
    assert envelope['error_code'] == 'TOOL_FAILED'
    assert envelope['message'].startswith('RemoteProtocolError: ')


@pytest.mark.usefixtures('network_env')
async def test_a_network_tool_raises_a_tool_error_with_the_redacted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaky = 'password=' + 'FAKE-TOOL-ERROR-PASSWORD-MUST-NOT-APPEAR'  # pragma: allowlist secret
    _serve_exception(monkeypatch, httpx.ConnectError(leaky))

    with pytest.raises(ToolError) as info:
        await network_tools.get_networks()

    assert info.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert 'FAKE-TOOL-ERROR-PASSWORD' not in info.value.message
    assert 'password=' in info.value.message


# --- protect --------------------------------------------------------------------------------


def _failing_client(exc: Exception) -> type:
    class _Failing:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> None:
            raise exc

        async def __aexit__(self, *_exc: object) -> None:
            return None

    return _Failing


@pytest.mark.usefixtures('protect_env')
@pytest.mark.parametrize('tool', PROTECT_TOOLS)
@pytest.mark.parametrize(
    ('exc', 'code'),
    [
        (
            ConnectionError('Failed to connect to Protect controller'),
            ErrorCodes.CONTROLLER_UNREACHABLE,
        ),
        (AuthenticationError('Failed to authenticate'), ErrorCodes.AUTHENTICATION_FAILED),
        (RuntimeError('boom'), 'TOOL_FAILED'),
    ],
    ids=['connection', 'authentication', 'unnamed'],
)
async def test_a_protect_failure_is_an_error_result(
    tool: str, exc: Exception, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(protect_tools, 'UniFiProtectClient', _failing_client(exc))

    envelope, is_error = await _envelope(tool)

    assert is_error is True
    assert envelope['ok'] is False
    assert envelope['error_code'] == code


@pytest.mark.usefixtures('protect_env')
async def test_a_missing_nvr_is_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoNvr:
        nvr = None

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> '_NoNvr':
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(protect_tools, 'UniFiProtectClient', _NoNvr)

    envelope, is_error = await _envelope('get_nvr_info')

    assert is_error is True
    assert envelope['error_code'] == ErrorCodes.NO_DATA


@pytest.mark.usefixtures('protect_env')
async def test_a_protect_tool_raises_a_tool_error_with_the_redacted_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaky = 'password=' + 'FAKE-TOOL-ERROR-PASSWORD-MUST-NOT-APPEAR'  # pragma: allowlist secret
    monkeypatch.setattr(
        protect_tools, 'UniFiProtectClient', _failing_client(ConnectionError(leaky))
    )

    with pytest.raises(ToolError) as info:
        await protect_tools.get_cameras()

    assert info.value.error_code == ErrorCodes.CONTROLLER_UNREACHABLE
    assert 'FAKE-TOOL-ERROR-PASSWORD' not in info.value.message
