"""`configure_logging` and `UNIFI_MAPPER_DEBUG` are gone (issue 045).

The function set up a loguru JSON-file sink under ``~/.unifi-mapper/logs/`` and read
``UNIFI_MAPPER_DEBUG``, but nothing called it, so the variable did nothing and a later caller
would have started writing a log file in the home directory unannounced. The CLI
(``typer_cli.setup_logging``) and the MCP server (``server._configure_logging``) each have
their own working setup, so the dead one and its two re-exports are deleted.
"""

from __future__ import annotations

import importlib
import pytest
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PUBLIC_MODULES = [
    'unifi_mapper.core',
    'unifi_mapper.core.utils',
    'unifi_mapper.core.utils.logging',
]


@pytest.mark.parametrize('module_name', PUBLIC_MODULES)
def test_configure_logging_is_not_a_public_name(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert not hasattr(module, 'configure_logging')
    assert 'configure_logging' not in getattr(module, '__all__', ())


def test_the_loguru_helper_the_clis_use_stays() -> None:
    logging_module = importlib.import_module('unifi_mapper.core.utils.logging')
    assert callable(logging_module.replace_default_loguru_handler)


def test_unifi_mapper_debug_is_named_nowhere_but_its_issue() -> None:
    roots = [
        REPO / 'src',
        REPO / 'docs',
        REPO / 'scripts',
        REPO / 'README.md',
        REPO / '.env.example',
    ]
    hits: list[str] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(p for p in root.rglob('*') if p.is_file())
        for path in files:
            if '__pycache__' in path.parts or path.suffix in {'.pyc', '.png', '.svg'}:
                continue
            if path.parent == REPO / 'docs' / 'issues':
                continue  # the issue files are the record of what was removed
            if 'UNIFI_MAPPER_DEBUG' in path.read_text(encoding='utf-8', errors='ignore'):
                hits.append(str(path.relative_to(REPO)))
    assert hits == []
