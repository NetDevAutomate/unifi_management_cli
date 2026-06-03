"""Configuration drift detection for UniFi devices.

Snapshots full device configuration and diffs against baseline to detect
manual UI changes or unexpected configuration drift.
"""

import json
from datetime import datetime
from pathlib import Path
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_CONFIG_PATH = "reports/config-baseline.json"

# Fields to track for drift (ignore volatile stats fields)
TRACKED_FIELDS = {
    "usw": ["port_overrides", "stp_priority", "stp_version", "mgmt_network_id",
             "config_network", "snmp_contact", "snmp_location"],
    "uap": ["radio_table", "bandsteering_mode", "mesh_sta_vap_enabled",
             "config_network", "mgmt_network_id"],
    "udm": ["port_overrides", "config_network", "mgmt_network_id"],
}

# Per-port fields to track
PORT_TRACKED = ["name", "poe_mode", "forward", "speed", "autoneg",
                "port_security_enabled", "stp_port_mode"]

# Per-radio fields to track
RADIO_TRACKED = ["radio", "channel", "ht", "tx_power", "tx_power_mode",
                 "min_rssi_enabled", "min_rssi", "sens_level_enabled"]


async def snapshot_config(output_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Snapshot tracked configuration fields for all devices."""
    async with UniFiClient() as client:
        devices = await client.get_devices()

    snapshot = {"timestamp": datetime.now().isoformat(), "devices": []}

    for d in devices:
        dev_type = d.get("type", "")
        if dev_type not in TRACKED_FIELDS:
            continue

        entry = {
            "device_id": d["_id"],
            "name": d.get("name", "Unknown"),
            "mac": d.get("mac", ""),
            "type": dev_type,
            "config": {},
        }

        # Track top-level fields
        for field in TRACKED_FIELDS.get(dev_type, []):
            if field in d:
                entry["config"][field] = d[field]

        # Track port config (filtered to relevant fields)
        if "port_table" in d:
            entry["config"]["ports"] = [
                {k: p.get(k) for k in PORT_TRACKED if k in p}
                | {"port_idx": p.get("port_idx")}
                for p in d["port_table"]
            ]

        # Track radio config for APs
        if dev_type == "uap" and "radio_table" in d:
            entry["config"]["radios"] = [
                {k: r.get(k) for k in RADIO_TRACKED if k in r}
                for r in d["radio_table"]
            ]

        snapshot["devices"].append(entry)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    return snapshot


async def detect_drift(baseline_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Compare current config against baseline and report differences."""
    path = Path(baseline_path)
    if not path.exists():
        raise ToolError(
            message=f"No config baseline at {baseline_path}. Run snapshot first.",
            error_code=ErrorCodes.NO_DATA,
            suggestion="Run: unifi-mapper config snapshot",
        )

    baseline = json.loads(path.read_text())

    async with UniFiClient() as client:
        devices = await client.get_devices()

    # Build current config in same format
    current_lookup = {}
    for d in devices:
        dev_type = d.get("type", "")
        if dev_type not in TRACKED_FIELDS:
            continue
        entry = {"config": {}}
        for field in TRACKED_FIELDS.get(dev_type, []):
            if field in d:
                entry["config"][field] = d[field]
        if "port_table" in d:
            entry["config"]["ports"] = [
                {k: p.get(k) for k in PORT_TRACKED if k in p}
                | {"port_idx": p.get("port_idx")}
                for p in d["port_table"]
            ]
        if dev_type == "uap" and "radio_table" in d:
            entry["config"]["radios"] = [
                {k: r.get(k) for k in RADIO_TRACKED if k in r}
                for r in d["radio_table"]
            ]
        current_lookup[d["_id"]] = entry

    # Compare
    drifts = []
    for dev in baseline["devices"]:
        dev_id = dev["device_id"]
        dev_name = dev["name"]
        current = current_lookup.get(dev_id)

        if not current:
            drifts.append({"device": dev_name, "type": "MISSING", "details": "Device no longer found"})
            continue

        baseline_config = dev["config"]
        current_config = current["config"]

        for key in baseline_config:
            if key not in current_config:
                drifts.append({"device": dev_name, "field": key, "type": "REMOVED",
                               "baseline": baseline_config[key], "current": None})
            elif baseline_config[key] != current_config[key]:
                drifts.append({"device": dev_name, "field": key, "type": "CHANGED",
                               "baseline": baseline_config[key], "current": current_config[key]})

    return {
        "timestamp": datetime.now().isoformat(),
        "baseline_timestamp": baseline["timestamp"],
        "devices_checked": len(baseline["devices"]),
        "drifts_detected": len(drifts),
        "drifts": drifts,
    }
