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
from datetime import datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


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


# === Mode selection (Phase D T6 part A) ===
#
# Per D4 locked decision tree:
#   RED    → NONE (scorecard refused recommendation)
#   YELLOW → SOFT (min_rssi only — least disruptive)
#   GREEN  → HARD_DISABLE if no IoT on 2.4-only, else HYBRID
#
# The IoT classifier is intentionally conservative: a false negative (missed
# IoT) just lets a GREEN AP hard-disable instead of hybrid (acceptable), and
# a false positive just pushes a GREEN AP to hybrid (safer than hard). So
# the heuristic uses only OUI and hostname substrings; the radio_proto
# heuristic from the design doc is deferred — too many false positives on
# older but non-IoT clients.


# Short list of vendor substrings commonly seen in UniFi's `oui` field for
# IoT devices. Case-insensitive substring match.
IOT_OUI_PREFIXES: tuple[str, ...] = (
    "tuya",
    "shelly",
    "sonoff",
    "espressif",
    "philips",      # Hue
    "signify",      # Hue (renamed)
    "lifx",
    "nest",
    "google nest",
    "ring",
    "amazon technologies",   # Echo / Ring
    "tp-link",               # Kasa / Tapo
    "sonos",
    "roku",
    "belkin",                # Wemo
    "ezviz",
    "dahua",
    "hikvision",
)


# Short list of hostname substrings. Case-insensitive substring match; matches
# anywhere in the hostname (prefix/suffix/middle).
IOT_HOSTNAME_PATTERNS: tuple[str, ...] = (
    "shelly",
    "tuya",
    "hue",
    "esp_",
    "tasmota",
    "blink",
    "ring-",
    "nest-",
    "sonos",
    "echo-",
    "kasa",
    "tapo",
    "wemo",
    "lifx",
)


def classify_iot_client(client: dict[str, Any]) -> bool:
    """Best-effort IoT client classification.

    Returns True if the client's ``oui`` or ``hostname`` matches a known IoT
    vendor/keyword list (case-insensitive substring match). Returns False on
    missing fields or ambiguous data — conservative by design since this
    flag only toggles GREEN-confidence recommendations between
    ``HARD_DISABLE`` and ``HYBRID``.
    """
    oui = (client.get("oui") or "").lower()
    if any(prefix in oui for prefix in IOT_OUI_PREFIXES):
        return True

    hostname = (client.get("hostname") or "").lower()
    if any(pattern in hostname for pattern in IOT_HOSTNAME_PATTERNS):
        return True

    return False


def select_disable_mode(
    confidence: Confidence,
    two_four_only_iot_count: int,
) -> Mode:
    """Choose the disable mode per the D4 decision tree.

    Args:
        confidence: GREEN / YELLOW / RED scorecard classification.
        two_four_only_iot_count: Count of IoT clients on this AP that are
            currently 2.4-only (via :func:`classify_iot_client` applied to
            :func:`compute_twofour_only_clients` output).

    Returns:
        NONE when confidence is RED (no recommendation), SOFT when YELLOW
        (least disruptive — min_rssi only), HARD_DISABLE when GREEN with no
        IoT clients to worry about, and HYBRID when GREEN but IoT clients
        exist (combines tx_power reduction with min_rssi so IoT still
        reaches its controller over 2.4 but 5 GHz clients steer to 5).
    """
    if confidence == Confidence.RED:
        return Mode.NONE
    if confidence == Confidence.YELLOW:
        return Mode.SOFT
    # GREEN
    if two_four_only_iot_count == 0:
        return Mode.HARD_DISABLE
    return Mode.HYBRID


# === Channel width scoring (Phase D T6 part B) ===
#
# The D3 formula:
#   effective = MAC_OVERHEAD_FACTOR × phy_rate × (1 - worst_subchannel_occupied)
#             × (DFS_PENALTY_FACTOR if is_dfs else 1.0) × neighbour_crowd_factor
#
# Width recommendation picks the best effective throughput across {20, 40, 80}
# on 5 GHz (2.4 GHz locked at 20 per Q2), applying a 10% narrower-tiebreaker.


