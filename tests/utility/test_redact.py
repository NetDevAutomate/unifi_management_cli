"""Tests for the shared secret stripper used by every diagnostic output."""

import json
import pytest
from unifi_mapper.core.utils.redact import (
    REDACTED,
    is_secret_key,
    mask_secret_values,
    mask_secrets,
    mcp_secret_values,
    redact_text,
    redact_traceback,
    strip_secrets,
)


FAKE = 'FAKE-SECRET-MUST-NOT-APPEAR'  # pragma: allowlist secret

pytestmark = pytest.mark.usefixtures('block_network')


def test_x_prefixed_keys_are_removed_at_every_depth():
    payload = {
        'name': 'Test USW Flex XG',
        'x_authkey': FAKE,
        'port_table': [{'port_idx': 1, 'x_port_secret': FAKE, 'nested': {'x_inner': FAKE}}],
    }
    clean, removed = strip_secrets(payload, 'device')
    assert clean == {'name': 'Test USW Flex XG', 'port_table': [{'port_idx': 1, 'nested': {}}]}
    assert removed == [
        'device.x_authkey',
        'device.port_table[0].x_port_secret',
        'device.port_table[0].nested.x_inner',
    ]
    assert FAKE not in json.dumps(clean)


@pytest.mark.parametrize(
    'key',
    [
        'admin_password',
        'Radius_Secret',
        'csrf_token',
        'device_authkey',
        'wpa_psk',
        'x_passphrase',
        'PASSPHRASE',
        'api_key',
        'apiKey',
        'private-key',
        'X_SSH_KEYS',
    ],
)
def test_every_secret_keyword_is_stripped_case_insensitively(key):
    clean, removed = strip_secrets({key: FAKE, 'keep': 1})
    assert clean == {'keep': 1}
    assert removed == [key]


@pytest.mark.parametrize('key', ['key', 'name', 'id', '_id', 'monkey', 'max_rate', 'mac'])
def test_ordinary_keys_survive(key):
    assert not is_secret_key(key)
    clean, removed = strip_secrets({key: 'EVT_SW_Connected'})
    assert clean == {key: 'EVT_SW_Connected'}
    assert removed == []


def test_input_is_not_mutated_and_tuples_become_lists():
    payload = {'a': ({'x_k': FAKE}, 2)}
    clean, removed = strip_secrets(payload)
    assert payload == {'a': ({'x_k': FAKE}, 2)}
    assert clean == {'a': [{}, 2]}
    assert removed == ['a[0].x_k']


def test_values_are_not_scanned():
    """Only keys decide what is removed; a value mentioning 'password' stays."""
    clean, removed = strip_secrets({'msg': 'Admin changed password policy'})
    assert clean == {'msg': 'Admin changed password policy'}
    assert removed == []


@pytest.mark.parametrize(
    'text',
    [
        f"x_authkey='{FAKE}'",
        f'password={FAKE}',
        f'{{"token": "{FAKE}"}}',  # pragma: allowlist secret
        f'GET https://192.0.2.1/api?api_key={FAKE}&x=1',
        f'Authorization: Bearer {FAKE}',
    ],
)
def test_redact_text_masks_secret_values(text):
    out = redact_text(text)
    assert FAKE not in out
    assert REDACTED in out


def test_redact_text_leaves_ordinary_text_and_truncates():
    assert redact_text('HTTP 404 Not Found') == 'HTTP 404 Not Found'
    long = 'a' * 1000
    out = redact_text(long, limit=300)
    assert len(out) == 300
    assert out.endswith('…')


def test_redact_text_masks_a_secret_straddling_the_truncation_point():
    text = 'x' * 290 + f' token={FAKE}'
    out = redact_text(text, limit=300)
    assert len(out) <= 300
    assert 'FAKE' not in out


# ---------------------------------------------------------------------------
# T9 module cases: MCP masking (mask_secrets, mask_secret_values, mcp_secret_values)
# ---------------------------------------------------------------------------

