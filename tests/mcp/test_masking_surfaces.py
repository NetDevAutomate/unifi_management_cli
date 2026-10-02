"""T9, surface level: no secret value leaves an MCP surface (results or error text).

Each case asserts on ``structuredContent`` and on ``content[0].text`` (parsed and as a
raw substring search).
"""

import json
import pytest
from mcp.types import CallToolResult
from pathlib import Path
from tests.mcp import fakes
from typing import Any
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.runner import ExecuteResult, ToolRunner


REDACTED = '***redacted***'
SECRETS = (fakes.SECRET_TOKEN, fakes.SECRET_API_KEY, fakes.SECRET_PASSWORD, fakes.AUTHKEY)


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolRunner:
    """A runner over the fakes, with credential values exported as a host would."""
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', fakes.SECRET_TOKEN)
    monkeypatch.setenv('UNIFI_NETWORK_API_KEY', fakes.SECRET_API_KEY)
    monkeypatch.setenv('PROTECT_PASSWORD', fakes.SECRET_PASSWORD)
    monkeypatch.setenv('FOO_TOKEN', 'true')  # unrelated: must not turn 'true' into a mask
    return ToolRunner(fakes.fake_registry(tmp_path), settings=ServerSettings())


def _assert_clean(out: CallToolResult) -> None:
    dumped = json.dumps(out.model_dump(mode='json'))
    for secret in SECRETS:
        assert secret not in dumped
    for block in out.content:
        text = getattr(block, 'text', '')
        for secret in SECRETS:
            assert secret not in text


async def _run(runner: ToolRunner, name: str, params: dict[str, Any] | None = None) -> Any:
    out = await runner.run(name, params, 'execute_tool')
    _assert_clean(out)
    assert json.loads(out.content[0].text) == out.structuredContent
    ExecuteResult.model_validate(out.structuredContent)
    return out.structuredContent


async def test_model_result_masks_x_keys(runner) -> None:
    out = await _run(runner, 'returns_device')
    assert out['result'] == {
        'name': 'USW Flex XG',
        'x_authkey': REDACTED,
        'x_has_ssh_hostkey': True,  # non-string: untouched
    }


async def test_list_result_masks_x_keys_and_env_values(runner) -> None:
    out = await _run(runner, 'returns_device_list')
    assert out['result'] == [{'name': 'sw', 'x_authkey': REDACTED, 'note': f'token is {REDACTED}'}]


async def test_untyped_result_is_masked(runner) -> None:
    out = await _run(runner, 'returns_untyped')
    assert out['result'] == {'x_authkey': REDACTED, 'echo': REDACTED}


async def test_env_values_in_free_text_are_masked_but_true_survives(runner) -> None:
    out = await _run(runner, 'returns_env_secrets')
    assert out['result'] == {
        'summary': f'used {REDACTED} and {REDACTED} and {REDACTED}',
        'flag': 'true',
    }


async def test_exception_text_with_env_secret_is_masked(runner) -> None:
    text = f'connect failed for {fakes.SECRET_API_KEY} / {fakes.SECRET_PASSWORD}'
    out = await _run(runner, 'raise_exc', {'kind': 'RuntimeError', 'text': text})
    assert out['message'] == f'RuntimeError: connect failed for {REDACTED} / {REDACTED}'


async def test_handler_validation_error_with_env_secret_is_masked(runner) -> None:
    out = await _run(runner, 'raise_validation', {'value': fakes.SECRET_TOKEN})
    assert out['error_code'] == 'TOOL_FAILED'


async def test_secret_written_after_the_runner_was_built_is_masked(runner, monkeypatch) -> None:
    late = 'LATE-RESOLVED-TOKEN-987654'  # pragma: allowlist secret
    monkeypatch.setenv('UNIFI_API_TOKEN', late)  # as apply_credentials_to_env would
    out = await runner.run('raise_exc', {'kind': 'RuntimeError', 'text': late}, 'execute_tool')
    assert late not in json.dumps(out.model_dump(mode='json'))
