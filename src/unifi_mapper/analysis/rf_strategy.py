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
