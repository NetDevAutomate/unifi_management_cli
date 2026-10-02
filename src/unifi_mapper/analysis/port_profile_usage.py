"""Port-profile usage audit: where each profile is applied and which ones are traps.

Per profile: every port it is the effective profile of (the sibling's
``profile_usage``, so this audit, ``ports list`` and ``ports profile-diff`` can
never disagree), whether it forces a speed, its native network, forward mode and
PoE mode. Read-only: one guarded GET each for ``stat/device``, ``rest/portconf``
and ``rest/networkconf``.

Codes:

* ``DANGLING_PROFILE_REF`` (HIGH): a port's effective profile id is not a known profile.
* ``FORCED_SPEED_PROFILE`` (WARNING): the profile turns autonegotiation off and forces a
  speed. Recommend Auto unless both ends are verified (see ``audit_link_speeds``).
* ``OVERRIDE_SHADOWS_PROFILE`` (WARNING): a port's ``port_overrides`` entry sets
  autoneg, a forced speed or the native network differently from its profile.
* ``DUPLICATE_PROFILES`` (INFO): two differently named profiles whose settings are
  identical (``build_profile_diff``; ``_id``, ``name``, ``site_id`` and ``attr_*`` are
  ignored).
* ``UNUSED_PROFILE`` (INFO): no port runs the profile.

Complements ``validate_port_profiles`` (STP edge/BPDU safety) and the pairwise
``diff_port_profiles`` without repeating either.
"""

import asyncio
import time
from pydantic import BaseModel, Field
from typing import Annotated, Any, Callable, Literal, Optional
from unifi_mapper.analysis.link_settings import effective_port_settings, effective_profile_id
from unifi_mapper.diagnostic_reads import (
    Collection,
    DiagnosticModel,
    int_or_none,
    local_iso,
    normalise_mac,
    port_entries,
    rows,
    str_or_none,
)
from unifi_mapper.diagnostics import port_diagnostics_tools
from unifi_mapper.port_diagnostics import (
    ProfileUsage,
    _load_networks,
    build_profile_diff,
    find_profile,
    load_profiles,
    profile_usage,
)


Severity = Literal['HIGH', 'WARNING', 'INFO']

SEVERITY_ORDER: dict[str, int] = {'HIGH': 0, 'WARNING': 1, 'INFO': 2}
MAX_PORTS_PER_PROFILE = 50
MAX_LIMIT = 1000

# Clock seam: tests replace it; production reads the wall clock.
_now: Callable[[], float] = time.time


class ProfileUsageEntry(BaseModel):
    """One port profile and every port it is the effective profile of."""

    id: str
    name: Optional[str] = None
    port_count: int = 0
    ports: list[ProfileUsage] = Field(default_factory=lambda: [])
    ports_truncated: bool = False
    forces_speed: bool = False
    forced_speed_mbps: Optional[int] = None
    autoneg: Optional[bool] = None
    native_network_id: Optional[str] = None
    native_network_name: Optional[str] = None
    native_vlan: Any = None
    forward: Any = None
    poe_mode: Any = None


class ProfileUsageFinding(BaseModel):
    """A profile, a pair of profiles, or one port that needs attention."""

    severity: Severity
    code: str
    profile_id: Optional[str] = None
    profile_name: Optional[str] = None
    other_profile_id: Optional[str] = None
    other_profile_name: Optional[str] = None
    switch: Optional[str] = None
    switch_mac: Optional[str] = None
    port_idx: Optional[int] = None
    shadowed_fields: list[str] = Field(default_factory=lambda: [])
    message: str
    recommendation: str = ''


class PortProfileUsageReport(DiagnosticModel):
    """Where every port profile is used, which force speed, and which are traps."""

    generated_at: str = ''
    profiles_total: int = 0
    devices_analyzed: int = 0
    ports_analyzed: int = 0
    profiles: list[ProfileUsageEntry] = Field(default_factory=lambda: [])
    findings_total: int = 0
    findings: list[ProfileUsageFinding] = Field(default_factory=lambda: [])
    validation_passed: bool = True
    truncated: bool = False
    next_offset: Optional[int] = None


