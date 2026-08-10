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

import pytest
import re
import typer
from pathlib import Path
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
    ``unifi-mapper ports inspect "Switch" 2`` resolves to ``ports inspect``.
    """
    text = README.read_text(encoding='utf-8')
    documented: set[str] = set()
    for block in re.findall(r'```(?:bash)?\n(.*?)```', text, re.S):
        for line in block.splitlines():
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


def test_readme_documents_at_least_the_known_command_groups():
    """Guard against the extractor silently matching nothing."""
    documented = _documented_commands()
    assert len(documented) > 15, f'extractor found only {len(documented)} commands'
    for expected in ('ports refresh', 'stp analyze', 'radio snapshot'):
        assert expected in documented


@pytest.mark.parametrize('command', sorted(_documented_commands()))
def test_every_readme_command_is_registered(command: str):
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


def test_main_guard_is_after_every_command_definition():
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


def test_command_set_is_identical_for_both_invocation_paths():
    """Importing the module registers the same commands the guard path would.

    Re-importing under a fresh module name proves registration does not depend
    on import order or on the guard's position.
    """
    import importlib

    module = importlib.reload(importlib.import_module('unifi_mapper.typer_cli'))
    assert _registered_commands(module.app) == _registered_commands(app)


def test_documented_groups_expose_expected_command_counts():
    """Lock the subcommand counts that the mid-file guard silently reduced."""
    registered = _registered_commands(app)
    for group, minimum in (('analyze', 14), ('radio', 5), ('diagnose', 5), ('stp', 11)):
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


def test_command_reference_table_lists_every_command():
    """Every registered command appears in the README reference table."""
    missing = sorted(_registered_commands(app) - _reference_table_commands())
    assert not missing, (
        f'{len(missing)} command(s) are missing from the README Command Reference table: {missing}'
    )


def test_command_reference_table_has_no_phantom_commands():
    """The README reference table lists nothing that does not exist."""
    phantom = sorted(_reference_table_commands() - _registered_commands(app))
    assert not phantom, (
        f'{len(phantom)} command(s) in the README Command Reference table are not '
        f'registered: {phantom}'
    )
