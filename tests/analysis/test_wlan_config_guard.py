"""Tests for safe WLAN writes with guard-field verification.

Motivated by the 2026-08-03 incident. Updating two `minrate_*` fields on a 5 GHz WLAN was
done by fetching the WLAN object, mutating it and PUTting the whole object back. Controller
10.5.67 responded by running schema migration on the echoed object and silently changed four
fields nobody asked for:

    wlan_bands:      ['5g'] -> ['5g', '6g']
    wpa3_support:    False  -> True
    wpa3_transition: False  -> True
    pmf_mode:        'disabled' -> 'optional'

6 GHz mandates WPA3, so adding the band dragged WPA3 transition mode in with it, which broke
association for the existing WPA2 clients. Roughly nine devices fell off the 5 GHz SSID onto
the 2.4 GHz IoT SSID. The 2.4-only WLAN was untouched because it has no 6 GHz band to add.

Two rules follow, both enforced here:
  * send a MINIMAL patch, never the whole object;
  * after writing, assert the security-relevant fields did not move.
"""

from __future__ import annotations

from unifi_mapper.analysis.wlan_config import (
    WLAN_GUARD_FIELDS,
    check_minrate_gate,
    verify_wlan_patch,
)


def _wlan(**over) -> dict:
    base = {
        '_id': 'w1',
        'name': 'Unifi-5G',
        'enabled': True,
        'wlan_bands': ['5g'],
        'wpa_mode': 'wpa2',
        'wpa_enc': 'ccmp',
        'wpa3_support': False,
        'wpa3_transition': False,
        'pmf_mode': 'disabled',
        'x_passphrase': 'secret-pass',
        'minrate_setting_preference': 'auto',
        'minrate_na_enabled': False,
        'minrate_na_data_rate_kbps': 6000,
        'bc_filter_enabled': False,
    }
    base.update(over)
    return base


# ─── Guard-field drift detection ─────────────────────────────────────────────


def test_guard_fields_cover_the_fields_that_actually_drifted() -> None:
    for field in ('wpa3_support', 'wpa3_transition', 'pmf_mode', 'wlan_bands'):
        assert field in WLAN_GUARD_FIELDS


def test_passphrase_is_guarded() -> None:
    """A round-tripped or masked passphrase would break auth for every client."""
    assert 'x_passphrase' in WLAN_GUARD_FIELDS


def test_detects_the_wpa3_migration_drift() -> None:
    """Replay of the incident: the patch applied, but four guard fields moved."""
    before = _wlan()
    after = _wlan(
        minrate_setting_preference='manual',
        minrate_na_enabled=True,
        wlan_bands=['5g', '6g'],
        wpa3_support=True,
        wpa3_transition=True,
        pmf_mode='optional',
    )
    patch = {'minrate_setting_preference': 'manual', 'minrate_na_enabled': True}

    result = verify_wlan_patch(before, after, patch)

    assert result['ok'] is False
    assert set(result['drifted']) == {
        'wlan_bands',
        'wpa3_support',
        'wpa3_transition',
        'pmf_mode',
    }
    assert result['drifted']['wlan_bands'] == (['5g'], ['5g', '6g'])


def test_clean_partial_patch_passes() -> None:
    before = _wlan()
    after = _wlan(minrate_setting_preference='manual', bc_filter_enabled=True)
    patch = {'minrate_setting_preference': 'manual', 'bc_filter_enabled': True}

    result = verify_wlan_patch(before, after, patch)

    assert result['ok'] is True
    assert result['drifted'] == {}
    assert result['not_applied'] == {}


def test_silently_reverted_field_is_reported() -> None:
    """The controller recomputes minrate when the preference gate is left on 'auto'."""
    before = _wlan()
    after = _wlan()  # nothing changed — write was swallowed
    patch = {'minrate_na_data_rate_kbps': 12000}

    result = verify_wlan_patch(before, after, patch)

    assert result['ok'] is False
    assert result['not_applied'] == {'minrate_na_data_rate_kbps': (12000, 6000)}


def test_drift_and_revert_are_reported_independently() -> None:
    before = _wlan()
    after = _wlan(wpa3_support=True)
    patch = {'bc_filter_enabled': True}

    result = verify_wlan_patch(before, after, patch)

    assert 'wpa3_support' in result['drifted']
    assert 'bc_filter_enabled' in result['not_applied']


def test_extra_guard_fields_can_be_supplied() -> None:
    before = _wlan(hide_ssid=False)
    after = _wlan(hide_ssid=True)

    result = verify_wlan_patch(before, after, {}, guard_fields=('hide_ssid',))

    assert result['ok'] is False
    assert result['drifted']['hide_ssid'] == (False, True)


# ─── minrate preference gate ─────────────────────────────────────────────────


def test_minrate_gate_warns_when_rate_set_without_manual_preference() -> None:
    """Writing a rate while the preference is 'auto' is silently recomputed away."""
    warnings = check_minrate_gate({'minrate_ng_data_rate_kbps': 6000})

    assert warnings
    assert any('minrate_setting_preference' in w for w in warnings)


def test_minrate_gate_quiet_when_preference_included() -> None:
    warnings = check_minrate_gate(
        {
            'minrate_setting_preference': 'manual',
            'minrate_ng_data_rate_kbps': 6000,
        }
    )

    assert warnings == []


def test_minrate_gate_quiet_for_unrelated_patch() -> None:
    assert check_minrate_gate({'bc_filter_enabled': True}) == []


def test_minrate_gate_flags_auto_preference_explicitly_set() -> None:
    warnings = check_minrate_gate(
        {
            'minrate_setting_preference': 'auto',
            'minrate_na_data_rate_kbps': 12000,
        }
    )

    assert warnings
