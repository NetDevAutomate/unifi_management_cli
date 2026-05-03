"""Neighbour AP scan for UniFi networks.

Triggers RF environment scans on APs and reports neighbouring networks
per channel to identify external interference sources.
"""

import asyncio
from datetime import datetime
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def scan_neighbours(
    ap_name: str | None = None,
    wait_seconds: int = 30,
) -> dict:
    """Trigger RF scan on APs and collect neighbour results.

    Args:
        ap_name: Specific AP to scan (None = all APs, sequential)
        wait_seconds: How long to wait for scan results (default 30s)

    Returns:
        Report with neighbour APs per channel
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()

    aps = [d for d in devices if d.get('type') == 'uap']
    if ap_name:
        aps = [d for d in aps if ap_name.lower() in d.get('name', '').lower()]
        if not aps:
            raise ToolError(
                message=f"No AP matching '{ap_name}' found",
                error_code=ErrorCodes.NO_DATA,
            )

    results = []
    for ap in aps:
        mac = ap['mac']
        name = ap.get('name', 'Unknown')

        # Trigger scan
        async with UniFiClient() as client:
            path = client.build_path('cmd/devmgr')
            try:
                await client.post(path, {'cmd': 'spectrum-scan', 'mac': mac})
            except ToolError as e:
                if 'InProgress' in str(e):
                    pass  # Already scanning, just wait
                else:
                    results.append({'ap': name, 'status': 'SCAN_FAILED', 'error': str(e)})
                    continue

        # Wait for scan to complete
        await asyncio.sleep(wait_seconds)

        # Read results
        async with UniFiClient() as client:
            devices2 = await client.get_devices()

        ap2 = next((d for d in devices2 if d['mac'] == mac), None)
        if not ap2:
            continue

        scan_table = ap2.get('scan_radio_table', [])
        if not scan_table:
            results.append({'ap': name, 'status': 'NO_RESULTS', 'neighbours': []})
            continue

        # Parse neighbours
        neighbours = []
        for entry in scan_table:
            neighbours.append(
                {
                    'bssid': entry.get('bssid', ''),
                    'ssid': entry.get('essid', '<hidden>'),
                    'channel': entry.get('channel', 0),
                    'rssi': entry.get('rssi', 0),
                    'security': entry.get('security', ''),
                    'is_adhoc': entry.get('is_adhoc', False),
                }
            )

        # Sort by signal strength
        neighbours.sort(key=lambda x: -(x.get('rssi') or -100))

        # Summarise by channel
        channel_summary: dict[int, int] = {}
        for n in neighbours:
            ch = n['channel']
            channel_summary[ch] = channel_summary.get(ch, 0) + 1

        results.append(
            {
                'ap': name,
                'status': 'OK',
                'total_neighbours': len(neighbours),
                'channel_summary': dict(sorted(channel_summary.items())),
                'strongest': neighbours[:10],
            }
        )

    return {
        'timestamp': datetime.now().isoformat(),
        'aps_scanned': len(results),
        'results': results,
    }


async def get_cached_neighbours() -> dict:
    """Read any cached scan results without triggering new scans.

    Useful for checking results after a scan has already been triggered.
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()

    results = []
    for d in devices:
        if d.get('type') != 'uap':
            continue
        scan_table = d.get('scan_radio_table', [])
        if not scan_table:
            continue

        neighbours = []
        channel_summary: dict[int, int] = {}
        for entry in scan_table:
            ch = entry.get('channel', 0)
            channel_summary[ch] = channel_summary.get(ch, 0) + 1
            neighbours.append(
                {
                    'bssid': entry.get('bssid', ''),
                    'ssid': entry.get('essid', '<hidden>'),
                    'channel': entry.get('channel', 0),
                    'rssi': entry.get('rssi', 0),
                }
            )

        neighbours.sort(key=lambda x: -(x.get('rssi') or -100))
        results.append(
            {
                'ap': d.get('name', 'Unknown'),
                'total_neighbours': len(neighbours),
                'channel_summary': dict(sorted(channel_summary.items())),
                'strongest': neighbours[:10],
            }
        )

    return {
        'timestamp': datetime.now().isoformat(),
        'aps_with_data': len(results),
        'results': results,
    }
