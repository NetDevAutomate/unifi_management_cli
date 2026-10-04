"""Tests for the 5GHz channel plan applied by `scripts/apply_ap_channel_plan.py`.

The script is an operator tool that mutates live radio configuration, so the
plan data itself is the thing worth testing: a self-colliding plan silently
produces the contention the script exists to remove.

Found by review on 2026-08-27: the plan assigned one AP primary 157 at 40MHz and
another primary 161 at 40MHz. In UNII-3 the 40MHz bonded pairs are 149+153 and
157+161, so both primaries resolve to the SAME 157+161 block - two APs on
identical spectrum.

The site's own plan lives outside the repository, in its targets file
(`scripts/site_targets.py`, issue 046), and the script checks it with
`find_overlaps` at startup. The repository ships `site-targets.example.json`,
whose plan keeps the corrected channel layout under placeholder names, so the
layout is still tested here.

`scripts/` is not an importable package, so the modules are loaded by path.
"""

from __future__ import annotations

import importlib.util
import pytest
import sys
from pathlib import Path
from typing import Any


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'

pytestmark = pytest.mark.usefixtures('block_network')


def _load(name: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load ``scripts/<name>.py`` and register it, so the scripts' own imports find it."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def targets(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripts/site_targets.py``, registered for the script's import."""
    return _load('site_targets', monkeypatch)


@pytest.fixture
def mod(targets: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``scripts/apply_ap_channel_plan.py``."""
    return _load('apply_ap_channel_plan', monkeypatch)


@pytest.fixture
def example_plan(targets: Any) -> list[tuple[str, int, str]]:
    """The channel plan of the shipped example targets file."""
    return targets.channel_plan(targets.EXAMPLE)


# ─── The plan data must not collide with itself ──────────────────────────────


def test_example_plan_has_no_overlapping_blocks(mod: Any, example_plan: list[Any]) -> None:
    """Every AP in the shipped example plan occupies its own 40MHz block."""
    assert mod.find_overlaps(example_plan) == []


def test_find_overlaps_catches_the_157_161_collision(mod: Any) -> None:
    """The guard discriminates: hand it the shipped-and-fixed collision.

    Without this, `find_overlaps(plan) == []` would pass just as well
    against a guard that never returns anything.
    """
    colliding = [('AP-1', 157, '40'), ('AP-2', 161, '40')]

    assert mod.find_overlaps(colliding) == [('AP-1', 'AP-2', (157, 161))]


def test_occupied_channels_bonds_40mhz_pairs(mod: Any) -> None:
    """A 40MHz primary claims its whole bonded pair, not just itself."""
    assert mod.occupied_channels(157, '40') == (157, 161)
    assert mod.occupied_channels(161, '40') == (157, 161)
    assert mod.occupied_channels(149, '40') == (149, 153)
    # 20MHz claims only itself, so 157 and 161 stop colliding at that width.
    assert mod.occupied_channels(157, '20') == (157,)


def test_plan_widths_are_strings(example_plan: list[Any]) -> None:
    """`ht` must be a string.

    The controller stores widths as strings ('80', '40'); an int is accepted by
    the API and then ignored, which is the silent-no-op failure mode
    `_coerce_radio_value` documents. The plan feeds `ht` straight through, so
    the loader rejects an int width (see tests/test_site_targets.py).
    """
    assert example_plan
    assert [w for _, _, w in example_plan if not isinstance(w, str)] == []
