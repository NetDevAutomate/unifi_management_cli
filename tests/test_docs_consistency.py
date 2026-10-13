"""Keep the committed docs in step with the code they describe (the docs-drift guard).

``test_cli_documentation.py`` checks the README's ``unifi-mapper`` command paths. This module
checks the whole documentation set (``README.md``, ``.env.example``, ``docs/**/*.md`` apart
from ``docs/artefacts/``, and ``scripts/*.sh``), offline and without a controller:

- every documented ``unifi-mapper``, ``unifi-inventory``, ``unifi-network-toolkit`` and
  ``unifi-mcp`` invocation resolves to a real command, every option exists on that command,
  and no root shortcut flag sits before a subcommand that refuses it (exit 2);
- MCP tool names, ``unifi://`` resources and prompts exist. The category table rows, the
  tool index, the surface sums, the "Of the N" split sentence and the ``--check`` output equal
  what ``ToolRegistry()`` holds; any other tool count in an MCP line is the registry's total
  unless its sentence names a category, a surface or a kind of tool (``McpFacts.qualified``),
  whose own count it may then be;
- the ``diagnose all`` check count and list match ``typer_cli.diagnose_all``;
- every backticked CamelCase name, and every class a Mermaid ``classDiagram`` declares or
  relates, is a class or type alias under ``src/`` or one of ``KNOWN_EXTERNAL_TYPES``;
- relative links and ``#anchors`` resolve, and no doc names a machine-local path;
- no Mermaid sequence-diagram line holds a ``;``, which ends the statement there, so GitHub
  can't render the diagram;
- every ``UNIFI_*``, ``PROTECT_*`` and ``XDG_*`` variable a doc names is read by the code;
- privacy: MAC addresses in docs are locally administered, no private, link-local or CGNAT
  IPv4 address appears in a doc, and no device or client name from the local captures
  (``reports/*.json``, when they exist) appears in a doc, under ``src/unifi_mapper/``, or in a
  tracked file under ``tests/`` or ``scripts/``. Tests and scripts also hold no MAC address,
  serial number, 24-hex or UUID device or site ID, address in a captured /24, IPv6 address
  in a captured /48, public IPv4 address from an address field (the WAN address) or
  link-local IPv6 address from those captures (decision 11: the repository is public). The
  docs' MAC rule can't apply there, since a fixture may keep a public vendor OUI; a name
  equal to a model string the code classifies (``analysis/model_capabilities``) is generic.

Each detector is a pure function over ``(path, text)`` and has a negative self-test on a
synthetic snippet, so no guard can pass because it matched nothing. Failures name
``path:line`` and a kind, never a matched address, identifier or device name.

"Current" docs are everything except ``docs/issues/``, which records
history and proposals on purpose; links, local paths, Mermaid and privacy cover every doc.
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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tests.markdown_blocks import code_blocks
from unifi_mapper.analysis import model_capabilities
from unifi_mapper.inventory_cli import inventory_app
from unifi_mapper.mcp import server as mcp_server
from unifi_mapper.mcp.catalog import is_direct
from unifi_mapper.mcp.registry import CREDENTIAL_FAMILIES, ToolMetadata, ToolRegistry
from unifi_mapper.network_cli import create_main_parser
from unifi_mapper.typer_cli import app


REPO = Path(__file__).resolve().parent.parent
HISTORICAL = ('docs/issues/',)
MCP_GUIDE = 'docs/mcp-server/MCP_SERVER_GUIDE.md'

# Every test here is offline by design; block_network fails any test that reaches a network.
pytestmark = pytest.mark.usefixtures('block_network')

# Each tree maps a command path ('' is the program itself) to (is a group, {option: takes a
# value}).
Tree = dict[str, tuple[bool, dict[str, bool]]]


# ---------------------------------------------------------------------------
# The documentation set
# ---------------------------------------------------------------------------


@functools.cache
def _tracked() -> frozenset[str]:
    """Return every path in the git index; skip outside a git checkout (an sdist, say)."""
    if not (REPO / '.git').exists():
        pytest.skip('not a git checkout: the docs guard reads the git index')
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


def _code_lines(text: str) -> set[int]:
    """Return the line numbers inside fenced code blocks, fences included."""
    lines: set[int] = set()
    for start, _info, body in code_blocks(text):
        lines.update(range(start - 1, start + len(body) + 1))
    return lines


# ---------------------------------------------------------------------------
# CLI invocations
# ---------------------------------------------------------------------------

ENTRY = re.compile(
    r'(?<![\w/-])(unifi-mapper|unifi-inventory|unifi-network-toolkit|unifi-mcp)(?=\s|$|`)'
)
# The lookahead keeps `unifi-mcp-launch.sh` (a script, not the program) out.
INLINE = re.compile(
    r'`((?:unifi-mapper|unifi-inventory|unifi-network-toolkit|unifi-mcp)(?=[\s`])[^`]*)`'
)
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
        'unifi-mcp': _argparse_tree(mcp_server._arg_parser()),
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
                where = f'{program} {path}'.strip()
                problems.append(f'unknown option {name} for "{where}".')
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
        'uvx --from . unifi-mcp --surface direct --no-such-flag\n'
        '```\n'
        'Inline: `unifi-network-toolkit find mac 02:00:00:00:00:01 --bogus`.\n'
        'Inline: `unifi-mcp --check --bogus`, but not `scripts/unifi-mcp-launch.sh --x`'
        ' or `unifi-mcp-launch.sh --x`.\n'
    )
    problems = cli_problems('demo.md', text, _trees())
    assert problems == [
        'demo.md:2: unknown option --no-such-flag for "unifi-mapper discover".',
        'demo.md:3: root --dry-run before ports exits 2',
        'demo.md:4: root --apply before discover exits 2',
        'demo.md:5: unknown command "unifi-mapper no-such-command"',
        'demo.md:8: unknown option --no-such-flag for "unifi-mcp".',
        'demo.md:10: unknown option --bogus for "unifi-network-toolkit find mac".',
        'demo.md:11: unknown option --bogus for "unifi-mcp".',
    ]


def test_documented_invocations_resolve() -> None:
    """Every invocation in the current docs names a real command with real options."""
    docs = _current_docs()
    found = [program for p, t in docs.items() for _line, program, _rest in invocations(p, t)]
    assert len(found) > 150, f'the extractor found only {len(found)} invocations: format moved?'
    trees = _trees()
    assert {program: found.count(program) > 5 for program in trees} == dict.fromkeys(trees, True)
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
# ``96 tools``, ``57 registered MCP tools``, ``82 non-mutating, non-pipeline catalog tools``;
# not the ``3`` of a ``13.3`` section number.
COUNT = re.compile(
    r'(?<![\d.])\b(\d+)\s+(?:[a-z-]+,?\s+){0,3}?(tools?|meta-tools|categories|schemas)\b', re.I
)
# ``Total registered tools: **87**``: a total written after the noun.
TOTAL_AFTER_NOUN = re.compile(r'\btools:\s*\**(\d+)\b', re.I)
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


@dataclass(frozen=True)
class McpFacts:
    """The MCP numbers the docs may state, computed from the registry by ``_facts()``.

    A free-text tool count must equal ``total`` unless its sentence names a category, a
    surface or a kind of tool; ``qualified`` maps each such word (a regex, matched
    case-insensitively on a word boundary) to the counts it allows as well. The exact checks
    use the named fields.
    """

    total: int
    categories: dict[str, int]
    mutating: int
    pipeline: int
    direct_catalog: int
    meta_tools: int
    direct_listed: int
    qualified: dict[str, frozenset[int]]


@functools.cache
def _facts() -> McpFacts:
    """Return the MCP numbers the docs may state, computed from the registry."""
    registry = _registry()
    metas = {
        n: registry.get_metadata(n) for names in registry.get_categories().values() for n in names
    }
    categories = {c: len(v) for c, v in registry.get_categories().items()}
    direct = sum(1 for m in metas.values() if is_direct(m))
    meta_tools = len(mcp_server.META_TOOLS)
    mutating = sum(1 for m in metas.values() if m.mutates)
    pipeline = sum(1 for m in metas.values() if m.pipeline)
    qualified = {category: frozenset({count}) for category, count in categories.items()}
    qualified['discovery'] = qualified.get('discovery', frozenset()) | {meta_tools}  # a surface
    qualified.update(
        {
            'direct': frozenset({direct, direct + meta_tools}),
            'listed': frozenset({direct + meta_tools}),
            'read-only': frozenset({direct}),  # the catalog a client may call
            'meta[- ]tools?': frozenset({meta_tools}),
            'mutating': frozenset({mutating}),
            'pipeline': frozenset({pipeline}),
            'schemas?': frozenset({direct + meta_tools}),
        }
    )
    return McpFacts(
        total=len(metas),
        categories=categories,
        mutating=mutating,
        pipeline=pipeline,
        direct_catalog=direct,
        meta_tools=meta_tools,
        direct_listed=direct + meta_tools,
        qualified=qualified,
    )


def src_known_names(bindings: SrcBindings) -> frozenset[str]:
    """Return the names a Python source binds that a doc may use as a tool-like name.

    Functions, classes, module-level names, class attributes (model and result fields) and
    parameters: the bindings a doc can legitimately describe. A local variable or a keyword
    argument is not one, so a stale tool name that happens to match one is still reported.
    """
    return (
        bindings.defs
        | bindings.classes
        | bindings.module_names
        | bindings.class_attributes
        | bindings.parameters
    )


@functools.cache
def _known_names() -> frozenset[str]:
    """Return the backticked names a doc may use: tools, meta-tools, prompts, src names."""
    registry = _registry()
    names = {n for v in registry.get_categories().values() for n in v}
    names |= set(mcp_server.META_TOOLS) | set(CREDENTIAL_FAMILIES)
    names |= {p.name for p in anyio.run(mcp_server.create_server('discovery').list_prompts)}
    names |= src_known_names(_src_bindings())
    for path in sorted(p for p in _tracked() if p.startswith('src/') and p.endswith('.py')):
        names.add(Path(path).stem)
    for path in sorted(_tracked()):
        if path.startswith('src/unifi_mapper/mcp/manifests/') and path.endswith('.yaml'):
            text = (REPO / path).read_text(encoding='utf-8')
            names |= set(re.findall(r'^\s{6,}([a-z_][a-z0-9_]*):', text, re.M))
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


SENTENCE_END = re.compile(r'[.!?;](?=\s|$)')
BLOCK_START = re.compile(r'^\s*(?:#|[-*] |\d+\. |\||```|~~~|$)')


def _continues(line: str) -> bool:
    """True when a prose line runs on into the next one (no sentence end, not a block)."""
    stripped = line.strip()
    return bool(stripped) and not BLOCK_START.match(line) and stripped[-1] not in '.!?:'


def _sentence(lines: list[str], index: int, start: int, code: set[int]) -> str:
    """Return the sentence holding offset ``start`` of ``lines[index]``.

    Wrapped prose is joined with the lines before and after it; a table row or a line in a
    fenced code block (a Mermaid label, a tree) stands alone, since neither wraps.

    Args:
        lines: The file's lines.
        index: The 0-based index of the line holding the match.
        start: The match's offset in that line.
        code: The 1-based line numbers inside fenced code blocks.

    Returns:
        The sentence, whitespace collapsed to single spaces.
    """
    line = lines[index]
    if index + 1 in code or line.lstrip().startswith('|'):
        return line
    first = index
    while first > 0 and _continues(lines[first - 1]) and not BLOCK_START.match(lines[first]):
        first -= 1
    last = index
    while (
        last + 1 < len(lines)
        and _continues(lines[last])
        and not BLOCK_START.match(lines[last + 1])
    ):
        last += 1
    text = ' '.join(ln.strip() for ln in lines[first : last + 1])
    offset = sum(len(ln.strip()) + 1 for ln in lines[first:index])
    offset += start - (len(line) - len(line.lstrip()))
    begin = max((m.end() for m in SENTENCE_END.finditer(text, 0, offset)), default=0)
    end = SENTENCE_END.search(text, offset)
    return text[begin : end.end() if end else len(text)]


def _allowed_counts(sentence: str, noun: str, facts: McpFacts) -> frozenset[int]:
    """Return the counts a ``<number> <noun>`` claim in ``sentence`` may equal.

    ``categories``, ``meta-tools`` and ``schemas`` name their own count. A tool count is the
    total, or the count of each category, surface or kind the sentence names.
    """
    noun = noun.lower()
    if noun == 'categories':
        return frozenset({len(facts.categories)})
    if noun == 'meta-tools':
        return frozenset({facts.meta_tools})
    if noun == 'schemas':
        return facts.qualified['schemas?']
    allowed = {facts.total}
    for word, counts in facts.qualified.items():
        if re.search(rf'\b{word}\b', sentence, re.I):
            allowed |= counts
    return frozenset(allowed)


def mcp_count_problems(path: str, text: str, facts: McpFacts) -> list[str]:
    """Return ``path:line: problem`` for each MCP count that the registry doesn't support.

    A free-text tool count in an MCP line must be the registry's total, unless its sentence
    names a category, a surface (``direct``, ``discovery``, ``listed``) or a kind
    (``meta-tools``, ``mutating``, ``pipeline``, ``read-only``), whose own counts it may then
    equal. Category table rows, the tool index's headings, the direct-surface sums and the
    "Of the N" sentence are checked exactly.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        facts: The numbers computed by ``_facts()``.

    Returns:
        The problems in file order.
    """
    categories = facts.categories
    lines, code = text.splitlines(), _code_lines(text)
    problems = []
    for index, line in enumerate(lines):
        n = index + 1
        if 'mcp' in path.lower() or 'MCP' in line or 'tool' in line.lower():
            for m in COUNT.finditer(line):
                number = int(m.group(1))
                if not 2 < number <= 500:
                    continue
                sentence = _sentence(lines, index, m.start(), code)
                allowed = _allowed_counts(sentence, m.group(2), facts)
                if number not in allowed:
                    expected = ', '.join(str(c) for c in sorted(allowed))
                    problems.append(f'{path}:{n}: {number} {m.group(2)}: expected {expected}')
            for m in TOTAL_AFTER_NOUN.finditer(line):
                if int(m.group(1)) != facts.total:
                    problems.append(f'{path}:{n}: "{m.group(0)}", not the total {facts.total}')
            for m in WORD_CATEGORIES.finditer(line):
                if NUMBER_WORDS[m.group(1).lower()] != len(categories):
                    problems.append(f'{path}:{n}: "{m.group(0)}", not {len(categories)}')
        for m in (CATEGORY_ROW.match(line), INDEX_HEADING.match(line)):
            if m and m.group(1) in categories and int(m.group(2)) != categories[m.group(1)]:
                problems.append(f'{path}:{n}: {m.group(1)} has {categories[m.group(1)]} tools')
        for m in SURFACE_SUM.finditer(line):
            numbers = tuple(int(g) for g in m.groups())
            expected = (facts.direct_listed, facts.meta_tools, facts.direct_catalog)
            if numbers != expected:
                problems.append(f'{path}:{n}: surface sum {m.group(0)} should be {expected}')
    expected = (facts.total, facts.mutating, facts.pipeline, facts.direct_catalog)
    for m in SPLIT_SENTENCE.finditer(text):
        if tuple(int(g) for g in m.groups()) != expected:
            problems.append(f'{path}:{_line_of(text, m.start())}: split should be {expected}')
    expected = (facts.total, facts.meta_tools, facts.direct_listed)
    for m in CHECK_OUTPUT.finditer(text):
        if tuple(int(g) for g in m.groups()) != expected:
            problems.append(f'{path}:{_line_of(text, m.start())}: --check should be {expected}')
    return problems


def _marks(meta: ToolMetadata) -> str:
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
    total, listed, meta = facts.total, facts.direct_listed, facts.meta_tools
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


def test_mcp_count_detector_requires_the_total_unless_the_sentence_qualifies_it() -> None:
    """A bare tool count must be the total; a category, surface or kind names its own count."""
    facts = _facts()
    analysis, direct = facts.categories['analysis'], facts.direct_catalog
    meta, listed, total = facts.meta_tools, facts.direct_listed, facts.total
    text = (
        f'The server registers {analysis} tools.\n'  # a stale total that equals a category
        f'The analysis category holds {analysis} tools; `analysis.yaml` lists {analysis} tools.\n'
        f'| `direct` | the meta-tools plus the catalog | {listed} tools, {direct} + {meta} |\n'
        f'With `--surface direct` a client sees the\n'
        f'{direct} tools, {listed} in all.\n'
        f'The {meta} discovery meta-tools; {direct} read-only tools; {facts.pipeline} pipeline tools;\n'
        f'the {facts.mutating} mutating tools; the {listed} schemas; {total} tools.\n'
        f'Analysis Tools ({analysis} tools) and Diagnostics ({facts.pipeline} tools).\n'
        '### 13.3 MCP Tool Discovery\n'
        f'Total registered tools: **{facts.pipeline}** (the total, written after the noun).\n'
        f'Also the {total + 1} non-mutating, non-pipeline catalog tools (the comma hid it).\n'
    )
    problems = mcp_count_problems('docs/mcp-demo.md', text, facts)
    assert [p.split(': ', 1)[0] for p in problems] == [
        'docs/mcp-demo.md:1',
        'docs/mcp-demo.md:8',  # Diagnostics names a category; the pipeline count is not its count
        'docs/mcp-demo.md:10',
        'docs/mcp-demo.md:11',
    ]


def test_mcp_name_detector_reports_a_name_bound_only_as_a_local_variable() -> None:
    """A tool-like name that src/ binds only as a local or keyword argument is unknown."""
    source = (
        'check_module_level = 1\n'
        'check_annotated: int = 2\n'
        '\n'
        '\n'
        'class Result:\n'
        '    check_field: int = 0\n'
        '\n'
        '    def run(self, check_parameter):\n'
        '        check_local_only = call(\n'
        '            check_keyword=2,\n'
        '        )\n'
        '        return check_local_only\n'
    )
    known = src_known_names(src_bindings(source))
    text = (
        '`check_local_only`, `check_keyword`, `check_module_level`, `check_annotated`,\n'
        '`check_field`, `check_parameter`, `run`, `Result`.\n'
    )
    assert mcp_name_problems('demo.md', text, known, frozenset()) == [
        'demo.md:1: unknown tool-like name check_local_only',
        'demo.md:1: unknown tool-like name check_keyword',
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


def test_documented_mcp_names_resources_and_counts_match_the_server() -> None:
    """Names, URIs and counts in the current docs come from the registry and the server."""
    facts = _facts()
    listed = anyio.run(mcp_server.create_server('direct').list_tools)
    assert len(listed) == facts.direct_listed == facts.direct_catalog + facts.meta_tools
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
# Class names
# ---------------------------------------------------------------------------

# A backticked CamelCase name, alone, called or with a member: `UniFiClient`, `ToolRegistry()`,
# `UniFiClient.get_devices()`. Two or more capitals and a lower-case letter, so a product name
# (`UNIFI`) or a one-word type (`Path`) is not a class reference.
CLASS_REF = re.compile(r'`([A-Z][A-Za-z0-9]*)(?:\(\)|\.[A-Za-z_][\w.]*(?:\(\))?)?`')
# In a Mermaid classDiagram: a ``class Name`` statement, and the two ends of a relation
# (``A <|-- B``, ``A "1" *-- "*" B : label`` and the other arrows).
MERMAID_CLASS = re.compile(r'^\s*class\s+([A-Za-z_]\w*)')
MERMAID_RELATION = re.compile(
    r'^\s*([A-Za-z_]\w*)\s*(?:"[^"]*"\s*)?'
    r'(?:<\|--|<\|\.\.|--\|>|\.\.\|>|\*--|--\*|o--|--o|<--|-->|<\.\.|\.\.>|--|\.\.)'
    r'\s*(?:"[^"]*"\s*)?([A-Za-z_]\w*)'
)
# Built-in and third-party types the current docs name. A name joins only after a check that
# the library really defines it (``python -c 'import mcp.types; mcp.types.ToolAnnotations'``,
# the ONVIF Media and Device specifications); a name defined under ``src/`` never does, since
# the detector reads those from the source and a stale one must fail.
KNOWN_EXTERNAL_TYPES = frozenset(
    {
        'Exception',  # Python
        'ImportError',
        'PermissionError',
        'ValueError',
        'BaseModel',  # pydantic
        'SecretStr',
        'CallToolResult',  # mcp.types
        'ToolAnnotations',
        'ProtectApiClient',  # uiprotect
        'GetStreamUri',  # ONVIF: the Media service operation
        'XAddr',  # ONVIF: the service-address element of GetCapabilities and GetServices
    }
)


@dataclass(frozen=True)
class SrcBindings:
    """The names one Python source (or every tracked one under ``src/``) binds.

    Attributes:
        defs: Function and method names.
        classes: Class names.
        module_names: Module-level assignment targets (constants, type aliases, Typer apps).
        class_attributes: Names assigned in a class body (model and result fields).
        parameters: Function parameter names.
    """

    defs: frozenset[str]
    classes: frozenset[str]
    module_names: frozenset[str]
    class_attributes: frozenset[str]
    parameters: frozenset[str]

    def __or__(self, other: SrcBindings) -> SrcBindings:
        """Merge two sources' bindings."""
        return SrcBindings(
            self.defs | other.defs,
            self.classes | other.classes,
            self.module_names | other.module_names,
            self.class_attributes | other.class_attributes,
            self.parameters | other.parameters,
        )