def validate_page(limit: int, offset: int) -> None:
    """Raise ValueError unless ``1 <= limit <= MAX_LIMIT`` and ``offset >= 0``."""
    if isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f'limit must be between 1 and {MAX_LIMIT}, got {limit}')
    if isinstance(offset, bool) or offset < 0:
        raise ValueError(f'offset must be 0 or more, got {offset}')


# ---------------------------------------------------------------------------
# Pure core
# ---------------------------------------------------------------------------


def _profile_negotiation(profile: dict[str, Any]) -> tuple[Optional[bool], Optional[int]]:
    """Return the profile's (autoneg, forced speed); same rule as ``effective_port_settings``."""
    autoneg = profile.get('autoneg') if isinstance(profile.get('autoneg'), bool) else None
    speed = int_or_none(profile.get('speed'))
    return autoneg, speed if autoneg is False and speed else None


def _label(profile: dict[str, Any], profile_id: str) -> str:
    return str_or_none(profile.get('name')) or profile_id


def _shadowed_fields(
    device: dict[str, Any],
    entry: dict[str, Any],
    idx: int,
    profiles: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
) -> list[str]:
    """Return the fields a port's override sets differently from its effective profile."""
    settings = effective_port_settings(device, entry, idx, profiles, networks)
    profile = profiles.get(settings.profile_id or '') or {}
    autoneg, forced = _profile_negotiation(profile)
    shadowed: list[str] = []
    if settings.sources.get('autoneg') == 'override' and settings.autoneg != autoneg:
        shadowed.append('autoneg')
    if (
        settings.sources.get('forced_speed_mbps') == 'override'
        and settings.forced_speed_mbps != forced
    ):
        shadowed.append('forced_speed_mbps')
    if settings.sources.get('native_network_id') == 'override' and settings.native_network_id != (
        profile.get('native_networkconf_id')
    ):
        shadowed.append('native_network_id')
    return shadowed


