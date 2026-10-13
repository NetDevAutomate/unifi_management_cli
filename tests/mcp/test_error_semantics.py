"""T4 + T12: ToolRunner error codes, error-text masking and caps, and the text-block contract.

Fakes come from tests/mcp/fakes.py and declare ``credentials: none``; the gate cases
use a monkeypatched ``ensure_controller_credentials`` or fake family env values.
"""

import anyio
import json
import pydantic_core
import pytest
from mcp.types import CallToolResult, TextContent
from pathlib import Path
from tests.mcp import fakes
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes
from unifi_mapper.mcp import runner as runner_module
from unifi_mapper.mcp import server
from unifi_mapper.mcp.config import CredentialsMissingError, ServerSettings
from unifi_mapper.mcp.runner import (
    ERROR_TEXT_LIMIT,
    ERRORS_SET_IS_ERROR,
    TOOL_FAILED_TEXT_LIMIT,
    ExecuteResult,
    ToolRunner,
)


REDACTED = '***redacted***'
# The api_key value the INVALID_PARAMETERS test passes: a dummy that fails int validation.
INVALID_API_KEY = 'not-an-int'  # pragma: allowlist secret


@pytest.fixture
def make_runner(tmp_path: Path):
    """Build a ToolRunner over the fake manifest."""

    def _make(credentials: str = 'none', extra: str = '', **settings: Any) -> ToolRunner:
        registry = fakes.fake_registry(tmp_path, credentials=credentials, extra=extra)
        return ToolRunner(registry, settings=ServerSettings(**settings))

    return _make


@pytest.fixture
def runner(make_runner) -> ToolRunner:
    return make_runner()


async def _envelope(runner: ToolRunner, name: str, params: dict[str, Any] | None = None) -> dict:
    out = await runner.run(name, params)
    assert isinstance(out, CallToolResult)
    assert out.structuredContent is not None
    return out.structuredContent


def _assert_text_contract(out: CallToolResult) -> None:
    assert len(out.content) == 1 and isinstance(out.content[0], TextContent)
    text = out.content[0].text
    assert json.loads(text) == out.structuredContent
    assert text == pydantic_core.to_json(out.structuredContent, fallback=str, indent=2).decode()
    ExecuteResult.model_validate(out.structuredContent)


# ---------------------------------------------------------------------------
# Codes (design §2.13)
# ---------------------------------------------------------------------------

FAILURES = [
    ('nope', None, 'TOOL_NOT_FOUND'),
    ('apply_things', None, 'MUTATION_REFUSED'),
    ('read_port', {'switch': 'S'}, 'INVALID_PARAMETERS'),
    ('read_port', {'switch': 'S', 'port': 1, 'colour': 'red'}, 'INVALID_PARAMETERS'),
    ('raise_domain', {'code': 'DEVICE_NOT_FOUND', 'message': 'gone'}, 'DEVICE_NOT_FOUND'),
    ('raise_exc', {'kind': 'RuntimeError', 'text': 'boom'}, 'TOOL_FAILED'),
    ('raise_exc', {'kind': 'ReadOnlyViolation', 'text': 'PUT refused'}, 'READ_ONLY_VIOLATION'),
]


@pytest.mark.parametrize(('name', 'params', 'code'), FAILURES)
async def test_failure_codes_and_is_error(runner, name, params, code) -> None:
    out = await runner.run(name, params)
    assert out.structuredContent['ok'] is False
    assert out.structuredContent['error_code'] == code
    assert out.isError is ERRORS_SET_IS_ERROR is True
    _assert_text_contract(out)


async def test_today_s_texts_for_not_found_and_mutation(runner) -> None:
    assert await _envelope(runner, 'nope') == {
        'ok': False,
        'error_code': 'TOOL_NOT_FOUND',
        'message': "No tool named 'nope'",
        'suggestion': 'Use search_tools or list_categories to find the right name.',
    }
    assert await _envelope(runner, 'apply_things') == {
        'ok': False,
        'error_code': 'MUTATION_REFUSED',
        'message': 'apply_things changes live controller configuration and is not '
        'executable over MCP.',
        'suggestion': 'Generate a plan with the read-only tools, review it, then apply it '
        'with the unifi-mapper CLI.',
    }


async def test_invalid_parameters_envelope_keys(runner) -> None:
    out = await _envelope(runner, 'read_port', {'switch': 'S'})
    assert list(out) == [
        'ok',
        'error_code',
        'message',
        'suggestion',
        'parameters',
        'input_schema',
    ]
    assert out['message'] == 'invalid parameter(s): port (Field required)'
    assert out['suggestion'] == 'Check get_tool_info for the parameter list.'
    assert out['parameters'] == {}
    assert set(out['input_schema']['properties']) == {'switch', 'port'}


