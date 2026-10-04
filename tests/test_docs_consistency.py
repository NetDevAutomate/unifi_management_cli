"""Keep the committed docs in step with the code they describe (the docs-drift guard).

``test_cli_documentation.py`` checks the README's ``unifi-mapper`` command paths. This module
checks the whole documentation set (``README.md``, ``.env.example``, ``docs/**/*.md`` apart
from ``docs/artefacts/``, and ``scripts/*.sh``), offline and without a controller:

- every documented ``unifi-mapper``, ``unifi-inventory`` and ``unifi-network-toolkit``
  invocation resolves to a real command, every option exists on that command, and no root
  shortcut flag sits before a subcommand that refuses it (exit 2);
- MCP tool names, ``unifi://`` resources and prompts exist, and tool counts, the category
  tables and the MCP guide's tool index equal what ``ToolRegistry()`` holds;
- the ``diagnose all`` check count and list match ``typer_cli.diagnose_all``;
- relative links and ``#anchors`` resolve, and no doc names a machine-local path;
- every ``UNIFI_*``, ``PROTECT_*`` and ``XDG_*`` variable a doc names is read by the code;
- privacy: MAC addresses are locally administered, no private, link-local or CGNAT IPv4
  address appears, and no device name from the local captures (``reports/*.json``, when they
  exist) appears in a doc or under ``src/unifi_mapper/``.

Each detector is a pure function over ``(path, text)`` and has a negative self-test on a
synthetic snippet, so no guard can pass because it matched nothing. Failures name
``path:line`` and a kind, never a matched address or device name.

"Current" docs are everything except ``docs/issues/`` and ``docs/solutions/``, which record
history and proposals on purpose; links, local paths and privacy cover every doc.
"""

from __future__ import annotations

import anyio
import argparse
import ast
import click
import functools
import ipaddress
import json
import posixpath
import pytest
import re
import shlex
import subprocess
import typer
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from unifi_mapper.inventory_cli import inventory_app
from unifi_mapper.mcp import server as mcp_server
from unifi_mapper.mcp.catalog import is_direct
from unifi_mapper.mcp.registry import CREDENTIAL_FAMILIES, ToolRegistry
from unifi_mapper.network_cli import create_main_parser
from unifi_mapper.typer_cli import app


REPO = Path(__file__).resolve().parent.parent
HISTORICAL = ('docs/issues/', 'docs/solutions/')
MCP_GUIDE = 'docs/mcp-server/MCP_SERVER_GUIDE.md'

# Each tree maps a command path ('' is the program itself) to (is a group, {option: takes a
# value}).
Tree = dict[str, tuple[bool, dict[str, bool]]]


# ---------------------------------------------------------------------------
# The documentation set
# ---------------------------------------------------------------------------


