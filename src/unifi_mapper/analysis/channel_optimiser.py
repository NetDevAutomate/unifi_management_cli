"""Auto-channel optimiser for UniFi APs.

Analyses current channel utilization and recommends optimal channel assignments
for both 5GHz and 2.4GHz bands. Generates before/after reports in table and markdown format.
"""

from datetime import datetime
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
            band = '5GHz' if ch > 14 else '2.4GHz'
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
            band = '5GHz' if rid == 'na' else '2.4GHz'
            if band in ap_info['radios']:
                ap_info['radios'][band]['ht'] = rt.get('ht', '20')

        aps.append(ap_info)

    return {'timestamp': datetime.now().isoformat(), 'aps': aps}


def optimize_5ghz(aps: list[dict]) -> list[dict]:
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

    # Available 80MHz-compatible primary channels
    available = [36, 44, 52, 60, 100, 108, 112, 116, 120, 132, 140, 149, 153, 157, 161]
    used_channels: set[int] = set()
    recommendations = []

    for ap in ap_5ghz:
        current = ap['current_channel']

        # Score each channel: measured utilization + DFS penalty
        best_ch = current
        best_score = float('inf')

        for ch in available:
            if ch in used_channels:
                continue
            measured_util = channel_utilization.get(ch, 0)
            dfs_penalty = 15 if 52 <= ch <= 144 else 0
            score = measured_util + dfs_penalty

            if score < best_score:
                best_score = score
                best_ch = ch

        used_channels.add(best_ch)
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


def optimize_24ghz(aps: list[dict]) -> list[dict]:
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
    recommendations = []

    for ap in ap_24ghz:
        # Score channels: measured avg utilization, penalise if already at max count
        best_ch = ap['current_channel'] if ap['current_channel'] in channels else channels[0]
        best_score = float('inf')

        for ch in channels:
            if channel_count[ch] >= max_per_channel:
                continue
            score = avg_util[ch]
            if score < best_score:
                best_score = score
                best_ch = ch

        channel_count[best_ch] += 1
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
    rec_5 = optimize_5ghz(aps) if band in ('5ghz', 'both') else []
    rec_24 = optimize_24ghz(aps) if band in ('2.4ghz', 'both') else []
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
    rec_5 = optimize_5ghz(aps)
    rec_24 = optimize_24ghz(aps)
    report = generate_report(state, rec_5, rec_24)
    return format_report_markdown(report)
