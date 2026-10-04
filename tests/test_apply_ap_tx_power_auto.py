"""Tests for the TX-power release performed by `scripts/apply_ap_tx_power_auto.py`.

The case the script exists for is subtle: an AP reports
`tx_power_mode == 'auto'` while a manual `tx_power` of 6 dBm still pins it low.
Setting the mode is therefore a no-op, and the override has to be removed. These
tests pin both halves - the detection heuristic, and the fact that the emitted
change both sets the mode AND asks for the override to be deleted.

`scripts/` is not an importable package, so the module is loaded by path.
"""

from __future__ import annotations

import pytest
from tests.script_modules import load_script
from typing import Any


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripts/apply_ap_tx_power_auto.py``."""
    return load_script('apply_ap_tx_power_auto', monkeypatch)


# ─── Detection ────────────────────────────────────────────────────────────────


def test_needs_update_flags_a_manual_override_hiding_under_auto_mode(mod: Any) -> None:
    """The pathological case: mode already reads 'auto' but power is pinned."""
    assert mod.needs_update({'radio': 'na', 'tx_power_mode': 'auto', 'tx_power': 6}) is True


def test_needs_update_ignores_a_genuinely_automatic_radio(mod: Any) -> None:
    """No manual override and a sane mode means nothing to do."""
    assert mod.needs_update({'radio': 'na', 'tx_power_mode': 'auto'}) is False
    # At the threshold the radio is acceptable, so it is left alone.
    threshold = mod.MIN_ACCEPTABLE_DBM
    radio = {'radio': 'na', 'tx_power_mode': 'auto', 'tx_power': threshold}
    assert mod.needs_update(radio) is False


def test_needs_update_flags_low_and_medium_modes(mod: Any) -> None:
    """A named low/medium mode counts even with no numeric override."""
    assert mod.needs_update({'radio': 'na', 'tx_power_mode': 'low'}) is True
    assert mod.needs_update({'radio': 'na', 'tx_power_mode': 'medium'}) is True
    assert mod.needs_update({'radio': 'na', 'tx_power_mode': 'high'}) is False


# ─── The emitted change ───────────────────────────────────────────────────────


def test_change_for_sets_auto_and_removes_the_override(mod: Any) -> None:
    """Setting the mode alone would be a no-op, so the change must do both."""
    change = mod.change_for({'_id': 'abc123', 'name': 'Charlie2 U6-Pro'})

    assert change['device_id'] == 'abc123'
    assert change['radio'] == 'na'
    assert change['tx_power_mode'] == 'auto'
    assert change['remove_fields'] == ['tx_power'], (
        'the manual override must be deleted, not set to null'
    )
