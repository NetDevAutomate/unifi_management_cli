"""Derive durable switch port labels from live LLDP and wired-client data.

Why this exists
---------------
Port labels drift. On 2026-08-03 an audit found `Office USW Ultra 210W` ports 1-7 still
reading the factory default ``PoE Out + Data`` when they were seven named access points,
and `Mike2 USW Flex 2.5G 8 PoE` p1/p2 had their two downstream switches transposed. Stale
labels are worse than absent ones: two diagnoses during that session were wrong because a
port label was trusted as evidence (a "faulty" camera link was really a switch uplink, and
a "100 Mbps Raspberry Pi" was really a JetKVM).

The existing ``discover`` path resolves an LLDP peer from ``system_name``, which UniFi APs
do not send. It therefore fell back to keeping the stale label. This module resolves the
LLDP ``chassis_id`` against the adopted-device registry instead, which is what recovers
those AP names.

Naming precedence
-----------------
1. LLDP peer that resolves to an adopted UniFi device -> its name, plus the remote port
   when the peer reports a usable port id (a MAC is not usable).
2. Exactly one wired client on the port -> that client's name.
3. Several wired clients (a downstream unmanaged switch) -> ``<best name> +N``.
4. Otherwise leave the label alone.

Guards
------
Four failure modes were observed while building the plan against a live estate, each of
which loses information or churns pointlessly:

* ``would_lose_information`` - a client that momentarily reports no hostname would rename
  ``Google Streamer 4K`` to ``02:00:fe:02:00:0f``.
* ``name_quality`` - a raw MAC sorts first alphabetically, so a multi-client port labelled
  ``Hotel3-Apple-TV`` would become ``02:00:fe:02:00:06 +2``.
* ``is_cosmetic_change`` - ``AI-Port`` -> ``AI Port`` is pure churn.
* ``strip_multi_suffix`` - a device that comes and goes makes the ``+N`` counter oscillate
  between runs forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unifi_mapper.core.utils.client import UniFiClient


# UniFi rejects port names longer than this.
NAME_MAX = 32

# Factory-default labels that carry no information. `_is_default_port_name` in
# run_methods only knew about "Port N"; the Ultra series ships "PoE Out + Data", which is
# why those labels survived earlier refreshes.
PLACEHOLDER_PREFIXES = ('poe out', 'poe in', 'sfp', 'port ')

# Trailing tokens that mark a name as an OUI manufacturer string rather than a
# device identity. Used to stop a curated label being replaced by one.
VENDOR_SUFFIXES = (
    'inc',
    'incorporated',
    'corp',
    'corporation',
    'ltd',
    'limited',
    'llc',
    'gmbh',
    'co',
    'technology',
    'technologies',
    'electronics',
)


@dataclass
class PortRename:
    """One proposed port label change."""

    device_id: str
    device: str
    port_idx: int
    current: str
    proposed: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of this rename."""
        return {
            'device_id': self.device_id,
            'device': self.device,
            'port_idx': self.port_idx,
            'current': self.current,
            'proposed': self.proposed,
            'reason': self.reason,
        }