EMPTY_BINDINGS = SrcBindings(frozenset(), frozenset(), frozenset(), frozenset(), frozenset())


def _assigned(statement: ast.stmt) -> set[str]:
    """Return the names an ``Assign`` or ``AnnAssign`` statement binds (tuples unpacked)."""
    if isinstance(statement, ast.Assign):
        return {n.id for t in statement.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return {statement.target.id}
    return set()


def src_bindings(text: str) -> SrcBindings:
    """Return the names one Python source binds, by kind, read from its AST.

    Args:
        text: The source.

    Returns:
        The bindings. A local variable or a keyword argument on its own line is no binding
        a doc may name, so neither is collected.
    """
    tree = ast.parse(text)
    defs: set[str] = set()
    classes: set[str] = set()
    class_attributes: set[str] = set()
    parameters: set[str] = set()
    module_names = {name for statement in tree.body for name in _assigned(statement)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.add(node.name)
            class_attributes |= {n for statement in node.body for n in _assigned(statement)}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.add(node.name)
            args = node.args
            parameters |= {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            parameters |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
    return SrcBindings(
        frozenset(defs),
        frozenset(classes),
        frozenset(module_names),
        frozenset(class_attributes),
        frozenset(parameters),
    )


@functools.cache
def _src_bindings() -> SrcBindings:
    """Return the bindings of every tracked Python file under ``src/``."""
    bindings = EMPTY_BINDINGS
    for path in sorted(p for p in _tracked() if p.startswith('src/') and p.endswith('.py')):
        bindings |= src_bindings((REPO / path).read_text(encoding='utf-8'))
    return bindings


def _is_class_reference(name: str) -> bool:
    """True for a CamelCase name: two or more capitals and at least one lower-case letter."""
    return sum(c.isupper() for c in name) >= 2 and any(c.islower() for c in name)


@functools.cache
def _known_classes() -> frozenset[str]:
    """Return the class names a doc may use: ``src/`` classes, type aliases, external types.

    A module-level CamelCase assignment is a type alias (``UnsubscribeFunc = Callable[[],
    None]``), which a doc names like a class.
    """
    bindings = _src_bindings()
    aliases = {n for n in bindings.module_names if _is_class_reference(n)}
    return bindings.classes | aliases | KNOWN_EXTERNAL_TYPES


def class_name_problems(path: str, text: str, known: frozenset[str]) -> list[str]:
    """Return ``path:line: problem`` for each class name that no code defines.

    A backticked CamelCase name in prose, and each class a Mermaid ``classDiagram`` declares or
    relates, must be a class or type alias under ``src/`` or one of ``KNOWN_EXTERNAL_TYPES``.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        known: Every class name a doc may use (``_known_classes()``).

    Returns:
        The problems in file order.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for name in CLASS_REF.findall(line):
            if _is_class_reference(name) and name not in known:
                problems.append(f'{path}:{n}: unknown class {name}')
    if not path.endswith('.md'):
        return problems
    for start, info, body in code_blocks(text):
        if not info.startswith('mermaid') or _diagram_type(body) != 'classDiagram':
            continue
        for offset, line in enumerate(body):
            names = MERMAID_CLASS.findall(line)
            names += [end for ends in MERMAID_RELATION.findall(line) for end in ends]
            for name in names:
                if name not in known:
                    problems.append(
                        f'{path}:{start + offset}: unknown class {name} in a classDiagram'
                    )
    return sorted(problems, key=lambda p: int(p.split(':')[1]))


def test_class_name_detector_reports_an_unknown_class() -> None:
    """A made-up class in prose or a classDiagram is reported; real and external ones are not."""
    known = _known_classes()
    text = (
        'A `NoSuchManager` wraps `UniFiClient`; `ToolRegistry()` and `UniFiClient.get_devices()`\n'
        'are fine, as are `BaseModel` (pydantic), `Path`, `UNIFI_URL` and `README.md`.\n'
        '\n'
        '```mermaid\n'
        'classDiagram\n'
        '    class NoSuchThing {\n'
        '        +run() None\n'
        '    }\n'
        '    class UniFiClient\n'
        '    Exception <|-- UniFiApiError\n'
        '    NoSuchBase <|-- NoSuchThing\n'
        '    ToolRegistry "1" *-- "*" ToolMetadata : holds\n'
        '```\n'
    )
    assert class_name_problems('demo.md', text, known) == [
        'demo.md:1: unknown class NoSuchManager',
        'demo.md:6: unknown class NoSuchThing in a classDiagram',
        'demo.md:11: unknown class NoSuchBase in a classDiagram',
        'demo.md:11: unknown class NoSuchThing in a classDiagram',
    ]
    assert class_name_problems('demo.py', '`NoSuchManager`\n', known) == [
        'demo.py:1: unknown class NoSuchManager'
    ]


def test_src_bindings_sorts_names_by_kind() -> None:
    """Module names, class attributes and parameters are collected; locals and kwargs are not."""
    source = (
        'MODULE_NAME = 1\n'
        'Alias = dict[str, int]\n'
        'a, b = 1, 2\n'
        '\n'
        '\n'
        'class Model:\n'
        '    field: int = 0\n'
        '    other = 1\n'
        '\n'
        '    def method(self, param, *rest, key=None, **extra):\n'
        '        local = call(keyword=1)\n'
        '        return local\n'
    )
    bindings = src_bindings(source)
    assert bindings.module_names == {'MODULE_NAME', 'Alias', 'a', 'b'}
    assert bindings.classes == {'Model'}
    assert bindings.defs == {'method'}
    assert bindings.class_attributes == {'field', 'other'}
    assert bindings.parameters == {'self', 'param', 'rest', 'key', 'extra'}
    assert 'local' not in bindings.module_names and 'keyword' not in bindings.module_names


def test_documented_class_names_exist_in_the_code() -> None:
    """Every CamelCase name and classDiagram class in the current docs is defined somewhere."""
    docs, known = _current_docs(), _known_classes()
    references = sum(
        1 for t in docs.values() for m in CLASS_REF.findall(t) if _is_class_reference(m)
    )
    assert references > 100, f'found only {references} class references: has the pattern moved?'
    assert 'UniFiClient' in known and 'UnsubscribeFunc' in known
    assert _all_problems(docs, lambda p, t: class_name_problems(p, t, known)) == []


# ---------------------------------------------------------------------------
# diagnose all
# ---------------------------------------------------------------------------

CHECK_COUNT = re.compile(r'\b(\d+)(?:-| | independent | diagnostic )checks?\b')
CHECK_COUNT_LINE = re.compile(r'diagnose[ _]all|loop \d+ checks|\d+ diagnostic checks')
CHECK_LIST = re.compile(r'`diagnose all`[^\n]*?\bruns (\d+) [^:\n]*?: (?P<items>[^.]+)\.')


@functools.cache
def _diagnose_all_checks() -> tuple[str, ...]:
    """Return the check names ``diagnose all`` and ``run_all_diagnostics`` run."""
    from unifi_mapper.diagnostics.run_all import CHECKS

    return tuple(check.name for check in CHECKS)


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
# Mermaid
# ---------------------------------------------------------------------------

# Mermaid's escape codes, such as #59; for a ';', are text, not a statement break.
MERMAID_ENTITY = re.compile(r'#\w+;')


def _front_matter_end(body: list[str]) -> int:
    """Return the index of a Mermaid block's first line after its YAML front matter.

    Front matter is a ``---`` first line, up to the next ``---`` line (a ``title:``, say).

    Args:
        body: The block's lines, without the fences.

    Returns:
        0 when the block has no complete front matter.
    """
    if not body or body[0].strip() != '---':
        return 0
    return next((i + 1 for i, line in enumerate(body[1:], 1) if line.strip() == '---'), 0)


def _diagram_type(body: list[str]) -> str:
    """Return a Mermaid block's diagram type: the first word of its first statement.

    A leading front-matter section is skipped.
    """
    for line in body[_front_matter_end(body) :]:
        statement = line.strip()
        if statement and not statement.startswith('%%'):
            return statement.split()[0]
    return ''


def mermaid_problems(path: str, text: str) -> list[str]:
    """Return ``path:line: problem`` for each sequence-diagram line that breaks the render.

    In a Mermaid ``sequenceDiagram`` a ``;`` ends the statement, so a message such as
    ``A->>B: open; read`` stops at ``open`` and the rest of the line doesn't parse: GitHub
    shows an error box instead of the diagram. ``%%`` comment lines and entity codes such as
    ``#59;`` are allowed, and so is YAML front matter. Other diagram types are not checked: a
    ``;`` inside a flowchart label renders.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        One entry per offending line, in file order.
    """
    if not path.endswith('.md'):
        return []
    problems = []
    for start, info, body in code_blocks(text):
        if not info.startswith('mermaid') or _diagram_type(body) != 'sequenceDiagram':
            continue
        skip = _front_matter_end(body)
        for offset, line in enumerate(body[skip:], skip):
            if not line.strip().startswith('%%') and ';' in MERMAID_ENTITY.sub('', line):
                problems.append(f'{path}:{start + offset}: ";" ends a sequence-diagram statement')
    return problems


def test_mermaid_detector_reports_a_semicolon_in_a_sequence_message() -> None:
    """A ``;`` in a sequence message is reported; comments, escapes and flowcharts are not."""
    text = (
        '```mermaid\n'
        'sequenceDiagram\n'
        '    %% a comment; allowed\n'
        '    A->>B: open; read\n'
        '    B-->>A: done #59; next\n'
        '```\n'
        '\n'
        '```mermaid\n'
        'flowchart LR\n'
        '    A["one; two"] --> B\n'
        '```\n'
    )
    assert mermaid_problems('docs/demo.md', text) == [
        'docs/demo.md:4: ";" ends a sequence-diagram statement'
    ]


def test_mermaid_detector_reads_past_front_matter() -> None:
    """A sequence diagram that opens with front matter is still checked; the YAML is not."""
    text = (
        '```mermaid\n'
        '---\n'
        'title: Login; refresh\n'
        '---\n'
        'sequenceDiagram\n'
        '    A->>B: open; read\n'
        '```\n'
    )
    assert mermaid_problems('docs/demo.md', text) == [
        'docs/demo.md:6: ";" ends a sequence-diagram statement'
    ]


def test_no_sequence_diagram_breaks_a_statement_at_a_semicolon() -> None:
    """Every Mermaid sequence diagram in every doc parses past each message's text."""
    docs = _docs()
    sequences = sum(
        1
        for text in docs.values()
        for _start, info, body in code_blocks(text)
        if info.startswith('mermaid') and _diagram_type(body) == 'sequenceDiagram'
    )
    assert sequences > 10, f'found only {sequences} sequence diagrams: has the syntax moved?'
    assert _all_problems(docs, mermaid_problems) == []


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
# An expression that is the environment: ``os.environ``, ``environ``, an ``env`` parameter
# (``load_server_settings(env=None)``) or ``(os.environ if env is None else env)``.
ENVIRONMENT = re.compile(r'\benviron\b|^env$')
MAPPING_READS = frozenset({'get', 'pop', 'setdefault'})


def _is_environment(node: ast.expr) -> bool:
    """True when ``node`` evaluates to the process environment or an injected env mapping."""
    return bool(ENVIRONMENT.search(ast.unparse(node)))


def _env_key_nodes(tree: ast.Module) -> list[ast.expr]:
    """Return the expressions the source reads from the environment by key.

    A read is the subscript of ``os.environ[...]``, the first argument of ``.get``, ``.pop``
    or ``.setdefault`` on the environment, of ``os.getenv`` / ``getenv`` and of a same-file
    helper whose parameter is itself read that way (``_bounded_number(env, key, ...)``), the
    left side of ``in`` / ``not in`` against the environment, and an option's ``envvar=``.
    """
    keys: list[ast.expr] = []
    helpers: dict[str, int] = {}  # helper name -> the index of its key parameter
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [a.arg for a in (*node.args.posonlyargs, *node.args.args)]
            for inner in ast.walk(node):
                for key in _direct_env_keys(inner):
                    if isinstance(key, ast.Name) and key.id in names:
                        helpers[node.name] = names.index(key.id)
    for node in ast.walk(tree):
        keys += _direct_env_keys(node)
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            index = helpers.get(name or '')
            if index is not None and len(node.args) > index:
                keys.append(node.args[index])
        elif isinstance(node, ast.keyword) and node.arg == 'envvar':
            keys.append(node.value)
    return keys


def _direct_env_keys(node: ast.AST) -> list[ast.expr]:
    """Return the key expressions of one environment access node (none for other nodes)."""
    if isinstance(node, ast.Subscript) and _is_environment(node.value):
        return [node.slice]
    if isinstance(node, ast.Compare) and len(node.comparators) == 1:
        if isinstance(node.ops[0], (ast.In, ast.NotIn)) and _is_environment(node.comparators[0]):
            return [node.left]
    if isinstance(node, ast.Call) and node.args:
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in MAPPING_READS and _is_environment(func.value):
                return [node.args[0]]
            if func.attr == 'getenv':
                return [node.args[0]]
        elif isinstance(func, ast.Name) and func.id == 'getenv':
            return [node.args[0]]
    return []


def _module_constants(tree: ast.Module) -> dict[str, list[str]]:
    """Return ``{name: variable names}`` for each module-level assignment of exact names.

    ``CALL_AUDIT_ENV = 'UNIFI_MCP_CALL_AUDIT'`` and a table such as ``CREDENTIAL_KEYS``
    bind the keys the code reads later, by the constant's name or by iterating the table; a
    message constant (``'set UNIFI_URL first'``) is not an exact name and does not count.
    """
    constants: dict[str, list[str]] = {}
    for statement in tree.body:
        names = _assigned(statement)
        value = getattr(statement, 'value', None)
        if not names or value is None:
            continue
        exact = [
            n.value
            for n in ast.walk(value)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and ENV_VAR.fullmatch(n.value)
        ]
        for name in names:
            constants[name] = exact
    return constants


def env_vars_read(path: str, text: str) -> frozenset[str]:
    """Return the ``UNIFI_*``, ``PROTECT_*`` and ``XDG_*`` names one source file reads.

    In Python a variable counts as read when its name is the key of an environment read
    (``os.environ[...]``, ``os.environ.get``, ``os.getenv``, an injected ``env`` mapping,
    ``in os.environ``, a same-file helper's key parameter, an option's ``envvar=``), given as
    a string or as a module-level constant, or when it is one of the exact names a
    module-level constant or table binds. A name that appears only in a message, hint, help
    text, docstring or comment is not read, so a variable the code stopped reading fails the
    docs guard even while a message still names it. In a shell script or YAML file every
    line but a comment counts.

    Args:
        path: The repo-relative file name.
        text: The file's text.

    Returns:
        The variable names.
    """
    if not path.endswith('.py'):
        code = '\n'.join(ln for ln in text.splitlines() if not ln.lstrip().startswith('#'))
        return frozenset(ENV_VAR.findall(code))
    tree = ast.parse(text)
    constants = _module_constants(tree)
    names: set[str] = {n for exact in constants.values() for n in exact}
    for key in _env_key_nodes(tree):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.update(ENV_VAR.findall(key.value))
        elif isinstance(key, ast.Name):
            names.update(constants.get(key.id, ()))
    return frozenset(names)


@functools.cache
def _read_env_vars() -> frozenset[str]:
    """Return every environment variable the code under ``src/`` and ``scripts/`` reads."""
    names: set[str] = set()
    for path in _tracked():
        if path.startswith(('src/', 'scripts/')) and path.endswith(('.py', '.sh', '.yaml')):
            names |= env_vars_read(path, (REPO / path).read_text(encoding='utf-8'))
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


def test_env_reader_ignores_docstrings_and_comments() -> None:
    """A variable only a docstring or comment names isn't read; a string constant is."""
    source = (
        '"""Module docs name UNIFI_DOC_ONLY."""\n'
        'import os\n'
        '\n'
        '\n'
        'def get() -> str | None:\n'
        '    """Function docs name UNIFI_ALSO_DOC_ONLY."""\n'
        '    # A comment names UNIFI_COMMENT_ONLY.\n'
        "    return os.environ.get('UNIFI_READ_HERE')\n"
    )
    shell = '# UNIFI_SHELL_COMMENT\nexport UNIFI_SHELL_READ="${UNIFI_SHELL_READ:-x}"\n'
    assert env_vars_read('src/demo.py', source) == {'UNIFI_READ_HERE'}
    assert env_vars_read('scripts/demo.sh', shell) == {'UNIFI_SHELL_READ'}


def test_env_reader_counts_reads_but_not_messages() -> None:
    """A variable named only in a message, hint or help text is not read (issue 055)."""
    source = (
        'import os\n'
        'from os import environ, getenv\n'
        '\n'
        "KEY = 'UNIFI_VIA_CONSTANT'\n"
        "TABLE = {'controller': (('UNIFI_IN_A_TABLE',),)}\n"
        "HINT = 'set UNIFI_IN_A_HINT in the config file'\n"
        '\n'
        '\n'
        'def _number(env, key, low):\n'
        '    return env.get(key)\n'
        '\n'
        '\n'
        'def read(env=None):\n'
        '    env = os.environ if env is None else env\n'
        "    a = os.environ['UNIFI_SUBSCRIPT']\n"
        "    b = os.environ.get('UNIFI_GET', '')\n"
        "    c = os.getenv('UNIFI_GETENV')\n"
        "    d = getenv('UNIFI_BARE_GETENV')\n"
        "    e = environ.get('UNIFI_BARE_ENVIRON')\n"
        "    f = env.get('UNIFI_INJECTED_ENV')\n"
        "    g = (os.environ if env is None else env).get('UNIFI_EITHER_ENV')\n"
        "    h = _number(env, 'UNIFI_VIA_HELPER', 1)\n"
        "    if 'UNIFI_MEMBERSHIP' not in os.environ:\n"
        '        raise ValueError(\n'
        "            f'{KEY} and UNIFI_IN_A_MESSAGE are unset; see UNIFI_IN_AN_FSTRING'\n"
        '        )\n'
        "    option(envvar='UNIFI_VIA_OPTION', help='or set UNIFI_IN_HELP_TEXT')\n"
        "    warn('UNIFI_IN_A_WARNING is deprecated', suggestion='use UNIFI_IN_A_SUGGESTION')\n"
        '    return a, b, c, d, e, f, g, h\n'
    )
    read = env_vars_read('src/demo.py', source)
    assert read == {
        'UNIFI_VIA_CONSTANT',
        'UNIFI_IN_A_TABLE',
        'UNIFI_SUBSCRIPT',
        'UNIFI_GET',
        'UNIFI_GETENV',
        'UNIFI_BARE_GETENV',
        'UNIFI_BARE_ENVIRON',
        'UNIFI_INJECTED_ENV',
        'UNIFI_EITHER_ENV',
        'UNIFI_VIA_HELPER',
        'UNIFI_MEMBERSHIP',
        'UNIFI_VIA_OPTION',
    }
    for message_only in ('UNIFI_IN_A_HINT', 'UNIFI_IN_A_MESSAGE', 'UNIFI_IN_AN_FSTRING'):
        assert message_only not in read
    assert not {'UNIFI_IN_HELP_TEXT', 'UNIFI_IN_A_WARNING', 'UNIFI_IN_A_SUGGESTION'} & read


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
GENERIC_NAME = re.compile(r'^(Port \d+|default|LAN|WAN\d?|Internal|Guest|IoT|Management)$', re.I)


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


@functools.cache
def _model_strings() -> frozenset[str]:
    """Return the model tokens the code classifies, normalised as ``classify_model`` does."""
    tokens: set[str] = set()
    for attribute in dir(model_capabilities):
        value = getattr(model_capabilities, attribute)
        if attribute.endswith('_TOKENS') and isinstance(value, tuple):
            tokens.update(str(token) for token in value)
    return frozenset(tokens)


def is_model_string(name: str) -> bool:
    """True for a name that is just a model the code knows, such as a device's default name."""
    return re.sub(r'[\s_-]', '', name).upper() in _model_strings()


def local_device_names(reports: Path) -> frozenset[str]:
    """Return the device and client names in the local ``reports/*.json`` captures.

    Only device and client records count, so a port label, network, SSID or profile name in a
    new capture can't fail the suite: a ``name`` is taken from a record that also carries a
    ``mac`` or ``device_id``, and a ``hostname`` or ``device_name`` from any record, never from
    a port (a record with a ``port_idx``). Strings longer than 4 and shorter than 60
    characters count, minus generic words, bare numbers, ``GENERIC_NAMES`` and model strings
    the code classifies (a device that kept its model as its name names no site).

    Args:
        reports: The directory holding the captures.

    Returns:
        The names; empty when there are no captures (a fresh clone).
    """
    names: set[str] = set()

    def walk(node: object) -> None:
        """Collect the device and client names anywhere in one parsed capture."""
        if isinstance(node, dict):
            if 'port_idx' not in node:
                keys = ['hostname', 'device_name']
                if 'mac' in node or 'device_id' in node:
                    keys.append('name')
                for key in keys:
                    value = node.get(key)
                    if isinstance(value, str) and 4 < len(value) < 60:
                        names.add(value)
            for value in node.values():
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
        if not GENERIC_NAME.match(n)
        and not re.fullmatch(r'[\d.]+', n)
        and n not in GENERIC_NAMES
        and not is_model_string(n)
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
    captures = {
        'devices': [
            {'name': 'Synthetic Lounge Switch', 'mac': '02:00:00:00:00:01'},
            {'name': 'U6 LR', 'device_id': 'a' * 24},
            {'name': 'USW-Flex-XG', 'mac': '02:00:00:00:00:02'},
            {'name': 'Synthetic Port Label', 'port_idx': 4},
        ],
        'clients': [{'hostname': 'synthetic-laptop'}, {'hostname': 'Port 3'}],
        'plan': [{'device_name': 'Synthetic Core Switch'}, {'device_name': '12.3.4'}],
        'networks': [{'name': 'Synthetic Guest Network', 'vlan': 30}],
    }
    (tmp_path / 'capture.json').write_text(json.dumps(captures), encoding='utf-8')
    names = local_device_names(tmp_path)
    # 'USW-Flex-XG' is a model the code classifies: a device that kept its default name.
    assert is_model_string('USW-Flex-XG') and not is_model_string('Synthetic Core Switch')
    assert names == {'Synthetic Lounge Switch', 'synthetic-laptop', 'Synthetic Core Switch'}
    assert device_name_problems('demo.md', text, _names_pattern(names)) == [
        'demo.md:3: device name from the local captures'
    ]


def test_documented_identifiers_are_documentation_values() -> None:
    """Every MAC in the docs is locally administered and no IPv4 address is private."""
    docs = _docs()
    assert sum(len(MAC.findall(t)) for t in docs.values()) > 0, 'no MAC found: has MAC moved?'
    assert _all_problems(docs, mac_problems) == []
    assert _all_problems(docs, ipv4_problems) == []


def _tracked_texts(prefixes: tuple[str, ...]) -> dict[str, str]:
    """Return ``{path: text}`` for every tracked UTF-8 file under ``prefixes``."""
    texts: dict[str, str] = {}
    for path in sorted(_tracked()):
        if not path.startswith(prefixes) or not (REPO / path).is_file():
            continue
        try:
            texts[path] = (REPO / path).read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
    return texts


def test_no_device_name_from_the_local_captures() -> None:
    """No doc, source, test or script file names a device from the local captures."""
    names = local_device_names(REPO / 'reports')
    if not names:
        pytest.skip('no local captures in reports/ (a fresh clone): nothing to compare')
    pattern = _names_pattern(names)
    sources = {
        p: t
        for p, t in _tracked_texts(('src/unifi_mapper/',)).items()
        if p.endswith(('.py', '.yaml'))
    }
    corpus = {**_docs(), **sources, **_tracked_texts(('tests/', 'scripts/'))}
    assert any(p.startswith('tests/') for p in corpus) and any(
        p.startswith('scripts/') for p in corpus
    ), 'no tracked test or script read: has the corpus moved?'
    problems = _all_problems(corpus, lambda p, t: device_name_problems(p, t, pattern))
    assert problems == [], (
        'a device or client name from reports/*.json appears on these lines (the name is not '
        'shown). Replace it with a placeholder, or, if it is a product model or a factory port '
        'label rather than a site name, add it to GENERIC_NAMES once that is checked.'
    )


# ---------------------------------------------------------------------------
# Privacy in tests and scripts: identifiers from the local captures
# ---------------------------------------------------------------------------

# A fixture may keep a public vendor OUI, so the docs' MAC rule above can't apply to tests/
# and scripts/: there a MAC, serial, ID or address counts only when the local captures hold it.
BARE_MAC = re.compile(r'(?<![0-9A-Za-z])[0-9A-Fa-f]{12}(?![0-9A-Za-z])')
HEX_ID = re.compile(r'(?<![0-9A-Za-z])[0-9a-fA-F]{24}(?![0-9A-Za-z])')
UUID_ID = re.compile(
    r'(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])'
)
IPV6 = re.compile(r'(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])')
WORD_TOKEN = re.compile(r'[0-9A-Za-z]{6,}')
CIDR_SUFFIX = re.compile(r'/(\d{1,2})\b')
NOT_AN_ADDRESS = re.compile(r'version|firmware|build', re.I)
# Global unicast and unique-local IPv6, minus the documentation prefix.
SITE_V6 = tuple(ipaddress.IPv6Network(n) for n in ('2000::/3', 'fc00::/7'))
DOC_V6 = ipaddress.IPv6Network('2001:db8::/32')
LINK_LOCAL_V6 = ipaddress.IPv6Network('fe80::/10')
# A public IPv4 address identifies the site by value, but only when it sits in a field that
# holds an address of the site (the WAN and gateway fields of stat/device and stat/health,
# a VPN peer); a vendor's cloud or update host, or a resolver, is in some other field.
ADDRESS_KEY = re.compile(r'^(?:ip|ip6|ipv6|gateway|gw)$|_(?:ip|ip6|ipv6|gateway|gw)$|^wan\d?$')
NOT_A_SITE_ADDRESS_KEY = re.compile(r'dns|ntp|server|host|resolver|speedtest', re.I)
# Public resolvers a capture holds in its DNS fields: Cloudflare, Google, Quad9, OpenDNS.
PUBLIC_RESOLVERS = frozenset(
    ipaddress.IPv4Address(a)
    for a in (
        '1.1.1.1',
        '1.0.0.1',
        '8.8.8.8',
        '8.8.4.4',
        '9.9.9.9',
        '149.112.112.112',
        '208.67.222.222',
        '208.67.220.220',
    )
)
# Space no site's WAN address lies in: the documentation ranges, loopback, multicast,
# reserved, "this network" and the broadcast address (PRIVATE_NETWORKS covers the rest).
NOT_PUBLIC_V4 = tuple(
    ipaddress.IPv4Network(n)
    for n in (
        '192.0.2.0/24',
        '198.51.100.0/24',
        '203.0.113.0/24',
        '0.0.0.0/8',
        '127.0.0.0/8',
        '224.0.0.0/4',
        '240.0.0.0/4',
    )
)


@dataclass(frozen=True)
class CapturedIdentifiers:
    """The identifiers of the live network that the local captures hold.

    Attributes:
        macs: MAC addresses, as 12 lower-case hex digits.
        serials: Serial numbers, lower case.
        ids: 24-hex object IDs and UUIDs (device and site IDs), lower case.
        subnets: The /24 of every private, link-local or CGNAT address.
        prefixes: The /48 of every global or unique-local IPv6 address.
        addresses: Every public IPv4 address in an address field, by value (the WAN address).
        link_local: Every link-local IPv6 address, by value (it can embed a MAC address).
    """

    macs: frozenset[str]
    serials: frozenset[str]
    ids: frozenset[str]
    subnets: frozenset[ipaddress.IPv4Network]
    prefixes: frozenset[ipaddress.IPv6Network]
    addresses: frozenset[ipaddress.IPv4Address] = frozenset()
    link_local: frozenset[ipaddress.IPv6Address] = frozenset()

    def __bool__(self) -> bool:
        """True when the captures held any identifier."""
        return bool(
            self.macs
            or self.serials
            or self.ids
            or self.subnets
            or self.prefixes
            or self.addresses
            or self.link_local
        )


def _mac_digits(token: str) -> str | None:
    """Return a MAC-shaped token as 12 lower-case hex digits; None for all zeros or ones."""
    digits = re.sub('[^0-9A-Fa-f]', '', token).lower()
    if len(digits) != 12 or set(digits) == {'0'} or set(digits) == {'f'}:
        return None
    return digits


def _json_strings(node: object, key: str = '') -> list[tuple[str, str]]:
    """Return ``(key, value)`` for every string value in a parsed JSON document."""
    if isinstance(node, dict):
        return [pair for k, v in node.items() for pair in _json_strings(v, str(k))]
    if isinstance(node, list):
        return [pair for item in node for pair in _json_strings(item, key)]
    return [(key, node.strip())] if isinstance(node, str) else []


def _is_site_public_v4(key: str, address: ipaddress.IPv4Address) -> bool:
    """True for a public address in a field that holds an address of the site (the WAN)."""
    if not ADDRESS_KEY.search(key.lower()) or NOT_A_SITE_ADDRESS_KEY.search(key):
        return False
    if address in PUBLIC_RESOLVERS or any(address in n for n in NOT_PUBLIC_V4):
        return False
    return not any(address in network for network in PRIVATE_NETWORKS)


def captured_identifiers(reports: Path) -> CapturedIdentifiers:
    """Collect the identifiers in ``reports/*.json``: MACs, serials, IDs, networks, addresses.

    Args:
        reports: The directory holding the captures.

    Returns:
        The identifiers; empty when there are no captures (a fresh clone).
    """
    macs: set[str] = set()
    serials: set[str] = set()
    ids: set[str] = set()
    subnets: set[ipaddress.IPv4Network] = set()
    prefixes: set[ipaddress.IPv6Network] = set()
    addresses: set[ipaddress.IPv4Address] = set()
    link_local: set[ipaddress.IPv6Address] = set()
    for capture in sorted(reports.glob('*.json')):
        try:
            document = json.loads(capture.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for key, value in _json_strings(document):
            lower_key = key.lower()
            if MAC.fullmatch(value) or ('mac' in lower_key and BARE_MAC.fullmatch(value)):
                digits = _mac_digits(value)
                if digits:
                    macs.add(digits)
            if (
                'serial' in lower_key
                and re.fullmatch(r'[0-9A-Za-z-]{6,}', value)
                and sum(c.isdigit() for c in value) >= 2
            ):
                serials.add(value.lower())
            if (HEX_ID.fullmatch(value) or UUID_ID.fullmatch(value)) and not value.isdigit():
                ids.add(value.lower())
            if NOT_AN_ADDRESS.search(key):
                continue
            try:
                address = ipaddress.ip_address(value.split('/')[0])
            except ValueError:
                continue
            if isinstance(address, ipaddress.IPv4Address):
                if any(address in network for network in PRIVATE_NETWORKS):
                    subnets.add(ipaddress.IPv4Network(f'{address}/24', strict=False))
                elif _is_site_public_v4(key, address):
                    addresses.add(address)
            elif address in LINK_LOCAL_V6:
                link_local.add(address)
            elif any(address in network for network in SITE_V6) and address not in DOC_V6:
                prefixes.add(ipaddress.IPv6Network(f'{address}/48', strict=False))
    return CapturedIdentifiers(
        frozenset(macs),
        frozenset(serials),
        frozenset(ids),
        frozenset(subnets),
        frozenset(prefixes),
        frozenset(addresses),
        frozenset(link_local),
    )


def _address_kind(token: str, captured: CapturedIdentifiers) -> str | None:
    """Return the problem kind when an IPv4 or IPv6 token is, or lies in, a captured one."""
    try:
        address = ipaddress.ip_address(token)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv4Address):
        if address in captured.addresses:
            return 'public IPv4 address'
        if any(address in subnet for subnet in captured.subnets):
            return 'address in a captured subnet'
    elif address in captured.link_local:
        return 'link-local IPv6 address'
    elif any(address in prefix for prefix in captured.prefixes):
        return 'IPv6 address in a captured prefix'
    return None


def captured_identifier_problems(path: str, text: str, captured: CapturedIdentifiers) -> list[str]:
    """Return ``path:line: problem`` for each identifier on a line that the captures hold.

    Args:
        path: The repo-relative file name.
        text: The file's text.
        captured: The identifiers from ``captured_identifiers``.

    Returns:
        The problems in file order, one per kind and line, without the identifier.
    """
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        kinds: set[str] = set()
        for rx in (MAC, BARE_MAC):
            for m in rx.finditer(line):
                digits = _mac_digits(m.group(0))
                if digits in captured.macs:
                    kinds.add('MAC address')
                elif digits in captured.serials:
                    kinds.add('serial number')
        if any(m.group(0).lower() in captured.serials for m in WORD_TOKEN.finditer(line)):
            kinds.add('serial number')
        for rx in (HEX_ID, UUID_ID):
            if any(m.group(0).lower() in captured.ids for m in rx.finditer(line)):
                kinds.add('device or site ID')
        for m in IPV4.finditer(line):
            cidr = CIDR_SUFFIX.match(line, m.end())
            if cidr and int(cidr.group(1)) < 24:
                continue  # an RFC 1918 block, say: it names no site subnet
            if (kind := _address_kind(m.group(0), captured)) is not None:
                kinds.add(kind)
        for m in IPV6.finditer(line):
            if (kind := _address_kind(m.group(0), captured)) is not None:
                kinds.add(kind)
        problems += [f'{path}:{n}: {kind} from the local captures' for kind in sorted(kinds)]
    return problems


def test_captured_identifier_detector_reports_what_the_captures_hold(tmp_path: Path) -> None:
    """Captured MACs, serials, IDs, subnets, prefixes and addresses are reported; look-alikes not."""
    # Built at run time, so this file holds no literal a privacy scan could take for real.
    mac = ':'.join(['3c', '22', 'fb', '12', '34', '56'])  # universally administered
    host = '.'.join(['10', '20', '30', '40'])
    neighbour = '.'.join(['10', '20', '30', '99'])
    elsewhere = '.'.join(['10', '20', '31', '5'])
    # A dotted version string that parses as a private address: its key ('version') says it
    # is no address, so its /24 must not become a captured subnet.
    version = '.'.join(['10', '99', '0', '1'])
    version_neighbour = '.'.join(['10', '99', '0', '7'])
    prefix_host = ':'.join(['3fff', '1', '2', '0', '0', '0', '0', '10'])
    neighbour_v6 = ':'.join(['3fff', '1', '2', 'ab', '0', '0', '0', '1'])
    # The WAN address is public and identifies the site by value; its /24 neighbour does not.
    wan = '.'.join(['11', '22', '33', '44'])
    wan_neighbour = '.'.join(['11', '22', '33', '45'])
    resolver = '.'.join(['1', '1', '1', '1'])  # a public resolver: never an identifier
    # A public address outside an address field (a vendor's update host, say) is not collected.
    update_host = '.'.join(['11', '22', '34', '1'])
    link_local = ':'.join(['fe80', '', '1a2b', '3c4d', '5e6f', '7a8b'])
    serial = 'SYN' + '0123456789'
    object_id = '5f0e1d2c' + '3b4a5968' + '77665544'
    site_id = '-'.join(['12345678', '90ab', '4cde', '8f01', '23456789abcd'])
    capture = {
        'devices': [
            {'mac': mac, 'ip': host, 'serial': serial, '_id': object_id, 'ip6': prefix_host},
            {'version': version, 'site_id': site_id},
            {'wan_ip': wan, 'dns1': resolver, 'update_host': update_host, 'ipv6': link_local},
        ]
    }
    (tmp_path / 'capture.json').write_text(json.dumps(capture), encoding='utf-8')
    captured = captured_identifiers(tmp_path)
    text = (
        f"MAC '{mac.upper()}', bare {mac.replace(':', '')}.\n"
        f'Same vendor, other NIC: {mac[:9]}00:00:01; documentation MAC 00:00:5E:00:53:01.\n'
        f'Hosts {neighbour}; elsewhere {elsewhere}, 10.0.0.0/8 and 192.0.2.10.\n'
        f'Serial {serial.lower()}, object {object_id.upper()}, site {site_id}.\n'
        f'IPv6 {neighbour_v6}; documentation 2001:db8::1.\n'
        f'Next to the version string: {version_neighbour}.\n'
        f'WAN {wan}; next door {wan_neighbour}; resolver {resolver}; update host {update_host}.\n'
        f'Link-local {link_local.upper()}; another fe80::1.\n'
    )
    assert captured_identifier_problems('demo.py', text, captured) == [
        'demo.py:1: MAC address from the local captures',
        'demo.py:3: address in a captured subnet from the local captures',
        'demo.py:4: device or site ID from the local captures',
        'demo.py:4: serial number from the local captures',
        'demo.py:5: IPv6 address in a captured prefix from the local captures',
        'demo.py:7: public IPv4 address from the local captures',
        'demo.py:8: link-local IPv6 address from the local captures',
    ]


def test_tests_and_scripts_hold_no_identifier_from_the_local_captures() -> None:
    """No tracked test or script holds a MAC, serial, ID or address the captures hold."""
    captured = captured_identifiers(REPO / 'reports')
    if not captured:
        pytest.skip('no local captures in reports/ (a fresh clone): nothing to compare')
    files = _tracked_texts(('tests/', 'scripts/'))
    assert len(files) > 100, f'read only {len(files)} files: has the corpus moved?'
    problems = _all_problems(files, lambda p, t: captured_identifier_problems(p, t, captured))
    assert problems == [], (
        'a network identifier from reports/*.json appears on these lines (the value is not '
        'shown). Use a documentation value: 192.0.2.0/24, 198.51.100.0/24 or 203.0.113.0/24, '
        '2001:db8::/32, or a 02:00:00:... MAC (keep a public vendor OUI only where a test '
        'needs the vendor).'
    )
