"""RF strategy scorecard engine for UniFi networks.

Pure-analysis module: computes per-AP RF recommendations (band disable,
channel width, channel, power) from controller data + roaming history.
No controller writes — see ``rf_applier.py`` for apply-side logic.

Design reference: ``docs/plans/2026-05-04-phase-d-rf-strategy-design.md``

Task T4 adds the scaffolding only: constants, enums, and frozen dataclasses.
The computation (scorecard, mode selection, plan generation) lands in
T5–T7 and will import from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


# === Constants (locked design decisions) ===
#
# Changes to any value in this block require a matching update to
# docs/plans/2026-05-04-phase-d-rf-strategy-design.md and, if the
# plan-json schema changes, a bump to PLAN_SCHEMA_VERSION below.

MIN_HISTORY_HOURS = 48.0             # Q1: refuse recommendations below this
WIDTH_24GHZ_FORCED = 20              # Q2: footgun — 2.4 GHz locked at 20 MHz
MAC_OVERHEAD_FACTOR = 0.55           # D3: WiFi PHY-to-goodput ratio
DFS_PENALTY_FACTOR = 0.80            # D3: conservative DFS constant for v1
WIDTH_TIEBREAKER_MARGIN = 0.10       # D3: prefer narrower within 10%
NEIGHBOUR_PENALTY_CAP = 35           # reused from channel_optimiser.py

# D2 scorecard weights — must sum to 1.0 (enforced by test_constants_match_design_doc)
COVERAGE_WEIGHT_ROAM_HISTORY = 0.5
COVERAGE_WEIGHT_AP_OVERLAP = 0.3
COVERAGE_WEIGHT_RSSI_MARGIN = 0.2

CONFIDENCE_GREEN_THRESHOLD = 0.7
CONFIDENCE_YELLOW_THRESHOLD = 0.4
# Below YELLOW threshold = RED (no recommendation).

# D4 mode-specific defaults
SOFT_MIN_RSSI_DBM = -72              # SOFT mode: min_rssi only
HYBRID_MIN_RSSI_DBM = -67            # HYBRID mode: min_rssi
HYBRID_TX_POWER_DBM = 6              # HYBRID mode: tx_power

# D5 rolling-apply defaults
DEFAULT_SETTLE_DELAY_SECONDS = 30
DEFAULT_SURVEY_DELAY_SECONDS = 300   # 5 min post-change survey
MAX_APS_PER_APPLY_DIVISOR = 2        # sanity limit = half of floor-AP count

# Q4: plan-JSON schema version. Applier refuses unknown versions with a
# clear error. Bump only on breaking plan-schema changes.
PLAN_SCHEMA_VERSION = "1.0"


# === Enums ===


class Confidence(StrEnum):
    """Scorecard confidence band.

    GREEN above ``CONFIDENCE_GREEN_THRESHOLD``, YELLOW between GREEN and
    ``CONFIDENCE_YELLOW_THRESHOLD``, RED below YELLOW (no recommendation
    emitted).
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class Mode(StrEnum):
    """Recommended enforcement mode for a disable suggestion.

    - ``HARD_DISABLE``: turn the radio/band off at the controller.
    - ``SOFT``: leave the radio up but set ``min_rssi`` only.
    - ``HYBRID``: ``min_rssi`` + ``tx_power`` reduction (GREEN with hesitation).
    - ``NONE``: no change — either RED scorecard or already optimal.
    """

    HARD_DISABLE = "hard"
    SOFT = "soft"
    HYBRID = "hybrid"
    NONE = "none"


class Band(StrEnum):
    """Radio band targeted by a recommendation."""

    TWO_FOUR = "2.4ghz"
    FIVE = "5ghz"


