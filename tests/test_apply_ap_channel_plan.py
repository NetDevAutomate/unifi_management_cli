"""Tests for the 5GHz channel plan applied by `scripts/apply_ap_channel_plan.py`.

The script is an operator tool that mutates live radio configuration, so the
plan data itself is the thing worth testing: a self-colliding plan silently
produces the contention the script exists to remove.

Found by review on 2026-08-27: the plan assigned `Sierra3 U6-Pro` primary 157 at
40MHz and `U6 LR` primary 161 at 40MHz. In UNII-3 the 40MHz bonded pairs are
149+153 and 157+161, so both primaries resolve to the SAME 157+161 block - two
APs on identical spectrum.

`scripts/` is not an importable package, so the module is loaded by path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_ap_channel_plan.py'


def _load() -> Any:
    spec = importlib.util.spec_from_file_location('apply_ap_channel_plan', _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── The plan data must not collide with itself ───────────────────────────────


def test_channel_plan_has_no_overlapping_blocks() -> None:
    """Every AP in the shipped plan occupies its own 40MHz block."""
    mod = _load()

    assert mod.find_overlaps(mod.CHANNEL_PLAN) == []


def test_find_overlaps_catches_the_157_161_collision() -> None:
    """The guard discriminates: hand it the shipped-and-fixed collision.

    Without this, `find_overlaps(CHANNEL_PLAN) == []` would pass just as well
    against a guard that never returns anything.
    """
    mod = _load()

    colliding = [('Sierra3 U6-Pro', 157, '40'), ('U6 LR', 161, '40')]

    assert mod.find_overlaps(colliding) == [('Sierra3 U6-Pro', 'U6 LR', (157, 161))]


def test_occupied_channels_bonds_40mhz_pairs() -> None:
    """A 40MHz primary claims its whole bonded pair, not just itself."""
    mod = _load()

    assert mod.occupied_channels(157, '40') == (157, 161)
    assert mod.occupied_channels(161, '40') == (157, 161)
    assert mod.occupied_channels(149, '40') == (149, 153)
    # 20MHz claims only itself, so 157 and 161 stop colliding at that width.
    assert mod.occupied_channels(157, '20') == (157,)


def test_plan_widths_are_strings() -> None:
    """`ht` must be a string.

    The controller stores widths as strings ('80', '40'); an int is accepted by
    the API and then ignored, which is the silent-no-op failure mode
    `_coerce_radio_value` documents. The plan feeds `ht` straight through.
    """
    mod = _load()

    assert [w for _, _, w in mod.CHANNEL_PLAN if not isinstance(w, str)] == []