# WiFi 6 (802.11ax) PHY rate table.
#
# Keys: (width_mhz, max_mcs, nss). Values: nominal PHY rate in Mbps.
# Covers the MCS range UniFi devices commonly report for modern 5 GHz
# clients (MCS 7 / 9 / 11 at 1-2 spatial streams). Synthetic test values
# use MCS 11 SS 2 → 1200 / 600 / 300 at 80 / 40 / 20 MHz which matches the
# IEEE standard table exactly for 80 MHz and approximates for 40/20.
# For completeness, the 40/20 values are the standard WiFi-6 GI 0.8us
# figures rounded to clean integers. An unknown key returns 0.
_PHY_RATE_AX_TABLE: dict[tuple[int, int, int], int] = {
    # 80 MHz
    (80, 11, 2): 1200,
    (80, 11, 1): 600,
    (80, 9, 2): 960,
    (80, 9, 1): 480,
    (80, 7, 2): 600,
    (80, 7, 1): 300,
    # 40 MHz (roughly half the 80 MHz figures)
    (40, 11, 2): 600,
    (40, 11, 1): 300,
    (40, 9, 2): 480,
    (40, 9, 1): 240,
    (40, 7, 2): 300,
    (40, 7, 1): 150,
    # 20 MHz (roughly quarter the 80 MHz figures)
    (20, 11, 2): 300,
    (20, 11, 1): 150,
    (20, 9, 2): 240,
    (20, 9, 1): 120,
    (20, 7, 2): 150,
    (20, 7, 1): 75,
}


def compute_nominal_phy_rate(width_mhz: int, max_mcs: int, nss: int) -> int:
    """Nominal WiFi 6 PHY rate in Mbps for ``(width, mcs, nss)``.

    Returns 0 when the combination isn't in the lookup table — typically
    because ``max_mcs < 0``, ``nss < 1``, or the width isn't one of
    {20, 40, 80}. Callers treat 0 as "no recommendation possible".
    """
    if max_mcs < 0 or nss < 1:
        return 0
    return _PHY_RATE_AX_TABLE.get((width_mhz, max_mcs, nss), 0)


def cap_phy_rate_by_weakest_client(
    ap_name: str,
    band: Band,
    width_mhz: int,
    current_clients: list[dict[str, Any]],
) -> int:
    """Cap nominal PHY rate by the weakest client's achievable rate.

    Walks clients on this AP/band and returns the minimum of their
    per-width PHY rates (derived from their reported ``mcs`` + ``nss``).
    No wireless clients on this AP/band → returns the peak rate the AP's
    capability allows at this width (MCS 11 SS 2 assumed — modern AX AP).
    """
    _ = band  # reserved for per-band rate differences if tables are split later

    peak = compute_nominal_phy_rate(width_mhz=width_mhz, max_mcs=11, nss=2)

    matching_rates: list[int] = []
    for client in current_clients:
        if client.get("ap_name") != ap_name:
            continue
        mcs = client.get("mcs")
        nss = client.get("nss")
        if mcs is None or nss is None:
            continue
        rate = compute_nominal_phy_rate(width_mhz=width_mhz, max_mcs=mcs, nss=nss)
        if rate > 0:
            matching_rates.append(rate)

    if not matching_rates:
        return peak
    return min(matching_rates)


