"""Client roaming analysis for UniFi networks.

Tracks which APs clients are connected to over time and identifies
sticky clients that should roam but don't.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_ROAMING_PATH = "reports/client-roaming-history.json"

# Retention configuration — referenced by rf_strategy.py's 48h history gate.
# Bumped from 288 (24h) to 576 (48h) during Phase D design to support the
# scorecard's minimum-history requirement for disable recommendations.
# See: docs/plans/2026-05-04-phase-d-rf-strategy-design.md
SNAPSHOT_INTERVAL_SECONDS = 300  # 5 minutes baseline cadence
RETENTION_HOURS = 48
MAX_SNAPSHOTS_RETAINED = (RETENTION_HOURS * 3600) // SNAPSHOT_INTERVAL_SECONDS  # = 576

# UniFi 2.4 GHz channels. 1–13 cover US/EU/AU; 14 is JP-only. Any channel
# outside this set (36, 40, 44, ... 149, 153, 157, 161, 165) is 5 GHz.
# 6 GHz is not handled here — Phase D scope is 2.4/5 coexistence only, and
# 6 GHz (Wi-Fi 6E) uses channels 1–233 in a separate UNII-5/6/7/8 space which
# UniFi exposes via a distinct `ng` vs `na` radio_name. For the current
# snapshot schema where only `channel` is recorded, assume 1–14 = 2.4 GHz.
CHANNELS_24GHZ = frozenset(range(1, 15))


async def snapshot_client_associations(output_path: str = DEFAULT_ROAMING_PATH) -> dict:
    """Record current client-to-AP associations for roaming tracking.

    Each run appends to the history file, building a time-series of
    which AP each client is connected to.
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()
        clients = await client.get_clients()

    # Build AP name lookup
    ap_names = {}
    for d in devices:
        if d.get("type") == "uap":
            ap_names[d.get("mac", "")] = d.get("name", "Unknown")

    # Current associations
    now = datetime.now().isoformat()
    associations = []
    for c in clients:
        ap_mac = c.get("ap_mac")
        if not ap_mac:
            continue
        associations.append({
            "client_mac": c.get("mac", ""),
            "client_name": c.get("name") or c.get("hostname") or c.get("mac", ""),
            "ap_mac": ap_mac,
            "ap_name": ap_names.get(ap_mac, "Unknown"),
            "rssi": c.get("rssi"),
            "channel": c.get("channel"),
            "ssid": c.get("essid", ""),
        })

    # Load existing history or create new
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        history = json.loads(path.read_text())
    else:
        history = {"snapshots": []}

    history["snapshots"].append({"timestamp": now, "associations": associations})

    # Keep the most recent snapshots within the retention window (48h at 5-min intervals = 576).
    history["snapshots"] = history["snapshots"][-MAX_SNAPSHOTS_RETAINED:]
    path.write_text(json.dumps(history, indent=2))

    return {"timestamp": now, "clients_tracked": len(associations), "snapshots_stored": len(history["snapshots"])}