KEY_TABLE = [
    'admin_password',
    'Radius_Secret',
    'csrf_token',
    'device_authkey',
    'wpa_psk',
    'x_passphrase',
    'PASSPHRASE',
    'api_key',
    'apiKey',
    'private-key',
    'X_SSH_KEYS',
    'key',
    'name',
    'id',
    '_id',
    'monkey',
    'max_rate',
    'mac',
    'x_iapp_key',
    'x_has_ssh_hostkey',
]


@pytest.mark.parametrize('key', KEY_TABLE)
def test_one_predicate_for_strip_and_mask(key):
    clean, removed = strip_secrets({key: FAKE})
    masked = mask_secrets({key: FAKE}, frozenset())
    assert is_secret_key(key) is bool(removed)
    assert (masked[key] == REDACTED) is is_secret_key(key)
    assert clean == ({} if removed else {key: FAKE})


def test_mask_secrets_masks_x_strings_in_dicts_and_lists_and_keeps_keys():
    payload = {
        'name': 'USW Flex XG',
        'x_authkey': FAKE,
        'x_has_ssh_hostkey': True,
        'wlans': [{'name': 'home', 'x_passphrase': FAKE, 'x_iapp_key': FAKE, 'vlan': 10}],
        'nested': {'deeper': [{'x_authkey': FAKE}]},
    }
    masked = mask_secrets(payload, frozenset())
    assert masked == {
        'name': 'USW Flex XG',
        'x_authkey': REDACTED,
        'x_has_ssh_hostkey': True,
        'wlans': [{'name': 'home', 'x_passphrase': REDACTED, 'x_iapp_key': REDACTED, 'vlan': 10}],
        'nested': {'deeper': [{'x_authkey': REDACTED}]},
    }
    assert payload['x_authkey'] == FAKE  # input not mutated
    assert FAKE not in json.dumps(masked)


def test_mask_secrets_leaves_non_string_values_under_secret_keys():
    masked = mask_secrets({'x_count': 3, 'token_ttl': None, 'x_flag': False}, frozenset())
    assert masked == {'x_count': 3, 'token_ttl': None, 'x_flag': False}


def test_mask_secrets_replaces_known_values_inside_other_strings():
    secret = 'FAKE-VALUE-12345678'  # pragma: allowlist secret
    masked = mask_secrets(
        {'msg': f'auth with {secret} failed', 'list': [secret, 'ok'], 'n': 1},
        frozenset({secret}),
    )
    assert masked == {'msg': f'auth with {REDACTED} failed', 'list': [REDACTED, 'ok'], 'n': 1}


def test_mask_secret_values_replaces_a_value_straddling_the_limit_before_truncating():
    secret = 'S' * 40
    text = 'x' * 480 + secret + 'y' * 100
    out = mask_secret_values(text, frozenset({secret}), limit=500)
    assert len(out) == 500 and out.endswith('…')
    assert 'SSSS' not in out


def test_mask_secret_values_defaults_to_500_and_applies_redact_text():
    out = mask_secret_values('token=abc12345 ' + 'z' * 900, frozenset())
    assert out.startswith(f'token={REDACTED} ')
    assert len(out) == 500


def test_mcp_secret_values_takes_credential_keys_only():
    env = {
        'UNIFI_CONSOLE_API_TOKEN': 'console-token-123',  # pragma: allowlist secret
        'UNIFI_NETWORK_API_KEY': 'network-key-456',  # pragma: allowlist secret
        'PROTECT_PASSWORD': 'protect-pass-789',  # pragma: allowlist secret
        # < 8 characters: never masked by value
        'UNIFI_PASSWORD': 'short',  # pragma: allowlist secret
        'UNIFI_URL': 'https://192.0.2.1',
        'FOO_TOKEN': 'true',
        'HOME': '/Users/someone',
    }
    assert mcp_secret_values(env) == frozenset(
        {'console-token-123', 'network-key-456', 'protect-pass-789'}  # pragma: allowlist secret
    )


