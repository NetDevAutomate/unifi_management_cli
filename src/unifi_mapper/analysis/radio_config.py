"""Radio configuration management for UniFi APs.

Supports snapshot (backup), apply (optimise), and restore operations
so changes are always reversible.
"""

import json
from datetime import datetime
from pathlib import Path
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def snapshot_radio_config(output_path: str | None = None) -> dict:
    """Snapshot current radio configuration for all APs.

    Returns dict and optionally writes to file for later restore.
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()

    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "aps": [],
    }

    for d in devices:
        if d.get("type") != "uap":
            continue
        snapshot["aps"].append({
            "device_id": d["_id"],
            "name": d.get("name", "Unknown"),
            "mac": d.get("mac", ""),
            "radio_table": d.get("radio_table", []),
        })

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2))

    return snapshot


async def apply_radio_config(
    changes: list[dict],
    dry_run: bool = True,
) -> list[dict]:
    """Apply radio configuration changes to APs.

    Args:
        changes: List of dicts with keys:
            - device_id: AP device ID
            - radio: 'ng' (2.4GHz) or 'na' (5GHz)
            - channel: int (0 = auto)
            - ht: str channel width ('20', '40', '80', '160')
            - tx_power_mode: 'auto', 'high', 'medium', 'low', 'custom'
            - tx_power: int dBm (when mode='custom')
            - min_rssi_enabled: bool (optional)
            - min_rssi: int (optional, negative dBm value)
        dry_run: If True, only report what would change

    Returns:
        List of result dicts with status per device
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()

    device_map = {d["_id"]: d for d in devices if d.get("type") == "uap"}
    results = []

    async with UniFiClient() as client:
        for change in changes:
            device_id = change["device_id"]
            device = device_map.get(device_id)
            if not device:
                results.append({"device_id": device_id, "status": "NOT_FOUND"})
                continue

            name = device.get("name", "Unknown")
            current_radio_table = device.get("radio_table", [])

            # Build updated radio_table
            new_radio_table = []
            target_radio = change.get("radio")  # 'ng' or 'na'

            for radio in current_radio_table:
                radio_id = radio.get("radio") or radio.get("name")
                if radio_id == target_radio:
                    # Apply changes to this radio
                    updated = dict(radio)
                    for field in ("channel", "ht", "tx_power_mode", "tx_power",
                                  "min_rssi_enabled", "min_rssi"):
                        if field in change:
                            updated[field] = change[field]
                    new_radio_table.append(updated)
                else:
                    new_radio_table.append(radio)

            if dry_run:
                results.append({
                    "device_id": device_id,
                    "name": name,
                    "radio": target_radio,
                    "status": "DRY_RUN",
                    "changes": {k: v for k, v in change.items()
                                if k not in ("device_id", "radio")},
                })
                continue

            # Build PUT payload
            payload = {
                "_id": device_id,
                "mac": device["mac"],
                "radio_table": new_radio_table,
            }
            # Include config version for persistence
            for field in ("config_version", "cfgversion", "config_revision"):
                if field in device:
                    payload[field] = device[field]

            try:
                path = client.build_path(f"rest/device/{device_id}")
                resp = await client.put(path, payload)  # noqa: F841
                await client.force_provision(device["mac"])
                results.append({
                    "device_id": device_id,
                    "name": name,
                    "radio": target_radio,
                    "status": "APPLIED",
                })
            except Exception as e:
                results.append({
                    "device_id": device_id,
                    "name": name,
                    "radio": target_radio,
                    "status": f"FAILED: {e}",
                })

    return results


async def restore_radio_config(snapshot_path: str, dry_run: bool = True) -> list[dict]:
    """Restore radio configuration from a snapshot file.

    Args:
        snapshot_path: Path to snapshot JSON file
        dry_run: If True, only report what would change
    """
    path = Path(snapshot_path)
    if not path.exists():
        raise ToolError(
            message=f"Snapshot file not found: {snapshot_path}",
            error_code=ErrorCodes.NO_DATA,
        )

    snapshot = json.loads(path.read_text())
    results = []

    async with UniFiClient() as client:
        devices = await client.get_devices()

    device_map = {d["_id"]: d for d in devices if d.get("type") == "uap"}

    async with UniFiClient() as client:
        for ap in snapshot["aps"]:
            device_id = ap["device_id"]
            device = device_map.get(device_id)
            if not device:
                results.append({
                    "device_id": device_id,
                    "name": ap["name"],
                    "status": "NOT_FOUND",
                })
                continue

            if dry_run:
                results.append({
                    "device_id": device_id,
                    "name": ap["name"],
                    "status": "DRY_RUN (would restore)",
                })
                continue

            payload = {
                "_id": device_id,
                "mac": device["mac"],
                "radio_table": ap["radio_table"],
            }
            for field in ("config_version", "cfgversion", "config_revision"):
                if field in device:
                    payload[field] = device[field]

            try:
                path_url = client.build_path(f"rest/device/{device_id}")
                await client.put(path_url, payload)
                await client.force_provision(device["mac"])
                results.append({
                    "device_id": device_id,
                    "name": ap["name"],
                    "status": "RESTORED",
                })
            except Exception as e:
                results.append({
                    "device_id": device_id,
                    "name": ap["name"],
                    "status": f"FAILED: {e}",
                })

    return results


