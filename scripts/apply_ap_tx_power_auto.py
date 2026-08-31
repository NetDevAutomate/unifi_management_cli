#!/usr/bin/env python3
"""Release 5GHz transmit power back to the controller's auto algorithm.

Some APs sit at `tx_power_mode='auto'` while a manual `tx_power` of 6 dBm still
pins them low, which costs downlink ACKs and shows up as client-side retry
storms. Because the mode already reads 'auto', setting the mode alone is a
no-op: the manual override has to be DELETED. The controller rejects a null
value, so the key must be absent from the payload - which is what
`remove_fields` on a radio change does.

Writes go through `apply_radio_config`, the repo's tested apply path, rather
than raw HTTP. `UniFiClient` raises on a non-2xx response AND on
`meta.rc == 'error'`, which the controller returns with HTTP 200 for a REJECTED
update; a hand-rolled `requests` version of this script reported those as
'applied'. The client also preserves `config_version` and force-provisions the
device, which a bare PUT omits.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from unifi_mapper.analysis.radio_config import apply_radio_config
from unifi_mapper.cli import get_default_config_path, load_env_from_config
from unifi_mapper.core.utils.client import UniFiClient


def load_config(config: str | None = None) -> None:
    """Populate the environment from the config file, exactly as `unifi-mapper` does.

    `UniFiClient` reads UNIFI_URL / UNIFI_CONSOLE_API_TOKEN from os.environ and
    does NOT read the config file itself, so a script that skips this step fails
    with 'No credentials found from any source' even when the config is present.
    """
    path = Path(config).expanduser() if config else get_default_config_path()
    load_env_from_config(str(path))


# A radio reporting less than this many dBm is treated as pinned low.
MIN_ACCEPTABLE_DBM = 18


def needs_update(radio: dict[str, Any]) -> bool:
    """Return True if this radio is held below auto and should be released."""
    tx_power = radio.get('tx_power')
    if tx_power is not None and str(tx_power).isdigit() and int(tx_power) < MIN_ACCEPTABLE_DBM:
        return True
    return radio.get('tx_power_mode') in ('low', 'medium')


def change_for(device: dict[str, Any]) -> dict[str, Any]:
    """Build the radio change that releases a device's 5GHz power to auto."""
    return {
        'device_id': device['_id'],
        'radio': 'na',
        'tx_power_mode': 'auto',
        # Set-and-delete in one change: mode to auto, manual override removed.
        'remove_fields': ['tx_power'],
    }


async def _load_aps() -> list[dict[str, Any]]:
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return [d for d in devices if d.get('type') == 'uap']


def _radio_5ghz(device: dict[str, Any]) -> dict[str, Any] | None:
    return next((r for r in device.get('radio_table', []) if r.get('radio') == 'na'), None)


async def main() -> int:
    """Release 5GHz TX power to auto on pinned APs, or preview under dry-run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit (default: dry-run)')
    parser.add_argument('--config', help='Path to a .env config file (default: XDG lookup)')
    args = parser.parse_args()

    load_config(args.config)

    try:
        devices = await _load_aps()
    except Exception as exc:
        print(f'Could not read the device list: {exc}')
        return 2

    pinned: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for device in sorted(devices, key=lambda d: d.get('name') or ''):
        radio = _radio_5ghz(device)
        if radio is not None and needs_update(radio):
            pinned.append((device, radio))

    if not pinned:
        print('No APs are pinned below auto. Nothing to do.')
        return 0

    print(f'{len(pinned)} AP(s) will have 5GHz TX power released to auto:\n')
    print(f'{"AP":<26}{"Mode":>10}{"Power":>12}{"New":>14}')
    print('-' * 62)
    for device, radio in pinned:
        name = (device.get('name') or '?')[:24]
        power = f'{radio.get("tx_power")} dBm'
        print(f'{name:<26}{str(radio.get("tx_power_mode")):>10}{power:>12}{"auto":>14}')

    changes = [change_for(device) for device, _ in pinned]

    if not args.apply:
        results = await apply_radio_config(changes, dry_run=True)
        print(f'\nDRY RUN - {len(results)} radio write(s) would be made.')
        print('Re-run with --apply to commit.')
        return 0

    print(f'\nApplying to {len(changes)} AP(s)...\n')
    results: list[dict[str, Any]] = []
    for (device, _), change in zip(pinned, changes, strict=True):
        print(f'  -> {device.get("name")}: ', end='', flush=True)
        applied = await apply_radio_config([change], dry_run=False)
        results.extend(applied)
        print(', '.join(r.get('status', '?') for r in applied))
        # Pace the writes: each apply force-provisions the AP, and back-to-back
        # provisions were observed backing up the controller queue.
        await asyncio.sleep(1.5)

    ok = [r for r in results if r.get('status') == 'APPLIED']
    bad = [r for r in results if r.get('status') != 'APPLIED']
    print(f'\nApplied: {len(ok)}/{len(results)}')
    if bad:
        print(f'Failed: {len(bad)}')
        for r in bad:
            print(f'    - {r.get("name", r.get("device_id"))}: {r.get("status")}')
        return 2

    print('\nRadios may briefly re-tune. Wait 60-90s before re-measuring retry rates.')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