def compute_effective_throughput(
    width_mhz: int,
    nominal_phy_rate: int,
    worst_sub_channel_occupied_fraction: float,
    is_dfs: bool,
    neighbour_crowd_factor: float,
) -> float:
    """Apply the D3 formula for effective throughput (Mbps).

    - ``MAC_OVERHEAD_FACTOR`` (0.55) converts raw PHY to goodput.
    - ``worst_sub_channel_occupied_fraction`` ∈ [0, 1]: 0 = clean, 1 = saturated.
    - ``DFS_PENALTY_FACTOR`` (0.80) when ``is_dfs=True``.
    - ``neighbour_crowd_factor`` ∈ [0, 1]: 1 = no neighbour pressure, 0 = heavy.

    ``width_mhz`` is accepted for future per-width adjustments but not
    currently used (the width's effect is already baked into
    ``nominal_phy_rate``).
    """
    _ = width_mhz  # future use
    dfs_multiplier = DFS_PENALTY_FACTOR if is_dfs else 1.0
    return (
        MAC_OVERHEAD_FACTOR
        * nominal_phy_rate
        * (1.0 - worst_sub_channel_occupied_fraction)
        * dfs_multiplier
        * neighbour_crowd_factor
    )


def compute_width_recommendation(
    ap_name: str,
    band: Band,
    current_clients: list[dict[str, Any]],
    channel_scores: dict[int, dict[int, float]],
    neighbour_crowd: dict[int, float],
    is_channel_dfs: dict[int, bool],
) -> int:
    """Recommend channel width in MHz for this AP/band.

    - 2.4 GHz: always returns ``WIDTH_24GHZ_FORCED`` (20) per Q2 decision.
    - 5 GHz: evaluates widths {20, 40, 80} via
      :func:`compute_effective_throughput` and applies the
      narrower-tiebreaker (``WIDTH_TIEBREAKER_MARGIN`` = 10%): if
      ``effective(wider) < effective(narrower) × 1.10``, prefer narrower.

    Args:
        ap_name: AP to recommend for (used to filter clients and pick the
            channel the AP is currently on).
        band: :class:`Band.TWO_FOUR` or :class:`Band.FIVE`.
        current_clients: ``stat/sta`` payload list — used to cap the PHY
            rate by the weakest associated client per width.
        channel_scores: ``{width_mhz: {channel: worst_sub_channel_fraction}}``.
            Missing channels default to 0.0 (clean).
        neighbour_crowd: ``{width_mhz: crowd_factor_0_to_1}``. Missing
            widths default to 1.0 (no crowd).
        is_channel_dfs: ``{channel: bool}``. Missing channels default to False.

    Returns:
        Recommended width in MHz: 20, 40, or 80.
    """
    if band == Band.TWO_FOUR:
        return WIDTH_24GHZ_FORCED

    # Evaluate 5 GHz widths in ascending order so the tiebreaker walk is
    # straightforward: start with narrowest as the incumbent, compare each
    # wider candidate against it.
    candidates = sorted(w for w in (20, 40, 80) if w in channel_scores)
    if not candidates:
        return WIDTH_24GHZ_FORCED  # defensive; shouldn't hit in practice

    # Determine the channel this AP is currently on. Use the first client's
    # channel on this AP as a proxy; if no clients, fall back to the channel
    # with the lowest worst_sub_channel_fraction across candidates.
    ap_channel: int | None = None
    for client in current_clients:
        if client.get("ap_name") == ap_name and client.get("channel"):
            ap_channel = client["channel"]
            break
    if ap_channel is None:
        # Pick any channel present in the narrowest candidate's scores.
        first_width = candidates[0]
        if channel_scores[first_width]:
            ap_channel = next(iter(channel_scores[first_width]))
        else:
            return WIDTH_24GHZ_FORCED

    # Score each candidate width.
    def score(width: int) -> float:
        sub_frac = channel_scores.get(width, {}).get(ap_channel, 0.0)
        crowd = neighbour_crowd.get(width, 1.0)
        is_dfs = is_channel_dfs.get(ap_channel, False)
        phy_rate = cap_phy_rate_by_weakest_client(ap_name, band, width, current_clients)
        return compute_effective_throughput(
            width_mhz=width,
            nominal_phy_rate=phy_rate,
            worst_sub_channel_occupied_fraction=sub_frac,
            is_dfs=is_dfs,
            neighbour_crowd_factor=crowd,
        )

    best_width = candidates[0]
    best_eff = score(best_width)

    for wider in candidates[1:]:
        wider_eff = score(wider)
        # Prefer wider only if it's meaningfully better (more than
        # WIDTH_TIEBREAKER_MARGIN above the current best).
        if wider_eff >= best_eff * (1.0 + WIDTH_TIEBREAKER_MARGIN):
            best_width = wider
            best_eff = wider_eff
        elif wider_eff > best_eff:
            # Wider is higher but not by enough — leave best at narrower.
            pass
        # else: wider is lower than or equal to best → stay with best.

    return best_width


