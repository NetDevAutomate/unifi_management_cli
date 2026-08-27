#!/usr/bin/env python3
"""Apply 5GHz channel + width plan to reduce inter-AP contention.

After a power disruption 5 APs rebooted and auto-selected overlapping 80MHz
blocks. This script narrows all APs to 40MHz and assigns non-overlapping
channels, giving every AP its own airtime.

The AP holding the user's current Wi-Fi association is applied LAST.
"""

from __future__ import annotations

import argparse
import os
import requests
import sys
import time
import urllib3
from typing import Any


urllib3.disable_warnings()

# -----------------------------------------------------------------------------
# Plan: (name, 5GHz primary channel, 80|40|20 width MHz)
# -----------------------------------------------------------------------------
CHANNEL_PLAN: list[tuple[str, int, int]] = [
    ('Charlie2 U6-Pro', 36, 40),
    ('Juliett U6 IW', 120, 40),
    ('Hotel3 U6-Pro', 132, 40),
    ('Yankee U6-Pro', 52, 40),
    ('Mike2 U6 Pro', 60, 40),
    ('Bravo4 U6-Pro', 112, 40),
    ('Victor3 U6-Pro', 149, 40),
    ('Sierra3 U6-Pro', 157, 40),
    ('U6 LR', 161, 40),
    # Oscar-Papa goes LAST — this is the AP the operator is connected via.
    ('Oscar Papa U6-Pro', 140, 40),
]


def get_session() -> tuple[requests.Session, str, str]:
    """Return an authenticated session with the controller base URL and site."""
    base = os.environ['UNIFI_URL'].rstrip('/')
    token = os.environ['UNIFI_CONSOLE_API_TOKEN']
    site = os.environ.get('UNIFI_SITE', 'default')
    s = requests.Session()
    s.verify = False
    s.headers.update({'X-API-Key': token, 'Accept': 'application/json'})
    return s, base, site


def load_devices(s: requests.Session, base: str, site: str) -> list[dict[str, Any]]:
    """Fetch the full device list for a site."""
    r = s.get(f'{base}/proxy/network/api/s/{site}/stat/device', timeout=10)
    r.raise_for_status()
    return [d for d in r.json().get('data', []) if d.get('type') == 'uap']


def apply_change(
    s: requests.Session,
    base: str,
    site: str,
    device: dict[str, Any],
    new_channel: int,
    new_width: int,
) -> dict[str, Any]:
    """PUT new radio config to a single AP. Returns summary dict."""
    mac = device['mac']
    name = device.get('name', '?')
    device_id = device['_id']

    # Preserve the full radio_table, only modifying the 5GHz (na) entry.
    radio_table = list(device.get('radio_table', []))
    modified = False
    for radio in radio_table:
        if radio.get('radio') == 'na':
            radio['channel'] = new_channel
            radio['ht'] = new_width  # 'ht' is the width field in UniFi API
            radio['tx_power_mode'] = radio.get('tx_power_mode', 'auto')
            modified = True
            break

    if not modified:
        return {'name': name, 'status': 'skipped', 'error': 'no 5GHz radio found'}

    payload = {
        '_id': device_id,
        'mac': mac,
        'radio_table': radio_table,
    }

    url = f'{base}/proxy/network/api/s/{site}/rest/device/{device_id}'
    r = s.put(url, json=payload, timeout=15)

    if r.status_code >= 300:
        return {
            'name': name,
            'status': 'failed',
            'http': r.status_code,
            'error': r.text[:200],
        }

    return {
        'name': name,
        'status': 'applied',
        'channel': new_channel,
        'width': new_width,
    }


def main() -> int:
    """Apply the 5GHz channel and width plan, or preview it under dry-run."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Commit (default: dry-run)')
    args = parser.parse_args()

    s, base, site = get_session()
    devices = load_devices(s, base, site)
    by_name = {d.get('name'): d for d in devices}

    # Build actionable changes
    plan: list[tuple[dict[str, Any], int, int, dict[str, int]]] = []
    missing: list[str] = []
    for name, ch, width in CHANNEL_PLAN:
        d = by_name.get(name)
        if not d:
            missing.append(name)
            continue
        current = next((r for r in d.get('radio_table', []) if r.get('radio') == 'na'), {})
        cur_ch = current.get('channel')
        cur_w = current.get('ht')
        if str(cur_ch) == str(ch) and str(cur_w) == str(width):
            continue
        plan.append((d, ch, width, {'ch': cur_ch, 'w': cur_w}))

    if missing:
        print('⚠️  Not found on controller:')
        for m in missing:
            print(f'    - {m}')

    if not plan:
        print('✅ All APs already match the plan. Nothing to do.')
        return 0

    print(f'\n📋 {len(plan)} AP change(s) proposed:\n')
    print(f'{"AP":<24}{"Current":>14}{"→":>4}{"New":>12}')
    print('-' * 56)
    for d, ch, width, before in plan:
        print(
            f'{d.get("name", "?")[:22]:<24}'
            f'{f"ch{before['ch']}@{before['w']}MHz":>14}'
            f'{"→":>4}'
            f'{f"ch{ch}@{width}MHz":>12}'
        )

    if not args.apply:
        print('\n🔍 DRY RUN — re-run with --apply to commit.')
        return 0

    print('\n⚡ Applying changes (Oscar-Papa LAST to preserve shell Wi-Fi)...\n')
    results: list[dict[str, Any]] = []
    for d, ch, width, _ in plan:
        print(f'  → {d.get("name")}: setting ch{ch}@{width}MHz ... ', end='', flush=True)
        r = apply_change(s, base, site, d, ch, width)
        results.append(r)
        print(r['status'].upper() + (f' ({r.get("error", "")[:80]})' if r.get('error') else ''))
        # Brief inter-AP pause to avoid controller queue backlog
        time.sleep(1.5)

    success = sum(1 for r in results if r['status'] == 'applied')
    failed = [r for r in results if r['status'] != 'applied']

    print(f'\n✅ Applied: {success}/{len(results)}')
    if failed:
        print(f'❌ Failed:  {len(failed)}')
        for r in failed:
            print(f'    - {r["name"]}: {r.get("error", r.get("status"))}')
        return 2

    print('\n🕐 APs will restart their 5GHz radios over the next 30–60s.')
    print('   Your Wi-Fi may drop briefly when Oscar Papa U6-Pro applies.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
