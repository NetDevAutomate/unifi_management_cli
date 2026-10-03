"""House rule (plan §0.4): a fake credential in a test carries ``# pragma: allowlist secret``.

Code-review F9 found eleven dict entries that mapped a credential key (a console API token,
say) to a fake value without the pragma. This scan covers that shape: a quoted credential-named
key mapped to a string literal of four or more characters. Values that are deliberately not
secrets (the redaction tests check that ``'true'`` survives masking) are listed in
``NOT_SECRETS``.
"""

import re
from pathlib import Path


TESTS = Path(__file__).resolve().parent
PRAGMA = 'pragma: allowlist secret'
CREDENTIAL_ENTRY = re.compile(
    r"""['"][A-Z_]*(?:TOKEN|API_KEY|PASSWORD|SECRET)[A-Z_]*['"]\s*:\s*['"]([^'"]{4,})['"]"""
)
NOT_SECRETS = frozenset({'true', 'false'})


def _unmarked_entries() -> list[str]:
    hits = []
    for path in sorted(TESTS.rglob('*.py')):
        for n, line in enumerate(path.read_text().splitlines(), start=1):
            if PRAGMA in line:
                continue
            if any(m.group(1) not in NOT_SECRETS for m in CREDENTIAL_ENTRY.finditer(line)):
                hits.append(f'{path.relative_to(TESTS)}:{n}')
    return hits


def test_scan_finds_an_unmarked_fake_credential() -> None:
    line = "    env = {'UNIFI_CONSOLE_API_TOKEN': 'lab-token'}"  # pragma: allowlist secret
    assert [m.group(1) for m in CREDENTIAL_ENTRY.finditer(line)] == ['lab-token']
    assert not CREDENTIAL_ENTRY.search("{'FOO_TOKEN': 'abc'}")  # under four characters


def test_every_fake_credential_entry_in_tests_carries_the_pragma() -> None:
    assert _unmarked_entries() == []
