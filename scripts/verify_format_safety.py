#!/usr/bin/env python3
"""Verify a formatting sweep changed no code semantics.

Parses every Python file to an AST, strips docstrings (which ruff may legally
rewrite when ``docstring-code-format`` is enabled), and records a hash of the
remaining structure. Run once before formatting and once after; identical
hashes prove the sweep only moved whitespace.

Usage:
    python scripts/verify_format_safety.py record  baseline.json
    python scripts/verify_format_safety.py compare baseline.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path


TARGETS = ('src', 'tests', 'scripts')


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove docstring expressions so docstring reformatting is ignored."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, 'body', None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _fingerprint(path: Path) -> str | None:
    """Return a semantic fingerprint for one file, or None if unparseable."""
    try:
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        print(f'  SKIP {path}: {exc}')
        return None
    dumped = ast.dump(_strip_docstrings(tree), annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dumped.encode('utf-8')).hexdigest()


def _collect(root: Path) -> dict[str, str]:
    """Fingerprint every Python file under the target directories."""
    prints: dict[str, str] = {}
    for target in TARGETS:
        base = root / target
        if not base.exists():
            continue
        for path in sorted(base.rglob('*.py')):
            if '__pycache__' in path.parts or '.venv' in path.parts:
                continue
            fp = _fingerprint(path)
            if fp is not None:
                prints[str(path.relative_to(root))] = fp
    return prints


def main() -> int:
    """Record or compare fingerprints, returning a process exit code."""
    if len(sys.argv) != 3 or sys.argv[1] not in ('record', 'compare'):
        print(__doc__)
        return 2

    mode, outfile = sys.argv[1], Path(sys.argv[2])
    root = Path(__file__).resolve().parent.parent
    current = _collect(root)

    if mode == 'record':
        outfile.write_text(json.dumps(current, indent=2, sort_keys=True))
        print(f'recorded {len(current)} file fingerprints -> {outfile}')
        return 0

    baseline = json.loads(outfile.read_text())
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    changed = sorted(f for f in set(baseline) & set(current) if baseline[f] != current[f])

    print(f'compared {len(current)} files against {len(baseline)} baseline entries')
    for label, items in (('added', added), ('removed', removed), ('CHANGED', changed)):
        if items:
            print(f'  {label}: {len(items)}')
            for item in items:
                print(f'    {item}')

    if changed or added or removed:
        print('\nFAIL: code semantics differ — this was not a formatting-only change')
        return 1
    print('\nPASS: every file has an identical AST ignoring docstrings')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
