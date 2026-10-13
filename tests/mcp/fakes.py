"""Importable fake tool handlers with real signatures, and a manifest that registers them.

Every entry declares ``credentials: none`` (the gate is tested separately), so no test
using these fakes ever reaches the credential chain.
"""

import anyio
import time
from dataclasses import dataclass
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from unifi_mapper.core.utils.errors import ToolError
from unifi_mapper.core.utils.readonly import ReadOnlyViolation
from unifi_mapper.mcp.registry import ToolRegistry


SECRET_TOKEN = 'FAKE-CONSOLE-TOKEN-0123456789'  # pragma: allowlist secret
SECRET_API_KEY = 'FAKE-NETWORK-KEY-abcdefgh'  # pragma: allowlist secret
SECRET_PASSWORD = 'FAKE-PROTECT-PASSWORD-xyz'  # pragma: allowlist secret
AUTHKEY = 'FAKE-AUTHKEY-deadbeef'  # pragma: allowlist secret
PRINTED = 'handler output that must not reach the protocol stream'


class PasswordDeleteError(Exception):
    """Shaped like keyring's PasswordDeleteError: a secret keyword in the class name."""


class Aliased(BaseModel):
    """A model whose field has an alias (execute_tool dumps field names, direct aliases)."""

    model_config = ConfigDict(populate_by_name=True)

    port_name: str = Field(alias='portName')
    speed: int = 10000


class Device(BaseModel):
    """A model that carries a secret-looking key."""

    name: str
    x_authkey: str
    x_has_ssh_hostkey: bool = True


@dataclass
class Point:
    """A dataclass result."""

    x: int
    y: int


# --- results ------------------------------------------------------------------------


def read_port(switch: str, port: int) -> dict[str, Any]:
    """Return a fixed result (T12's success envelope)."""
    return {'a': 1}


async def returns_none() -> None:
    """Return None."""
    return None


def returns_aliased() -> Aliased:
    """Return a model with an aliased field."""
    return Aliased(port_name='Port 5')


def returns_dataclass() -> Point:
    """Return a dataclass."""
    return Point(x=1, y=2)


def returns_int_keys() -> Any:
    """Return a dict with a non-string key."""
    return {1: 'a'}


def returns_collections() -> Any:
    """Return a tuple and a set."""
    return {'t': (1, 2), 's': {3}}


def returns_device() -> Device:
    """Return a model carrying x_authkey."""
    return Device(name='USW Flex XG', x_authkey=AUTHKEY)


def returns_device_list() -> list[dict[str, Any]]:
    """Return a list of dicts (a wrap_output tool) carrying x_authkey."""
    return [{'name': 'sw', 'x_authkey': AUTHKEY, 'note': f'token is {SECRET_TOKEN}'}]


def returns_untyped():  # noqa: ANN201 - deliberately unannotated: no outputSchema
    """Return a dict with no return annotation (listed without an outputSchema)."""
    return {'x_authkey': AUTHKEY, 'echo': SECRET_API_KEY}


def returns_env_secrets() -> dict[str, Any]:
    """Return env-style secret values embedded in free text."""
    return {
        'summary': f'used {SECRET_TOKEN} and {SECRET_API_KEY} and {SECRET_PASSWORD}',
        'flag': 'true',
    }


def prints() -> dict[str, str]:
    """Print, as some legacy helpers do."""
    print(PRINTED)
    return {'status': 'ok'}


# --- typed parameters ---------------------------------------------------------------


def int_param(n: int) -> dict[str, Any]:
    """Echo an int parameter."""
    return {'n': n, 'type': type(n).__name__}


def str_param(s: str) -> dict[str, Any]:
    """Echo a str parameter."""
    return {'s': s}


def literal_param(verbosity: Literal['guided', 'expert'] = 'guided') -> dict[str, Any]:
    """Echo a Literal parameter."""
    return {'verbosity': verbosity}


