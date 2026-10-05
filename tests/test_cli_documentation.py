"""Tests that keep documented commands and the real CLI in step.

Two drift modes have bitten this project:

1. A command documented in the README but not reachable on the CLI. Users copy
   the example, get "No such command", and conclude the feature is missing.
2. A ``if __name__ == '__main__': app()`` guard placed mid-module. Every command
   defined below it still registers when the console-script entry point imports
   the module, but silently disappears when the module is run with
   ``python -m unifi_mapper.typer_cli``, because the guard calls ``app()`` and
   exits before the remaining decorators execute. Ten commands were invisible
   this way, which read exactly like a missing implementation.

Both are cheap to assert and expensive to rediscover.
"""

from __future__ import annotations

import ast
import click
import pytest
import re
import typer
from collections.abc import Iterator
from pathlib import Path
from tests.markdown_blocks import code_blocks
from unifi_mapper.typer_cli import app


REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / 'README.md'
TYPER_CLI = REPO_ROOT / 'src' / 'unifi_mapper' / 'typer_cli.py'

# Entry points documented in the README that this test resolves. Only
# unifi-mapper is a Typer app; the others are argparse and are checked by
# existence of their module-level parsers elsewhere.
TYPER_ENTRY_POINT = 'unifi-mapper'


def _registered_commands(t: typer.Typer, prefix: str = '') -> set[str]:
    """Return every command path registered on a Typer app, recursively."""
    found: set[str] = set()
    for command in t.registered_commands:
        name = command.name or (
            command.callback.__name__.replace('_', '-') if command.callback else ''
        )
        if name:
            found.add(f'{prefix}{name}'.strip())
    for group in t.registered_groups:
        if group.typer_instance is None:
            continue
        found |= _registered_commands(group.typer_instance, f'{prefix}{group.name or ""} ')
    return found


def _documented_commands() -> set[str]:
    """Extract unifi-mapper command paths from README fenced code blocks.

    Flags and positional arguments are dropped, leaving the subcommand path so
    ``unifi-mapper ports inspect "Switch" 2`` resolves to ``ports inspect``. Only shell
    blocks (``bash``, ``sh`` or no info string) are read.
    """
    text = README.read_text(encoding='utf-8')
    documented: set[str] = set()
    for _start, info, block in code_blocks(text):
        if info not in ('', 'bash', 'sh'):
            continue
        for line in block:
            line = line.strip()
            if not line.startswith(f'{TYPER_ENTRY_POINT} '):
                continue
            tokens = line.split()[1:]
            path: list[str] = []
            for token in tokens:
                # Stop at the first flag or quoted/numeric positional argument.
                if token.startswith('-') or token.startswith(('"', "'")):
                    break
                if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', token):
                    break
                path.append(token)
            if path:
                documented.add(' '.join(path))
    return documented


# ---------------------------------------------------------------------------
# Documented commands must exist
# ---------------------------------------------------------------------------


def test_code_blocks_pair_fences_whatever_the_info_string() -> None:
    """A ``text`` block must not swallow the next ``bash`` block, as the old regex let it."""
    text = '```text\nnot a command\n```\n\nprose\n\n```bash\nunifi-mapper ports refresh\n```\n'
    assert list(code_blocks(text)) == [
        (2, 'text', ['not a command']),
        (8, 'bash', ['unifi-mapper ports refresh']),
    ]


def test_code_blocks_run_an_unclosed_fence_to_the_end() -> None:
    """A last fence that is never closed is still a block, so its commands are checked."""
    text = '```bash\nunifi-mapper version\n```\n\n```sh\nunifi-mapper ports refresh\n'
    assert list(code_blocks(text)) == [
        (2, 'bash', ['unifi-mapper version']),
        (6, 'sh', ['unifi-mapper ports refresh']),
    ]


def test_readme_documents_at_least_the_known_command_groups() -> None:
    """Guard against the extractor silently matching nothing."""
    documented = _documented_commands()
    assert len(documented) > 15, f'extractor found only {len(documented)} commands'
    for expected in ('ports refresh', 'stp analyze', 'radio snapshot'):
        assert expected in documented


@pytest.mark.parametrize('command', sorted(_documented_commands()))
def test_every_readme_command_is_registered(command: str) -> None:
    """Every unifi-mapper example in the README resolves to a real command."""
    registered = _registered_commands(app)
    # A documented path may name a group whose subcommands are listed separately
    # (for example `inventory list` where `inventory` is the group).
    if command in registered:
        return
    is_group_prefix = any(r.startswith(f'{command} ') for r in registered)
    assert is_group_prefix, (
        f'README documents `unifi-mapper {command}` but no such command is '
        f'registered. Closest matches: '
        f'{sorted(r for r in registered if r.split()[0] == command.split()[0])}'
    )


# ---------------------------------------------------------------------------
# The main guard must not truncate registration
# ---------------------------------------------------------------------------


def test_main_guard_is_after_every_command_definition() -> None:
    """No command may be defined below the __main__ guard.

    A guard placed mid-module calls app() and exits during `python -m`
    execution, so decorators below it never run and their commands vanish from
    that invocation path while still working via the console script.
    """
    lines = TYPER_CLI.read_text(encoding='utf-8').splitlines()

    guard_lines = [i for i, line in enumerate(lines, 1) if line.startswith('if __name__')]
    assert len(guard_lines) == 1, f'expected exactly one __main__ guard, found {guard_lines}'
    guard_line = guard_lines[0]

    decorator = re.compile(r'^@(?:app|[a-z_]+_app)\.(?:command|callback)\b')
    definitions = [i for i, line in enumerate(lines, 1) if decorator.match(line)]
    assert definitions, 'no command decorators found — has the CLI moved?'

    late = [i for i in definitions if i > guard_line]
    assert not late, (
        f'{len(late)} command(s) are defined after the __main__ guard on line '
        f'{guard_line} (first at line {late[0] if late else None}). They will be '
        f'missing when the module is run with `python -m unifi_mapper.typer_cli`. '
        f'Move the guard to the end of the file.'
    )