# === Plan generator + impact preview (Phase D T7) ===
#
# Top-level composition. Reads data from the controller, stitches T1–T6
# outputs, produces an RFStrategyPlan. No writes.


# Threshold for distinguishing "strong" vs "weak" inter-AP overlap when
# predicting post-disable roam behaviour. Matches the compute_ap_overlap_score
# "strong" cutoff (-60 dBm) to keep the two views consistent.
_IMPACT_STRONG_OVERLAP_DBM = -60


def _best_overlap_target(
    current_ap: str,
    candidate_aps: set[str],
    overlap_matrix: dict[tuple[str, str], int],
) -> tuple[str | None, int | None]:
    """Find the candidate AP that hears ``current_ap`` most strongly.

    Returns ``(ap_name, rssi)`` for the best overlap pair, or ``(None, None)``
    when no overlap is recorded between ``current_ap`` and any candidate.
    """
    best_name: str | None = None
    best_rssi: int | None = None
    for other in candidate_aps:
        if other == current_ap:
            continue
        rssi = overlap_matrix.get((other, current_ap))
        if rssi is None:
            continue
        if best_rssi is None or rssi > best_rssi:
            best_rssi = rssi
            best_name = other
    return best_name, best_rssi


def _build_client_impacts(
    ap_name: str,
    band: Band,
    mode: Mode,
    current_clients: list[dict[str, Any]],
    mobility_graph: dict[str, set[str]],
    overlap_matrix: dict[tuple[str, str], int],
) -> tuple[ClientImpact, ...]:
    """Predict per-client impact of a recommendation.

    Scope: wireless clients currently associated to ``ap_name`` on the given
    ``band`` (2.4 GHz channels for :class:`Band.TWO_FOUR`, 5 GHz otherwise).

    Impact logic:
    - ``HYBRID`` / ``SOFT`` modes keep the radio up, so every affected
      client is flagged as LOW risk with a "reassociate in-place" message.
    - ``HARD_DISABLE`` with ≥1 known other AP + strong overlap (RSSI >=
      ``_IMPACT_STRONG_OVERLAP_DBM``) → LOW, "likely roam to {target}".
    - ``HARD_DISABLE`` with ≥1 known other AP but weak / no overlap →
      MEDIUM, "possible roam to {target}".
    - ``HARD_DISABLE`` with no known other AP → HIGH, "⚠ DISCONNECT — no
      known coverage elsewhere".
    - ``NONE`` mode skipped entirely (no recommendation, no impact).
    """
    # Local import to avoid cycling with roaming_analysis at module load.
    from unifi_mapper.analysis.roaming_analysis import CHANNELS_24GHZ

    if mode == Mode.NONE:
        return ()

    impacts: list[ClientImpact] = []

    for client in current_clients:
        if client.get("ap_name") != ap_name:
            continue

        channel = client.get("channel")
        on_24ghz = channel in CHANNELS_24GHZ if channel is not None else False
        if band == Band.TWO_FOUR and not on_24ghz:
            continue
        if band == Band.FIVE and on_24ghz:
            continue

        mac = client.get("mac") or ""
        known_aps_set = mobility_graph.get(mac, set())
        other_aps = tuple(sorted(ap for ap in known_aps_set if ap != ap_name))
        rssi_value = client.get("rssi")
        rssi = int(rssi_value) if rssi_value is not None else 0
        name = client.get("name") or client.get("hostname") or mac

        if mode in (Mode.HYBRID, Mode.SOFT):
            predicted = "reassociate in-place, may roam if signal drops"
            risk = Risk.LOW
        else:
            # HARD_DISABLE — need actual coverage elsewhere.
            if not other_aps:
                predicted = "⚠ DISCONNECT — no known coverage elsewhere"
                risk = Risk.HIGH
            else:
                best_target, best_rssi = _best_overlap_target(
                    ap_name, known_aps_set, overlap_matrix,
                )
                if best_target is not None and best_rssi is not None and best_rssi >= _IMPACT_STRONG_OVERLAP_DBM:
                    predicted = f"likely roam to {best_target}"
                    risk = Risk.LOW
                else:
                    target_label = best_target or other_aps[0]
                    predicted = f"possible roam to {target_label}"
                    risk = Risk.MEDIUM

        impacts.append(ClientImpact(
            mac=mac,
            name=name,
            known_other_aps=other_aps,
            current_rssi=rssi,
            predicted_impact=predicted,
            risk=risk,
        ))

    return tuple(impacts)