@functools.cache
def _tracked() -> frozenset[str]:
    """Return every path in the git index."""
    out = subprocess.run(
        ['git', 'ls-files'], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(out.splitlines())


def _is_doc(path: str) -> bool:
    """Return True for a file in the documentation set."""
    if path in ('README.md', '.env.example'):
        return True
    if path.startswith('docs/') and path.endswith('.md'):
        return not path.startswith('docs/artefacts/')
    return path.startswith('scripts/') and path.endswith('.sh')


@functools.cache
def _docs() -> dict[str, str]:
    """Return ``{path: text}`` for every tracked doc."""
    return {
        p: (REPO / p).read_text(encoding='utf-8')
        for p in sorted(_tracked())
        if _is_doc(p) and (REPO / p).is_file()
    }


def _current_docs() -> dict[str, str]:
    """Return the docs that describe the code as it is (not issues or solutions)."""
    return {p: t for p, t in _docs().items() if not p.startswith(HISTORICAL)}


def _all_problems(docs: Mapping[str, str], detector: Callable[[str, str], list[str]]) -> list[str]:
    """Run one ``(path, text)`` detector over a set of docs."""
    return [problem for path, text in docs.items() for problem in detector(path, text)]


FENCE_OPEN = re.compile(r'(`{3,}|~{3,})([^`]*)$')


def code_blocks(text: str) -> Iterator[tuple[int, str, list[str]]]:
    """Yield ``(first body line, info string, body lines)`` for each fenced code block.

    Args:
        text: Markdown text.

    Yields:
        One tuple per block, line numbers 1-based. A fence that is never closed runs to the
        end of the text, as in CommonMark.
    """
    fence: str | None = None
    info, start, body = '', 0, []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if fence is None:
            opening = FENCE_OPEN.match(stripped)
            if opening:
                fence, info, start, body = opening.group(1), opening.group(2).strip(), n + 1, []
        elif stripped.startswith(fence) and not stripped.strip(fence[0]):
            yield start, info, body
            fence = None
        else:
            body.append(line)
    if fence is not None:
        yield start, info, body


def _code_lines(text: str) -> set[int]:
    """Return the line numbers inside fenced code blocks, fences included."""
    lines: set[int] = set()
    for start, _info, body in code_blocks(text):
        lines.update(range(start - 1, start + len(body) + 1))
    return lines


# ---------------------------------------------------------------------------
# CLI invocations
# ---------------------------------------------------------------------------

ENTRY = re.compile(r'(?<![\w/-])(unifi-mapper|unifi-inventory|unifi-network-toolkit)(?=\s|$|`)')
INLINE = re.compile(r'`((?:unifi-mapper|unifi-inventory|unifi-network-toolkit)[^`]*)`')
COMMAND_START = re.compile(r'(?:^\s*#?\s*|\brun\s+|\$\s|`)$')
STOP = {'|', '||', '&&', ';', '>', '>>', '2>', '2>&1', '&', '#', '<<'}
NUMBER = re.compile(r'-?\d+(\.\d+)?')
WORD = re.compile(r'[a-z][a-z0-9-]*')
# Before any subcommand but discover these exit 2; --apply exits 2 before any subcommand.
ROOT_PREVIEW_FLAGS = ('--dry-run', '--connected-devices', '--verify-updates')


def _click_tree(cmd: click.Command, path: str = '') -> Tree:
    """Return the command tree of a Click (Typer) command without invoking it."""
    options = {
        name: not p.is_flag and not p.count
        for p in cmd.params
        if isinstance(p, click.Option)
        for name in (*p.opts, *p.secondary_opts)
    }
    tree: Tree = {path: (isinstance(cmd, click.Group), options)}
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            tree.update(_click_tree(sub, f'{path} {name}'.strip()))
    return tree


def _argparse_tree(parser: argparse.ArgumentParser, path: str = '') -> Tree:
    """Return the command tree of an argparse parser without parsing anything."""
    options: dict[str, bool] = {}
    subparsers: dict[str, argparse.ArgumentParser] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers.update(action.choices)
            continue
        for name in action.option_strings:
            options[name] = action.nargs != 0
    tree: Tree = {path: (bool(subparsers), options)}
    for name, sub in subparsers.items():
        tree.update(_argparse_tree(sub, f'{path} {name}'.strip()))
    return tree


@functools.cache
def _trees() -> dict[str, Tree]:
    """Return the command tree of each documented program."""
    return {
        'unifi-mapper': _click_tree(typer.main.get_command(app)),
        'unifi-inventory': _click_tree(typer.main.get_command(inventory_app)),
        'unifi-network-toolkit': _argparse_tree(create_main_parser()),
    }


def invocations(path: str, text: str) -> list[tuple[int, str, str]]:
    """Return ``(line, program, rest of the line)`` for each documented invocation.

    In markdown, every non-Mermaid code block line and every inline ``program ...`` span
    counts (Mermaid labels are prose). Elsewhere (``.env.example``, shell scripts) a program
    counts only where it starts a command: the first word of a line or comment, after
    ``run`` or a ``$`` prompt, or inside backticks.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        The invocations in file order.
    """
    found: list[tuple[int, str, str]] = []
    if not path.endswith('.md'):
        for n, line in enumerate(text.splitlines(), 1):
            for m in ENTRY.finditer(line):
                if COMMAND_START.search(line[: m.start()]):
                    found.append((n, m.group(1), line[m.end() :]))
        return found
    for start, info, body in code_blocks(text):
        if info.startswith('mermaid'):
            continue
        buffer, first = '', start
        for offset, line in enumerate(body):
            if not buffer:
                first = start + offset
            if line.rstrip().endswith('\\'):
                buffer += line.rstrip()[:-1] + ' '
                continue
            joined, buffer = buffer + line, ''
            for m in ENTRY.finditer(joined):
                found.append((first, m.group(1), joined[m.end() :]))
    in_code = _code_lines(text)
    for n, line in enumerate(text.splitlines(), 1):
        if n in in_code:
            continue
        for m in INLINE.finditer(line):
            program = m.group(1).split()[0]
            found.append((n, program, m.group(1)[len(program) :]))
    return sorted(found)


def _tokens(rest: str) -> list[str]:
    """Split the arguments of one command line, stopping where prose or a pipe starts."""
    rest = rest.split(' # ')[0]
    try:
        raw = shlex.split(rest, posix=True)
    except ValueError:
        raw = [t.strip('\'"') for t in rest.split()]
    out: list[str] = []
    for token in raw:
        if token in STOP or token.startswith(('#', '2>', '>', '|')):
            break
        trail = re.search(r'[`,.;:)\]]+$', token)
        if trail and token.startswith('-'):
            out.append(token[: trail.start()])
            break
        if '<' in token and '>' in token and token.startswith('-'):
            token = token.split('<', 1)[0]
        out.append(token)
    return out


def _resolve(program: str, tree: Tree, tokens: list[str]) -> list[str]:
    """Walk one command line through a tree; return what doesn't exist or is refused."""
    problems: list[str] = []
    path, expect_value, root_flags = '', False, []
    for token in tokens:
        if expect_value:
            expect_value = False
            continue
        is_group, options = tree[path]
        if token.startswith('-') and len(token) > 1 and not NUMBER.fullmatch(token):
            name = token.split('=', 1)[0]
            if name in ('--help', '-h', '--…'):
                continue
            if name not in options:
                problems.append(f'unknown option {name} for "{program} {path}".')
                continue
            if not path:
                root_flags.append(name)
            expect_value = options[name] and '=' not in token
            continue
        if not is_group:
            continue
        candidate = f'{path} {token}'.strip()
        if candidate in tree:
            if not path and program == 'unifi-mapper':
                refused = [
                    f
                    for f in root_flags
                    if f == '--apply' or (f in ROOT_PREVIEW_FLAGS and token != 'discover')
                ]
                if refused:
                    problems.append(f'root {", ".join(refused)} before {token} exits 2')
            path = candidate
            continue
        if WORD.fullmatch(token):
            problems.append(f'unknown command "{program} {candidate}"')
            break
    if program == 'unifi-mapper' and {'--apply', '--dry-run'} <= set(root_flags):
        problems.append('root --apply with --dry-run exits 2')
    return problems


def cli_problems(path: str, text: str, trees: Mapping[str, Tree]) -> list[str]:
    """Return ``path:line: problem`` for each documented invocation that doesn't resolve.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        trees: The command tree of each program.

    Returns:
        The problems in file order.
    """
    return [
        f'{path}:{line}: {problem}'
        for line, program, rest in invocations(path, text)
        for problem in _resolve(program, trees[program], _tokens(rest))
    ]


def test_cli_detector_reports_unknown_flags_commands_and_refused_root_flags() -> None:
    """The detector must report every kind of bad invocation it exists to catch."""
    text = (
        '```bash\n'
        'unifi-mapper discover --no-such-flag\n'
        'unifi-mapper --dry-run ports list\n'
        'unifi-mapper --apply discover\n'
        'unifi-mapper no-such-command\n'
        'unifi-mapper discover --format svg \\\n'
        '  --output reports/x.md\n'
        '```\n'
        'Inline: `unifi-network-toolkit find mac 02:00:00:00:00:01 --bogus`.\n'
    )
    problems = cli_problems('demo.md', text, _trees())
    assert problems == [
        'demo.md:2: unknown option --no-such-flag for "unifi-mapper discover".',
        'demo.md:3: root --dry-run before ports exits 2',
        'demo.md:4: root --apply before discover exits 2',
        'demo.md:5: unknown command "unifi-mapper no-such-command"',
        'demo.md:9: unknown option --bogus for "unifi-network-toolkit find mac".',
    ]


def test_documented_invocations_resolve() -> None:
    """Every invocation in the current docs names a real command with real options."""
    docs = _current_docs()
    count = sum(len(invocations(p, t)) for p, t in docs.items())
    assert count > 150, f'the extractor found only {count} invocations: has the format moved?'
    trees = _trees()
    assert _all_problems(docs, lambda p, t: cli_problems(p, t, trees)) == []


# ---------------------------------------------------------------------------
# MCP names, resources, counts and the tool index
# ---------------------------------------------------------------------------

TOOLISH = re.compile(
    r'^(get|find|analy[sz]e|audit|check|detect|diagnose|discover|validate|monitor|optimi[sz]e|'
    r'snapshot|apply|restore|inspect|trace|compare|search|list|execute|path|firewall|'
    r'connectivity|network|performance|security|client|traceroute|summari[sz]e|simulate|'
    r'calculate|generate|identify|plan|preflight|track|scan|diff|export|run)_[a-z0-9_]+$'
)
URI = re.compile(r'unifi://[a-z/_-]+')
COUNT = re.compile(r'\b(\d+)\s+(?:[a-z-]+\s+){0,3}?(tools?|meta-tools|categories|schemas)\b', re.I)
CATEGORY_ROW = re.compile(r'^\|\s*`?([a-z]+)`?\s*\|\s*(\d+)\s*\|')
INDEX_HEADING = re.compile(r'^### ([a-z]+) \((\d+)\)$')
INDEX_ROW = re.compile(
    r'^\| `(?P<name>[a-z0-9_]+)` \| `(?P<family>[a-z_]+)` \| (?P<marks>[^|]*?) ?\| '
    r'(?P<description>.*) \|$'
)
SURFACE_SUM = re.compile(r'(\d+) tools \((\d+) \+ (\d+)\)')
SPLIT_SENTENCE = re.compile(
    r'Of\s+the\s+(\d+):\s+(\d+)\s+are\s+mutating\b.*?\band\s+(\d+)\s+are\s+pipeline\s+tools,'
    r'\s+leaving\s+(\d+)\s+on\s+the\s+direct\s+surface',
    re.S,
)
CHECK_OUTPUT = re.compile(
    r'`tool_count`\s+(\d+);\s+`listed_tools`\s+(\d+)\s+on\s+`discovery`,'
    r'\s+(\d+)\s+on\s+`direct`'
)
NUMBER_WORDS = {
    w: i
    for i, w in enumerate(
        'zero one two three four five six seven eight nine ten eleven twelve'.split()
    )
}
WORD_CATEGORIES = re.compile(r'\b(' + '|'.join(NUMBER_WORDS) + r') categories\b', re.I)


@functools.cache
def _registry() -> ToolRegistry:
    """Return one registry for the module (it only reads the YAML manifests)."""
    return ToolRegistry()


@functools.cache
def _facts() -> dict[str, object]:
    """Return the MCP numbers the docs may state, computed from the registry."""
    registry = _registry()
    metas = {
        n: registry.get_metadata(n) for names in registry.get_categories().values() for n in names
    }
    categories = {c: len(v) for c, v in registry.get_categories().items()}
    direct = sum(1 for m in metas.values() if is_direct(m))
    meta_tools = len(mcp_server.META_TOOLS)
    facts: dict[str, object] = {
        'total': len(metas),
        'categories': categories,
        'mutating': sum(1 for m in metas.values() if m.mutates),
        'pipeline': sum(1 for m in metas.values() if m.pipeline),
        'direct_catalog': direct,
        'meta_tools': meta_tools,
        'direct_listed': direct + meta_tools,
    }
    facts['valid'] = {
        facts['total'],
        direct,
        direct + meta_tools,
        meta_tools,
        facts['mutating'],
        facts['pipeline'],
        len(categories),
        *categories.values(),
        sum(1 for m in metas.values() if not m.open_world),
        sum(1 for m in metas.values() if not m.idempotent),
    }
    return facts


@functools.cache
def _known_names() -> frozenset[str]:
    """Return the backticked names a doc may use: tools, meta-tools, prompts, src names."""
    registry = _registry()
    names = {n for v in registry.get_categories().values() for n in v}
    names |= set(mcp_server.META_TOOLS) | set(CREDENTIAL_FAMILIES)
    names |= {p.name for p in anyio.run(mcp_server.create_server('discovery').list_prompts)}
    for path in (REPO / 'src').rglob('*.py'):
        source = path.read_text(encoding='utf-8')
        names |= set(re.findall(r'\b(?:def|class)\s+([A-Za-z_]\w*)', source))
        names |= set(re.findall(r'^\s*([a-z_][a-z0-9_]*)\s*[:=]', source, re.M))
        names.add(path.stem)
    for manifest in (REPO / 'src/unifi_mapper/mcp/manifests').glob('*.yaml'):
        names |= set(re.findall(r'^\s{6,}([a-z_][a-z0-9_]*):', manifest.read_text(), re.M))
    return frozenset(names)


@functools.cache
def _resources() -> frozenset[str]:
    """Return the URIs of the resources the MCP server registers (built in memory)."""
    server = mcp_server.create_server('discovery')
    return frozenset(str(r.uri) for r in anyio.run(server.list_resources))


def mcp_name_problems(
    path: str, text: str, known: frozenset[str], resources: frozenset[str]
) -> list[str]:
    """Return ``path:line: problem`` for unknown tool-like names and ``unifi://`` URIs.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        known: Every name a doc may use (tools, meta-tools, prompts, names in ``src/``).
        resources: The resource URIs the server registers.

    Returns:
        The problems in file order.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for token in re.findall(r'`([a-z][a-z0-9_]+)(?:\(\))?`', line):
            if TOOLISH.match(token) and token not in known:
                problems.append(f'{path}:{n}: unknown tool-like name {token}')
        for uri in URI.findall(line):
            if uri.rstrip('/') not in resources:
                problems.append(f'{path}:{n}: unknown resource {uri}')
    return problems


def _line_of(text: str, offset: int) -> int:
    """Return the 1-based line number of a character offset."""
    return text.count('\n', 0, offset) + 1


def mcp_count_problems(path: str, text: str, facts: Mapping[str, object]) -> list[str]:
    """Return ``path:line: problem`` for each MCP count that the registry doesn't support.

    Checks tool and category counts in MCP lines, category table rows, the tool index's
    headings, the direct-surface sums and the "Of the N" sentence.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        facts: The numbers computed by ``_facts()``.

    Returns:
        The problems in file order.
    """
    valid = facts['valid']
    categories = facts['categories']
    assert isinstance(valid, set) and isinstance(categories, dict)
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        if 'mcp' in path.lower() or 'MCP' in line or 'tool' in line.lower():
            for m in COUNT.finditer(line):
                number = int(m.group(1))
                if 2 < number <= 500 and number not in valid:
                    problems.append(f'{path}:{n}: {number} {m.group(2)} matches no registry count')
            for m in WORD_CATEGORIES.finditer(line):
                if NUMBER_WORDS[m.group(1).lower()] != len(categories):
                    problems.append(f'{path}:{n}: "{m.group(0)}", not {len(categories)}')
        for m in (CATEGORY_ROW.match(line), INDEX_HEADING.match(line)):
            if m and m.group(1) in categories and int(m.group(2)) != categories[m.group(1)]:
                problems.append(f'{path}:{n}: {m.group(1)} has {categories[m.group(1)]} tools')
        for m in SURFACE_SUM.finditer(line):
            numbers = tuple(int(g) for g in m.groups())
            expected = (facts['direct_listed'], facts['meta_tools'], facts['direct_catalog'])
            if numbers != expected:
                problems.append(f'{path}:{n}: surface sum {m.group(0)} should be {expected}')
    expected = (facts['total'], facts['mutating'], facts['pipeline'], facts['direct_catalog'])
    for m in SPLIT_SENTENCE.finditer(text):
        if tuple(int(g) for g in m.groups()) != expected:
            problems.append(f'{path}:{_line_of(text, m.start())}: split should be {expected}')
    expected = (facts['total'], facts['meta_tools'], facts['direct_listed'])
    for m in CHECK_OUTPUT.finditer(text):
        if tuple(int(g) for g in m.groups()) != expected:
            problems.append(f'{path}:{_line_of(text, m.start())}: --check should be {expected}')
    return problems


def _marks(meta: object) -> str:
    """Return the tool index's marks column for one tool."""
    marks = [
        label
        for flag, label in (
            ('mutates', 'mutating'),
            ('pipeline', 'pipeline'),
            ('writes_local', 'writes a local file'),
        )
        if getattr(meta, flag, False)
    ]
    return ', '.join(marks)


@functools.cache
def _index_rows() -> dict[str, dict[str, tuple[str, str, str]]]:
    """Return ``{category: {tool: (family, marks, description)}}`` from the registry."""
    registry = _registry()
    rows: dict[str, dict[str, tuple[str, str, str]]] = {}
    for category, names in registry.get_categories().items():
        rows[category] = {}
        for name in names:
            meta = registry.get_metadata(name)
            description = ' '.join((meta.description or '').split()).replace('|', '\\|')
            rows[category][name] = (meta.credentials, _marks(meta), description)
    return rows


def tool_index_problems(
    path: str, text: str, expected: Mapping[str, Mapping[str, tuple[str, str, str]]]
) -> list[str]:
    """Return the differences between a doc's "Tool Index" section and the registry.

    Args:
        path: The repo-relative file name.
        text: The doc's text.
        expected: ``{category: {tool: (family, marks, description)}}`` from the registry.

    Returns:
        One entry per missing, extra or different category, tool or column.
    """
    lines = text.splitlines()
    try:
        start = lines.index('## Tool Index')
    except ValueError:
        return [f'{path}: no "## Tool Index" section']
    found: dict[str, dict[str, tuple[str, str, str]]] = {}
    category = ''
    for n, line in enumerate(lines[start + 1 :], start + 2):
        if line.startswith('## '):
            break
        heading = INDEX_HEADING.match(line)
        if heading:
            category = heading.group(1)
            found[category] = {}
            continue
        row = INDEX_ROW.match(line)
        if row and category:
            columns = (row['family'], row['marks'].strip(), row['description'])
            found[category][row['name']] = columns
    problems = []
    for missing in sorted(set(expected) - set(found)):
        problems.append(f'{path}: category {missing} is missing from the tool index')
    for extra in sorted(set(found) - set(expected)):
        problems.append(f'{path}: category {extra} is in the tool index but not registered')
    for category in sorted(set(found) & set(expected)):
        have, want = found[category], expected[category]
        for name in sorted(set(want) - set(have)):
            problems.append(f'{path}: {category}: {name} is missing from the tool index')
        for name in sorted(set(have) - set(want)):
            problems.append(f'{path}: {category}: {name} is not a registered {category} tool')
        for name in sorted(set(have) & set(want)):
            for label, got, wanted in zip(
                ('family', 'marks', 'description'), have[name], want[name], strict=True
            ):
                if got != wanted:
                    problems.append(
                        f'{path}: {category}: {name} {label} differs from the manifest'
                    )
    return problems


def test_mcp_detectors_report_unknown_names_resources_and_counts() -> None:
    """The MCP detectors must report a made-up tool, resource, count and category row."""
    known = _known_names()
    text = '`get_no_such_tool` reads `unifi://no/such/thing`.\n'
    assert mcp_name_problems('demo.md', text, known, _resources()) == [
        'demo.md:1: unknown tool-like name get_no_such_tool',
        'demo.md:1: unknown resource unifi://no/such/thing',
    ]
    facts = _facts()
    total, listed, meta = facts['total'], facts['direct_listed'], facts['meta_tools']
    assert isinstance(total, int) and isinstance(listed, int) and isinstance(meta, int)
    text = (
        f'The MCP server registers {total + 100} tools in two categories.\n'
        '| analysis | 1 |\n'
        f'| `direct` | {listed} tools ({meta} + {listed - meta - 1}) |\n'
        f'Of the {total}: 0 are mutating (none) and 0 are pipeline tools, leaving 0 on the\n'
        'direct surface.\n'
    )
    problems = mcp_count_problems('docs/mcp-demo.md', text, facts)
    assert [p.split(': ', 1)[0] for p in problems] == [
        'docs/mcp-demo.md:1',
        'docs/mcp-demo.md:1',
        'docs/mcp-demo.md:2',
        'docs/mcp-demo.md:3',
        'docs/mcp-demo.md:4',
    ]


def test_tool_index_detector_reports_a_missing_tool_and_a_wrong_column() -> None:
    """The index check must notice a missing tool and a family that differs."""
    expected = {'demo': {'find_a': ('controller', '', 'Finds A'), 'find_b': ('none', '', 'B')}}
    text = (
        '## Tool Index\n\n### demo (2)\n\n| Tool | Family | Marks | Description |\n'
        '| --- | --- | --- | --- |\n| `find_a` | `protect` |  | Finds A |\n'
    )
    assert tool_index_problems('guide.md', text, expected) == [
        'guide.md: demo: find_b is missing from the tool index',
        'guide.md: demo: find_a family differs from the manifest',
    ]


@pytest.mark.usefixtures('block_network')
def test_documented_mcp_names_resources_and_counts_match_the_server() -> None:
    """Names, URIs and counts in the current docs come from the registry and the server."""
    facts = _facts()
    listed = anyio.run(mcp_server.create_server('direct').list_tools)
    assert len(listed) == facts['direct_listed'] == facts['direct_catalog'] + facts['meta_tools']
    docs = _current_docs()
    claims = sum(len(COUNT.findall(t)) for t in docs.values())
    assert claims > 20, f'found only {claims} count claims: has the wording moved?'
    named = {m for t in docs.values() for m in re.findall(r'`([a-z][a-z0-9_]+)(?:\(\))?`', t)}
    registered = {n for names in _registry().get_categories().values() for n in names}
    assert sorted(registered - named) == [], 'registered tools that no current doc names'
    known, resources = _known_names(), _resources()
    assert _all_problems(docs, lambda p, t: mcp_name_problems(p, t, known, resources)) == []
    assert _all_problems(docs, lambda p, t: mcp_count_problems(p, t, facts)) == []


def test_mcp_guide_tool_index_matches_the_registry() -> None:
    """The guide's tool index lists every registered tool with its manifest columns."""
    assert tool_index_problems(MCP_GUIDE, _docs()[MCP_GUIDE], _index_rows()) == []


# ---------------------------------------------------------------------------
# diagnose all
# ---------------------------------------------------------------------------

CHECK_COUNT = re.compile(r'\b(\d+)(?:-| | independent | diagnostic )checks?\b')
CHECK_COUNT_LINE = re.compile(r'diagnose[ _]all|loop \d+ checks|\d+ diagnostic checks')
CHECK_LIST = re.compile(r'`diagnose all`[^\n]*?\bruns (\d+) [^:\n]*?: (?P<items>[^.]+)\.')


@functools.cache
def _diagnose_all_checks() -> tuple[str, ...]:
    """Return the check names ``typer_cli.diagnose_all`` runs, read from its source."""
    source = (REPO / 'src/unifi_mapper/typer_cli.py').read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == 'diagnose_all':
            for statement in ast.walk(node):
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id == 'checks'
                    and isinstance(statement.value, ast.List)
                ):
                    return tuple(
                        ast.literal_eval(item.elts[0])
                        for item in statement.value.elts
                        if isinstance(item, ast.Tuple)
                    )
    raise AssertionError('diagnose_all no longer builds a checks list: has it moved?')


