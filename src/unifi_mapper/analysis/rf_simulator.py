"""What-if simulation for RF strategy recommendations.

Thin wrapper over :mod:`rf_strategy` — same scorecard, same data layer,
but the user picks a specific AP/band and mode/width and the simulator
reports what WOULD happen if that change were applied, plus warnings
when the request diverges from the scorecard's preference.

Design reference: ``docs/plans/2026-05-04-phase-d-rf-strategy-design.md``
(D1 — γ-first simulation pattern).

Unlike :func:`rf_strategy.generate_plan`, the simulator does not produce
a full plan — it produces a single focused :class:`SimulationResult`
for one AP/band pair. That keeps the mental model simple: one question,
one answer, one set of warnings to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from unifi_mapper.analysis import rf_strategy as _rfs
from unifi_mapper.analysis.rf_strategy import (
    APRecommendation,
    Band,
    Mode,
)
from unifi_mapper.analysis.roaming_analysis import DEFAULT_ROAMING_PATH
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


@dataclass(frozen=True)
class SimulationResult:
    """Outcome of a single what-if simulation.

    Attributes:
        ap_name: Name of the AP the simulation applied to.
        band: Band that was simulated (2.4 or 5 GHz).
        scenario: Human-readable description of the question asked, e.g.
            "force HARD_DISABLE on Kitchen 2.4 GHz" or "set Kitchen 5 GHz
            width to 80 MHz".
        recommendation: Fully-populated :class:`APRecommendation` for the
            simulated scenario — including displaced-client impacts so
            the operator can see the consequences before committing.
        warning_notes: Advisory strings. Empty when the simulation
            matches the scorecard's preferred outcome. Populated when
            the user's choice diverges from the scorecard (e.g. forcing
            HARD_DISABLE against YELLOW confidence).
    """

    ap_name: str
    band: Band
    scenario: str
    recommendation: APRecommendation
    warning_notes: tuple[str, ...]


def _find_uap(
    ap_name: str,
    uaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Locate a UAP by name. Case-insensitive partial match on name field.

    Raises:
        ToolError(DEVICE_NOT_FOUND) if no UAP matches.
    """
    needle = ap_name.lower()
    for ap in uaps:
        name = (ap.get("name") or "").lower()
        if name == needle or needle in name:
            return ap
    known_names = sorted((ap.get("name") or ap.get("mac", "")) for ap in uaps)
    raise ToolError(
        message=(
            f"No UAP matches name '{ap_name}'. Known APs: "
            + ", ".join(known_names) if known_names else "no UAPs registered."
        ),
        error_code=ErrorCodes.DEVICE_NOT_FOUND,
        suggestion="Check the AP name spelling; use the CLI 'inventory list --filter uap' to see all UAPs.",
    )


def _build_override_warnings(
    scorecard_recommendation: APRecommendation,
    user_override: APRecommendation,
) -> tuple[str, ...]:
    """Flag divergences between the scorecard's choice and the user's override.

    Returns an empty tuple when the user's override matches the scorecard's
    preferred outcome — silence is agreement.
    """
    warnings: list[str] = []

    if scorecard_recommendation.mode != user_override.mode:
        sc_mode = scorecard_recommendation.mode.value.upper()
        user_mode = user_override.mode.value.upper()
        warnings.append(
            f"forcing {user_mode} against {scorecard_recommendation.confidence.value.upper()} "
            f"confidence (coverage score {scorecard_recommendation.coverage_score:.2f}); "
            f"scorecard's default is {sc_mode}"
        )

    if scorecard_recommendation.recommended_width != user_override.recommended_width:
        warnings.append(
            f"width override: scorecard preferred {scorecard_recommendation.recommended_width} MHz, "
            f"user requested {user_override.recommended_width} MHz "
            f"(narrower-tiebreaker / DFS / crowd may favour the scorecard choice)"
        )

    return tuple(warnings)


async def simulate_disable(
    ap_name: str,
    band: Band,
    mode_override: Mode | None = None,
    history_path: str = DEFAULT_ROAMING_PATH,
    min_history_hours: float = _rfs.MIN_HISTORY_HOURS,
) -> SimulationResult:
    """Simulate disabling (or softening) a band on a specific AP.

    Args:
        ap_name: AP to simulate on (case-insensitive partial match).
        band: 2.4 GHz or 5 GHz.
        mode_override: Force a specific :class:`Mode`. ``None`` (default)
            lets the scorecard pick.
        history_path: Path to the roaming history file.
        min_history_hours: Reject if history is too short (same gate as
            :func:`generate_plan`; raises ``ToolError(CONFIG_INVALID)``).

    Raises:
        ToolError(CONFIG_INVALID): History file below ``min_history_hours``.
        ToolError(DEVICE_NOT_FOUND): ``ap_name`` doesn't match any UAP.
    """
    _ = (ap_name, band, mode_override, history_path, min_history_hours)
    raise NotImplementedError("simulate_disable to be implemented in step 4")


async def simulate_width_change(
    ap_name: str,
    band: Band,
    width_mhz: Literal[20, 40, 80],
    history_path: str = DEFAULT_ROAMING_PATH,
    min_history_hours: float = _rfs.MIN_HISTORY_HOURS,
) -> SimulationResult:
    """Simulate setting a specific channel width on an AP/band.

    2.4 GHz is hard-locked at 20 MHz (Q2 design decision): any other width
    raises ``ToolError(CONFIG_INVALID)`` referencing the design doc. Users
    who want to experiment with 40 MHz 2.4 GHz should read
    ``docs/plans/2026-05-04-phase-d-rf-strategy-design.md`` for the
    rationale (airtime waste + adjacent-channel interference + modern
    deployments treat it as a footgun).

    For 5 GHz, runs the full width-scoring engine for the requested width
    and reports it as the recommendation, with a warning note when the
    scorecard would have chosen differently.
    """
    _ = (ap_name, band, width_mhz, history_path, min_history_hours)
    raise NotImplementedError("simulate_width_change to be implemented in step 5")