def render_impact_preview(plan: RFStrategyPlan) -> str:
    """Render an :class:`RFStrategyPlan` as a plain-text preview.

    Format mirrors the D5 example: per-AP sections with header (name/band/
    mode/confidence), rationale bullets, width/channel/power delta lines,
    and a displaced-client block. Pure plain-ASCII for maximum terminal
    compatibility — ``rich``-based colouring is deferred to Phase 4 (CLI)
    where it can detect TTY capability.
    """
    # Skip early on empty plans with a clear signal to the operator.
    if not plan.recommendations:
        return (
            "No recommendations — network is optimal, or insufficient history "
            f"(have {plan.history_hours_available:.1f}h, need "
            f"{MIN_HISTORY_HOURS:.1f}h)."
        )

    lines: list[str] = []
    lines.append(
        f"RF Strategy Plan  (schema {plan.schema_version}, "
        f"tool {plan.tool_version}, site {plan.site}, "
        f"{plan.history_hours_available:.1f}h of history)"
    )
    summary = plan.summary
    lines.append(
        f"Summary: {summary.recommendations_count}/{summary.total_aps} APs — "
        f"GREEN={summary.green_count} YELLOW={summary.yellow_count} "
        f"RED={summary.red_count} | "
        f"hard={summary.hard_disable_count} soft={summary.soft_count} "
        f"hybrid={summary.hybrid_count}"
    )
    lines.append("")

    for rec in plan.recommendations:
        lines.append("=" * 72)
        lines.append(
            f"AP: {rec.ap_name} ({rec.ap_mac})  "
            f"Band: {rec.band.value}  "
            f"Mode: {rec.mode.value.upper()}  "
            f"Confidence: {rec.confidence.value.upper()} "
            f"(score {rec.coverage_score:.2f})"
        )

        # Rationale bullets
        if rec.rationale:
            lines.append("")
            lines.append("Rationale:")
            for reason in rec.rationale:
                lines.append(f"  - {reason}")

        # Width / channel / power delta table — show rows even when unchanged
        # so the operator sees the full picture, and mark deltas clearly.
        lines.append("")
        lines.append("Proposed changes:")
        lines.append(f"  Width:   {rec.current_width} MHz -> {rec.recommended_width} MHz"
                     f"{'  (unchanged)' if rec.current_width == rec.recommended_width else ''}")
        lines.append(f"  Channel: {rec.current_channel} -> {rec.recommended_channel}"
                     f"{'  (unchanged)' if rec.current_channel == rec.recommended_channel else ''}")
        lines.append(f"  Power:   {rec.current_tx_power} dBm -> {rec.recommended_tx_power} dBm"
                     f"{'  (unchanged)' if rec.current_tx_power == rec.recommended_tx_power else ''}")

        # Displaced-client block
        if rec.displaced_clients:
            lines.append("")
            lines.append(f"Displaced clients (to Disassociate if {rec.mode.value.upper()} applied):")
            for impact in rec.displaced_clients:
                other = ", ".join(impact.known_other_aps) if impact.known_other_aps else "(none)"
                lines.append(
                    f"  - {impact.name:<24} {impact.mac}  "
                    f"RSSI {impact.current_rssi:>4} dBm  "
                    f"risk={impact.risk.value.upper():<6}  "
                    f"other APs: {other}"
                )
                lines.append(f"      -> {impact.predicted_impact}")

        lines.append("")

    return "\n".join(lines)