@dataclass
class PortNamePlan:
    """Proposed renames plus the switches they belong to."""

    renames: list[PortRename] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Number of proposed renames."""
        return len(self.renames)

    def by_device(self) -> dict[str, list[PortRename]]:
        """Group renames by switch name, each list ordered by port index."""
        grouped: dict[str, list[PortRename]] = {}
        for rename in self.renames:
            grouped.setdefault(rename.device, []).append(rename)
        for items in grouped.values():
            items.sort(key=lambda r: r.port_idx)
        return grouped


def looks_like_mac(value: str) -> bool:
    """True for colon-separated hardware addresses."""
    return value.count(':') >= 4


def is_weak_label(name: str) -> bool:
    """True for hex-blob names that read as an address rather than a device.

    Catches both `02:00:fe:02:00:0f` and `0200fe00000a`.
    """
    cleaned = (name or '').replace('-', '').replace(':', '').strip()
    return (
        bool(cleaned)
        and len(cleaned) <= 12
        and all(c in '0123456789abcdefABCDEF' for c in cleaned)
    )


def is_placeholder_name(name: str, port_idx: int | None = None) -> bool:
    """True for controller defaults that carry no information."""
    cleaned = (name or '').strip().lower()
    if cleaned in ('', 'port'):
        return True
    if port_idx is not None and cleaned == f'port {port_idx}':
        return True
    if cleaned.startswith(PLACEHOLDER_PREFIXES):
        remainder = cleaned.split(' ', 1)[1] if ' ' in cleaned else ''
        # "Port 7" is a placeholder; "Port 7 Media Rack" is a real label.
        return cleaned.startswith(('poe out', 'poe in', 'sfp')) or remainder.isdigit()
    return False


def is_vendor_only_label(name: str) -> bool:
    """True for a bare OUI vendor string such as 'Synology Incorporated'.

    These arrive when a client reports no hostname, so the only name available is
    its manufacturer. They are legitimate as a last resort on an unlabelled port,
    but they identify a manufacturer rather than a device: every NIC from the same
    vendor collapses to an identical label. Treated as a downgrade so a curated
    label is never traded for one.
    """
    cleaned = (name or '').strip().lower().rstrip('.')
    return bool(cleaned) and cleaned.endswith(VENDOR_SUFFIXES)


def name_quality(value: str) -> tuple[int, str]:
    """Sort key preferring human-readable names over addresses and vendor strings."""
    if looks_like_mac(value) or is_weak_label(value):
        return (2, value)
    if is_vendor_only_label(value):
        return (1, value)
    return (0, value)


def strip_multi_suffix(name: str) -> str:
    """Drop a trailing ' +N' multi-client counter."""
    head, _, tail = name.rpartition(' +')
    return head if head and tail.isdigit() else name


def is_cosmetic_change(current: str, proposed: str) -> bool:
    """True when a rename differs only by punctuation, spacing or case."""

    def norm(value: str) -> str:
        return ''.join(c for c in value.lower() if c.isalnum())

    return norm(current) == norm(proposed)


def would_lose_information(current: str, proposed: str) -> bool:
    """True when the rename trades a readable label for a weaker one.

    A weaker label is either a bare hardware address or a vendor-only OUI
    string. Renaming is always allowed over a controller placeholder or an
    existing weak label, since neither carries information worth keeping.
    """
    if is_placeholder_name(current) or is_weak_label(current):
        return False
    return is_weak_label(proposed) or is_vendor_only_label(proposed)


def resolve_peer(
    lldp_entry: dict[str, Any],
    unifi_by_mac: dict[str, dict[str, Any]],
    name_max: int = NAME_MAX,
) -> str | None:
    """Resolve an LLDP entry to an adopted UniFi device label.

    Uses ``chassis_id`` against the device registry rather than ``system_name``, which
    UniFi APs do not populate. Appends the peer's port id when it is not just a MAC.
    """
    chassis_id = lldp_entry.get('chassis_id')
    if not isinstance(chassis_id, str):
        return None
    peer = unifi_by_mac.get(chassis_id)
    if not peer:
        return None
    name = str(peer.get('name') or '').strip()
    if not name:
        return None
    port_id = str(lldp_entry.get('port_id') or '').strip()
    if port_id and not looks_like_mac(port_id):
        candidate = f'{name} {port_id}'
        if len(candidate) <= name_max:
            return candidate
    return name


def index_wired_clients(clients: list[dict[str, Any]]) -> dict[tuple[str, int], list[str]]:
    """Map (switch_mac, port_idx) -> wired client names."""
    index: dict[tuple[str, int], list[str]] = {}
    for client in clients:
        if not client.get('is_wired'):
            continue
        switch_mac, port_idx = client.get('sw_mac'), client.get('sw_port')
        if not switch_mac or port_idx is None:
            continue
        name = (
            client.get('name') or client.get('hostname') or client.get('oui') or client.get('mac')
        )
        index.setdefault((switch_mac, port_idx), []).append(str(name))
    return index


def build_port_name_plan(
    devices: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    name_max: int = NAME_MAX,
) -> PortNamePlan:
    """Compute port label changes for every connected switch port.

    Down ports and non-switch devices are left alone — clearing a disconnected port's
    label discards the only record of what used to be plugged into it.
    """
    unifi_by_mac = {d['mac']: d for d in devices if d.get('mac')}
    wired = index_wired_clients(clients)

    plan = PortNamePlan()
    for device in devices:
        if device.get('type') != 'usw':
            continue
        switch_mac = device.get('mac')
        lldp = {entry.get('local_port_idx'): entry for entry in (device.get('lldp_table') or [])}

        for port in device.get('port_table') or []:
            if not port.get('up'):
                continue
            port_idx = port.get('port_idx')
            current = str(port.get('name') or '')

            proposed = resolve_peer(lldp.get(port_idx, {}), unifi_by_mac, name_max)
            reason = 'lldp-peer'
            if not proposed:
                key = (str(switch_mac), int(port_idx))
                names = sorted(set(wired.get(key, [])), key=name_quality)
                if len(names) == 1:
                    proposed, reason = names[0], 'wired-client'
                elif len(names) > 1:
                    proposed = f'{names[0]} +{len(names) - 1}'
                    reason = f'{len(names)} wired clients'

            if not proposed:
                continue
            proposed = proposed[:name_max]

            if (
                proposed == current
                or is_cosmetic_change(current, proposed)
                or would_lose_information(current, proposed)
                or strip_multi_suffix(current) == strip_multi_suffix(proposed)
            ):
                continue

            plan.renames.append(
                PortRename(
                    device_id=device['_id'],
                    device=str(device.get('name') or '?'),
                    port_idx=port_idx,
                    current=current,
                    proposed=proposed,
                    reason=reason,
                )
            )

    return plan


async def analyse_port_names() -> PortNamePlan:
    """Fetch live state and compute the rename plan."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
        clients = await client.get_clients()
    return build_port_name_plan(devices, clients)


async def apply_port_names(plan: PortNamePlan, dry_run: bool = True) -> list[dict[str, Any]]:
    """Write the plan, one merged update per switch.

    Uses ``update_port_names``, which merges into existing ``port_overrides`` so
    poe_mode / port_profile / speed overrides are preserved rather than replaced.
    """
    results: list[dict[str, Any]] = []
    grouped = plan.by_device()

    if dry_run:
        return [
            {'device': device, 'ports': len(items), 'status': 'DRY_RUN'}
            for device, items in grouped.items()
        ]

    async with UniFiClient() as client:
        for device, items in grouped.items():
            updates = {item.port_idx: item.proposed for item in items}
            try:
                ok = await client.update_port_names(items[0].device_id, updates)
                status = 'APPLIED' if ok else 'FAILED: update rejected'
            except Exception as exc:  # noqa: BLE001 - report per device and continue
                status = f'FAILED: {exc}'
            results.append({'device': device, 'ports': len(updates), 'status': status})

    return results