def list_param(items: list[str]) -> dict[str, Any]:
    """Echo a list[str] parameter."""
    return {'items': items}


def api_key_param(api_key: int) -> dict[str, Any]:
    """A parameter whose name looks secret."""
    return {'ok': True}


def no_params() -> dict[str, Any]:
    """Take no parameters."""
    return {'ok': True}


# --- failures -----------------------------------------------------------------------

EXCEPTIONS: dict[str, type[BaseException]] = {
    'KeyError': KeyError,
    'ValueError': ValueError,
    'PermissionError': PermissionError,
    'RuntimeError': RuntimeError,
    'TimeoutError': TimeoutError,
    'PasswordDeleteError': PasswordDeleteError,
    'ReadOnlyViolation': ReadOnlyViolation,
}


def raise_exc(kind: str, text: str = '') -> dict[str, Any]:
    """Raise ``EXCEPTIONS[kind](text)``."""
    raise EXCEPTIONS[kind](text)


def raise_domain(code: str, message: str, suggestion: str = '') -> dict[str, Any]:
    """Raise a domain ToolError."""
    raise ToolError(message=message, error_code=code, suggestion=suggestion)


class _Strict(BaseModel):
    port: int


def raise_validation(value: str) -> dict[str, Any]:
    """Raise a pydantic ValidationError whose input is ``value``."""
    _Strict.model_validate({'port': value})
    return {}


IN_FLIGHT = {'now': 0, 'max': 0}


async def sleeper(seconds: float = 0.2) -> dict[str, Any]:
    """Sleep, tracking how many calls are in flight at once."""
    IN_FLIGHT['now'] += 1
    IN_FLIGHT['max'] = max(IN_FLIGHT['max'], IN_FLIGHT['now'])
    try:
        await anyio.sleep(seconds)
    finally:
        IN_FLIGHT['now'] -= 1
    return {'slept': seconds}


def blocks(seconds: float = 0.2) -> dict[str, Any]:
    """Block the event loop with a sync sleep (the shape of a sync catalog handler)."""
    time.sleep(seconds)
    return {'blocked': seconds}


# --- manifest -----------------------------------------------------------------------

_HANDLERS = [
    'read_port',
    'returns_none',
    'returns_aliased',
    'returns_dataclass',
    'returns_int_keys',
    'returns_collections',
    'returns_device',
    'returns_device_list',
    'returns_untyped',
    'returns_env_secrets',
    'prints',
    'int_param',
    'str_param',
    'literal_param',
    'list_param',
    'api_key_param',
    'no_params',
    'raise_exc',
    'raise_domain',
    'raise_validation',
    'sleeper',
    'blocks',
]


def manifest_text(credentials: str = 'none', extra: str = '') -> str:
    """Return a manifest registering every fake handler under its own name.

    Args:
        credentials: The ``credentials`` family every fake declares.
        extra: More entries (YAML, indented by two spaces) to append.

    Returns:
        The YAML text.
    """
    lines = ['category: fake', 'tools:']
    for name in _HANDLERS:
        lines += [
            f'  {name}:',
            '    module: tests.mcp.fakes',
            f'    handler: {name}',
            f'    description: fake {name}',
            f'    credentials: {credentials}',
        ]
    lines += [
        '  apply_things:',
        '    module: tests.mcp.fakes',
        '    handler: no_params',
        '    description: Writes live config',
        '    mutates: true',
        '    credentials: none',
    ]
    return '\n'.join(lines) + '\n' + extra


def fake_registry(tmp_path: Path, credentials: str = 'none', extra: str = '') -> ToolRegistry:
    """Write :func:`manifest_text` under ``tmp_path`` and return a strict registry over it."""
    manifests = tmp_path / 'fake-manifests'
    manifests.mkdir(exist_ok=True)
    (manifests / 'fake.yaml').write_text(manifest_text(credentials, extra))
    return ToolRegistry(manifests, strict=True)
