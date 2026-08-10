"""Neighbour AP scan via UniFi passive rogue AP detection (stat/rogueap).

Reads always-fresh background-scanned neighbour data instead of triggering
spectrum-scan (which is deprecated/non-functional on UniFi OS 5.x).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unifi_mapper.core.utils.client import UniFiClient


# Oracle-validated RSSI thresholds (aligned with 802.11 CCA)
RSSI_WEIGHT_STRONG = 3.0  # signal > -67 dBm (CCA-ED preamble detect)
RSSI_WEIGHT_MEDIUM = 1.0  # signal -67 to -82 dBm (CCA energy detect)
RSSI_WEIGHT_WEAK = 0.5  # signal < -82 dBm (near noise floor)

# Stale entry filter
MAX_ROGUE_AGE_SECONDS = 300

# 2.4 GHz adjacent-channel compensation (dB offsets before RSSI bucketing)
ADJACENT_CHANNEL_OFFSETS_24GHZ = {
    0: 0,  # co-channel
    1: -25,  # ±1 channel spacing
    2: -40,  # ±2 channel spacing
}


def rssi_weight(signal_dbm: int) -> float:
    """Return RSSI bucket weight per oracle-validated CCA thresholds.

    Boundaries: -67 falls in MEDIUM, -82 falls in WEAK.
    """
    if signal_dbm > -67:
        return RSSI_WEIGHT_STRONG
    if signal_dbm > -82:
        return RSSI_WEIGHT_MEDIUM
    return RSSI_WEIGHT_WEAK


def effective_rssi_for_channel(
    signal_dbm: int,
    source_channel: int,
    target_channel: int,
    band: str,
) -> int | None:
    """Compute effective RSSI an AP on source_channel contributes to target_channel.

    - 5 GHz ('na'): None unless source == target (channels don't overlap)
    - 2.4 GHz ('ng'): applies dB offset based on channel distance;
      None if distance > 2
    """
    if band == 'na':
        return signal_dbm if source_channel == target_channel else None
    distance = abs(source_channel - target_channel)
    offset = ADJACENT_CHANNEL_OFFSETS_24GHZ.get(distance)
    if offset is None:
        return None
    return signal_dbm + offset


def compute_channel_neighbour_score(
    neighbours: list[dict[str, Any]],
    target_channel: int,
    band: str,
) -> float:
    """Sum RSSI-weighted neighbour contribution for target_channel."""
    total = 0.0
    for nb in neighbours:
        source_ch = nb.get('channel', 0)
        signal = nb.get('signal', -100)
        effective = effective_rssi_for_channel(signal, source_ch, target_channel, band)
        if effective is None:
            continue
        total += rssi_weight(effective)
    return total


def filter_live_rogue_entries(
    rogue_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only rogue entries that are relevant for neighbour analysis.

    Applies the two standard filters: exclude own-network APs (is_ubnt=True)
    and exclude stale entries (age > MAX_ROGUE_AGE_SECONDS). Shared between
    `scan_neighbours` (per-AP grouping) and `channel_optimiser.analyze_channels`
    (network-wide channel scoring) so both see identical data.
    """
    return [
        e
        for e in rogue_entries
        if not e.get('is_ubnt', False) and e.get('age', 0) <= MAX_ROGUE_AGE_SECONDS
    ]


def _filter_own_network_observations(
    rogue_entries: list[dict[str, Any]],
    our_ap_bssids: set[str],
) -> list[dict[str, Any]]:
    """Keep only rogue entries observing OUR own BSSIDs, with stale-age filter.

    Inverse of :func:`filter_live_rogue_entries`. Unlike that helper,
    ``is_ubnt=True`` entries are KEPT here: when an AP hears another of our
    APs, that IS our own network, which is exactly the signal we want for
    AP-to-AP RF overlap. The ``is_ubnt`` flag is the controller's own
    identification of Ubiquiti-manufactured radios; it is not a reliable
    indicator of our specific deployment, so we use the explicit BSSID
    allowlist instead.
    """
    our_ap_bssids_lower = {b.lower() for b in our_ap_bssids}
    return [
        e
        for e in rogue_entries
        if e.get('bssid', '').lower() in our_ap_bssids_lower
        and e.get('age', 0) <= MAX_ROGUE_AGE_SECONDS
    ]


def compute_ap_to_ap_overlap(
    rogue_entries: list[dict[str, Any]],
    our_ap_bssids: set[str],
    ap_mac_to_name: dict[str, str],
) -> dict[tuple[str, str], int]:
    """Compute per-AP-pair RSSI overlap from stat/rogueap observations.

    For each entry where the observed `bssid` is one of our own APs' BSSIDs
    (i.e. observer_ap heard observed_ap's beacon), record the RSSI keyed by
    (observer_ap_name, observed_ap_name). If multiple radios on the same
    observer hear the same neighbour BSSID (2.4 + 5 separately), keep the
    strongest RSSI — max() of negative dBm values is the less-negative one.

    BSSID comparison is case-insensitive; ``our_ap_bssids`` may be supplied
    in any case (``get_our_ap_bssids`` already returns lowercased).

    Args:
        rogue_entries: Raw ``stat/rogueap`` payload entries.
        our_ap_bssids: Set of BSSIDs that belong to our own APs (any case).
        ap_mac_to_name: Mapping of mac/bssid → friendly AP name. Lookups fall
            back to the raw mac/bssid string when no name is registered, so
            the result is always human-readable but never raises.

    Returns:
        Mapping of (observer_ap_name, observed_ap_name) → strongest RSSI
        (int dBm). Empty dict if no overlaps found or ``our_ap_bssids`` is
        empty.
    """
    if not our_ap_bssids:
        return {}

    own_observations = _filter_own_network_observations(rogue_entries, our_ap_bssids)
    overlap: dict[tuple[str, str], int] = {}

    for entry in own_observations:
        observer_mac: str = entry.get('ap_mac') or ''
        observed_bssid: str = (entry.get('bssid') or '').lower()
        signal = entry.get('signal')
        if signal is None:
            continue

        observer_name = ap_mac_to_name.get(observer_mac, observer_mac)
        observed_name = ap_mac_to_name.get(observed_bssid, observed_bssid)
        pair: tuple[str, str] = (observer_name, observed_name)

        # max() keeps the stronger signal (less negative dBm).
        prior = overlap.get(pair)
        overlap[pair] = signal if prior is None else max(prior, signal)

    return overlap


def _group_rogue_entries(
    rogue_entries: list[dict[str, Any]],
    ap_mac_to_name: dict[str, str],
    filter_ap_mac: str | None = None,
) -> list[dict[str, Any]]:
    """Group stat/rogueap entries by detecting AP.

    Filters: is_ubnt=True excluded, age > MAX_ROGUE_AGE_SECONDS excluded,
    optionally filter to single ap_mac.
    """
    by_ap: dict[str, list[dict[str, Any]]] = {}
    for entry in filter_live_rogue_entries(rogue_entries):
        ap_mac = entry.get('ap_mac', '')
        if filter_ap_mac and ap_mac != filter_ap_mac:
            continue
        by_ap.setdefault(ap_mac, []).append(entry)

    result = []
    for ap_mac, entries in by_ap.items():
        channel_summary: dict[int, int] = {}
        for e in entries:
            ch = e.get('channel', 0)
            channel_summary[ch] = channel_summary.get(ch, 0) + 1
        strongest = sorted(entries, key=lambda e: e.get('signal', -100), reverse=True)[:5]
        result.append(
            {
                'ap_mac': ap_mac,
                'ap_name': ap_mac_to_name.get(ap_mac, ap_mac),
                'channel_summary': channel_summary,
                'neighbours': entries,
                'total_neighbours': len(entries),
                'strongest': strongest,
            }
        )
    return result


async def scan_neighbours(ap_name: str | None = None) -> dict[str, Any]:
    """Fetch passive neighbour AP data from stat/rogueap endpoint.

    Always-fresh data; no scan trigger, no wait. UniFi controller runs
    passive background scanning continuously on UniFi OS 5.x.
    """
    async with UniFiClient() as client:
        rogue = await client.get_rogue_aps()
        devices = await client.get_devices()

    ap_mac_to_name = {d['mac']: d.get('name', d['mac']) for d in devices if d.get('type') == 'uap'}

    filter_mac = None
    if ap_name:
        for mac, name in ap_mac_to_name.items():
            if ap_name.lower() in name.lower():
                filter_mac = mac
                break

    aps = _group_rogue_entries(rogue, ap_mac_to_name, filter_ap_mac=filter_mac)
    return {'timestamp': datetime.now().isoformat(), 'aps': aps}


async def get_our_ap_bssids(client: UniFiClient) -> set[str]:
    """Extract all BSSIDs from our own APs via ``client.get_devices()``.

    Walks ``vap_table`` entries across all devices where ``type == "uap"``
    and returns the set of lowercased BSSID strings, suitable as the
    ``our_ap_bssids`` argument to :func:`compute_ap_to_ap_overlap`.

    Non-UAP devices (switches, gateways) are skipped even if they carry an
    unexpected ``vap_table`` — the filter is on device type, not presence
    of the field.
    """
    devices = await client.get_devices()
    bssids: set[str] = set()
    for device in devices:
        if device.get('type') != 'uap':
            continue
        for vap in device.get('vap_table', []):
            bssid = vap.get('bssid')
            if bssid:
                bssids.add(bssid.lower())
    return bssids
