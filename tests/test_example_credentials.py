"""Usage examples in the code show a placeholder, never a password.

``python -m unifi_mapper.verify_cli --help`` printed an example with a real-looking password.
The example is help text, and detect-secrets' keyword plugin doesn't read the
``--password VALUE`` shape, so nothing flagged it. This scan reads every string literal in
``src/`` (help text, epilogs and docstrings; never code) and fails on a password option or
argument whose value is not an explicit placeholder:

- ``--password VALUE`` or ``--password=VALUE``, a command line in help text or a docstring;
- ``password=VALUE``, with or without quotes or ``SecretStr(...)``, a call in a docstring.

Allowed values: a ``<placeholder>``, an environment variable (``$VAR`` or ``${VAR}``) or a
``{template}`` field, quoted or not. Failures name a location only, never the value.
``scripts/`` is left out: its site scripts hold runtime credentials that issue 041 tracks.
"""

from __future__ import annotations

import io
import re
import subprocess
import tokenize
from collections.abc import Iterator
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PASSWORD_VALUE = re.compile(
    r"""(?:--password(?:\s+|=)|\bpassword\s*=\s*)(?:SecretStr\()?"""
    r"""(?P<q>['"]?)(?P<value>[^\s'"(),]+)(?P=q)""",
    re.IGNORECASE,
)
PLACEHOLDER = re.compile(r'<[^<>]+>|\$\{?\w+\}?|\{[^{}]*\}')
FSTRING_MIDDLE = getattr(tokenize, 'FSTRING_MIDDLE', None)


def _strings(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(first line, text)`` for each string literal (or f-string part) in source."""
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.STRING or (
            FSTRING_MIDDLE is not None and tok.type == FSTRING_MIDDLE
        ):
            yield tok.start[0], tok.string


def password_examples(path: str, text: str) -> list[str]:
    """Return ``path:line`` for each password example in ``text`` that shows a real value.

    Args:
        path: The file name to report.
        text: The Python source to scan.

    Returns:
        One ``path:line`` entry per password option or argument whose value is not a
        placeholder, in source order.
    """
    found = []
    for first_line, string in _strings(text):
        for m in PASSWORD_VALUE.finditer(string):
            if not PLACEHOLDER.fullmatch(m.group('value')):
                found.append(f'{path}:{first_line + string.count(chr(10), 0, m.start())}')
    return found


def _tracked_sources() -> list[Path]:
    """Return every tracked Python file under ``src/``."""
    out = subprocess.run(
        ['git', 'ls-files', '--', 'src/*.py'], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [REPO / name for name in out.split()]


def test_scan_reports_a_password_in_a_usage_example() -> None:
    value = 'x' * 8  # assembled at run time, so this file holds no password-looking literal
    source = (
        f'EPILOG = """\n  tool --user admin --password {value}\n"""\n'
        f"def f():\n    '''Example: Client(password='{value}')'''\n"
        f'HELP = \'run tool --password="{value}"\'\n'
    )
    assert password_examples('demo.py', source) == ['demo.py:2', 'demo.py:5', 'demo.py:6']


def test_scan_allows_placeholders_and_ignores_code() -> None:
    source = (
        'EPILOG = "tool --password \'<password>\' or --password $UNIFI_PASSWORD"\n'
        'DOC = \'Client(password=SecretStr("<password>")) or password={password}\'\n'
        'client = Client(password=password)\n'
    )
    assert password_examples('demo.py', source) == []


def test_no_usage_example_in_src_shows_a_password() -> None:
    sources = _tracked_sources()
    assert len(sources) > 100, f'found only {len(sources)} tracked files under src/'
    found = [
        hit
        for path in sources
        for hit in password_examples(str(path.relative_to(REPO)), path.read_text(encoding='utf-8'))
    ]
    assert found == []