def _check_key(name: str) -> str:
    """Normalise a check name for comparison: case, spelling and plurals."""
    words = name.lower().replace('isation', 'ization').split()
    return ' '.join(w[:-1] if w.endswith('s') else w for w in words)


def diagnose_all_problems(path: str, text: str, checks: tuple[str, ...]) -> list[str]:
    """Return ``path:line: problem`` for a wrong ``diagnose all`` count or check list.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        checks: The check names the command runs.

    Returns:
        The problems in file order.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        if CHECK_COUNT_LINE.search(line):
            for m in CHECK_COUNT.finditer(line):
                if int(m.group(1)) != len(checks):
                    problems.append(f'{path}:{n}: {m.group(0)}, not {len(checks)}')
    for m in CHECK_LIST.finditer(text):
        items = re.split(r',\s+(?:and\s+)?|\s+and\s+', ' '.join(m['items'].split()))
        if {_check_key(i) for i in items} != {_check_key(c) for c in checks}:
            problems.append(f'{path}:{_line_of(text, m.start())}: the check list differs')
    return problems


def test_diagnose_all_detector_reports_a_wrong_count_and_list() -> None:
    """A stale count, in either wording, and a short list are all reported."""
    text = (
        '`diagnose all` runs 11 checks: link quality and capacity planning.\n'
        '# Run all 12 diagnostic checks with a summary\n'
    )
    checks = ('Link Quality', 'Capacity Planning', 'DHCP Pool')
    assert diagnose_all_problems('demo.md', text, checks) == [
        'demo.md:1: 11 checks, not 3',
        'demo.md:2: 12 diagnostic checks, not 3',
        'demo.md:1: the check list differs',
    ]
    good = '`diagnose all` runs 3 checks: link quality, capacity planning and DHCP pools.\n'
    assert diagnose_all_problems('demo.md', good, checks) == []


def test_documented_diagnose_all_checks_match_the_code() -> None:
    """Every ``diagnose all`` count and check list in the current docs matches the code."""
    checks = _diagnose_all_checks()
    assert len(checks) >= 10, f'found only {len(checks)} checks in diagnose_all'
    docs = _current_docs()
    lists = sum(len(CHECK_LIST.findall(t)) for t in docs.values())
    assert lists >= 2, f'found {lists} documented check lists: has the wording moved?'
    assert _all_problems(docs, lambda p, t: diagnose_all_problems(p, t, checks)) == []


# ---------------------------------------------------------------------------
# Links, anchors and machine-local paths
# ---------------------------------------------------------------------------

LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)|!\[[^\]]*\]\(([^)\s]+)\)')
SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*:')
LOCAL_PATH = re.compile(
    r'(?<!~/)\.kiro/|\.agents/|\.yolo-sisyphus|/Users/(?!you\b)[A-Za-z0-9_.-]+|'
    r'personal_docs/|personal_scripts/|~/Desktop'
)


def slug(heading: str) -> str:
    """Return the GitHub anchor of a markdown heading."""
    heading = re.sub(r'`([^`]*)`', r'\1', heading)
    heading = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', heading)
    heading = re.sub(r'<[^>]+>', '', heading).strip().lower()
    return re.sub(r'[^\w\- ]', '', heading).replace(' ', '-')


def anchors(text: str) -> set[str]:
    """Return every anchor a markdown text defines (headings outside code, and HTML ids)."""
    in_code = _code_lines(text)
    seen: dict[str, int] = {}
    found: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        if n in in_code:
            continue
        heading = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', line)
        if heading:
            base = slug(heading.group(2))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f'{base}-{count}')
            seen[base] = count + 1
        found.update(re.findall(r'<a\s+(?:name|id)="([^"]+)"', line))
    return found


def link_problems(
    path: str, text: str, tracked: frozenset[str], anchors_of: Callable[[str], set[str]]
) -> list[str]:
    """Return ``path:line: problem`` for each relative link or anchor that doesn't resolve.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        tracked: Every tracked path.
        anchors_of: Returns the anchors a tracked markdown file defines.

    Returns:
        The problems in file order. Links inside code blocks are not links.
    """
    if not path.endswith('.md'):
        return []
    directories = {str(Path(p).parent) for p in tracked} | {
        str(parent) for p in tracked for parent in Path(p).parents
    }
    in_code = _code_lines(text)
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        if n in in_code:
            continue
        for m in LINK.finditer(line):
            target = m.group(1) or m.group(2)
            if SCHEME.match(target):
                continue
            file_part, _, fragment = target.partition('#')
            destination = path
            if file_part:
                destination = posixpath.normpath(
                    posixpath.join(posixpath.dirname(path), file_part)
                )
                if destination.startswith('..'):
                    problems.append(f'{path}:{n}: link {target} leaves the repository')
                    continue
                if destination not in tracked and destination.rstrip('/') not in directories:
                    problems.append(f'{path}:{n}: link {target} is not a tracked path')
                    continue
            if fragment and destination.endswith('.md'):
                if fragment not in anchors_of(destination):
                    problems.append(f'{path}:{n}: anchor {target} is not in {destination}')
    return problems


def local_path_problems(path: str, text: str) -> list[str]:
    """Return ``path:line: problem`` for each machine-local path a doc names.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        One entry per git-ignored scratch path, personal directory or home path.
    """
    return [
        f'{path}:{n}: machine-local path'
        for n, line in enumerate(text.splitlines(), 1)
        for _ in LOCAL_PATH.finditer(line)
    ]


@functools.cache
def _anchors_of(path: str) -> set[str]:
    """Return the anchors of a tracked markdown file."""
    return anchors((REPO / path).read_text(encoding='utf-8'))


def test_link_and_local_path_detectors_report_what_they_guard() -> None:
    """A missing file, a missing anchor and machine-local paths are all reported."""
    text = (
        '[a](missing.md) [b](../README.md#no-such-heading) [c](#here) [d](https://x.test)\n'
        '# Here\n'
        'See .kiro/docs-hygiene/plan.md and ~/.kiro/settings/mcp.json.\n'
    )
    tracked = frozenset({'README.md', 'docs/demo.md'})
    defined = {'README.md': {'install'}, 'docs/demo.md': anchors(text)}
    problems = link_problems('docs/demo.md', text, tracked, defined.__getitem__)
    assert problems == [
        'docs/demo.md:1: link missing.md is not a tracked path',
        'docs/demo.md:1: anchor ../README.md#no-such-heading is not in README.md',
    ]
    assert local_path_problems('docs/demo.md', text) == ['docs/demo.md:3: machine-local path']


def test_relative_links_and_anchors_resolve() -> None:
    """Every relative link in every doc reaches a tracked file and an existing anchor."""
    docs, tracked = _docs(), _tracked()
    links = sum(len(LINK.findall(t)) for t in docs.values())
    assert links > 100, f'found only {links} links: has the link syntax moved?'
    problems = _all_problems(docs, lambda p, t: link_problems(p, t, tracked, _anchors_of))
    assert problems == []


def test_no_doc_names_a_machine_local_path() -> None:
    """No committed doc points at git-ignored scratch, a personal directory or a home path."""
    assert _all_problems(_docs(), local_path_problems) == []


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

ENV_VAR = re.compile(r'\b((?:UNIFI|PROTECT|XDG)_[A-Z0-9_]*[A-Z0-9])\b')
# Read through a prefix: from_env(prefix=...) + get_env('KEY').
PREFIXED_READERS = (
    ('src/unifi_mapper/network/config.py', 'UNIFI_NETWORK_'),
    ('src/unifi_mapper/protect/config.py', 'PROTECT_'),
)
# Python constants that only look like environment variables.
NOT_ENV_VARS = frozenset({'UNIFI_AES_KEY', 'UNIFI_AES_IV', 'UNIFI_LTE'})


@functools.cache
def _read_env_vars() -> frozenset[str]:
    """Return every environment variable the code under ``src/`` and ``scripts/`` reads."""
    names: set[str] = set()
    for path in _tracked():
        if path.startswith(('src/', 'scripts/')) and path.endswith(('.py', '.sh', '.yaml')):
            names |= set(ENV_VAR.findall((REPO / path).read_text(encoding='utf-8')))
    for path, prefix in PREFIXED_READERS:
        source = (REPO / path).read_text(encoding='utf-8')
        names |= {prefix + key for key in re.findall(r"get_env\('([A-Z_]+)'", source)}
    return frozenset(names - NOT_ENV_VARS)


def env_problems(path: str, text: str, read: frozenset[str]) -> list[str]:
    """Return ``path:line: problem`` for each variable a doc names that no code reads.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        read: Every environment variable the code reads.

    Returns:
        The problems in file order.
    """
    return [
        f'{path}:{n}: {name} is read by no code'
        for n, line in enumerate(text.splitlines(), 1)
        for name in ENV_VAR.findall(line)
        if name not in read
    ]


def test_env_detector_reports_an_unread_variable() -> None:
    """A made-up variable is reported; a real one and a wildcard are not."""
    text = 'Set UNIFI_NO_SUCH_SETTING=1, UNIFI_URL and any UNIFI_MCP_* setting.\n'
    assert env_problems('README.md', text, _read_env_vars()) == [
        'README.md:1: UNIFI_NO_SUCH_SETTING is read by no code'
    ]


def test_documented_env_vars_are_read_by_the_code() -> None:
    """Every ``UNIFI_*``, ``PROTECT_*`` and ``XDG_*`` name in the current docs is read."""
    docs, read = _current_docs(), _read_env_vars()
    mentions = sum(len(ENV_VAR.findall(t)) for t in docs.values())
    assert mentions > 100, f'found only {mentions} variable names: has the pattern moved?'
    assert _all_problems(docs, lambda p, t: env_problems(p, t, read)) == []


# ---------------------------------------------------------------------------
# Privacy: MAC and IPv4 addresses, device names
# ---------------------------------------------------------------------------

MAC = re.compile(r'(?<![0-9A-Fa-f:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])')
IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)')
# RFC 1918, link-local and CGNAT. ipaddress' is_private is also true for the documentation
# ranges and loopback, which docs may use, so the networks are listed explicitly.
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(n)
    for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10')
)
# Public UniFi product model names and factory port labels that also occur as names in the
# local captures; the same allowlist as the local privacy check. A string joins only after a
# check that it is a product or factory string, never a site name (a room, owner or place).
GENERIC_NAMES = frozenset({'Dream Machine Pro Max', 'US 8 60W', 'U6 LR', 'PoE Out + Data'})
GENERIC_NAME = re.compile(
    r'^(Port \d+|default|LAN|WAN\d?|Default|Internal|Guest|IoT|Management)$', re.I
)


def mac_problems(path: str, text: str) -> list[str]:
    """Return ``path:line: problem`` for each universally administered MAC address.

    A documented MAC must be locally administered (bit 0x02 of the first octet set, as in
    ``02:00:00:00:00:01``) or all zeros, so it can't be a real device's address.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        The problems in file order, without the address.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in MAC.finditer(line):
            digits = re.sub('[:-]', '', m.group(0))
            if not int(digits[:2], 16) & 0x02 and set(digits) != {'0'}:
                problems.append(f'{path}:{n}: universally administered MAC address')
    return problems