@dataclass(frozen=True)
class _PlanInputs:
    """Bundle of inputs shared by :func:`generate_plan` and the simulator.

    All fields are snapshot data — gathered once, used for deterministic
    per-AP computation. Frozen to prevent accidental mutation while the
    plan (or a simulation) iterates across APs.
    """

    hours_available: float
    devices: list[dict[str, Any]]
    current_clients: list[dict[str, Any]]
    uaps: list[dict[str, Any]]
    twofour_only: dict[str, list[dict[str, Any]]]
    mobility_graph: dict[str, set[str]]
    overlap_matrix: dict[tuple[str, str], int]
    ap_mac_to_name: dict[str, str]


async def _collect_inputs(
    history_path: str,
    min_history_hours: float,
) -> _PlanInputs:
    """Gather all shared data needed by the scorecard, one controller pass.

    Performs the history gate first (raises :class:`ToolError` with
    ``CONFIG_INVALID`` on shortfall — the same error code the spec calls
    INSUFFICIENT_DATA; that enum member doesn't exist so we use the
    closest semantic fit), then fetches devices/clients/rogue_aps and
    computes the AP-to-AP overlap matrix.

    Split from :func:`generate_plan` so :mod:`rf_simulator` can reuse the
    same inputs without double-fetching.
    """
    # Local imports — the roaming_analysis module depends on our
    # CHANNELS_24GHZ, so keep the dep function-scoped.
    from unifi_mapper.analysis.neighbour_scan import (
        compute_ap_to_ap_overlap,
        get_our_ap_bssids,
    )
    from unifi_mapper.analysis.roaming_analysis import (
        build_mobility_graph,
        compute_twofour_only_clients,
        history_hours_available,
    )

    hours_available = history_hours_available(history_path)
    if hours_available < min_history_hours:
        shortfall = min_history_hours - hours_available
        raise ToolError(
            message=(
                f"Insufficient roaming history for recommendations: have "
                f"{hours_available:.1f}h, need {min_history_hours:.1f}h "
                f"(short by {shortfall:.1f}h)."
            ),
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion=(
                "Wait for more snapshots (baseline cadence: every 5 min) or "
                "pass --min-history-hours to override for experimentation."
            ),
        )

    twofour_only = compute_twofour_only_clients(history_path)
    mobility_graph = build_mobility_graph(history_path)

    async with UniFiClient() as client:
        devices = await client.get_devices()
        current_clients = await client.get_clients()
        rogue_entries = await client.get_rogue_aps()
        our_bssids = await get_our_ap_bssids(client)

    uaps = [d for d in devices if d.get("type") == "uap"]

    ap_mac_to_name: dict[str, str] = {}
    for d in uaps:
        mac = d.get("mac", "")
        name = d.get("name", mac)
        if mac:
            ap_mac_to_name[mac] = name
        for vap in d.get("vap_table", []) or []:
            bssid = vap.get("bssid")
            if bssid:
                ap_mac_to_name[bssid.lower()] = name

    overlap_matrix = compute_ap_to_ap_overlap(
        rogue_entries=rogue_entries,
        our_ap_bssids=our_bssids,
        ap_mac_to_name=ap_mac_to_name,
    )

    return _PlanInputs(
        hours_available=hours_available,
        devices=devices,
        current_clients=current_clients,
        uaps=uaps,
        twofour_only=twofour_only,
        mobility_graph=mobility_graph,
        overlap_matrix=overlap_matrix,
        ap_mac_to_name=ap_mac_to_name,
    )


