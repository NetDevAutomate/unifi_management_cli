#!/usr/bin/env python3
"""Raise 5GHz TX power mode to 'auto' on low-power APs.

Many APs are pinned at 'auto' mode name with tx_power=6 dBm, which is too low
and causes downlink ACK loss → client-side retry storms. Setting mode to 'auto'
without a fixed tx_power lets the controller manage power based on neighbours.

Skips APs already at tx_power_mode=auto with no manual tx_power override.
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

DRY_RUN_NOTE = """
🔍 DRY RUN — re-run with --apply to commit.
"""


def get_session() -> tuple[requests.Session, str, str]:
    """Return an authenticated session with the controller base URL and site."""
    base = os.environ['UNIFI_URL'].rstrip('/')
    token = os.environ['UNIFI_CONSOLE_API_TOKEN']
    site = os.environ.get('UNIFI_SITE', 'default')
    s = requests.Session()
    s.verify = False
    s.headers.update({'X-API-Key': token, 'Accept': 'application/json'})
    return s, base, site


def needs_update(radio: dict[str, Any]) -> bool:
    """Return True if this 5GHz radio is pinned below auto and should be raised."""
    tx_power = radio.get('tx_power')
    mode = radio.get('tx_power_mode')
    # The pathological case observed: mode=auto but tx_power=6 (manual override).
    # Clearing tx_power lets auto algorithm run.
    try:
        if tx_power is not None and str(tx_power).isdigit() and int(tx_power) < 18:
            return True
    except (ValueError, TypeError):
        pass
    if mode == 'low':
        return True
    if mode == 'medium':
        return True
    return False


def apply_change(
    s: requests.Session, base: str, site: str, device: dict[str, Any]
) -> dict[str, Any]:
    """PUT updated radio_table with tx_power cleared + mode=auto on 5GHz."""
    device_id = device['_id']
    mac = device['mac']
    name = device.get('name', '?')

    radio_table = list(device.get('radio_table', []))
    changed = False
    for radio in radio_table:
        if radio.get('radio') != 'na':
            continue
        if not needs_update(radio):
            continue
        # Force auto mode, remove manual tx_power override
        radio['tx_power_mode'] = 'auto'
        if 'tx_power' in radio:
            del radio['tx_power']  # API rejects null — key must be absent
        changed = True
        break

    if not changed:
        return {'name': name, 'status': 'skipped', 'reason': 'already auto'}

    payload = {
        '_id': device_id,
        'mac': mac,
        'radio_table': radio_table,
    }
    url = f'{base}/proxy/network/api/s/{site}/rest/device/{device_id}'
    r = s.put(url, json=payload, timeout=15)
    if r.status_code >= 300:
        return {'name': name, 'status': 'failed', 'http': r.status_code, 'error': r.text[:200]}
    return {'name': name, 'status': 'applied'}


def main() -> int:
    """Raise 5GHz TX power to auto on low-power APs, or preview under dry-run."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Commit (default: dry-run)')
    args = parser.parse_args()

    s, base, site = get_session()
    devices = [
        d
        for d in s.get(f'{base}/proxy/network/api/s/{site}/stat/device', timeout=10)
        .json()
        .get('data', [])
        if d.get('type') == 'uap'
    ]

    # Plan
    plan: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for d in sorted(devices, key=lambda x: x.get('name') or ''):
        radio = next((r for r in d.get('radio_table', []) if r.get('radio') == 'na'), None)
        if not radio:
            continue
        if needs_update(radio):
            plan.append((d, radio))

    if not plan:
        print('✅ No APs need TX power updates — all on auto already.')
        return 0

    print(f'📋 {len(plan)} AP(s) will have 5GHz TX power raised to auto:\n')
    print(f'{"AP":<26}{"Current mode":>14}{"Current power":>16}{"→":>4}{"New":>10}')
    print('-' * 76)
    for d, radio in plan:
        print(
            f'{(d.get("name") or "?")[:24]:<26}'
            f'{str(radio.get("tx_power_mode")):>14}'
            f'{str(radio.get("tx_power")) + " dBm":>16}'
            f'{"→":>4}'
            f'{"auto":>10}'
        )

    if not args.apply:
        print(DRY_RUN_NOTE)
        return 0

    print(f'\n⚡ Applying to {len(plan)} AP(s)...\n')
    results: list[dict[str, Any]] = []
    for d, _ in plan:
        print(f'  → {d.get("name")}: ', end='', flush=True)
        r = apply_change(s, base, site, d)
        results.append(r)
        print(r['status'].upper() + (f' ({r.get("error", "")[:80]})' if r.get('error') else ''))
        time.sleep(1.5)

    success = sum(1 for r in results if r['status'] == 'applied')
    failed = [r for r in results if r['status'] not in ('applied', 'skipped')]

    print(f'\n✅ Applied: {success}/{len(results)}')
    if failed:
        print(f'❌ Failed: {len(failed)}')
        for r in failed:
            print(f'    - {r["name"]}: {r.get("error", r.get("status"))}')
        return 2

    print('\n🕐 Radios may briefly re-tune. Wait 60-90s before re-measuring retry rates.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
