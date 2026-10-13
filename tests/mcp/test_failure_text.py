"""Issue 067: one redacted-failure helper and one error-text cap, in a leaf module.

``mcp/tools/network.py`` and ``mcp/tools/protect.py`` each carried a copy of
``_failure(action, error)`` and ``FAILURE_TEXT_LIMIT = 2000``, and ``mcp/runner.py`` a third
copy of the number as ``ERROR_TEXT_LIMIT``. They now share ``mcp/failure_text.py``, which
imports nothing from ``mcp/tools/`` so the runner can import it without loading the tool
wrappers (whose package ``__init__`` imports the Protect client).
"""

import ast
import pytest
from collections.abc import Iterator
from pathlib import Path
from unifi_mapper.mcp import failure_text, runner
from unifi_mapper.mcp.tools import network as network_tools
from unifi_mapper.mcp.tools import protect as protect_tools


SRC = Path(network_tools.__file__).parents[1]  # src/unifi_mapper/mcp


def test_the_runner_and_the_tools_share_one_cap() -> None:
    assert failure_text.ERROR_TEXT_LIMIT == 2000
    assert runner.ERROR_TEXT_LIMIT is failure_text.ERROR_TEXT_LIMIT
    for module in (network_tools, protect_tools):
        assert not hasattr(module, 'FAILURE_TEXT_LIMIT'), module.__name__
        assert not hasattr(module, '_failure'), module.__name__
        assert module.tool_failure is failure_text.tool_failure  # type: ignore[attr-defined]


def test_the_leaf_module_imports_nothing_from_the_tools_package() -> None:
    tree = ast.parse((SRC / 'failure_text.py').read_text())
    imported = [
        node.module or ''
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any('mcp.tools' in name or name.startswith('.tools') for name in imported), imported
    assert not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)), (
        'no relative imports: the module is a leaf'
    )


@pytest.fixture
def logged() -> Iterator[list[str]]:
    from loguru import logger

    lines: list[str] = []
    handler = logger.add(lambda message: lines.append(str(message)), level='ERROR', diagnose=False)
    yield lines
    logger.remove(handler)


def test_tool_failure_logs_and_returns_the_redacted_text(logged: list[str]) -> None:
    leaky = 'login failed: token=' + 'FAKE-067-TOKEN-MUST-NOT-APPEAR'  # pragma: allowlist secret

    text = failure_text.tool_failure('get things', RuntimeError(leaky))

    assert 'FAKE-067-TOKEN' not in text and 'token=' in text
    assert len(logged) == 1
    assert 'Failed to get things: ' in logged[0] and 'FAKE-067-TOKEN' not in logged[0]


def test_tool_failure_caps_at_the_shared_limit(logged: list[str]) -> None:
    text = failure_text.tool_failure('get things', RuntimeError('x' * 3000))
    assert len(text) == failure_text.ERROR_TEXT_LIMIT
