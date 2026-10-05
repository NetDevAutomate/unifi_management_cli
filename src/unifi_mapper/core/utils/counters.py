"""Reset-aware deltas for the controller's cumulative per-VAP counters.

UniFi per-VAP TX counters (``tx_packets``, ``tx_retries``) are cumulative and reset to zero
when an AP reboots. Naive subtraction across a reboot gives negative deltas; these helpers
treat a counter regression, or a VAP missing from the previous sample, as a reset and use the
current cumulative value as the interval's delta.

The honest per-radio health metric is the per-interval retry percentage (delta
``tx_retries`` / delta ``tx_packets``); below 5 to 10% is healthy. The radio-level
``cu_total`` statistic is unreliable on some AP firmware (it conflates receiver noise with
airtime), so the retry percentage is preferred for fault detection.

Pure: no I/O. Used by ``get_ap_retry_rates`` / ``diagnose ap-retries`` and the AP health
sampling.
"""

from dataclasses import dataclass


@dataclass
class VapCounters:
    """Cumulative TX/RX counters for one VAP at one sample instant."""

    essid: str
    tx_packets: int = 0
    tx_retries: int = 0
    tx_dropped: int = 0
    rx_packets: int = 0
    num_sta: int = 0
    channel: int | None = None


def vap_counters_from_dict(vap: dict) -> VapCounters:
    """Build ``VapCounters`` from a controller ``vap_table`` entry.

    Args:
        vap: One entry from a device's ``vap_table`` list.

    Returns:
        VapCounters with missing or None counters coerced to 0.
    """
    return VapCounters(
        essid=vap.get('essid', '?'),
        tx_packets=vap.get('tx_packets') or 0,
        tx_retries=vap.get('tx_retries') or 0,
        tx_dropped=vap.get('tx_dropped') or 0,
        rx_packets=vap.get('rx_packets') or 0,
        num_sta=vap.get('num_sta') or 0,
        channel=vap.get('channel'),
    )


def pick_vap(vaps: list[VapCounters], essid: str) -> VapCounters | None:
    """Select the VAP to track: the named SSID, else the busiest by ``tx_packets``.

    Args:
        vaps: Candidate VAPs (typically all VAPs of one radio on one AP).
        essid: Preferred SSID name.

    Returns:
        The matching VAP, the busiest VAP as a fallback, or None if empty.
    """
    vap = next((v for v in vaps if v.essid == essid), None)
    if vap is None and vaps:
        vap = max(vaps, key=lambda v: v.tx_packets)
    return vap


def retry_delta(
    prev_vaps: list[VapCounters] | None,
    cur_vaps: list[VapCounters],
    essid: str,
) -> tuple[int, int, float | None]:
    """Return the interval delta of ``tx_packets``/``tx_retries`` for one VAP, reset-aware.

    Counters are cumulative and reset on AP reboot. If either current cumulative value is
    lower than the previous sample's (or the VAP is missing from the previous sample), the
    counters are treated as freshly reset and the current cumulative values become the delta:
    never a negative number.

    Args:
        prev_vaps: VAP counters from the previous sample, or None for the first sample
            (baseline 0).
        cur_vaps: VAP counters from the current sample.
        essid: SSID whose VAP to track (falls back to the busiest VAP).

    Returns:
        ``(delta_packets, delta_retries, retry_pct)``. ``retry_pct`` is None when
        ``delta_packets`` is 0: no traffic means no honest percentage.
    """
    cur_v = pick_vap(cur_vaps, essid)
    if cur_v is None:
        return 0, 0, None

    if prev_vaps is None:
        base_p, base_r = 0, 0
    else:
        prev_v = next((v for v in prev_vaps if v.essid == cur_v.essid), None)
        # Counter reset (AP rebooted, or either counter went down): the cumulative value is
        # the delta, so neither delta is ever negative
        if (
            prev_v is None
            or cur_v.tx_packets < prev_v.tx_packets
            or cur_v.tx_retries < prev_v.tx_retries
        ):
            base_p, base_r = 0, 0
        else:
            base_p, base_r = prev_v.tx_packets, prev_v.tx_retries

    dp = cur_v.tx_packets - base_p
    dr = cur_v.tx_retries - base_r
    pct = round(100 * dr / dp, 1) if dp > 0 else None
    return dp, dr, pct