async def test_domain_error_keeps_to_dict_keys(runner) -> None:
    out = await _envelope(
        runner, 'raise_domain', {'code': 'DEVICE_NOT_FOUND', 'message': 'gone', 'suggestion': ''}
    )
    assert out == {
        'ok': False,
        'error_code': 'DEVICE_NOT_FOUND',
        'message': 'gone',
        'suggestion': '',
        'related_tools': [],
    }


@pytest.mark.parametrize('kind', ['KeyError', 'ValueError', 'PermissionError'])
async def test_handler_internal_errors_are_tool_failed(runner, kind) -> None:
    out = await _envelope(runner, 'raise_exc', {'kind': kind, 'text': 'inner'})
    assert out['error_code'] == 'TOOL_FAILED'
    assert out['message'].startswith(f'{kind}: ')


async def test_handler_validation_error_is_tool_failed_without_input(runner) -> None:
    out = await _envelope(runner, 'raise_validation', {'value': fakes.AUTHKEY})
    assert out['error_code'] == 'TOOL_FAILED'
    assert out['message'].startswith('ValidationError: ')
    assert 'port (' in out['message']
    assert fakes.AUTHKEY not in out['message']
    assert 'input_value' not in out['message']


async def test_not_loadable_tool_is_tool_failed(make_runner) -> None:
    extra = '  broken:\n    module: tests.mcp.no_such_module\n    credentials: none\n'
    runner = make_runner(extra=extra)
    out = await _envelope(runner, 'broken')
    assert out['error_code'] == 'TOOL_FAILED'
    assert out['message'] == 'tool not loadable: ModuleNotFoundError'
    assert runner.catalog.find('broken') is None


async def test_none_result_keeps_result_key(runner) -> None:
    out = await runner.run('returns_none', None)
    assert out.structuredContent == {'ok': True, 'result': None}
    assert out.content[0].text == '{\n  "ok": true,\n  "result": null\n}'
    assert out.isError is False
    _assert_text_contract(out)


async def test_success_text_contract(runner) -> None:
    out = await runner.run('read_port', {'switch': 'S', 'port': 1})
    assert out.structuredContent == {'ok': True, 'result': {'a': 1}}
    assert out.isError is False
    _assert_text_contract(out)


# ---------------------------------------------------------------------------
# Deadline and concurrency
# ---------------------------------------------------------------------------


async def test_default_deadline_is_300_seconds_and_a_quick_call_passes(runner) -> None:
    assert runner.settings.tool_timeout == 300.0  # issue 012 (D11)
    out = await _envelope(runner, 'sleeper', {'seconds': 0.1})
    assert out == {'ok': True, 'result': {'slept': 0.1}}


async def test_no_deadline_when_tool_timeout_is_none(make_runner) -> None:
    runner = make_runner(tool_timeout=None)
    out = await _envelope(runner, 'sleeper', {'seconds': 0.1})
    assert out == {'ok': True, 'result': {'slept': 0.1}}


async def test_a_configured_timeout_is_the_timeout_code(make_runner) -> None:
    out = await make_runner(tool_timeout=0.05).run('sleeper', {'seconds': 0.5})
    assert out.structuredContent['error_code'] == 'TIMEOUT'
    assert 'UNIFI_MCP_TOOL_TIMEOUT' in out.structuredContent['message']
    _assert_text_contract(out)


async def test_handler_raised_timeout_error_is_tool_failed(make_runner) -> None:
    out = await make_runner(tool_timeout=30).run(
        'raise_exc', {'kind': 'TimeoutError', 'text': 'socket'}
    )
    assert out.structuredContent['error_code'] == 'TOOL_FAILED'
    assert out.structuredContent['message'] == 'TimeoutError: socket'


async def test_concurrency_cap(make_runner, monkeypatch) -> None:
    monkeypatch.setitem(fakes.IN_FLIGHT, 'max', 0)
    runner = make_runner(max_concurrency=4)
    async with anyio.create_task_group() as tg:
        for _ in range(5):
            tg.start_soon(runner.run, 'sleeper', {'seconds': 0.1})
    assert fakes.IN_FLIGHT['max'] == 4


# ---------------------------------------------------------------------------
# Credential gate
# ---------------------------------------------------------------------------