async def analyze_roaming(history_path: str = DEFAULT_ROAMING_PATH) -> dict:
    """Analyze roaming patterns from collected history.

    Identifies:
    - Clients that roamed between APs
    - Sticky clients (low RSSI but not roaming)
    - Frequent roamers (bouncing between APs)
    """
    path = Path(history_path)
    if not path.exists():
        raise ToolError(
            message=f"No roaming history at {history_path}. Collect snapshots first.",
            error_code=ErrorCodes.NO_DATA,
            suggestion="Run: unifi-mapper analyze roaming --snapshot (multiple times over time)",
        )

    history = json.loads(path.read_text())
    snapshots = history.get("snapshots", [])

    if len(snapshots) < 2:
        raise ToolError(
            message="Need at least 2 snapshots to analyze roaming. Collect more data.",
            error_code=ErrorCodes.NO_DATA,
            suggestion="Run snapshot collection periodically (e.g., every 5 minutes via cron)",
        )

    # Track AP associations per client across all snapshots
    client_history: dict[str, dict] = {}  # mac -> {name, aps: [(timestamp, ap_name, rssi)]}

    for snap in snapshots:
        ts = snap["timestamp"]
        for assoc in snap["associations"]:
            mac = assoc["client_mac"]
            if mac not in client_history:
                client_history[mac] = {"name": assoc["client_name"], "observations": []}
            client_history[mac]["observations"].append({
                "timestamp": ts,
                "ap_name": assoc["ap_name"],
                "rssi": assoc.get("rssi"),
            })
            # Update name to latest
            client_history[mac]["name"] = assoc["client_name"]

    # Analyze each client
    roamers = []
    sticky_clients = []

    for mac, data in client_history.items():
        obs = data["observations"]
        if len(obs) < 2:
            continue

        # Count unique APs
        unique_aps = {o["ap_name"] for o in obs}
        roam_count = len(unique_aps) - 1

        # Check for sticky (low RSSI, never roams)
        avg_rssi = sum(o["rssi"] for o in obs if o["rssi"]) / max(1, sum(1 for o in obs if o["rssi"]))
        min_rssi = min((o["rssi"] for o in obs if o["rssi"]), default=0)

        if roam_count > 0:
            # Count actual transitions (AP changed between consecutive observations)
            transitions = sum(1 for i in range(1, len(obs)) if obs[i]["ap_name"] != obs[i - 1]["ap_name"])
            roamers.append({
                "client": data["name"],
                "mac": mac,
                "unique_aps": len(unique_aps),
                "transitions": transitions,
                "aps_used": list(unique_aps),
                "avg_rssi": round(avg_rssi),
                "observations": len(obs),
            })
        elif min_rssi < 30 and len(obs) >= 3:
            # Sticky: low signal but never roams
            sticky_clients.append({
                "client": data["name"],
                "mac": mac,
                "stuck_on": obs[-1]["ap_name"],
                "avg_rssi": round(avg_rssi),
                "min_rssi": min_rssi,
                "observations": len(obs),
            })

    # Sort roamers by transitions (most active first)
    roamers.sort(key=lambda x: -x["transitions"])
    sticky_clients.sort(key=lambda x: x["min_rssi"])

    return {
        "timestamp": datetime.now().isoformat(),
        "snapshots_analyzed": len(snapshots),
        "time_span": f"{snapshots[0]['timestamp']} to {snapshots[-1]['timestamp']}",
        "clients_tracked": len(client_history),
        "roaming_clients": len(roamers),
        "sticky_clients": len(sticky_clients),
        "roamers": roamers[:20],
        "sticky": sticky_clients[:10],
    }


def history_hours_available(history_path: str = DEFAULT_ROAMING_PATH) -> float:
    """Return the number of hours between the oldest and newest snapshot.

    Used by the RF strategy scorecard (rf_strategy.py) to gate recommendation
    emission — recommendations are refused if < MIN_HISTORY_HOURS (48) is
    available.

    Returns:
        0.0 if the history file does not exist, has fewer than 2 snapshots,
        or has any malformed timestamps.

    Raises:
        ToolError(CONFIG_INVALID) if the history file exists but is not valid
        JSON or does not contain a "snapshots" list.
    """
    path = Path(history_path)
    if not path.exists():
        return 0.0

    try:
        history = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ToolError(
            message=f"Roaming history at {history_path} is not valid JSON: {err}",
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion="Inspect the file manually; rerun the snapshot command to rebuild if corrupt.",
        ) from err

    snapshots = history.get("snapshots")
    if not isinstance(snapshots, list):
        raise ToolError(
            message=f"Roaming history at {history_path} is missing a 'snapshots' list.",
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion="Delete the file and let snapshot collection rebuild it.",
        )

    if len(snapshots) < 2:
        return 0.0

    try:
        oldest = datetime.fromisoformat(snapshots[0]["timestamp"])
        newest = datetime.fromisoformat(snapshots[-1]["timestamp"])
    except (KeyError, ValueError, TypeError):
        return 0.0

    delta_seconds = (newest - oldest).total_seconds()
    return max(0.0, delta_seconds / 3600.0)


