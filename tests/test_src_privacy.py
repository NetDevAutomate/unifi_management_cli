"""Issue 046 item 5: the source tree's example addresses are documentation addresses.

Docstrings, help text and run-time hints under ``src/`` carried a site's own private
addresses. They now use the RFC 5737 documentation ranges, and this guard keeps it so: a
private (RFC 1918, link-local or CGNAT) IPv4 literal anywhere under ``src/`` fails. Range
checks in the code name their networks in words, not as address literals.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)')
# A dotted quad after one of these words is a software version (the Network API is 10.x), not
# an address: "API (10.1.2.3)", "Controller 10.0.1.5", "schema v10.2.0.1".
VERSION_CONTEXT = re.compile(r'(?i)(?:\bv|version|api|controller|schema|firmware)\W{0,3}$')
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(n)
    for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '100.64.0.0/10')
)


def _is_private(text: str) -> bool:
    try:
        address = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        return False
    return any(address in net for net in PRIVATE_NETWORKS)


def private_address_lines(path: str, text: str) -> list[str]:
    """Return ``path:line`` for every line holding a private IPv4 literal."""
    found: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in IPV4.finditer(line):
            if _is_private(m.group(0)) and not VERSION_CONTEXT.search(line[: m.start()]):
                found.append(f'{path}:{n}')
                break
    return found


def test_detector_sees_a_private_literal_and_ignores_documentation_ranges() -> None:
    text = 'a 192.0.2.1 b\nc 10.0.0.1 d\ne 169.254.1.1 f\ng 203.0.113.9 h\n'
    assert private_address_lines('x.py', text) == ['x.py:2', 'x.py:3']


def test_detector_ignores_software_versions() -> None:
    text = 'the Network API (10.1.2.3) and Controller 10.0.1.5; schema v10.2.0.1\n10.0.0.9\n'
    assert private_address_lines('x.py', text) == ['x.py:2']


def test_src_holds_no_private_address_literal() -> None:
    tracked = subprocess.run(
        ['git', 'ls-files', 'src'], capture_output=True, text=True, check=True, cwd=REPO
    ).stdout.split()
    assert len(tracked) > 100, 'has the source tree moved?'
    problems: list[str] = []
    for path in tracked:
        try:
            text = (REPO / path).read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        problems += private_address_lines(path, text)
    assert problems == []