class Risk(StrEnum):
    """Per-client displacement risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# === Dataclasses ===
#
# All frozen: safe to pass across module boundaries, hashable for caching,
# and prevents accidental mutation of plan state between analyse/simulate/apply.


@dataclass(frozen=True)
class ClientImpact:
    """Per-client predicted impact of a disable recommendation."""

    mac: str
    name: str                          # display name (hostname or MAC)
    known_other_aps: tuple[str, ...]   # AP names this client has associated to (from roaming history)
    current_rssi: int                  # dBm, from current stat/sta
    predicted_impact: str              # human-readable: "reassociate to 5GHz (same AP)", "roam to Office", etc.
    risk: Risk


@dataclass(frozen=True)
class APRecommendation:
    """Per-AP, per-band recommendation. One instance per AP-band combination."""

    ap_name: str
    ap_mac: str
    band: Band
    mode: Mode
    confidence: Confidence
    current_width: int                 # 20 | 40 | 80
    recommended_width: int
    current_channel: int
    recommended_channel: int
    current_tx_power: int              # dBm
    recommended_tx_power: int
    rationale: tuple[str, ...]         # human-readable reasons rendered in the preview
    displaced_clients: tuple[ClientImpact, ...]
    coverage_score: float              # raw 0.0-1.0 score (for debugging, JSON export)


@dataclass(frozen=True)
class PlanSummary:
    """Aggregate counts for the plan header."""

    total_aps: int
    recommendations_count: int         # APs with at least one non-NONE mode
    green_count: int
    yellow_count: int
    red_count: int
    hard_disable_count: int
    soft_count: int
    hybrid_count: int


@dataclass(frozen=True)
class RFStrategyPlan:
    """Top-level plan artefact. Serialises to plan JSON."""

    schema_version: str                # Q4: always "1.0" for this release
    generated_at: str                  # ISO timestamp
    tool_version: str                  # from unifi_mapper.__version__
    site: str
    history_hours_available: float     # from roaming_analysis.history_hours_available
    recommendations: tuple[APRecommendation, ...]
    summary: PlanSummary


# === Scorecard (Phase D T5) ===
#
# Three proxy scores combined by the weights above. Each returns 0.0-1.0,
# where 1.0 means "disabling 2.4 GHz here is low-risk" and 0.0 means "high risk".


# Thresholds for the two continuous scores, kept local to this section for
# readability — the scoring semantics belong with the score functions, not
# in the module-top constants table (which is for policy-level locks).
_AP_OVERLAP_STRONG_DBM = -60      # >= this → full score
_AP_OVERLAP_WEAK_DBM = -75        # <= this → zero score
_RSSI_MARGIN_SOLID_DBM = -55      # median >= this → full score
_RSSI_MARGIN_EDGE_DBM = -75       # median <= this → zero score


def _linear_score(value: float, low: float, high: float) -> float:
    """Clamp ``value`` to [low, high] then project to [0.0, 1.0]."""
    if value >= high:
        return 1.0
    if value <= low:
        return 0.0
    return (value - low) / (high - low)


def compute_roam_history_score(
    ap_name: str,
    twofour_only_clients: dict[str, list[dict[str, Any]]],
    mobility_graph: dict[str, set[str]],
) -> float:
    """Fraction of 2.4-only clients on this AP that have roamed elsewhere.

    A 2.4-only client whose mobility graph spans >1 AP has proven roam
    capability — disabling 2.4 GHz here should cause it to pick up another
    AP rather than disconnect. Returns 1.0 when there are no 2.4-only
    clients to worry about on this AP.
    """
    clients = twofour_only_clients.get(ap_name, [])
    if not clients:
        return 1.0

    roamed = sum(
        1 for c in clients
        if len(mobility_graph.get(c.get("client_mac", ""), set())) > 1
    )
    return roamed / len(clients)


def compute_ap_overlap_score(
    ap_name: str,
    overlap_matrix: dict[tuple[str, str], int],
) -> float:
    """Strength of coverage by neighbouring APs.

    Uses the MAX RSSI at which any other AP hears this AP's BSSID. -60 dBm
    or better → 1.0 (strong coverage); -75 dBm or worse → 0.0 (island AP).
    Linear between.
    """
    rssi_values = [
        rssi for (observer, observed), rssi in overlap_matrix.items()
        if observed == ap_name
    ]
    if not rssi_values:
        return 0.0

    strongest = max(rssi_values)
    return _linear_score(
        float(strongest),
        low=float(_AP_OVERLAP_WEAK_DBM),
        high=float(_AP_OVERLAP_STRONG_DBM),
    )


def compute_rssi_margin_score(
    ap_name: str,
    current_clients: list[dict[str, Any]],
) -> float:
    """Median RSSI comfort of the 2.4 GHz clients on this AP.

    Only wireless clients associated to ``ap_name`` on a 2.4 GHz channel
    count. Returns 1.0 when there are no such clients (nothing to worry
    about) and 0.0 when clients exist but every ``rssi`` is missing
    (insufficient data, be cautious).
    """
    # Local import avoids a top-level cycle risk; roaming_analysis does not
    # import this module, but keeping the dep local is cheap and robust.
    from unifi_mapper.analysis.roaming_analysis import CHANNELS_24GHZ

    twofour_rssis: list[int] = []
    has_twofour_client = False

    for client in current_clients:
        if client.get("ap_name") != ap_name:
            continue
        channel = client.get("channel")
        if channel not in CHANNELS_24GHZ:
            continue
        has_twofour_client = True
        rssi = client.get("rssi")
        if rssi is not None:
            twofour_rssis.append(rssi)

    if not has_twofour_client:
        return 1.0
    if not twofour_rssis:
        return 0.0

    twofour_rssis.sort()
    mid = len(twofour_rssis) // 2
    if len(twofour_rssis) % 2 == 1:
        median = float(twofour_rssis[mid])
    else:
        median = (twofour_rssis[mid - 1] + twofour_rssis[mid]) / 2.0

    return _linear_score(
        median,
        low=float(_RSSI_MARGIN_EDGE_DBM),
        high=float(_RSSI_MARGIN_SOLID_DBM),
    )


def compute_coverage_score(
    ap_name: str,
    twofour_only_clients: dict[str, list[dict[str, Any]]],
    mobility_graph: dict[str, set[str]],
    overlap_matrix: dict[tuple[str, str], int],
    current_clients: list[dict[str, Any]],
) -> float:
    """Weighted sum of the three proxy scores. Returns 0.0-1.0."""
    return (
        COVERAGE_WEIGHT_ROAM_HISTORY
        * compute_roam_history_score(ap_name, twofour_only_clients, mobility_graph)
        + COVERAGE_WEIGHT_AP_OVERLAP
        * compute_ap_overlap_score(ap_name, overlap_matrix)
        + COVERAGE_WEIGHT_RSSI_MARGIN
        * compute_rssi_margin_score(ap_name, current_clients)
    )


def classify_confidence(score: float) -> Confidence:
    """Map a 0.0-1.0 coverage score to a GREEN/YELLOW/RED bucket.

    Boundaries are inclusive on the upper side: ``score == 0.7`` → GREEN,
    ``score == 0.4`` → YELLOW.
    """
    if score >= CONFIDENCE_GREEN_THRESHOLD:
        return Confidence.GREEN
    if score >= CONFIDENCE_YELLOW_THRESHOLD:
        return Confidence.YELLOW
    return Confidence.RED