async def test_controller_gate_maps_to_config_missing(make_runner, monkeypatch) -> None:
    calls: list[float] = []

    async def missing(timeout: float, tried: Any = ()) -> None:
        calls.append(timeout)
        raise CredentialsMissingError('no controller credentials', tried=())

    monkeypatch.setattr(runner_module, 'ensure_controller_credentials', missing)
    runner = make_runner(credentials='controller', credential_timeout=7.0)
    out = await runner.run('read_port', {'switch': 'S', 'port': 1})
    assert out.structuredContent['error_code'] == 'CONFIG_MISSING'
    assert out.isError is True
    assert calls == [7.0]


async def test_controller_gate_passes_when_ready(make_runner, monkeypatch) -> None:
    async def ready(timeout: float, tried: Any = ()) -> None:
        return None

    monkeypatch.setattr(runner_module, 'ensure_controller_credentials', ready)
    out = await make_runner(credentials='controller').run('read_port', {'switch': 'S', 'port': 1})
    assert out.structuredContent == {'ok': True, 'result': {'a': 1}}


async def test_gate_runs_after_validation(make_runner, monkeypatch) -> None:
    async def forbidden(timeout: float, tried: Any = ()) -> None:
        raise AssertionError('gate before validation')

    monkeypatch.setattr(runner_module, 'ensure_controller_credentials', forbidden)
    out = await make_runner(credentials='controller').run('read_port', {'switch': 'S'})
    assert out.structuredContent['error_code'] == 'INVALID_PARAMETERS'


@pytest.mark.parametrize(
    ('family', 'keys'),
    [
        ('network_api', ('UNIFI_NETWORK_HOST', 'UNIFI_NETWORK_API_KEY', 'UNIFI_NETWORK_SITE_ID')),
        ('protect', ('PROTECT_HOST', 'PROTECT_USERNAME', 'PROTECT_PASSWORD')),
    ],
)
async def test_family_gate(make_runner, monkeypatch, family, keys) -> None:
    runner = make_runner(credentials=family)
    out = await _envelope(runner, 'read_port', {'switch': 'S', 'port': 1})
    assert out['error_code'] == 'CONFIG_MISSING'
    assert all(k in out['message'] for k in keys)
    for key in keys:
        monkeypatch.setenv(key, f'value-for-{key.lower()}')
    assert await _envelope(runner, 'read_port', {'switch': 'S', 'port': 1}) == {
        'ok': True,
        'result': {'a': 1},
    }


# ---------------------------------------------------------------------------
# Error-text masking and caps (§2.5 step 11), both surfaces
# ---------------------------------------------------------------------------


def _candidates(n: int) -> str:
    return ', '.join(f"'USW Flex {i}' (aa:bb:cc:00:00:{i:02x}, USWFLEXXG)" for i in range(n))


@pytest.mark.parametrize('surface', ['execute_tool', 'direct'])
async def test_long_authored_domain_text_arrives_unchanged(runner, surface) -> None:
    message = _candidates(40)[:1200]
    suggestion = '\n'.join(['Pass the MAC listed in the message.'] * 60)[:1500]
    assert len(message) == 1200 and len(suggestion) == 1500
    params = {'code': 'DEVICE_NOT_FOUND', 'message': message, 'suggestion': suggestion}
    out = await runner.run('raise_domain', params, surface)
    if surface == 'execute_tool':
        assert out.structuredContent['message'] == message
        assert out.structuredContent['suggestion'] == suggestion
    else:
        assert out.content[0].text == f'[DEVICE_NOT_FOUND] {message} — {suggestion}'


@pytest.mark.parametrize('surface', ['execute_tool', 'direct'])
async def test_domain_message_is_capped_at_2000(runner, surface) -> None:
    params = {'code': 'DEVICE_NOT_FOUND', 'message': 'x' * 2500}
    out = await runner.run('raise_domain', params, surface)
    if surface == 'execute_tool':
        message = out.structuredContent['message']
    else:
        message = out.content[0].text.removeprefix('[DEVICE_NOT_FOUND] ')
    assert len(message) == ERROR_TEXT_LIMIT == 2000
    assert message.endswith('…')


@pytest.mark.parametrize('surface', ['execute_tool', 'direct'])
async def test_tool_failed_message_is_capped_at_500(runner, surface) -> None:
    out = await runner.run('raise_exc', {'kind': 'RuntimeError', 'text': 'y' * 800}, surface)
    if surface == 'execute_tool':
        message = out.structuredContent['message']
    else:
        message = out.content[0].text.removeprefix('[TOOL_FAILED] ').split(' — ')[0]
    assert len(message) == TOOL_FAILED_TEXT_LIMIT == 500
    assert message.startswith('RuntimeError: ')
    assert message.endswith('…')


