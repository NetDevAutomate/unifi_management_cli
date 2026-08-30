#!/usr/bin/env python3
"""Apply custom STP priorities to UniFi switches.

Unlike ``unifi-mapper stp optimize``, this script applies *explicit* priorities
rather than relying on the auto-classifier's tier detection. Use this when the
topology auto-detection picks the wrong root (e.g. consumer-tier switch
classified as 'Core' because it is gateway-adjacent).

USAGE
-----
1. Review the PRIORITY_OVERRIDES table below.
2. Run with no flags to dry-run.
3. Run with --apply to commit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any
from unifi_mapper.analysis.stp_optimizer import (
    STPChange,
    apply_stp_changes,
    discover_stp_topology,
)


# -----------------------------------------------------------------------------
# Explicit priority assignments (Option B: Lounge XG primary, Shed XG secondary)
# -----------------------------------------------------------------------------
PRIORITY_OVERRIDES: dict[str, int] = {
    # 10G BACKBONE — roots
    'Mike2 10G Aggregation USW Flex XG': 4096,  # PRIMARY ROOT
    'Xray3 USW Flex XG 10G': 8192,  # SECONDARY ROOT
    # GATEWAY — in-topology, not root
    'Dream Machine Pro Max': 12288,
    # ACCESS TIER 3 (aggregation / dense edge)
    'Mike2 USW Flex 2.5G 8 PoE': 20480,  # was wrongly 4096
    'Mike2 USW-Ultra-210W': 20480,
    'Xray3 USW-Lite-16-PoE': 20480,  # demoted from 'Core'
    # ACCESS TIER 4
    'Victor3 USW Flex 2.5G 8 PoE': 24576,
    'Victor3 USW Flex 2.5G 5': 24576,
    'Victor3 Whiskey3 USW Flex 2.5G 5': 24576,
    'Mike2 USW Flex 2.5G 5': 24576,
    'Mike2 USW Lite 8 PoE': 24576,
    'Hotel3 USW Lite 8 PoE': 24576,
    'Juliett USW Flex 2.5G 5': 24576,
    'Foxtrot3 USW Flex 2.5G 5': 24576,
    # ACCESS TIER 5 (leaves)
    'Victor3 Juliett3 US 8 60W': 28672,
    'Victor3 India3 US 8 60W': 28672,
    'Xray3 Yankee3 US 8 60W': 28672,
}


async def build_changes() -> list[STPChange]:
    """Derive the STP priority changes required to reach the target topology."""
    topology = await discover_stp_topology()
    by_name = {sw.name: sw for sw in topology.switches}
    changes: list[STPChange] = []
    missing: list[str] = []

    for name, new_priority in PRIORITY_OVERRIDES.items():
        sw = by_name.get(name)
        if sw is None:
            missing.append(name)
            continue
        if sw.current_priority == new_priority:
            continue
        changes.append(
            STPChange(
                device_id=sw.device_id,
                device_name=sw.name,
                current_priority=sw.current_priority or 32768,
                new_priority=new_priority,
                hierarchy_tier=sw.hierarchy_tier,
                reason=f'Custom override: {name}',
            )
        )

    if missing:
        print('\n⚠️  Not found on network (typo / offline?):')
        for n in missing:
            print(f'    - {n}')
        print()

    return changes


def render_diff(changes: list[STPChange]) -> None:
    """Print the pending STP priority changes as a human-readable diff."""
    print(f'{"Switch":<42}{"Current":>10}{"New":>10}{"Delta":>12}')
    print('-' * 74)
    for c in sorted(changes, key=lambda x: (x.new_priority, x.device_name)):
        delta = c.new_priority - c.current_priority
        arrow = '▲' if delta > 0 else '▼'
        print(
            f'{c.device_name[:40]:<42}{c.current_priority:>10}{c.new_priority:>10}  {arrow}{abs(delta):>8,}'
        )
    print()


async def main() -> int:
    """Apply the custom STP priorities, or preview them under dry-run."""
    parser = argparse.ArgumentParser(description='Apply custom STP priorities.')
    parser.add_argument('--apply', action='store_true', help='Commit changes (default: dry-run)')
    parser.add_argument('--force', '-f', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    print('📡 Fetching current STP topology...')
    try:
        changes = await build_changes()
    except Exception as exc:
        # discover_stp_topology reaches the controller, so auth failure, an
        # unreachable host or a TLS problem all land here. Without this the
        # script exits on a traceback, which reads like a bug in the tool
        # rather than a connection problem.
        print(f'\n❌ Could not read the STP topology: {exc}')
        return 2

    if not changes:
        print('\n✅ No changes required — all priorities already match overrides.')
        return 0

    print(f'\n📋 {len(changes)} priority change(s) proposed:\n')
    render_diff(changes)

    if not args.apply:
        print('🔍 DRY RUN — no changes applied. Re-run with --apply to commit.')
        return 0

    if not args.force:
        resp = input(f'\n⚠️  Apply {len(changes)} STP priority changes? [y/N] ').strip().lower()
        if resp != 'y':
            print('Aborted.')
            return 1

    print('\n⚡ Applying changes...')
    try:
        result: dict[str, Any] = await apply_stp_changes(changes, dry_run=False)
    except Exception as exc:
        # apply_stp_changes reports per-device outcomes in result['failed'], so
        # reaching here means it aborted rather than a device rejecting a write.
        # Priorities are applied per switch, so earlier ones may already be live.
        print(f'\n❌ Apply aborted: {exc}')
        print('   Some priorities may already have been applied. Verify with:')
        print('       uv run unifi-mapper stp analyze')
        return 2

    print(f'\n✅ Applied: {len(result["applied"])}')
    for r in result['applied']:
        print(f'    {r["device_name"]}: {r["current_priority"]} → {r["new_priority"]}')

    if result['failed']:
        print(f'\n❌ Failed: {len(result["failed"])}')
        for r in result['failed']:
            print(f'    {r["device_name"]}: {r["error"]}')
        return 2

    print('\n🕐 Network will converge over 10-30s. Verify with:')
    print('    uv run unifi-network-toolkit analyze link-quality')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
