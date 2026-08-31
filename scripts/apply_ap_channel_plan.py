#!/usr/bin/env python3
"""Apply a 5GHz channel + width plan to reduce inter-AP contention.

After a power disruption several APs rebooted and auto-selected overlapping
80MHz blocks. This narrows every AP to 40MHz on a non-overlapping block, giving
each its own airtime.

Writes go through `apply_radio_config`, the repo's tested apply path, rather
than raw HTTP. That is deliberate and load-bearing: `UniFiClient` raises on a
non-2xx response AND on `meta.rc == 'error'`, which the controller returns with
HTTP 200 for a *rejected* update. A hand-rolled `requests` version of this
script reported such rejections as 'applied'. Going through the client also
preserves `config_version` on the payload and force-provisions the device, both
of which a bare PUT omits.

The AP holding the operator's own Wi-Fi association is applied LAST.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
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


# -----------------------------------------------------------------------------
# Plan: (AP name, 5GHz primary channel, width MHz as the controller stores it)
#
# `ht` is a STRING in this codebase (radio_config.py writes '80'); an int is
# accepted by the API and then ignored - the silent-no-op class that
# _coerce_radio_value's docstring warns about.
#
# Every entry must occupy a distinct 40MHz block. `find_overlaps` enforces it at
# startup, so a self-colliding plan cannot reach the network.
# -----------------------------------------------------------------------------
CHANNEL_PLAN: list[tuple[str, int, str]] = [
    ('Charlie2 U6-Pro', 36, '40'),
    # Was 161, which shares the 157+161 block with Sierra3 below - two APs on
    # identical spectrum, in a script whose purpose is removing contention.
    # 44+48 is the only free NON-DFS block, so a long-range AP is not subject
    # to radar-triggered channel changes.
    ('U6 LR', 44, '40'),
    ('Yankee U6-Pro', 52, '40'),
    ('Mike2 U6 Pro', 60, '40'),
    ('Bravo4 U6-Pro', 112, '40'),
    ('Juliett U6 IW', 120, '40'),
    ('Hotel3 U6-Pro', 132, '40'),
    ('Victor3 U6-Pro', 149, '40'),
    ('Sierra3 U6-Pro', 157, '40'),
    # Oscar-Papa goes LAST - this is the AP the operator is connected via.
    ('Oscar Papa U6-Pro', 140, '40'),
]

# Canonical 5GHz bonded blocks. A primary channel plus a width determines which
# 20MHz channels are actually occupied, which is what "non-overlapping" means.
_BLOCKS_40 = (
    (36, 40),
    (44, 48),
    (52, 56),
    (60, 64),
    (100, 104),
    (108, 112),
    (116, 120),
    (124, 128),
    (132, 136),
    (140, 144),
    (149, 153),
    (157, 161),
)
_BLOCKS_80 = (
    (36, 40, 44, 48),
    (52, 56, 60, 64),
    (100, 104, 108, 112),
    (116, 120, 124, 128),
    (132, 136, 140, 144),
    (149, 153, 157, 161),
)


def occupied_channels(channel: int, width: str) -> tuple[int, ...]:
    """Return the 20MHz channels a radio occupies at this primary and width."""
    if width == '20':
        return (channel,)
    table = _BLOCKS_40 if width == '40' else _BLOCKS_80 if width == '80' else ()
    for block in table:
        if channel in block:
            return tuple(block)
    # Unknown width or a primary outside the standard blocks: treat the channel
    # itself as occupied rather than silently claiming no spectrum.
    return (channel,)


def find_overlaps(plan: list[tuple[str, int, str]]) -> list[tuple[str, str, tuple[int, ...]]]:
    """Return (ap_a, ap_b, shared_channels) for every overlapping pair in a plan."""
    spans = [(name, set(occupied_channels(ch, width))) for name, ch, width in plan]
    clashes: list[tuple[str, str, tuple[int, ...]]] = []
    for i, (name_a, span_a) in enumerate(spans):
        for name_b, span_b in spans[i + 1 :]:
            shared = span_a & span_b
            if shared:
                clashes.append((name_a, name_b, tuple(sorted(shared))))
    return clashes


async def _load_aps() -> dict[str, dict]:
    """Return adopted APs by name."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return {d['name']: d for d in devices if d.get('type') == 'uap' and d.get('name')}


