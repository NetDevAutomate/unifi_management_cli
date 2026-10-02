"""Tests for the shared secret stripper used by every diagnostic output."""

import json
import pytest
from unifi_mapper.core.utils.redact import REDACTED, is_secret_key, redact_text, strip_secrets


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
        f'{{"token": "{FAKE}"}}',
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