def compute_twofour_only_clients(
    history_path: str = DEFAULT_ROAMING_PATH,
    window_hours: float = 48.0,
) -> dict[str, list[dict[str, Any]]]:
    """Identify clients observed ONLY on 2.4 GHz per AP within the window.

    Walks all snapshots newer than (newest_snapshot - window_hours). For each
    (ap_name, client_mac) pair, reports clients whose observations in the
    window on that AP were exclusively on 2.4 GHz channels (see
    ``CHANNELS_24GHZ``) — AND who never proved 5 GHz capability on ANY AP
    in the same window. The latter check matters: a client seen on 2.4 on
    AP-A but 5 on AP-B can safely roam to 5 when 2.4 is disabled on A.

    Args:
        history_path: Path to the roaming history JSON file.
        window_hours: How far back to look, relative to the newest snapshot
            timestamp in the file (not wall-clock ``now``; this keeps the
            function pure and deterministic for testing).

    Returns:
        Mapping of ``ap_name -> [{"client_mac": str, "client_name": str,
        "observation_count": int, "last_seen": iso_str}, ...]``. Every AP
        observed in the window appears as a key, with an empty list if no
        2.4-only clients on that AP. Empty dict if the history file is
        missing, empty, or has no snapshots in the window.

    Notes:
        - Observations with ``channel is None`` are skipped (not counted
          toward 2.4 or 5). A client with only None-channel observations is
          excluded from the result (insufficient data to classify).
        - Wired clients are already filtered out by
          ``snapshot_client_associations`` (no ``ap_mac``), so they never
          reach this code path.
    """
    path = Path(history_path)
    if not path.exists():
        return {}

    try:
        history = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise ToolError(
            message=f"Roaming history at {history_path} is not valid JSON: {err}",
            error_code=ErrorCodes.CONFIG_INVALID,
            suggestion="Inspect the file manually; rerun the snapshot command to rebuild if corrupt.",
        ) from err

    snapshots = history.get("snapshots", [])
    if not snapshots:
        return {}

    # Window cutoff is anchored to the newest snapshot, not wall-clock now —
    # keeps the function pure/testable without freezing time in tests.
    try:
        newest_ts = datetime.fromisoformat(snapshots[-1]["timestamp"])
    except (KeyError, ValueError, TypeError):
        return {}
    cutoff = newest_ts - timedelta(hours=window_hours)

    # Single walk — gather, per (ap_name, client_mac), the list of in-window
    # observations. Also track, globally, the set of clients seen on 5 GHz
    # anywhere in the window (those are excluded from all AP buckets).
    per_ap_client: dict[tuple[str, str], list[dict[str, Any]]] = {}
    clients_with_5ghz: set[str] = set()
    aps_seen: set[str] = set()

    for snap in snapshots:
        try:
            ts = datetime.fromisoformat(snap["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        if ts < cutoff:
            continue

        for assoc in snap.get("associations", []):
            ap_name = assoc.get("ap_name")
            client_mac = assoc.get("client_mac")
            if not ap_name or not client_mac:
                continue

            aps_seen.add(ap_name)
            channel = assoc.get("channel")

            # Track global 5 GHz capability proof (any AP, any observation).
            if channel is not None and channel not in CHANNELS_24GHZ:
                clients_with_5ghz.add(client_mac)

            per_ap_client.setdefault((ap_name, client_mac), []).append({
                "timestamp": snap["timestamp"],
                "channel": channel,
                "client_name": assoc.get("client_name") or client_mac,
            })

    # Build result: every AP is a key; populate lists with 2.4-only clients.
    result: dict[str, list[dict[str, Any]]] = {ap: [] for ap in aps_seen}

    for (ap_name, client_mac), obs in per_ap_client.items():
        # Skip clients that proved 5 GHz somewhere.
        if client_mac in clients_with_5ghz:
            continue

        # Evaluate observations on THIS AP: at least one 2.4 GHz sample,
        # no 5 GHz samples (already guaranteed by global filter above, but
        # defensive), and not all channels None.
        channels = [o["channel"] for o in obs]
        has_24ghz = any(c in CHANNELS_24GHZ for c in channels if c is not None)
        if not has_24ghz:
            # Either all None or all 5 GHz (the latter impossible here given
            # the global filter, but kept explicit for clarity).
            continue

        result[ap_name].append({
            "client_mac": client_mac,
            "client_name": obs[-1]["client_name"],
            "observation_count": len(obs),
            "last_seen": obs[-1]["timestamp"],
        })

    # Deterministic ordering — sort each AP's list by client_mac.
    for ap_name in result:
        result[ap_name].sort(key=lambda entry: entry["client_mac"])

    return result