def test_unrelated_true_survives_masking():
    secrets = mcp_secret_values({'FOO_TOKEN': 'true', 'UNIFI_API_TOKEN': 'abc'})
    assert secrets == frozenset()
    assert mask_secrets({'enabled': 'true'}, secrets) == {'enabled': 'true'}


# --- exact keys and pre-shared keys (the July port's config objects) ---------------------

SUFFIX_KEYS = [
    'community',
    'COMMUNITY',
    'Community',
    'snmp_community',
    'SNMP_Community',
    'syslog_key',
    'SYSLOG_KEY',
    'my_syslog_key',
    'lcm_tracker_seed',
    'device_lcm_tracker_seed',
]


@pytest.mark.parametrize('key', SUFFIX_KEYS)
def test_suffix_secret_keys_are_stripped_and_masked_in_any_case(key):
    clean, removed = strip_secrets({'snmp': {key: FAKE, 'enabled': True}}, 'setting[0]')
    assert clean == {'snmp': {'enabled': True}}
    assert removed == [f'setting[0].snmp.{key}']
    assert is_secret_key(key) is True
    assert mask_secrets({key: FAKE}, frozenset())[key] == REDACTED


@pytest.mark.parametrize('key', ['community_id', 'syslog_key_id', 'lcm_tracker_seed_version'])
def test_suffix_keys_must_end_the_key(key):
    assert is_secret_key(key) is False
    assert strip_secrets({key: 'value'}) == ({key: 'value'}, [])


@pytest.mark.parametrize(
    'text',
    [
        f"device {{'name': 'AP 1', 'syslog_key': '{FAKE}'}}",  # pragma: allowlist secret
        f'syslog_key={FAKE} name=AP-1',
        f'my_syslog_key: {FAKE}',
        f'LCM_TRACKER_SEED={FAKE}',
        f'{{\'lcm_tracker_seed\': "{FAKE}"}}',
    ],
)
def test_syslog_keys_and_the_lcm_seed_are_masked_in_free_text(text):
    assert FAKE not in redact_text(text)
    assert REDACTED in redact_text(text)


def test_a_key_that_only_starts_with_a_suffix_name_is_not_masked_in_free_text():
    text = 'syslog_key_id=5 lcm_tracker_seed_version=2'
    assert redact_text(text) == text


@pytest.mark.parametrize(
    'key', ['preshared_key', 'wireguard_preshared_key', 'PreShared', 'x_preshared']
)
def test_preshared_keys_are_stripped(key):
    assert is_secret_key(key) is True
    assert strip_secrets({key: FAKE}) == ({}, [key])


def test_preshared_values_are_masked_in_free_text():
    text = f'tunnel failed: preshared_key={FAKE} peer=203.0.113.9'
    assert FAKE not in redact_text(text)
    assert 'peer=203.0.113.9' in redact_text(text)


def test_community_is_an_ordinary_word_in_free_text():
    text = 'see community.ui.com for the release notes; community=public'
    assert redact_text(text) == text


def _caught(raiser) -> BaseException:
    try:
        raiser()
    except BaseException as error:  # noqa: BLE001 - the test wants whatever was raised
        return error
    raise AssertionError('expected an exception')


def test_redact_traceback_masks_causes_notes_and_groups():
    def _chained() -> None:
        try:
            raise KeyError(f'password={FAKE}')
        except KeyError as cause:
            error = RuntimeError(f'login failed: token={FAKE}')
            error.add_note(f'retry with api_key={FAKE}')
            raise error from cause

    def _grouped() -> None:
        raise ExceptionGroup('probes', [ValueError(f'secret={FAKE}'), OSError('timed out')])

    for raiser in (_chained, _grouped):
        text = redact_traceback(_caught(raiser))
        assert 'Traceback' in text and text.endswith('\n')
        assert FAKE not in text
    chained = redact_traceback(_caught(_chained))
    assert 'The above exception was the direct cause' in chained
    assert 'token=***redacted***' in chained and 'api_key=***redacted***' in chained
    assert 'secret=***redacted***' in redact_traceback(_caught(_grouped))