def _current_5ghz(device: dict) -> dict:
    return next((r for r in device.get('radio_table', []) if r.get('radio') == 'na'), {})


async def main() -> int:
    """Apply the 5GHz channel and width plan, or preview it under dry-run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Commit (default: dry-run)')
    parser.add_argument('--config', help='Path to a .env config file (default: XDG lookup)')
    args = parser.parse_args()

    # Validate the plan BEFORE touching config or the network: it is a pure data
    # check, so a self-colliding plan should be reported even with no credentials.
    overlaps = find_overlaps(CHANNEL_PLAN)
    if overlaps:
        print('CHANNEL_PLAN is self-inconsistent - refusing to touch the network:')
        for name_a, name_b, shared in overlaps:
            print(f'    {name_a} and {name_b} both occupy {list(shared)}')
        return 2

    load_config(args.config)

    try:
        by_name = await _load_aps()
    except Exception as exc:
        print(f'Could not read the device list: {exc}')
        return 2

    changes: list[dict] = []
    rows: list[tuple[str, str, str]] = []
    missing: list[str] = []

    for name, channel, width in CHANNEL_PLAN:
        device = by_name.get(name)
        if device is None:
            missing.append(name)
            continue
        current = _current_5ghz(device)
        if str(current.get('channel')) == str(channel) and str(current.get('ht')) == width:
            continue
        changes.append(
            {
                'device_id': device['_id'],
                'radio': 'na',
                'channel': channel,
                'ht': width,
            }
        )
        rows.append(
            (
                name,
                f'ch{current.get("channel")}@{current.get("ht")}MHz',
                f'ch{channel}@{width}MHz',
            )
        )

    if missing:
        print('Not found on the controller:')
        for name in missing:
            print(f'    - {name}')

    if not changes:
        print('All APs already match the plan. Nothing to do.')
        return 0 if not missing else 2

    print(f'\n{len(changes)} AP change(s) proposed:\n')
    print(f'{"AP":<24}{"Current":>16}{"New":>18}')
    print('-' * 58)
    for name, before, after in rows:
        print(f'{name[:22]:<24}{before:>16}{after:>18}')

    if not args.apply:
        results = await apply_radio_config(changes, dry_run=True)
        print(f'\nDRY RUN - {len(results)} radio write(s) would be made.')
        not_found = [r for r in results if r.get('status') == 'NOT_FOUND']
        if not_found:
            print(f'{len(not_found)} change(s) resolved to no device.')
        print('Re-run with --apply to commit.')
        return 0

    print('\nApplying (Oscar-Papa last, to preserve the operator shell)...\n')
    results: list[dict] = []
    for change, (name, _, after) in zip(changes, rows, strict=True):
        print(f'  -> {name}: {after} ... ', end='', flush=True)
        applied = await apply_radio_config([change], dry_run=False)
        results.extend(applied)
        print(', '.join(r.get('status', '?') for r in applied))
        # Pace the writes: each apply force-provisions the AP, and the original
        # operator run found back-to-back provisions backing up the controller.
        await asyncio.sleep(1.5)

    ok = [r for r in results if r.get('status') == 'APPLIED']
    bad = [r for r in results if r.get('status') != 'APPLIED']
    print(f'\nApplied: {len(ok)}/{len(results)}')
    if bad:
        print(f'Failed: {len(bad)}')
        for r in bad:
            print(f'    - {r.get("name", r.get("device_id"))}: {r.get("status")}')
        return 2

    print('\nAPs will restart their 5GHz radios over the next 30-60s.')
    print('Wi-Fi may drop briefly when Oscar Papa U6-Pro applies.')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