def test_command_set_is_identical_for_both_invocation_paths() -> None:
    """Importing the module registers the same commands the guard path would.

    Re-importing under a fresh module name proves registration does not depend
    on import order or on the guard's position.
    """
    import importlib

    module = importlib.reload(importlib.import_module('unifi_mapper.typer_cli'))
    assert _registered_commands(module.app) == _registered_commands(app)


def test_documented_groups_expose_expected_command_counts() -> None:
    """Lock the subcommand counts that the mid-file guard silently reduced."""
    registered = _registered_commands(app)
    for group, minimum in (
        ('analyze', 14),
        ('radio', 5),
        ('diagnose', 5),
        ('stp', 11),
        ('ports', 8),
    ):
        actual = len([r for r in registered if r.startswith(f'{group} ')])
        assert actual >= minimum, (
            f'group {group!r} exposes {actual} commands, expected at least {minimum}'
        )


# ---------------------------------------------------------------------------
# The README command reference must be exhaustive
# ---------------------------------------------------------------------------


def _reference_table_commands() -> set[str]:
    """Return the command names listed in the README's Command Reference table."""
    text = README.read_text(encoding='utf-8')
    if '### Command Reference' not in text:
        return set()
    section = text.split('### Command Reference')[1].split('\n### ')[0]
    return {m.group(1) for m in re.finditer(r'^\| `([a-z0-9 \-]+)`', section, re.M)}


def test_command_reference_table_lists_every_command() -> None:
    """Every registered command appears in the README reference table."""
    missing = sorted(_registered_commands(app) - _reference_table_commands())
    assert not missing, (
        f'{len(missing)} command(s) are missing from the README Command Reference table: {missing}'
    )


def test_command_reference_table_has_no_phantom_commands() -> None:
    """The README reference table lists nothing that does not exist."""
    phantom = sorted(_reference_table_commands() - _registered_commands(app))
    assert not phantom, (
        f'{len(phantom)} command(s) in the README Command Reference table are not '
        f'registered: {phantom}'
    )


# ---------------------------------------------------------------------------
# Help text is for users
# ---------------------------------------------------------------------------

# Internal tracker references: docs/issues numbers and review findings.
TRACKER_REFERENCE = re.compile(r'\bissue \d+|\bcode-review F\d+', re.IGNORECASE)


def _help_texts(command: click.Command, path: str) -> Iterator[tuple[str, str]]:
    """Yield ``(where, text)`` for a command's help and each parameter's help, recursively."""
    yield path, ' '.join(filter(None, (command.help, command.short_help, command.epilog)))
    for param in command.params:
        yield f'{path} {param.name}', getattr(param, 'help', None) or ''
    if isinstance(command, click.Group):
        for name, sub in command.commands.items():
            yield from _help_texts(sub, f'{path} {name}')


def test_help_text_names_no_internal_tracker_reference() -> None:
    """Code-review F34: ``discover --help`` ended with "(issue 027)", which users can't use."""
    texts = list(_help_texts(typer.main.get_command(app), TYPER_ENTRY_POINT))
    assert len(texts) > 100, f'the walk found only {len(texts)} help texts: has the CLI moved?'
    leaks = [f'{where}: {text}' for where, text in texts if TRACKER_REFERENCE.search(text)]
    assert not leaks, leaks


def _raises_exit_2(function: ast.FunctionDef) -> bool:
    """Whether the body raises ``typer.Exit(2)`` itself: a check that failed, not usage."""
    return any(
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Attribute)
        and node.exc.func.attr == 'Exit'
        and bool(node.exc.args)
        and isinstance(node.exc.args[0], ast.Constant)
        and node.exc.args[0].value == 2
        for node in ast.walk(function)
    )


def _commands_that_exit_2_on_a_check() -> set[str]:
    """``group command`` for every command whose body raises ``typer.Exit(2)``."""
    found: set[str] = set()
    for node in ast.parse(TYPER_CLI.read_text(encoding='utf-8')).body:
        if not isinstance(node, ast.FunctionDef) or not _raises_exit_2(node):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == 'command'
                and isinstance(decorator.func.value, ast.Name)
            ):
                continue
            group = decorator.func.value.id.removesuffix('_app')
            name = decorator.args[0]
            assert isinstance(name, ast.Constant), f'{node.name}: name its command'
            found.add(f'{group} {name.value}')
    return found


def test_the_exit_code_table_names_every_command_that_exits_2_on_a_failed_check() -> None:
    """Review M1: the README's exit 2 row said "a usage error" only, while a dozen
    commands exit 2 when their check fails; every such command must be named there."""
    lines = README.read_text(encoding='utf-8').splitlines()
    row = next(line for line in lines if line.startswith('| 2 |'))
    commands = _commands_that_exit_2_on_a_check()
    assert {'analyze link-speeds', 'diagnose all', 'stp apply'} <= commands  # the scan works
    missing = sorted(
        c for c in commands if f'`{c}`' not in row and f'`{c.split(" ", 1)[1]}`' not in row
    )
    assert missing == [], f'name these in the README exit-code table: {missing}'