async def test_secret_assignments_are_redacted_in_domain_text(runner) -> None:
    params = {
        'code': 'API_ERROR',
        'message': 'login failed token=abc12345 header Bearer abc12345',
        'suggestion': 'retry with token=abc12345 or Bearer abc12345',
    }
    out = await _envelope(runner, 'raise_domain', params)
    assert out['message'] == f'login failed token={REDACTED} header Bearer {REDACTED}'
    assert out['suggestion'] == f'retry with token={REDACTED} or Bearer {REDACTED}'


async def test_invalid_parameters_keeps_a_secret_looking_parameter_name(runner) -> None:
    out = await _envelope(runner, 'api_key_param', {'api_key': INVALID_API_KEY})
    assert out['error_code'] == 'INVALID_PARAMETERS'
    assert out['message'].startswith('invalid parameter(s): api_key (')
    assert INVALID_API_KEY not in out['message']


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('Item not found', 'PasswordDeleteError: Item not found'),
        ('token=abc12345', f'PasswordDeleteError: token={REDACTED}'),
    ],
)
async def test_class_name_with_secret_keyword_is_not_redacted(runner, text, expected) -> None:
    out = await _envelope(runner, 'raise_exc', {'kind': 'PasswordDeleteError', 'text': text})
    assert out['message'] == expected


async def test_password_delete_error_800_chars_is_capped_at_500(runner) -> None:
    out = await _envelope(runner, 'raise_exc', {'kind': 'PasswordDeleteError', 'text': 'z' * 800})
    assert len(out['message']) == 500 and out['message'].endswith('…')
    assert out['message'].startswith('PasswordDeleteError: zzz')


async def test_env_secret_values_are_masked_in_error_text(runner, monkeypatch) -> None:
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', fakes.SECRET_TOKEN)
    text = f'request with {fakes.SECRET_TOKEN} failed'
    out = await _envelope(runner, 'raise_exc', {'kind': 'RuntimeError', 'text': text})
    assert out['message'] == f'RuntimeError: request with {REDACTED} failed'


# ---------------------------------------------------------------------------
# Conversion parity (T12)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('returns_aliased', {'port_name': 'Port 5', 'speed': 10000}),
        ('returns_dataclass', {'x': 1, 'y': 2}),
        ('returns_int_keys', {'1': 'a'}),
        ('returns_collections', {'t': [1, 2], 's': [3]}),
    ],
)
async def test_execute_tool_result_is_today_s_to_jsonable(runner, name, expected) -> None:
    out = await runner.run(name, None)
    assert out.structuredContent == {'ok': True, 'result': expected}
    _assert_text_contract(out)


async def test_direct_surface_uses_aliases_and_matches_convert_result(runner) -> None:
    out = await runner.run('returns_aliased', None, 'direct')
    assert out.isError is False
    assert out.structuredContent == {'portName': 'Port 5', 'speed': 10000}
    tool = runner.catalog.get('returns_aliased')
    _, structured = tool.fn_metadata.convert_result(fakes.returns_aliased())
    assert out.structuredContent == structured


def test_to_jsonable_left_server() -> None:
    assert not hasattr(server, '_to_jsonable')


# ---------------------------------------------------------------------------
# Through the server's execute_tool
# ---------------------------------------------------------------------------


async def test_server_execute_tool_returns_call_tool_result(tmp_path, monkeypatch) -> None:
    registry = fakes.fake_registry(tmp_path)
    monkeypatch.setattr(server, 'get_registry', lambda: registry)
    out = await server.execute_tool('raise_domain', {'code': ErrorCodes.NO_DATA, 'message': 'm'})
    assert isinstance(out, CallToolResult) and out.isError is True
    assert out.structuredContent['error_code'] == 'NO_DATA'
    _assert_text_contract(out)
    assert server.get_runner().registry is registry


async def test_get_tool_info_and_full_search_add_schemas(tmp_path, monkeypatch) -> None:
    registry = fakes.fake_registry(tmp_path)
    monkeypatch.setattr(server, 'get_registry', lambda: registry)
    info = await server.get_tool_info('read_port')
    assert info is not None
    assert set(info['input_schema']['properties']) == {'switch', 'port'}
    assert info['output_schema'] is not None
    untyped = await server.get_tool_info('returns_untyped')
    assert untyped is not None and untyped['output_schema'] is None
    mutating = await server.get_tool_info('apply_things')
    assert mutating is not None and mutating['input_schema'] is None
    assert await server.get_tool_info('nope') is None

    full = {r['name']: r for r in await server.search_tools(detail_level='full')}
    assert set(full['read_port']['input_schema']['properties']) == {'switch', 'port'}
    assert full['apply_things']['input_schema'] is None
    summary = await server.search_tools(detail_level='summary')
    assert all(set(r) == {'name', 'description'} for r in summary)