async def generate_plan(
    site: str = "default",
    history_path: str = "reports/client-roaming-history.json",
    min_history_hours: float = MIN_HISTORY_HOURS,
) -> RFStrategyPlan:
    """Compose a full RF strategy plan from current controller state + history.

    Orchestrates T1–T6: history gate, data collection, per-AP scorecard,
    mode + width + channel + power selection, displaced-client prediction,
    and final ``RFStrategyPlan`` assembly. No controller writes.

    Args:
        site: UniFi site name (reserved for multi-site support; currently
            informational, stamped on the plan).
        history_path: Path to the roaming snapshot history file (written
            by :func:`snapshot_client_associations`).
        min_history_hours: Refuse to emit recommendations when the history
            file spans fewer hours than this. Default 48h (Q1 locked
            decision); override via CLI ``--min-history-hours`` for local
            experimentation.

    Raises:
        ToolError: with ``ErrorCodes.CONFIG_INVALID`` when history is
            insufficient. Message names the shortfall and suggests remedies.
    """
    inputs = await _collect_inputs(history_path, min_history_hours)
    hours_available = inputs.hours_available
    current_clients = inputs.current_clients
    uaps = inputs.uaps
    twofour_only = inputs.twofour_only
    mobility_graph = inputs.mobility_graph
    overlap_matrix = inputs.overlap_matrix

    # 5. Per-AP recommendations. One 2.4 GHz recommendation drives the
    # summary counts; the 5 GHz rec is width/channel/power only (Mode.NONE
    # for v1 per T7 spec).
    recommendations: list[APRecommendation] = []
    green = yellow = red = 0
    hard = soft = hybrid = 0

    for ap in uaps:
        ap_name = ap.get("name", ap.get("mac", ""))
        ap_mac = ap.get("mac", "")

        # Extract current radio config for both bands from radio_table.
        radios_by_band: dict[str, dict[str, Any]] = {}
        for radio in ap.get("radio_table", []) or []:
            band_code = radio.get("radio")  # UniFi: 'ng' = 2.4, 'na' = 5
            if band_code == "ng":
                radios_by_band["2.4"] = radio
            elif band_code == "na":
                radios_by_band["5"] = radio

        # 2.4 GHz recommendation — scorecard-driven, emits a mode.
        score = compute_coverage_score(
            ap_name,
            twofour_only,
            mobility_graph,
            overlap_matrix,
            current_clients,
        )
        confidence = classify_confidence(score)

        # Count IoT devices among this AP's 2.4-only clients (current
        # observations — we cross-reference the live stat/sta payload since
        # twofour_only only carries MAC/count/last_seen).
        twofour_only_macs = {c["client_mac"] for c in twofour_only.get(ap_name, [])}
        iot_count = sum(
            1 for c in current_clients
            if c.get("mac") in twofour_only_macs and classify_iot_client(c)
        )

        mode_24 = select_disable_mode(confidence, iot_count)

        radio_24 = radios_by_band.get("2.4", {})
        current_channel_24 = radio_24.get("channel", 0) or 0
        current_width_24 = radio_24.get("ht", WIDTH_24GHZ_FORCED) or WIDTH_24GHZ_FORCED
        current_power_24 = radio_24.get("tx_power", 0) or 0

        rationale_24: list[str] = [
            f"coverage score {score:.2f} → {confidence.value.upper()}",
        ]
        if mode_24 == Mode.NONE:
            rationale_24.append("insufficient safety margin to recommend a change")
        elif mode_24 == Mode.HARD_DISABLE:
            rationale_24.append("no IoT clients on 2.4-only — safe clean break")
        elif mode_24 == Mode.HYBRID:
            rationale_24.append(f"{iot_count} IoT client(s) on 2.4-only — hybrid keeps them reachable")
        elif mode_24 == Mode.SOFT:
            rationale_24.append("yellow confidence — min_rssi only, least disruptive")

        displaced_24 = _build_client_impacts(
            ap_name=ap_name,
            band=Band.TWO_FOUR,
            mode=mode_24,
            current_clients=current_clients,
            mobility_graph=mobility_graph,
            overlap_matrix=overlap_matrix,
        )

        recommendations.append(APRecommendation(
            ap_name=ap_name,
            ap_mac=ap_mac,
            band=Band.TWO_FOUR,
            mode=mode_24,
            confidence=confidence,
            current_width=int(current_width_24),
            recommended_width=WIDTH_24GHZ_FORCED,  # Q2: always 20 MHz
            current_channel=int(current_channel_24),
            recommended_channel=int(current_channel_24),  # channel tuning is T6-adjacent; v1 leaves 2.4 channel alone unless explicitly overridden
            current_tx_power=int(current_power_24),
            recommended_tx_power=HYBRID_TX_POWER_DBM if mode_24 == Mode.HYBRID else int(current_power_24),
            rationale=tuple(rationale_24),
            displaced_clients=displaced_24,
            coverage_score=score,
        ))

        # Tally summary — 2.4 GHz recommendations drive the counts.
        if confidence == Confidence.GREEN:
            green += 1
        elif confidence == Confidence.YELLOW:
            yellow += 1
        else:
            red += 1
        if mode_24 == Mode.HARD_DISABLE:
            hard += 1
        elif mode_24 == Mode.SOFT:
            soft += 1
        elif mode_24 == Mode.HYBRID:
            hybrid += 1

        # 5 GHz stub — width/channel/power-only, Mode.NONE for v1.
        radio_5 = radios_by_band.get("5", {})
        current_channel_5 = radio_5.get("channel", 36) or 36
        current_width_5 = radio_5.get("ht", 80) or 80
        current_power_5 = radio_5.get("tx_power", 0) or 0

        # Width recommendation needs channel_scores and neighbour_crowd inputs
        # we don't yet produce from real data — pass neutral defaults so the
        # recommendation is a no-op (current width stays). T9 will wire this
        # into the channel_optimiser output.
        recommendations.append(APRecommendation(
            ap_name=ap_name,
            ap_mac=ap_mac,
            band=Band.FIVE,
            mode=Mode.NONE,
            confidence=Confidence.GREEN,   # not scored for v1
            current_width=int(current_width_5),
            recommended_width=int(current_width_5),
            current_channel=int(current_channel_5),
            recommended_channel=int(current_channel_5),
            current_tx_power=int(current_power_5),
            recommended_tx_power=int(current_power_5),
            rationale=("5 GHz recommendations are T9-scope (CLI wiring)",),
            displaced_clients=(),
            coverage_score=0.0,
        ))

    recommendations_count = sum(1 for r in recommendations if r.band == Band.TWO_FOUR and r.mode != Mode.NONE)
    summary = PlanSummary(
        total_aps=len(uaps),
        recommendations_count=recommendations_count,
        green_count=green,
        yellow_count=yellow,
        red_count=red,
        hard_disable_count=hard,
        soft_count=soft,
        hybrid_count=hybrid,
    )

    try:
        tool_version = pkg_version("unifi-management-cli")
    except PackageNotFoundError:
        tool_version = "unknown"

    return RFStrategyPlan(
        schema_version=PLAN_SCHEMA_VERSION,
        generated_at=datetime.now().isoformat(),
        tool_version=tool_version,
        site=site,
        history_hours_available=hours_available,
        recommendations=tuple(recommendations),
        summary=summary,
    )
