"""Auto-channel optimiser for UniFi APs.

Analyses current channel utilization and recommends optimal channel assignments
for both 5GHz and 2.4GHz bands. Generates before/after reports in table and markdown format.
"""

from datetime import datetime
from unifi_mapper.analysis.neighbour_scan import (
    compute_channel_neighbour_score,
    filter_live_rogue_entries,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# 5GHz 80MHz-compatible primary channels (non-DFS preferred first)
CHANNELS_5GHZ_80MHZ = [36, 52, 100, 116, 132, 149]
# Non-DFS only
CHANNELS_5GHZ_80MHZ_NO_DFS = [36, 149]
# All usable 5GHz channels at 80MHz (UNII-1, UNII-2, UNII-2e, UNII-3)
CHANNELS_5GHZ_ALL = [
    36,
    40,
    44,
    48,
    52,
    56,
    60,
    64,
    100,
    104,
    108,
    112,
    116,
    120,
    124,
    128,
    132,
    136,
    140,
    144,
    149,
    153,
    157,
    161,
    165,
]

# 2.4GHz non-overlapping channels
CHANNELS_24GHZ = [1, 6, 11]  # Standard non-overlapping set (use 13 if region allows)
CHANNELS_24GHZ_ALL = [1, 6, 11, 13]  # Superset used for neighbour-score pre-compute
# so `optimize_24ghz` can dynamically pick 1/6/13 too
# 5GHz 80MHz block primaries. At 80MHz the four channels in a block (e.g. 149/153/
# 157/161) are the SAME spectrum, so only one AP can occupy a block without overlap.
# Selecting by primary channel alone let three APs be assigned 149, 153 and 157.
BLOCKS_5GHZ_80MHZ: dict[int, tuple[int, ...]] = {
    36: (36, 40, 44, 48),
    52: (52, 56, 60, 64),
    100: (100, 104, 108, 112),
    116: (116, 120, 124, 128),
    132: (132, 136, 140, 144),
    149: (149, 153, 157, 161),
}

# Radio identifiers the controller uses per band. Band MUST be derived from these
# rather than from the channel number: a 6GHz radio commonly sits on a low channel
# number (the U7 Pro XG Wall reports 6e on ch 37) which a `channel > 14` test
# misreads as 5GHz, overwriting the real 5GHz radio entry.
RADIO_ID_BANDS: dict[str, str] = {
    'ng': '2.4GHz',
    'na': '5GHz',
    '6e': '6GHz',
    '6g': '6GHz',
    'wifi2': '6GHz',
    'ax6': '6GHz',
}

NEIGHBOUR_PENALTY_CAP = 35  # Cap on neighbour penalty per channel.
# Rationale: with RSSI_WEIGHT_STRONG=3.0, saturates at ~12
# strong neighbours — prevents neighbour data from overwhelming
# measured utilization (0-100) while still steering away from
# crowded channels. Slightly above DFS penalty (15) so dense
# neighbour congestion outweighs radar-channel avoidance.


def band_for_radio(radio_id: str | None, channel: int | None) -> str:
    """Classify a radio's band from its controller radio id, not its channel number.

    Deriving the band from `channel > 14` misclassifies 6GHz radios, which report low
    channel numbers (a U7 Pro XG Wall's `6e` radio sits on ch 37). When both radios are
    keyed into the same per-AP dict under '5GHz', the 6GHz entry silently overwrites the
    real 5GHz telemetry and any recommendation for `na` is computed from 6GHz data.

    Args:
        radio_id: Controller radio identifier ('ng', 'na', '6e', ...). May be None on
            older controllers, in which case the channel heuristic is used.
        channel: Radio channel, used only as a fallback.

    Returns:
        One of '2.4GHz', '5GHz' or '6GHz'.
    """
    if radio_id:
        band = RADIO_ID_BANDS.get(str(radio_id).lower())
        if band:
            return band
    return '5GHz' if (channel or 0) > 14 else '2.4GHz'


def block_80mhz(channel: int) -> int | None:
    """Return the primary channel identifying the 80MHz block `channel` belongs to.

    Two APs sharing a block occupy identical spectrum regardless of which primary
    channel each is configured with.

    Returns:
        The block's lowest channel (36/52/100/116/132/149), or None when `channel` is
        not part of a known 80MHz block.
    """
    for primary, members in BLOCKS_5GHZ_80MHZ.items():
        if channel in members:
            return primary
    return None


async def analyze_channels() -> dict:
    """Gather current channel state for all APs.

    Returns dict with per-AP radio stats for both bands.
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
        except Exception as e:
            raise ToolError(
                message=f'Failed to fetch devices: {e}',
                error_code=ErrorCodes.API_ERROR,
            )
        try:
            rogue_entries = await client.get_rogue_aps()
        except (ToolError, KeyError, TypeError):
            # stat/rogueap may not be available on very old controllers or when
            # no AP has performed a background scan yet. Fall back to empty data
            # so channel optimisation still works using own-AP utilization alone.
            rogue_entries = []

    # Filter rogue entries via the shared helper (exclude own-network and stale)
    all_neighbours = filter_live_rogue_entries(rogue_entries)

    aps = []
    for d in devices:
        if d.get('type') != 'uap':
            continue

        ap_info = {
            'device_id': d['_id'],
            'name': d.get('name', 'Unknown'),
            'mac': d.get('mac', ''),
            'radios': {},
        }

        for radio in d.get('radio_table_stats', []):
            ch = radio.get('channel', 0)
            band = band_for_radio(radio.get('radio') or radio.get('name'), ch)
            ap_info['radios'][band] = {
                'channel': ch,
                'utilization': radio.get('cu_total', 0),
                'self_rx': radio.get('cu_self_rx', 0),
                'self_tx': radio.get('cu_self_tx', 0),
                'interference': radio.get('cu_total', 0)
                - radio.get('cu_self_rx', 0)
                - radio.get('cu_self_tx', 0),
                'num_sta': radio.get('num_sta', 0),
                'satisfaction': radio.get('satisfaction', -1),
            }

        # Get configured ht from radio_table
        for rt in d.get('radio_table', []):
            rid = rt.get('radio') or rt.get('name')
            band = band_for_radio(rid, rt.get('channel'))
            if band in ap_info['radios']:
                ap_info['radios'][band]['ht'] = rt.get('ht', '20')

        aps.append(ap_info)

    # Build per-band neighbour scores for all candidate channels
    neighbour_scores_5ghz = {
        ch: compute_channel_neighbour_score(all_neighbours, ch, band='na')
        for ch in CHANNELS_5GHZ_ALL
    }
    neighbour_scores_24ghz = {
        ch: compute_channel_neighbour_score(all_neighbours, ch, band='ng')
        for ch in CHANNELS_24GHZ_ALL
    }

    return {
        'timestamp': datetime.now().isoformat(),
        'aps': aps,
        'neighbour_scores': {
            '5ghz': neighbour_scores_5ghz,
            '24ghz': neighbour_scores_24ghz,
        },
    }


def optimize_5ghz(aps: list[dict], neighbour_data: dict | None = None) -> list[dict]:
    """Calculate optimal 5GHz channel assignments weighted by measured utilization.

    Strategy: APs with highest utilization get first pick of the cleanest channels.
    Channel scores are based on measured utilization data from APs currently on that
    channel, plus a DFS penalty for radar-prone channels.
    """
    # Get current 5GHz state
    ap_5ghz = []
    for ap in aps:
        radio = ap['radios'].get('5GHz')
        if radio:
            ap_5ghz.append(
                {
                    'device_id': ap['device_id'],
                    'name': ap['name'],
                    'current_channel': radio['channel'],
                    'utilization': radio['utilization'],
                    'interference': radio['interference'],
                    'num_sta': radio['num_sta'],
                }
            )

    if not ap_5ghz:
        return []

    # Build map of channel -> measured utilization from current assignments
    channel_utilization: dict[int, int] = {}
    for ap in ap_5ghz:
        channel_utilization[ap['current_channel']] = ap['utilization']

    # Sort APs by utilization (worst first — they get first pick)
    ap_5ghz.sort(key=lambda a: -a['utilization'])

    # Score whole 80MHz BLOCKS, not individual primary channels. Reserving primaries
    # only is what allowed 149 + 153 + 157 to be handed out to three APs — identical
    # spectrum under an 80MHz width.
    block_count: dict[int, int] = dict.fromkeys(BLOCKS_5GHZ_80MHZ, 0)
    block_load: dict[int, float] = dict.fromkeys(BLOCKS_5GHZ_80MHZ, 0.0)
    recommendations = []

    def score_block(primary: int, members: tuple[int, ...]) -> float:
        measured = sum(channel_utilization.get(ch, 0) for ch in members)
        dfs_penalty = 15 if primary in (52, 100, 116, 132) else 0
        neighbour_penalty = 0.0
        if neighbour_data:
            per_member = [float(neighbour_data.get(ch, 0.0)) for ch in members]
            neighbour_penalty = min(
                sum(per_member) / len(per_member) if per_member else 0.0,
                NEIGHBOUR_PENALTY_CAP,
            )
        return measured + dfs_penalty + neighbour_penalty

    for ap in ap_5ghz:
        current = ap['current_channel']

        # Fewest occupants first, then cheapest. Sorting on score alone made every AP
        # past the sixth pile onto the single cleanest block (ten APs, six blocks, and
        # ch116 was handed out five times).
        best_primary, best_members = min(
            BLOCKS_5GHZ_80MHZ.items(),
            key=lambda item: (
                block_count[item[0]],
                score_block(item[0], item[1]) + block_load[item[0]],
            ),
        )

        # Don't churn a radio that is already in the winning block: 44 and 36 are the
        # same spectrum, so moving 44 -> 36 buys nothing and drops clients.
        best_ch = current if current in best_members else best_primary

        block_count[best_primary] += 1
        block_load[best_primary] += float(ap['utilization'])
        recommendations.append(
            {
                'device_id': ap['device_id'],
                'name': ap['name'],
                'current_channel': current,
                'recommended_channel': best_ch,
                'current_utilization': ap['utilization'],
                'change_needed': current != best_ch,
            }
        )

    return recommendations


def optimize_24ghz(aps: list[dict], neighbour_data: dict | None = None) -> list[dict]:
    """Calculate optimal 2.4GHz channel assignments weighted by utilization.

    Strategy: distribute APs across channels 1, 6, 11/13 using measured utilization.
    APs on the most congested channels get moved to the least-loaded channel,
    while maintaining even AP count per channel (max difference of 1).
    """
    ap_24ghz = []
    for ap in aps:
        radio = ap['radios'].get('2.4GHz')
        if radio:
            ap_24ghz.append(
                {
                    'device_id': ap['device_id'],
                    'name': ap['name'],
                    'current_channel': radio['channel'],
                    'utilization': radio['utilization'],
                    'interference': radio['interference'],
                    'num_sta': radio['num_sta'],
                }
            )

    if not ap_24ghz:
        return []

    # Detect available channels from current usage
    uses_ch13 = any(a['current_channel'] == 13 for a in ap_24ghz)
    channels = [1, 6, 13] if uses_ch13 else CHANNELS_24GHZ

    # Calculate average utilization per channel (from APs currently on it)
    channel_util: dict[int, list[int]] = {ch: [] for ch in channels}
    for ap in ap_24ghz:
        ch = ap['current_channel']
        # Map non-standard channels to nearest non-overlapping
        if ch not in channels:
            nearest = min(channels, key=lambda c: abs(c - ch))
            channel_util[nearest].append(ap['utilization'])
        else:
            channel_util[ch].append(ap['utilization'])

    avg_util = {
        ch: (sum(utils) / len(utils) if utils else 0) for ch, utils in channel_util.items()
    }

    # Sort APs by utilization (worst first — they get first pick of cleanest channel)
    ap_24ghz.sort(key=lambda a: -a['utilization'])

    # Target: even distribution with max N APs per channel
    max_per_channel = -(-len(ap_24ghz) // len(channels))  # ceiling division
    channel_count: dict[int, int] = dict.fromkeys(channels, 0)
    # Load already committed to each channel by THIS run. Without it the scores stay
    # static and the two busiest APs both pick the same "cleanest" channel — which is
    # how a 37-client and an 18-client AP ended up sharing one channel while a
    # 3-client AP got one to itself.
    assigned_load: dict[int, float] = dict.fromkeys(channels, 0.0)
    recommendations = []

    for ap in ap_24ghz:
        # Score channels: measured avg utilization, penalise if already at max count
        best_ch = ap['current_channel'] if ap['current_channel'] in channels else channels[0]
        best_score = float('inf')

        for ch in channels:
            if channel_count[ch] >= max_per_channel:
                continue
            neighbour_penalty = 0.0
            if neighbour_data:
                neighbour_penalty = min(
                    neighbour_data.get(ch, 0.0),
                    NEIGHBOUR_PENALTY_CAP,
                )
            score = avg_util[ch] + neighbour_penalty + assigned_load[ch]
            if score < best_score:
                best_score = score
                best_ch = ch

        channel_count[best_ch] += 1
        assigned_load[best_ch] += float(ap['utilization'])
        recommendations.append(
            {
                'device_id': ap['device_id'],
                'name': ap['name'],
                'current_channel': ap['current_channel'],
                'recommended_channel': best_ch,
                'current_utilization': ap['utilization'],
                'change_needed': ap['current_channel'] != best_ch,
            }
        )

    return recommendations


def generate_report(
    state: dict,
    recommendations_5ghz: list[dict],
    recommendations_24ghz: list[dict],
) -> dict:
    """Generate a structured report with current state and recommendations."""
    changes_5 = [r for r in recommendations_5ghz if r['change_needed']]
    changes_24 = [r for r in recommendations_24ghz if r['change_needed']]

    return {
        'timestamp': state['timestamp'],
        'summary': {
            'aps_analyzed': len(state['aps']),
            'changes_5ghz': len(changes_5),
            'changes_24ghz': len(changes_24),
            'total_changes': len(changes_5) + len(changes_24),
        },
        'recommendations_5ghz': recommendations_5ghz,
        'recommendations_24ghz': recommendations_24ghz,
    }


def format_report_table(report: dict) -> str:
    """Format report as a rich-compatible table string for terminal display."""
    lines = []
    lines.append(f'📶 Channel Optimisation Report — {report["timestamp"]}')
    lines.append(
        f'   APs: {report["summary"]["aps_analyzed"]} | '
        f'5GHz changes: {report["summary"]["changes_5ghz"]} | '
        f'2.4GHz changes: {report["summary"]["changes_24ghz"]}'
    )
    lines.append('')

    # 5GHz table
    lines.append('5GHz Recommendations:')
    lines.append(f'  {"AP":<22} {"Current":<10} {"Recommended":<13} {"Util":<6} {"Action"}')
    lines.append(f'  {"-" * 22} {"-" * 10} {"-" * 13} {"-" * 6} {"-" * 10}')
    for r in report['recommendations_5ghz']:
        action = 'CHANGE' if r['change_needed'] else 'keep'
        lines.append(
            f'  {r["name"]:<22} ch {r["current_channel"]:<6} ch {r["recommended_channel"]:<9} '
            f'{r["current_utilization"]:>3}%   {action}'
        )

    lines.append('')

    # 2.4GHz table
    lines.append('2.4GHz Recommendations:')
    lines.append(f'  {"AP":<22} {"Current":<10} {"Recommended":<13} {"Util":<6} {"Action"}')
    lines.append(f'  {"-" * 22} {"-" * 10} {"-" * 13} {"-" * 6} {"-" * 10}')
    for r in report['recommendations_24ghz']:
        action = 'CHANGE' if r['change_needed'] else 'keep'
        lines.append(
            f'  {r["name"]:<22} ch {r["current_channel"]:<6} ch {r["recommended_channel"]:<9} '
            f'{r["current_utilization"]:>3}%   {action}'
        )

    return '\n'.join(lines)


def format_report_markdown(report: dict) -> str:
    """Format report as markdown for file output."""
    lines = []
    lines.append('# Channel Optimisation Report')
    lines.append(f'\n**Generated:** {report["timestamp"]}')
    lines.append('\n## Summary\n')
    lines.append(f'- APs analyzed: {report["summary"]["aps_analyzed"]}')
    lines.append(f'- 5GHz channel changes: {report["summary"]["changes_5ghz"]}')
    lines.append(f'- 2.4GHz channel changes: {report["summary"]["changes_24ghz"]}')

    lines.append('\n## 5GHz Channel Plan\n')
    lines.append('| AP | Current | Recommended | Utilization | Action |')
    lines.append('|---|---|---|---|---|')
    for r in report['recommendations_5ghz']:
        action = '⚡ CHANGE' if r['change_needed'] else '✅ Keep'
        lines.append(
            f'| {r["name"]} | Ch {r["current_channel"]} | Ch {r["recommended_channel"]} | '
            f'{r["current_utilization"]}% | {action} |'
        )

    lines.append('\n## 2.4GHz Channel Plan\n')
    lines.append('| AP | Current | Recommended | Utilization | Action |')
    lines.append('|---|---|---|---|---|')
    for r in report['recommendations_24ghz']:
        action = '⚡ CHANGE' if r['change_needed'] else '✅ Keep'
        lines.append(
            f'| {r["name"]} | Ch {r["current_channel"]} | Ch {r["recommended_channel"]} | '
            f'{r["current_utilization"]}% | {action} |'
        )

    return '\n'.join(lines)


# ─── MCP Tool Handlers ────────────────────────────────────────────────────────


async def optimize_radio_channels_mcp(band: str = 'both') -> dict:
    """Auto-optimise Wi-Fi channel assignments based on utilization data.

    When to use this tool:
    - When users report slow Wi-Fi or interference
    - After adding new APs to the network
    - During periodic network maintenance
    - When channel utilization is high on specific APs

    Args:
        band: Band to optimise - '5ghz', '2.4ghz', or 'both' (default)

    Returns:
        Report with current state and recommended channel changes
    """
    state = await analyze_channels()
    aps = state['aps']
    nb = state.get('neighbour_scores', {})
    rec_5 = optimize_5ghz(aps, neighbour_data=nb.get('5ghz')) if band in ('5ghz', 'both') else []
    rec_24 = (
        optimize_24ghz(aps, neighbour_data=nb.get('24ghz')) if band in ('2.4ghz', 'both') else []
    )
    return generate_report(state, rec_5, rec_24)


async def get_radio_channel_report_mcp() -> str:
    """Generate a channel utilization report in markdown format.

    When to use this tool:
    - To assess current Wi-Fi channel health
    - Before and after channel changes for comparison
    - When investigating Wi-Fi performance issues

    Returns:
        Markdown-formatted channel report
    """
    state = await analyze_channels()
    aps = state['aps']
    nb = state.get('neighbour_scores', {})
    rec_5 = optimize_5ghz(aps, neighbour_data=nb.get('5ghz'))
    rec_24 = optimize_24ghz(aps, neighbour_data=nb.get('24ghz'))
    report = generate_report(state, rec_5, rec_24)
    return format_report_markdown(report)