def audit_port_profile_usage_from_data(
    devices: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
    now: float,
    *,
    profile_id: Optional[str] = None,
    include_unused: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> PortProfileUsageReport:
    """Classify every port profile's usage from already-fetched data (no I/O).

    Args:
        devices: Sanitised ``stat/device`` records.
        profiles: Sanitised ``portconf`` records keyed by ``_id``.
        networks: ``{network_id: {name, vlan}}`` (``_load_networks``).
        now: Current epoch seconds (for ``generated_at``).
        profile_id: Report only this profile (and the findings about it).
        include_unused: List profiles no port uses, and report UNUSED_PROFILE.
        limit: Page size for ``profiles``.
        offset: Page start for ``profiles``.

    Returns:
        The report. ``findings`` is complete (not paged); ``validation_passed``
        is False when any HIGH finding exists.
    """
    validate_page(limit, offset)
    devices = [d for d in devices if isinstance(d, dict)]
    ordered = sorted(profiles, key=lambda pid: (_label(profiles[pid], pid).lower(), pid))
    selected = [pid for pid in ordered if profile_id is None or pid == profile_id]

    entries: list[ProfileUsageEntry] = []
    findings: list[ProfileUsageFinding] = []
    for pid in selected:
        profile = profiles[pid]
        name = str_or_none(profile.get('name'))
        usage = profile_usage(devices, pid)
        autoneg, forced = _profile_negotiation(profile)
        native_id = str_or_none(profile.get('native_networkconf_id'))
        native = networks.get(native_id or '') or {}
        if not usage and not include_unused:
            continue
        if forced is not None:
            findings.append(
                ProfileUsageFinding(
                    severity='WARNING',
                    code='FORCED_SPEED_PROFILE',
                    profile_id=pid,
                    profile_name=name,
                    message=(
                        f"Profile '{_label(profile, pid)}' turns autonegotiation off and forces "
                        f'{forced} Mbps on {len(usage)} port(s).'
                    ),
                    recommendation=(
                        'Use Auto unless both ends are verified to link at the forced speed; '
                        'audit_link_speeds (analyze link-speeds) shows how each port linked.'
                    ),
                )
            )
        if not usage:
            findings.append(
                ProfileUsageFinding(
                    severity='INFO',
                    code='UNUSED_PROFILE',
                    profile_id=pid,
                    profile_name=name,
                    message=f"No port runs profile '{_label(profile, pid)}'.",
                    recommendation='Remove it in the UniFi UI if it is no longer needed.',
                )
            )
        entries.append(
            ProfileUsageEntry(
                id=pid,
                name=name,
                port_count=len(usage),
                ports=usage[:MAX_PORTS_PER_PROFILE],
                ports_truncated=len(usage) > MAX_PORTS_PER_PROFILE,
                forces_speed=forced is not None,
                forced_speed_mbps=forced,
                autoneg=autoneg,
                native_network_id=native_id,
                native_network_name=str_or_none(native.get('name')),
                native_vlan=native.get('vlan'),
                forward=profile.get('forward'),
                poe_mode=profile.get('poe_mode'),
            )
        )

    # Pairs over sorted ids, so each pair is reported once.
    ids = sorted(profiles)
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1 :]:
            if profile_id is not None and profile_id not in (a_id, b_id):
                continue
            a, b = profiles[a_id], profiles[b_id]
            if _label(a, a_id).strip().lower() == _label(b, b_id).strip().lower():
                continue
            diff = build_profile_diff(a, b, networks, devices=[])
            if diff.differences or diff.only_in_a or diff.only_in_b:
                continue
            findings.append(
                ProfileUsageFinding(
                    severity='INFO',
                    code='DUPLICATE_PROFILES',
                    profile_id=a_id,
                    profile_name=str_or_none(a.get('name')),
                    other_profile_id=b_id,
                    other_profile_name=str_or_none(b.get('name')),
                    message=(
                        f"Profiles '{_label(a, a_id)}' and '{_label(b, b_id)}' have identical "
                        'settings (only identity and attr_* keys differ).'
                    ),
                    recommendation='Keep one and move its ports to it, to avoid drift.',
                )
            )

    ports_analyzed = 0
    devices_analyzed = 0
    for device in devices:
        table = port_entries(device)
        if table:
            devices_analyzed += 1
        for entry in table:
            idx = int_or_none(entry.get('port_idx'))
            if idx is None:
                continue
            ports_analyzed += 1
            effective, _ = effective_profile_id(device, entry, idx)
            if effective is None:
                continue
            where = {
                'switch': str_or_none(device.get('name')),
                'switch_mac': normalise_mac(device.get('mac')),
                'port_idx': idx,
            }
            if effective not in profiles:
                # An empty profile table means the read failed (recorded in errors).
                if profiles and profile_id is None:
                    findings.append(
                        ProfileUsageFinding(
                            severity='HIGH',
                            code='DANGLING_PROFILE_REF',
                            profile_id=effective,
                            message=(
                                f'{where["switch"]} port {idx} references port profile '
                                f'{effective}, which does not exist.'
                            ),
                            recommendation='Reassign the port to an existing profile in the UI.',
                            **where,
                        )
                    )
                continue
            if profile_id is not None and effective != profile_id:
                continue
            shadowed = _shadowed_fields(device, entry, idx, profiles, networks)
            if shadowed:
                label = _label(profiles[effective], effective)
                findings.append(
                    ProfileUsageFinding(
                        severity='WARNING',
                        code='OVERRIDE_SHADOWS_PROFILE',
                        profile_id=effective,
                        profile_name=str_or_none(profiles[effective].get('name')),
                        shadowed_fields=shadowed,
                        message=(
                            f'{where["switch"]} port {idx} overrides {", ".join(shadowed)} of '
                            f"profile '{label}'."
                        ),
                        recommendation=(
                            'The port does not behave like the profile says; move the setting '
                            'into a profile or remove the override.'
                        ),
                        **where,
                    )
                )

    findings.sort(
        key=lambda f: (
            SEVERITY_ORDER[f.severity],
            f.code,
            f.profile_name or f.profile_id or '',
            f.switch or '',
            f.port_idx or 0,
        )
    )
    page = entries[offset : offset + limit]
    truncated = offset + limit < len(entries)
    return PortProfileUsageReport(
        generated_at=local_iso(lambda: now),
        profiles_total=len(entries),
        devices_analyzed=devices_analyzed,
        ports_analyzed=ports_analyzed,
        profiles=page,
        findings_total=len(findings),
        findings=findings,
        validation_passed=not any(f.severity == 'HIGH' for f in findings),
        truncated=truncated,
        next_offset=offset + limit if truncated else None,
    )


# ---------------------------------------------------------------------------
# Fetch (sync, guarded) and the MCP handler
# ---------------------------------------------------------------------------


