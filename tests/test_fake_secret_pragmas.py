"""House rule (plan §0.4): a fake credential in a test carries ``# pragma: allowlist secret``.

Code-review F9 found eleven dict entries that mapped a credential key (a console API token,
say) to a fake value without the pragma. This scan covers that shape: a quoted credential-named
key, in any case (``'UNIFI_CONSOLE_API_TOKEN'`` or ``'api_key'``), mapped to a string literal
of four or more characters. Values that are deliberately not secrets (the redaction tests
check that ``'true'`` survives masking) are listed in ``NOT_SECRETS``.
"""

import pytest
import re
from pathlib import Path


TESTS = Path(__file__).resolve().parent
PRAGMA = 'pragma: allowlist secret'
# A credential-named key: a keyword anywhere in the key, or a key ending in one of redact.py's
# suffix names (so the deliberate survivors community_id and syslog_key_id are not matched).
CREDENTIAL_ENTRY = re.compile(
    r"""['"](?:[A-Z_]*(?:TOKEN|API_KEY|PASSWORD|SECRET|PRESHARED)[A-Z_]*"""
    r"""|(?:[A-Z0-9_]*_)?(?:COMMUNITY|SYSLOG_KEY|LCM_TRACKER_SEED))"""
    r"""['"]\s*:\s*['"]([^'"]{4,})['"]""",
    re.IGNORECASE,
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
    lower = "    params = {'api_key': 'not-an-int'}"  # pragma: allowlist secret
    assert [m.group(1) for m in CREDENTIAL_ENTRY.finditer(lower)] == ['not-an-int']
    assert not CREDENTIAL_ENTRY.search("{'FOO_TOKEN': 'abc'}")  # under four characters


@pytest.mark.parametrize(
    'line',
    [
        "    snmp = {'community': 'example-community'}",  # pragma: allowlist secret
        "    device = {'syslog_key': 'fake-syslog-key'}",  # pragma: allowlist secret
        "    device = {'lcm_tracker_seed': 'fake-seed'}",  # pragma: allowlist secret
        "    peer = {'wireguard_preshared_key': 'fake-psk'}",  # pragma: allowlist secret
        "    peer = {'PRESHARED_KEY': 'fake-psk'}",  # pragma: allowlist secret
        "    snmp = {'snmp_community': 'fake-community'}",  # pragma: allowlist secret
        "    device = {'my_syslog_key': 'fake-syslog-key'}",  # pragma: allowlist secret
    ],
)
def test_scan_knows_the_suffix_secret_keys_and_preshared(line: str) -> None:
    assert len(CREDENTIAL_ENTRY.findall(line)) == 1


@pytest.mark.parametrize(
    'line', ["{'community_id': 'abcd'}", "{'syslog_key_id': 'abcd'}", "{'communityname': 'ab'}"]
)
def test_scan_matches_suffix_keys_only_at_the_end_of_the_key(line: str) -> None:
    assert not CREDENTIAL_ENTRY.search(line)


def test_every_fake_credential_entry_in_tests_carries_the_pragma() -> None:
    assert _unmarked_entries() == []
