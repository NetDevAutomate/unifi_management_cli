"""Link error rate tracking with baseline snapshots and delta comparison.

Takes periodic snapshots of port error/drop counters and compares deltas
to distinguish active degradation from cumulative historical errors.
"""

import json
from datetime import datetime
from pathlib import Path
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_BASELINE_PATH = "reports/link-error-baseline.json"


async def snapshot_link_errors(output_path: str = DEFAULT_BASELINE_PATH) -> dict:
    """Capture current error counters for all ports as a baseline."""
    async with UniFiClient() as client:
        devices = await client.get_devices()

    snapshot = {"timestamp": datetime.now().isoformat(), "devices": []}

    for d in devices:
        if d.get("type") not in ("usw", "udm", "udmpro"):
            continue
        dev_entry = {
            "device_id": d["_id"],
            "name": d.get("name", "Unknown"),
            "ports": [],
        }
        for p in d.get("port_table", []):
            dev_entry["ports"].append({
                "port_idx": p.get("port_idx"),
                "name": p.get("name", ""),
                "rx_errors": p.get("rx_errors", 0) or 0,
                "tx_errors": p.get("tx_errors", 0) or 0,
                "rx_dropped": p.get("rx_dropped", 0) or 0,
                "tx_dropped": p.get("tx_dropped", 0) or 0,
                "rx_bytes": p.get("rx_bytes", 0) or 0,
                "tx_bytes": p.get("tx_bytes", 0) or 0,
            })
        snapshot["devices"].append(dev_entry)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2))
    return snapshot


async def compare_link_errors(
    baseline_path: str = DEFAULT_BASELINE_PATH,
    threshold_errors_per_min: float = 10.0,
) -> dict:
    """Compare current error counters against baseline to find active degradation.

    Args:
        baseline_path: Path to baseline snapshot JSON
        threshold_errors_per_min: Flag ports exceeding this error rate

    Returns:
        Report with deltas and flagged ports
    """
    path = Path(baseline_path)
    if not path.exists():
        raise ToolError(
            message=f"No baseline found at {baseline_path}. Run snapshot first.",
            error_code=ErrorCodes.NO_DATA,
            suggestion="Run: unifi-mapper analyze link-errors --snapshot",
        )

    baseline = json.loads(path.read_text())
    baseline_time = datetime.fromisoformat(baseline["timestamp"])

    async with UniFiClient() as client:
        devices = await client.get_devices()

    now = datetime.now()
    elapsed_minutes = max((now - baseline_time).total_seconds() / 60, 1)

    # Build baseline lookup: (device_id, port_idx) -> counters
    baseline_lookup = {}
    for dev in baseline["devices"]:
        for port in dev["ports"]:
            key = (dev["device_id"], port["port_idx"])
            baseline_lookup[key] = port

    flagged = []
    all_deltas = []

    for d in devices:
        if d.get("type") not in ("usw", "udm", "udmpro"):
            continue
        dev_id = d["_id"]
        dev_name = d.get("name", "Unknown")

        for p in d.get("port_table", []):
            port_idx = p.get("port_idx")
            key = (dev_id, port_idx)
            prev = baseline_lookup.get(key)
            if not prev:
                continue

            rx_err_delta = max(0, (p.get("rx_errors", 0) or 0) - prev["rx_errors"])
            tx_err_delta = max(0, (p.get("tx_errors", 0) or 0) - prev["tx_errors"])
            rx_drop_delta = max(0, (p.get("rx_dropped", 0) or 0) - prev["rx_dropped"])
            tx_drop_delta = max(0, (p.get("tx_dropped", 0) or 0) - prev["tx_dropped"])
            total_delta = rx_err_delta + tx_err_delta + rx_drop_delta + tx_drop_delta

            if total_delta == 0:
                continue

            rate_per_min = total_delta / elapsed_minutes
            entry = {
                "device": dev_name,
                "port_idx": port_idx,
                "port_name": p.get("name", f"Port {port_idx}"),
                "rx_errors_delta": rx_err_delta,
                "tx_errors_delta": tx_err_delta,
                "rx_dropped_delta": rx_drop_delta,
                "tx_dropped_delta": tx_drop_delta,
                "total_delta": total_delta,
                "rate_per_min": round(rate_per_min, 1),
                "elapsed_minutes": round(elapsed_minutes, 1),
            }
            all_deltas.append(entry)

            if rate_per_min >= threshold_errors_per_min:
                entry["severity"] = "CRITICAL" if rate_per_min > 100 else "WARNING"
                flagged.append(entry)

    # Sort by rate descending
    all_deltas.sort(key=lambda x: -x["rate_per_min"])
    flagged.sort(key=lambda x: -x["rate_per_min"])

    return {
        "timestamp": now.isoformat(),
        "baseline_timestamp": baseline["timestamp"],
        "elapsed_minutes": round(elapsed_minutes, 1),
        "threshold_errors_per_min": threshold_errors_per_min,
        "ports_with_new_errors": len(all_deltas),
        "ports_flagged": len(flagged),
        "flagged": flagged,
        "all_deltas": all_deltas[:20],  # Top 20
    }
