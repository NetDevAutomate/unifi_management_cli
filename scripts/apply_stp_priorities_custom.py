#!/usr/bin/env python3
"""Apply custom STP priorities to UniFi switches.

Unlike ``unifi-mapper stp optimize``, this script applies *explicit* priorities
rather than relying on the auto-classifier's tier detection. Use this when the
topology auto-detection picks the wrong root (e.g. consumer-tier switch
classified as 'Core' because it is gateway-adjacent).

USAGE
-----
1. Put each switch's priority in this site's targets file (``site_targets.py``).
2. Run with no flags to dry-run.
3. Run with --apply to commit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from site_targets import TargetsError, stp_priorities
from typing import Any
from unifi_mapper.analysis.stp_optimizer import (
    STPChange,
    apply_stp_changes,
    discover_stp_topology,
)


# -----------------------------------------------------------------------------
# The explicit priorities, {switch name: priority}, come from this site's targets
# file through site_targets.stp_priorities (issue 046); the repository keeps
# placeholders only, in site-targets.example.json. Lower wins: the primary root
# takes 4096, the secondary 8192, and each tier below a higher multiple of 4096.
# -----------------------------------------------------------------------------


async def build_changes(priorities: dict[str, int]) -> list[STPChange]:
    """Derive the STP priority changes required to reach the target topology.

    Args:
        priorities: The explicit priority for each switch, by name.

    Returns:
        One change per switch whose current priority differs.
    """
    topology = await discover_stp_topology()
    by_name = {sw.name: sw for sw in topology.switches}
    changes: list[STPChange] = []
    missing: list[str] = []

    for name, new_priority in priorities.items():
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
    parser.add_argument(
        '--targets',
        help='Path to the site targets file (default: the XDG config directory)',
    )
    args = parser.parse_args()

    try:
        priorities = stp_priorities(args.targets)
    except TargetsError as exc:
        print(f'apply_stp_priorities_custom.py: {exc}')
        return 2

    print('📡 Fetching current STP topology...')
    try:
        changes = await build_changes(priorities)
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
