#!/usr/bin/env python3
"""Explain why `ports refresh` proposes so few changes - read-only census.

`ports refresh` reports DRIFT, not coverage: it lists only ports whose label
needs changing. A small number usually means the rest are already correct, but
it cannot distinguish that from a guard over-suppressing, or from a port the
resolver simply cannot name.

This walks the same devices through the same decision functions imported from
`analysis.port_naming`, so it cannot drift from the real logic, and reports
which bucket every connected switch port lands in.

READ-ONLY BY CONSTRUCTION: it fetches and prints. There is no apply path and no
--apply flag, so it cannot modify the network.

Two buckets are worth attention:

  lldp-peer-not-adopted  The port HAS an LLDP neighbour, but resolve_peer only
                         names adopted UniFi devices (it looks chassis_id up in
                         the device registry). A NAS, printer or third-party
                         switch is discarded here.
  client-missing-sw-port A wired client exists whose controller record has no
                         sw_mac/sw_port, so it cannot be tied to a port.
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from typing import Any
from unifi_mapper.analysis.port_naming import (
    NAME_MAX,
    index_wired_clients,
    is_cosmetic_change,
    name_quality,
    resolve_peer,
    strip_multi_suffix,
    would_lose_information,
)
from unifi_mapper.core.utils.client import UniFiClient


def classify_port(
    port: dict[str, Any],
    lldp_entry: dict[str, Any],
    unifi_by_mac: dict[str, dict[str, Any]],
    wired_names: list[str],
    had_lldp: bool,
) -> tuple[str, str]:
    """Return (bucket, detail) for one UP switch port, mirroring the real plan logic."""
    current = str(port.get('name') or '')

    proposed = resolve_peer(lldp_entry, unifi_by_mac, NAME_MAX)
    if not proposed:
        names = sorted(set(wired_names), key=name_quality)
        if len(names) == 1:
            proposed = names[0]
        elif len(names) > 1:
            proposed = f'{names[0]} +{len(names) - 1}'

    if not proposed:
        if had_lldp:
            return 'lldp-peer-not-adopted', f'current={current!r}'
        return 'nothing-reported', f'current={current!r}'

    proposed = proposed[:NAME_MAX]

    if proposed == current:
        return 'already-correct', current
    if is_cosmetic_change(current, proposed):
        return 'cosmetic-only', f'{current!r} -> {proposed!r}'
    if would_lose_information(current, proposed):
        return 'would-downgrade', f'{current!r} -> {proposed!r}'
    if strip_multi_suffix(current) == strip_multi_suffix(proposed):
        return 'multi-suffix-same', f'{current!r} -> {proposed!r}'
    return 'WOULD-RENAME', f'{current!r} -> {proposed!r}'


async def main() -> int:
    """Print the port-label census."""
    try:
        async with UniFiClient() as client:
            devices = await client.get_devices()
            clients = await client.get_clients()
    except Exception as exc:
        print(f'Could not read the controller: {exc}')
        return 2

    unifi_by_mac = {d['mac']: d for d in devices if d.get('mac')}
    wired = index_wired_clients(clients)

    buckets: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    switches = 0
    ports_total = 0
    ports_down = 0
    non_switch_ports = 0

    for device in devices:
        dev_name = str(device.get('name') or '?')
        table = device.get('port_table') or []
        if device.get('type') != 'usw':
            non_switch_ports += len(table)
            continue
        switches += 1
        lldp = {e.get('local_port_idx'): e for e in (device.get('lldp_table') or [])}

        for port in table:
            ports_total += 1
            if not port.get('up'):
                ports_down += 1
                continue
            idx = port.get('port_idx')
            entry = lldp.get(idx, {})
            key = (str(device.get('mac')), int(idx))
            bucket, detail = classify_port(
                port, entry, unifi_by_mac, wired.get(key, []), bool(entry)
            )
            buckets[bucket].append((dev_name, int(idx), detail))

    up_ports = ports_total - ports_down
    print('PORT LABEL CENSUS\n')
    print(f'  switches (type=usw)        {switches}')
    print(f'  switch ports total         {ports_total}')
    print(f'    down (never touched)     {ports_down}')
    print(f'    up   (considered)        {up_ports}')
    print(f'  ports on non-switches      {non_switch_ports}  (gateway/APs: out of scope)')
    print(f'  wired clients tied to port {len(wired)}')
    print(f'  wired clients total        {sum(1 for c in clients if c.get("is_wired"))}')

    print('\nEvery UP switch port, by outcome:\n')
    order = [
        'WOULD-RENAME',
        'already-correct',
        'nothing-reported',
        'lldp-peer-not-adopted',
        'would-downgrade',
        'cosmetic-only',
        'multi-suffix-same',
    ]
    for bucket in order:
        rows = buckets.get(bucket, [])
        if not rows:
            continue
        print(f'  {bucket}  ({len(rows)})')
        for dev_name, idx, detail in sorted(rows):
            print(f'      {dev_name[:30]:<32} port {idx:<3} {detail}')
        print()

    accounted = sum(len(v) for v in buckets.values())
    if accounted != up_ports:
        print(f'  NOTE: {accounted} classified vs {up_ports} up ports - buckets are incomplete.')

    print(f'`ports refresh` would propose {len(buckets.get("WOULD-RENAME", []))} change(s).')
    print('Everything in the other buckets is deliberately left alone.')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
