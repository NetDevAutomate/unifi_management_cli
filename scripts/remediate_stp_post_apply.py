#!/usr/bin/env python3
"""Remediate post-STP-apply findings that are safe to change through UniFi API."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
from datetime import datetime
from pathlib import Path
from site_targets import TargetsError, post_apply_ports
from typing import Any, cast
from unifi_mapper.analysis.stp_optimizer import (
    apply_stp_changes,
    calculate_optimal_priorities,
    discover_stp_topology,
)
from unifi_mapper.cli import get_default_config_path, load_env_from_config
from unifi_mapper.core.utils.client import UniFiClient


JsonDict = dict[str, Any]

# The port profile to apply and the ports to apply it to come from this site's targets
# file through site_targets.post_apply_ports (issue 046); the repository keeps
# placeholders only, in site-targets.example.json.


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Remediate safe post-STP-apply findings for the 10G expansion.'
    )
    parser.add_argument(
        '--config',
        default=None,
        help='Path to UniFi mapper .env file.',
    )
    parser.add_argument(
        '--report',
        type=Path,
        default=Path('reports/stp-remediation.json'),
        help='JSON remediation report path.',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply changes. Without this flag the script only reports planned actions.',
    )
    parser.add_argument(
        '--targets',
        default=None,
        help='Path to the site targets file (default: the XDG config directory).',
    )
    return parser.parse_args()


async def main() -> int:
    """Run the remediation workflow.

    Returns:
        0 when the report was written; 2 when the site targets can't be read, which is
        checked before the controller config is read or the controller is contacted.
    """
    args = parse_args()
    try:
        profile_name, target_ports_by_switch = post_apply_ports(args.targets)
    except TargetsError as exc:
        print(f'remediate_stp_post_apply.py: {exc}')
        return 2
    config_path = args.config or get_default_config_path()
    load_env_from_config(str(config_path))

    report: dict[str, Any] = {
        'timestamp': datetime.now().isoformat(),
        'apply': args.apply,
        'stp_priority': {},
        'port_profile_normalisation': [],
        'not_api_remediated': [
            {
                'category': 'Root Guard',
                'reason': 'No root-guard write field was present in live port profile or port override payloads.',
                'action': 'Priority spacing is applied instead so downstream switches cannot tie the demoted gateway core.',
            },
            {
                'category': 'Port Errors',
                'reason': 'CRC/error counters are physical/link evidence, not a safe API mutation.',
                'action': 'Inspect the cabling and transceiver of a port whose counter increases.',
            },
            {
                'category': 'LAG',
                'reason': 'LAG candidates intentionally not applied; NAS NIC LAGs should be planned first.',
                'action': 'Leave LAG findings as recommendations only.',
            },
        ],
    }

    topology = await discover_stp_topology()
    priority_changes = await calculate_optimal_priorities(topology)
    stp_priority_report: dict[str, Any] = {
        'planned_count': len(priority_changes),
        'changes': [change.model_dump() for change in priority_changes],
    }
    if args.apply and priority_changes:
        stp_priority_report['result'] = await apply_stp_changes(priority_changes, dry_run=False)
    report['stp_priority'] = stp_priority_report

    async with UniFiClient() as client:
        devices = await client.get_devices()
        profiles = await client.get(client.build_path('rest/portconf'))
        profile = _find_profile(profiles, profile_name)
        if profile is None:
            raise RuntimeError(f'Port profile not found: {profile_name}')

        for device in devices:
            device_name = str(device.get('name') or '')
            target_ports = target_ports_by_switch.get(device_name)
            if not target_ports:
                continue
            actions = _normalise_device_ports(device, target_ports, str(profile['_id']))
            report['port_profile_normalisation'].extend(actions)
            if args.apply and any(action['changed'] for action in actions):
                await _replace_port_overrides(client, device)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _find_profile(profiles: object, name: str) -> JsonDict | None:
    if not isinstance(profiles, list):
        return None
    for profile in cast(list[object], profiles):
        if not isinstance(profile, dict):
            continue
        profile_dict = cast(JsonDict, profile)
        if profile_dict.get('name') == name:
            return profile_dict
    return None


def _normalise_device_ports(
    device: JsonDict,
    target_ports: dict[int, str],
    profile_id: str,
) -> list[JsonDict]:
    raw_overrides = copy.deepcopy(device.get('port_overrides', []))
    overrides = cast(list[object], raw_overrides) if isinstance(raw_overrides, list) else []

    actions: list[JsonDict] = []
    existing_by_idx: dict[int, JsonDict] = {}
    for override in overrides:
        if not isinstance(override, dict):
            continue
        clean_override = cast(JsonDict, override)
        if clean_override.get('port_idx') is None:
            continue
        existing_by_idx[int(clean_override.get('port_idx') or 0)] = clean_override

    for port_idx, expected_name in target_ports.items():
        current: JsonDict = existing_by_idx.get(port_idx, {'port_idx': port_idx})
        before: JsonDict = copy.deepcopy(current)
        desired = {
            'name': str(current.get('name') or expected_name),
            'port_idx': port_idx,
            'portconf_id': profile_id,
            'setting_preference': 'manual',
        }
        existing_by_idx[port_idx] = desired
        changed = before != desired
        actions.append(
            {
                'device': device.get('name'),
                'device_id': device.get('_id'),
                'port_idx': port_idx,
                'profile_id': profile_id,
                'before': before,
                'after': desired,
                'changed': changed,
            }
        )

    device['port_overrides'] = [
        existing_by_idx[idx] for idx in sorted(existing_by_idx) if idx != 0
    ]
    return actions


async def _replace_port_overrides(client: UniFiClient, device: JsonDict) -> None:
    device_id = str(device['_id'])
    payload: JsonDict = {
        '_id': device['_id'],
        'mac': device['mac'],
        'port_overrides': device['port_overrides'],
    }
    for field in ('config_version', 'cfgversion', 'config_revision'):
        if field in device:
            payload[field] = device[field]

    await client.put(client.build_path(f'rest/device/{device_id}'), payload)
    await client.force_provision(str(device['mac']))


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
