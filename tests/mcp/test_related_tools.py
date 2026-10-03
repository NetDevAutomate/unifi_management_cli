"""Issue 023: every tool an error hint names is a registered, read-only tool.

``execute_tool`` puts a ``ToolError``'s ``related_tools`` in its error envelope verbatim, with
the ``suggestion`` text beside them, so a name that isn't registered sends the model straight
to ``TOOL_NOT_FOUND``. An AST scan of every ``ToolError(...)`` call under src/unifi_mapper
checks both. A ``suggestion`` given as a variable is checked through every string assigned
to that name in the same module.
"""

import ast
import re
from pathlib import Path
from unifi_mapper.mcp.registry import ToolRegistry


SRC = Path(__file__).resolve().parents[2] / 'src' / 'unifi_mapper'
REGISTRY = ToolRegistry(strict=True)
# A tool named in prose the way the hints name one: snake_case with an underscore, then ().
TOOL_IN_TEXT = re.compile(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(\)')
# ToolError(message, error_code, suggestion, related_tools): more would be a new parameter.
MAX_POSITIONAL = 3


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _tool_error_calls() -> list[tuple[str, ast.Module, ast.Call]]:
    """Return ``(file:line, module, call)`` for every ``ToolError(...)`` call in the package."""
    calls = []
    for path in sorted(SRC.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee(node) == 'ToolError':
                calls.append((f'{path.relative_to(SRC).as_posix()}:{node.lineno}', tree, node))
    return calls


CALLS = _tool_error_calls()


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _related_tools(call: ast.Call) -> ast.expr | None:
    """The ``related_tools`` argument, by keyword or as the fourth positional argument."""
    value = _keyword(call, 'related_tools')
    if value is None and len(call.args) > MAX_POSITIONAL:
        value = call.args[MAX_POSITIONAL]
    return value


def _strings(node: ast.AST) -> list[str]:
    return [
        c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)
    ]


def _assigned_strings(tree: ast.Module, name: str) -> list[str]:
    """Every string constant assigned to ``name`` anywhere in ``tree``."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                found += _strings(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name) and node.target.id == name:
                found += _strings(node.value)
    return found


def _suggestion_strings(tree: ast.Module, call: ast.Call) -> list[str]:
    value = _keyword(call, 'suggestion')
    if value is None and len(call.args) > 2:
        value = call.args[2]
    if value is None:
        return []
    texts = _strings(value)
    for node in ast.walk(value):
        if isinstance(node, ast.Name):
            texts += _assigned_strings(tree, node.id)
    return texts


def _hinted() -> list[tuple[str, str]]:
    """Return ``(file:line, tool name)`` for every name in a ``related_tools`` literal."""
    return [
        (where, elt.value)
        for where, _tree, call in CALLS
        if isinstance(value := _related_tools(call), (ast.List, ast.Tuple))
        for elt in value.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    ]


def _unregistered_or_mutating(names: list[tuple[str, str]]) -> list[str]:
    bad = []
    for where, name in names:
        meta = REGISTRY.get_metadata(name)
        if meta is None:
            bad.append(f'{where}: {name} (not registered)')
        elif meta.mutates:
            bad.append(f'{where}: {name} (mutates)')
    return bad


def test_hints_are_literal_lists_of_tool_names() -> None:
    odd = []
    for where, _tree, call in CALLS:
        if len(call.args) > MAX_POSITIONAL + 1 or any(
            isinstance(a, ast.Starred) for a in call.args
        ):
            odd.append(f'{where}: positional *args or more than four arguments')
        if any(k.arg is None for k in call.keywords):
            odd.append(f'{where}: **kwargs')
        value = _related_tools(call)
        if value is None:
            continue
        if not isinstance(value, (ast.List, ast.Tuple)) or not all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
        ):
            odd.append(f'{where}: related_tools is not a literal list of names')
    assert odd == [], '\n'.join(odd)


def test_every_hinted_tool_is_registered_and_read_only() -> None:
    assert _unregistered_or_mutating(_hinted()) == []


def test_suggestions_name_only_registered_tools() -> None:
    named = [
        (where, name)
        for where, tree, call in CALLS
        for text in _suggestion_strings(tree, call)
        for name in TOOL_IN_TEXT.findall(text)
    ]
    assert _unregistered_or_mutating(named) == []


def test_the_scan_sees_the_hints() -> None:
    assert len(CALLS) > 50
    hinted = {name for _where, name in _hinted()}
    assert {'find_device', 'find_mac', 'get_client_history', 'diagnose_vlans'} <= hinted
    # The checker itself reports a missing name, so an empty result above means something.
    assert _unregistered_or_mutating([('x.py:1', 'get_network_topology')]) == [
        'x.py:1: get_network_topology (not registered)'
    ]
    assert TOOL_IN_TEXT.findall('Use find_device() or traceroute() first') == ['find_device']
