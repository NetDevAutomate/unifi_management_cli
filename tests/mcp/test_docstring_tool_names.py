"""Issue 028: every ``name()`` a docstring or a string constant mentions is a real tool.

A tool's docstring reaches the model when it is the FastMCP description, and
``path_analysis`` returns its recommendation strings in every result, so a name that is
neither a registered tool nor a function or class defined in the package sends the reader to
``TOOL_NOT_FOUND``. Two AST scans over ``src/unifi_mapper`` catch a new phantom name: one over
every module, class and function docstring, one over every other string constant. Names the
package defines are allowed (a docstring may name a helper); so are a few names from outside
the package that the prose legitimately calls (``stdio_server()`` from the MCP SDK,
``Path.as_uri()``).

The ``related_tools`` lists themselves are covered by ``test_related_tools.py`` (issue 023).
"""

import ast
import re
from pathlib import Path
from unifi_mapper.mcp.registry import ToolRegistry


SRC = Path(__file__).resolve().parents[2] / 'src' / 'unifi_mapper'
REGISTRY = ToolRegistry(strict=True)
# A tool named in prose the way the docstrings name one: snake_case with an underscore, then ().
TOOL_IN_TEXT = re.compile(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\(\)')
# Names from outside the package that the prose calls by their real names.
FOREIGN_NAMES = frozenset({'stdio_server', 'as_uri'})

Mention = tuple[str, str]  # (file:line, name)


def _modules() -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding='utf-8'), filename=str(path)))
        for path in sorted(SRC.rglob('*.py'))
    ]


MODULES = _modules()
DEFINED = {
    node.name
    for _path, tree in MODULES
    for node in ast.walk(tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
}


def _docstring_nodes(tree: ast.Module) -> list[ast.Constant]:
    """The string constant that is each module, class or function docstring."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.append(first.value)
    return found


def _mentions(path: Path, constants: list[ast.Constant]) -> list[Mention]:
    rel = path.relative_to(SRC).as_posix()
    return [
        (f'{rel}:{constant.lineno}', name)
        for constant in constants
        for name in TOOL_IN_TEXT.findall(constant.value)
    ]


def docstring_mentions() -> list[Mention]:
    return [m for path, tree in MODULES for m in _mentions(path, _docstring_nodes(tree))]


def other_string_mentions() -> list[Mention]:
    mentions = []
    for path, tree in MODULES:
        docstrings = {id(node) for node in _docstring_nodes(tree)}
        constants = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        mentions += _mentions(path, constants)
    return mentions


def _phantoms(mentions: list[Mention]) -> list[str]:
    """Mentions that are neither a registered tool nor a name the package (or SDK) defines."""
    return sorted(
        f'{where}: {name}()'
        for where, name in mentions
        if REGISTRY.get_metadata(name) is None
        and name not in DEFINED
        and name not in FOREIGN_NAMES
    )


def test_docstrings_name_only_tools_that_exist() -> None:
    assert _phantoms(docstring_mentions()) == []


def test_other_strings_name_only_tools_that_exist() -> None:
    """Recommendation and hint text reaches the model on every call."""
    assert _phantoms(other_string_mentions()) == []


def test_mentioned_tools_are_not_mutating() -> None:
    mutating = sorted(
        f'{where}: {name}()'
        for where, name in docstring_mentions() + other_string_mentions()
        if (meta := REGISTRY.get_metadata(name)) is not None and meta.mutates
    )
    assert mutating == []


def test_unreachable_controller_hints_do_not_name_controller_tools() -> None:
    """A CONTROLLER_UNREACHABLE hint naming a tool that needs the same controller cannot help."""
    offenders = []
    for path, tree in MODULES:
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'ToolError'):
                continue
            keywords = {k.arg: k.value for k in node.keywords}
            code = keywords.get('error_code')
            related = keywords.get('related_tools')
            if (
                isinstance(code, ast.Attribute)
                and code.attr == 'CONTROLLER_UNREACHABLE'
                and isinstance(related, (ast.List, ast.Tuple))
            ):
                names = [e.value for e in related.elts if isinstance(e, ast.Constant) and e.value]
                controller = [
                    n
                    for n in names
                    if (m := REGISTRY.get_metadata(n)) is not None
                    and m.credentials == 'controller'
                ]
                if controller:
                    offenders.append(
                        f'{path.relative_to(SRC).as_posix()}:{node.lineno}: {controller}'
                    )
    assert offenders == []


def test_the_scans_see_the_prose() -> None:
    docs = docstring_mentions()
    assert len(docs) > 100, len(docs)  # the tool docstrings cross-reference each other a lot
    assert {name for _where, name in docs} >= {'inspect_switch_port', 'find_device'}
    others = other_string_mentions()
    assert any(where.startswith('connectivity/path_analysis.py') for where, _name in others)
    # The checker itself reports a phantom, so an empty result above means something.
    assert _phantoms([('x.py:1', 'no_such_tool_xyz')]) == ['x.py:1: no_such_tool_xyz()']
    assert _phantoms([('x.py:1', 'stdio_server'), ('x.py:2', 'find_device')]) == []