def collect_port_profile_usage(
    api: Any,
    site: str,
    *,
    profile: Optional[str] = None,
    include_unused: bool = True,
    limit: int = 100,
    offset: int = 0,
    now: Optional[Callable[[], float]] = None,
) -> PortProfileUsageReport:
    """Read ``stat/device``, ``rest/portconf`` and ``rest/networkconf`` once and audit them.

    Args:
        api: Authenticated ``UnifiApiClient`` behind the read-only guard.
        site: Site name.
        profile: Report only this profile (exact name, case-insensitive, or ``_id``).
        include_unused: List profiles no port uses, and report UNUSED_PROFILE.
        limit: Page size for ``profiles`` (1 to 1000).
        offset: Page start for ``profiles``.
        now: Clock for ``generated_at``.

    Returns:
        The report.

    Raises:
        ProfileNotFound: ``profile`` matched no profile, or several by name.
        ValueError: ``limit`` or ``offset`` is out of range.
    """
    validate_page(limit, offset)
    clock = now or _now
    ctx = Collection()
    devices = [ctx.clean(d, 'device.raw') for d in rows(api.get_devices(site))]
    if not devices:
        ctx.error('devices', 'stat/device returned no devices')
    profiles = load_profiles(api, site, ctx)
    profile_id = str(find_profile(profiles, profile)['_id']) if profile is not None else None
    networks = _load_networks(api, site, ctx)
    report = audit_port_profile_usage_from_data(
        devices,
        profiles,
        networks,
        clock(),
        profile_id=profile_id,
        include_unused=include_unused,
        limit=limit,
        offset=offset,
    )
    report.errors = ctx.errors
    report.sanitised_paths = ctx.sanitised_paths
    return report


def _audit_sync(
    profile: Optional[str], include_unused: bool, limit: int, offset: int
) -> PortProfileUsageReport:
    validate_page(limit, offset)
    # Looked up on the module at call time, so a patched helper (tests) is used.
    with port_diagnostics_tools._readonly_sync_client() as (api, site):
        return collect_port_profile_usage(
            api, site, profile=profile, include_unused=include_unused, limit=limit, offset=offset
        )


async def audit_port_profile_usage(
    profile: Annotated[
        Optional[str],
        Field(description='Report only this port profile (exact name or _id). Omit for all.'),
    ] = None,
    include_unused: Annotated[
        bool, Field(description='List profiles no port uses (UNUSED_PROFILE)')
    ] = True,
    limit: Annotated[int, Field(description='Maximum profiles to return (1-1000)')] = 100,
    offset: Annotated[int, Field(description='Profiles to skip, for paging')] = 0,
) -> PortProfileUsageReport:
    """Show where every port profile is used and which ones are traps. Read-only.

    When to use this tool:
    - Finding every port on a profile that forces a speed (autoneg off)
    - Finding ports whose override silently differs from their profile
    - Cleaning up unused or duplicate profiles, or ports pointing at a deleted one

    Usage comes from the same rule as get_switch_ports and diff_port_profiles
    (the override's portconf_id wins over the port table's). For STP edge/BPDU
    safety use validate_port_profiles; to compare two profiles key by key use
    diff_port_profiles; for how each port actually linked use audit_link_speeds.

    Args:
        profile: Optional profile name or _id.
        include_unused: Include profiles no port uses.
        limit: Page size for profiles (1-1000).
        offset: Page start for profiles.

    Returns:
        PortProfileUsageReport: profiles (id, name, port_count, ports (first 50),
        ports_truncated, forces_speed, forced_speed_mbps, autoneg, native network
        and VLAN, forward, PoE mode), findings (DANGLING_PROFILE_REF,
        FORCED_SPEED_PROFILE, OVERRIDE_SHADOWS_PROFILE, DUPLICATE_PROFILES,
        UNUSED_PROFILE), validation_passed, truncated and next_offset.

    Raises:
        ToolError: PROFILE_NOT_FOUND for an unknown profile; CONFIG_INVALID for an
            out-of-range limit or offset; CONTROLLER_UNREACHABLE or
            READ_ONLY_VIOLATION.
    """
    return await asyncio.to_thread(
        port_diagnostics_tools._mapped, _audit_sync, profile, include_unused, limit, offset
    )
