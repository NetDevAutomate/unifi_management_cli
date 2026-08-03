"""Tests for ErrorCodes completeness.

`ErrorCodes.NO_DATA` was referenced by five analysis modules but never defined on the
class. Every one of those references raised `AttributeError` instead of constructing the
intended `ToolError`, so each module crashed on its own error path — for example
`analyze roaming` with no baseline snapshot on disk reported a traceback rather than
"no baseline found".

This test pins every ErrorCodes attribute referenced anywhere in the package.
"""

from __future__ import annotations

import re
from pathlib import Path
from unifi_mapper.core.utils.errors import ErrorCodes


SRC = Path(__file__).resolve().parents[1] / 'src' / 'unifi_mapper'


def test_no_data_is_defined() -> None:
    assert ErrorCodes.NO_DATA == 'NO_DATA'


def test_every_referenced_error_code_exists() -> None:
    """Any `ErrorCodes.X` used in the package must actually be defined."""
    referenced: set[str] = set()
    for path in SRC.rglob('*.py'):
        referenced.update(re.findall(r'ErrorCodes\.([A-Z_][A-Z0-9_]*)', path.read_text()))

    missing = sorted(name for name in referenced if not hasattr(ErrorCodes, name))

    assert missing == [], f'ErrorCodes referenced but not defined: {missing}'


def test_all_codes_are_self_named_strings() -> None:
    """Each code's value should equal its attribute name, for stable wire output."""
    for name in dir(ErrorCodes):
        if name.startswith('_'):
            continue
        value = getattr(ErrorCodes, name)
        if isinstance(value, str):
            assert value == name, f'{name} has mismatched value {value!r}'
