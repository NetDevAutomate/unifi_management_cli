"""Client roaming analysis for UniFi networks.

Tracks which APs clients are connected to over time and identifies
sticky clients that should roam but don't.
"""

import json
from datetime import datetime
from pathlib import Path
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_ROAMING_PATH = "reports/client-roaming-history.json"


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

    # Keep last 288 snapshots (24h at 5-min intervals)
    history["snapshots"] = history["snapshots"][-288:]
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