def ipv4_problems(path: str, text: str) -> list[str]:
    """Return ``path:line: problem`` for each private, link-local or CGNAT IPv4 address.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        The problems in file order, without the address. Documentation ranges, loopback
        and version strings pass.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in IPV4.finditer(line):
            try:
                address = ipaddress.IPv4Address(m.group(0))
            except ValueError:
                continue
            if any(address in network for network in PRIVATE_NETWORKS):
                problems.append(f'{path}:{n}: private, link-local or CGNAT IPv4 address')
    return problems


def local_device_names(reports: Path) -> frozenset[str]:
    """Return the identifying names in the local ``reports/*.json`` captures.

    Takes every ``name``, ``hostname`` and ``device_name`` string longer than 4 and shorter
    than 60 characters, minus generic words, bare numbers and ``GENERIC_NAMES``.

    Args:
        reports: The directory holding the captures.

    Returns:
        The names; empty when there are no captures (a fresh clone).
    """
    names: set[str] = set()

    def walk(node: object) -> None:
        """Collect the name-like strings anywhere in one parsed capture."""
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ('name', 'hostname', 'device_name') and isinstance(value, str):
                    if 4 < len(value) < 60:
                        names.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for capture in sorted(reports.glob('*.json')):
        try:
            walk(json.loads(capture.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    return frozenset(
        n
        for n in names
        if not GENERIC_NAME.match(n) and not re.fullmatch(r'[\d.]+', n) and n not in GENERIC_NAMES
    )


def device_name_problems(path: str, text: str, pattern: re.Pattern[str] | None) -> list[str]:
    """Return ``path:line: problem`` for each line holding a device name from the captures.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        pattern: One whole-word pattern for every name, from ``_names_pattern``.

    Returns:
        The problems in file order, without the name.
    """
    if pattern is None:
        return []
    return [
        f'{path}:{n}: device name from the local captures'
        for n, line in enumerate(text.splitlines(), 1)
        if pattern.search(line)
    ]


def _names_pattern(names: frozenset[str]) -> re.Pattern[str] | None:
    """Return one whole-word pattern matching any of ``names``, or None for no names."""
    if not names:
        return None
    alternatives = '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf'(?<![\w-])(?:{alternatives})(?![\w-])')


def test_privacy_detectors_report_real_looking_identifiers(tmp_path: Path) -> None:
    """A universal MAC, a private address and a captured device name are all reported."""
    private = '.'.join(['10', '20', '30', '40'])  # built at run time: no literal in this file
    text = (
        'MAC 00:00:5E:00:53:01 and 02:00:00:00:00:01, zero 00:00:00:00:00:00.\n'
        f'Hosts {private} and 192.0.2.10, loopback 127.0.0.1, firmware 9.80.3.1.\n'
        'Plug it into the Synthetic Lounge Switch, port 4.\n'
    )
    assert mac_problems('demo.md', text) == ['demo.md:1: universally administered MAC address']
    assert ipv4_problems('demo.md', text) == [
        'demo.md:2: private, link-local or CGNAT IPv4 address'
    ]
    captures = {'data': [{'name': 'Synthetic Lounge Switch'}, {'name': 'U6 LR'}]}
    captures['data'] += [{'hostname': 'Port 3'}, {'device_name': '12.3.4'}]
    (tmp_path / 'capture.json').write_text(json.dumps(captures), encoding='utf-8')
    names = local_device_names(tmp_path)
    assert names == {'Synthetic Lounge Switch'}
    assert device_name_problems('demo.md', text, _names_pattern(names)) == [
        'demo.md:3: device name from the local captures'
    ]


def test_documented_identifiers_are_documentation_values() -> None:
    """Every MAC in the docs is locally administered and no IPv4 address is private."""
    docs = _docs()
    assert sum(len(MAC.findall(t)) for t in docs.values()) > 0, 'no MAC found: has MAC moved?'
    assert _all_problems(docs, mac_problems) == []
    assert _all_problems(docs, ipv4_problems) == []


def test_no_device_name_from_the_local_captures() -> None:
    """No doc and no source file names a device from the local captures."""
    names = local_device_names(REPO / 'reports')
    if not names:
        pytest.skip('no local captures in reports/ (a fresh clone): nothing to compare')
    pattern = _names_pattern(names)
    sources = {
        p: (REPO / p).read_text(encoding='utf-8')
        for p in sorted(_tracked())
        if p.startswith('src/unifi_mapper/') and p.endswith(('.py', '.yaml'))
    }
    corpus = {**_docs(), **sources}
    assert _all_problems(corpus, lambda p, t: device_name_problems(p, t, pattern)) == []