def build_optimisation_plan(devices: list[dict]) -> list[dict]:
    """Build recommended radio changes based on current state.

    Recommendations:
    - 5GHz: increase to 80MHz width
    - 2.4GHz: reduce tx_power to 12 dBm
    - Kitchen 5GHz: move off channel 36 to channel 44
    - Enable min_rssi at -75 on all APs
    """
    changes = []

    for d in devices:
        if d.get("type") != "uap":
            continue

        device_id = d["_id"]
        name = d.get("name", "Unknown")

        for radio in d.get("radio_table", []):
            radio_id = radio.get("radio") or radio.get("name")

            if radio_id == "na":  # 5GHz
                current_ht = str(radio.get("ht", "20"))
                if int(current_ht) < 80:
                    change = {
                        "device_id": device_id,
                        "radio": "na",
                        "ht": "80",
                        "min_rssi_enabled": True,
                        "min_rssi": -75,
                    }
                    # Move Kitchen off channel 36
                    if "Kitchen" in name and radio.get("channel") == 36:
                        change["channel"] = 44
                    changes.append(change)

            elif radio_id == "ng":  # 2.4GHz
                # tx_power=None means auto (typically 16-23 dBm) — reduce to 12
                current_power = radio.get("tx_power")
                if current_power is None or current_power > 12:
                    changes.append({
                        "device_id": device_id,
                        "radio": "ng",
                        "tx_power_mode": "custom",
                        "tx_power": 12,
                        "min_rssi_enabled": True,
                        "min_rssi": -75,
                    })

    return changes


# ─── MCP Tool Handlers ────────────────────────────────────────────────────────


async def snapshot_radio_config_mcp() -> dict:
    """Snapshot current radio configuration for all APs.

    When to use this tool:
    - Before making any radio configuration changes
    - To create a restore point for rollback
    - As part of a change management workflow

    Returns:
        Snapshot data with AP count and file path
    """
    snapshot = await snapshot_radio_config(output_path="reports/radio-snapshot.json")
    return {
        "status": "saved",
        "aps_captured": len(snapshot["aps"]),
        "file": "reports/radio-snapshot.json",
        "timestamp": snapshot["timestamp"],
    }


async def apply_radio_optimization_mcp() -> list[dict]:
    """Apply recommended radio optimisations to all APs.

    Applies: 80MHz on 5GHz, reduced 2.4GHz Tx power, min RSSI -75.
    Auto-snapshots before applying for rollback safety.

    When to use this tool:
    - After reviewing optimize_radio_channels recommendations
    - When 5GHz is on narrow channel widths (20/40MHz)
    - When 2.4GHz Tx power is too high causing co-channel interference

    Returns:
        List of per-device apply results
    """
    from unifi_mapper.core.utils.client import UniFiClient

    # Snapshot first
    await snapshot_radio_config(output_path="reports/radio-pre-optimization.json")

    # Get devices and build plan
    async with UniFiClient() as client:
        devices = await client.get_devices()

    changes = build_optimisation_plan(devices)
    if not changes:
        return [{"status": "NO_CHANGES", "message": "Config already optimal"}]

    return await apply_radio_config(changes, dry_run=False)


async def restore_radio_config_mcp(
    snapshot_path: str = "reports/radio-snapshot.json",
) -> list[dict]:
    """Restore radio configuration from a snapshot file.

    When to use this tool:
    - After applying changes that caused issues
    - To rollback to a known-good configuration
    - When Wi-Fi performance degraded after optimization

    Args:
        snapshot_path: Path to snapshot JSON file (default: reports/radio-snapshot.json)

    Returns:
        List of per-device restore results
    """
    return await restore_radio_config(snapshot_path, dry_run=False)
