"""Fleet-wide link-speed audit: ports below their capability or forced into a trap.

Finds every port that negotiated below what the switch port supports (the
UGREEN-style 10G -> 5G downgrade), and every port forced to a fixed speed that
is down or linked at a different rate. Read-only: one guarded GET per endpoint.

Capability comes only from documented data. ``local_max_mbps`` and
``peer_max_mbps`` are the official Integration API's ``maxSpeedMbps`` for the
port; nothing else is ever treated as a capability. The controller's
``speed_caps`` value is undocumented, so it is never decoded: it is carried raw
as ``speed_caps_raw`` and only ever compared for equality, in the
``BELOW_PEER_PORTS_SAME_CAPS`` heuristic, which runs only when the Integration
API gave no capability for the port.

Codes (one finding per port: the first that matches, in this order):

* ``HALF_DUPLEX`` (CRITICAL): up, negotiated half duplex.
* ``FORCED_SPEED_LINK_DOWN`` (HIGH): autoneg off, forced speed set, enabled, not up.
* ``FORCED_SPEED_MISMATCH`` (HIGH): forced speed set, up, negotiated rate differs.
* ``BELOW_BOTH_ENDS`` (HIGH): autoneg, up, below both ends' Integration API maximum.
* ``BELOW_PORT_CAPABILITY`` (WARNING): autoneg, up, below this port's Integration API
  maximum; the far end's capability is unverified (the UGREEN case).
* ``BELOW_PEER_PORTS_SAME_CAPS`` (WARNING, heuristic): no Integration API capability
  for the port, and another up port on the switch with an identical raw
  ``speed_caps`` linked faster.
* ``CAPABILITY_UNKNOWN`` (INFO): no Integration API capability and no same-caps port
  to compare with. Listed only with ``include_ok``; never promoted.

With ``include_ok`` the up ports with no finding are listed too, as ``OK``.
Stale devices (``analysis/device_freshness``) are excluded from findings and
named in ``data_freshness_warnings``.
"""

import asyncio
import time
from pydantic import BaseModel, Field
from typing import Annotated, Any, Callable, Literal, Optional
from unifi_mapper.analysis.device_freshness import summarise_freshness_from_data
from unifi_mapper.analysis.link_settings import FieldSource, effective_port_settings
from unifi_mapper.diagnostic_reads import (
    Collection,
    DiagnosticModel,
    SwitchNotFound,
    api_path,
    int_or_none,
    local_iso,
    normalise_mac,
    port_entries,
    rows,
)
from unifi_mapper.diagnostics import port_diagnostics_tools
from unifi_mapper.port_diagnostics import (
    IntegrationPorts,
    PortSummary,
    _lldp_port,
    _load_networks,
    _load_rows,
    fetch_integration_ports,
    load_profiles,
    summarise_ports,
)
from unifi_mapper.port_inspect import _build_mac_index, match_switch


Severity = Literal['CRITICAL', 'HIGH', 'WARNING', 'INFO', 'OK']
CapabilitySource = Literal['integration_api', 'unavailable']

SEVERITY_ORDER: dict[str, int] = {'CRITICAL': 0, 'HIGH': 1, 'WARNING': 2, 'INFO': 3, 'OK': 4}
SWITCH_TYPES = ('usw',)
MAX_LIMIT = 1000

# Clock seam: tests replace it; production reads the wall clock.
_now: Callable[[], float] = time.time


class FasterPort(BaseModel):
    """Another port on the same switch, with an identical raw speed_caps, linked faster."""

    port_idx: int
    negotiated_mbps: int


class LinkSpeedFinding(BaseModel):
    """One audited port and why it was flagged."""

    severity: Severity
    code: str
    switch: Optional[str] = None
    switch_mac: Optional[str] = None
    port_idx: int
    port_name: Any = None
    profile_name: Optional[str] = None
    media: Any = None
    negotiated_mbps: Optional[int] = None
    local_max_mbps: Optional[int] = None
    capability_source: CapabilitySource = 'unavailable'
    speed_caps_raw: Any = None
    same_caps_faster_ports: list[FasterPort] = Field(default_factory=lambda: [])
    peer_name: Optional[str] = None
    peer_max_mbps: Optional[int] = None
    autoneg: Optional[bool] = None
    forced_speed_mbps: Optional[int] = None
    full_duplex: Any = None
    sources: dict[str, FieldSource] = Field(default_factory=lambda: {})
    message: str
    recommendation: str = ''


class LinkSpeedIntegration(BaseModel):
    """Whether the Integration API supplied port capabilities."""

    status: str = 'skipped'  # ok | skipped | unavailable | error
    base_path_used: Optional[str] = None
    reason: str = ''


class LinkSpeedAuditReport(DiagnosticModel):
    """Every port below its capability or forced into a speed trap, fleet-wide."""

    generated_at: str = ''
    switches_analyzed: int = 0
    ports_analyzed: int = 0
    findings_total: int = 0
    findings: list[LinkSpeedFinding] = Field(default_factory=lambda: [])
    integration: LinkSpeedIntegration = Field(default_factory=LinkSpeedIntegration)
    data_freshness_warnings: list[str] = Field(default_factory=lambda: [])
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


def _integration_ports(
    integration: Optional[IntegrationPorts], mac: Optional[str]
) -> dict[int, dict[str, Any]]:
    """Return the Integration API's ports for a device MAC, keyed by idx."""
    if integration is None or integration.status != 'ok' or not mac:
        return {}
    found = integration.devices.get(mac)
    device = found.device if found else None
    ports = ((device or {}).get('interfaces') or {}).get('ports') or []
    by_idx: dict[int, dict[str, Any]] = {}
    for port in ports if isinstance(ports, list) else []:
        if isinstance(port, dict):
            idx = int_or_none(port.get('idx'))
            if idx is not None:
                by_idx.setdefault(idx, port)
    return by_idx


def _reciprocal_port(peer: dict[str, Any], switch_mac: str) -> Optional[int]:
    """Return the peer's port whose LLDP neighbour is ``switch_mac``, if it reports one."""
    for entry in peer.get('lldp_table') or []:
        if isinstance(entry, dict) and normalise_mac(entry.get('chassis_id')) == switch_mac:
            return _lldp_port(entry)
    return None


def _faster_same_caps(row: PortSummary, rows_: list[PortSummary]) -> tuple[bool, list[FasterPort]]:
    """Return (comparison possible, ports with an identical raw speed_caps linked faster)."""
    negotiated = int_or_none(row.speed) or 0
    comparable = [
        other
        for other in rows_
        if other.port_idx is not None
        and other.port_idx != row.port_idx
        and other.up is True
        and other.enable is not False
        and row.speed_caps_raw is not None
        and other.speed_caps_raw == row.speed_caps_raw
    ]
    faster = [
        FasterPort(port_idx=other.port_idx, negotiated_mbps=speed)
        for other in comparable
        if other.port_idx is not None and (speed := int_or_none(other.speed) or 0) > negotiated
    ]
    return bool(comparable), sorted(faster, key=lambda p: p.port_idx)


def _classify(
    *,
    up: bool,
    enabled: bool,
    full_duplex: Any,
    autoneg: bool,
    forced: Optional[int],
    negotiated: Optional[int],
    local_max: Optional[int],
    peer_max: Optional[int],
    comparable: bool,
    faster: list[FasterPort],
) -> Optional[tuple[Severity, str]]:
    if up and full_duplex is False:
        return 'CRITICAL', 'HALF_DUPLEX'
    if not autoneg and forced and enabled and not up:
        return 'HIGH', 'FORCED_SPEED_LINK_DOWN'
    if forced and up and negotiated != forced:
        return 'HIGH', 'FORCED_SPEED_MISMATCH'
    if not (autoneg and up and negotiated):
        return None
    if local_max is not None and peer_max is not None:
        return ('HIGH', 'BELOW_BOTH_ENDS') if negotiated < min(local_max, peer_max) else None
    if local_max is not None:
        return ('WARNING', 'BELOW_PORT_CAPABILITY') if negotiated < local_max else None
    if faster:
        return 'WARNING', 'BELOW_PEER_PORTS_SAME_CAPS'
    if not comparable:
        return 'INFO', 'CAPABILITY_UNKNOWN'
    return None


def _describe(code: str, finding: LinkSpeedFinding, profile: Optional[str]) -> tuple[str, str]:
    """Return (message, recommendation) for a code."""
    port = f'{finding.switch} port {finding.port_idx}'
    negotiated = finding.negotiated_mbps
    forced = finding.forced_speed_mbps
    via = f" (profile '{profile}')" if profile else ''
    if code == 'HALF_DUPLEX':
        return (
            f'{port} is up at {negotiated} Mbps in half duplex.',
            'Set both ends to autonegotiate; a forced speed on one side only commonly '
            'falls back to half duplex. Check the cable and the far end.',
        )
    if code == 'FORCED_SPEED_LINK_DOWN':
        return (
            f'{port} is forced to {forced} Mbps with autonegotiation off{via} and the link '
            'is down.',
            'Multi-gigabit links normally need autonegotiation. Verify the far end supports '
            f'a forced {forced} Mbps link, or compare with the profile set to Auto.',
        )
    if code == 'FORCED_SPEED_MISMATCH':
        return (
            f'{port} is configured for {forced} Mbps{via} but negotiated {negotiated} Mbps.',
            'The device has not applied the configured speed, or the far end cannot run it. '
            'Check the profile assignment and the far end.',
        )
    if code == 'BELOW_BOTH_ENDS':
        return (
            f'{port} negotiated {negotiated} Mbps; this port supports {finding.local_max_mbps} '
            f'Mbps and the far end ({finding.peer_name}) {finding.peer_max_mbps} Mbps '
            '(Integration API maxSpeedMbps).',
            'Both ends support a faster link: check the cable, any patch panel and both '
            "ends' advertised speeds.",
        )
    if code == 'BELOW_PORT_CAPABILITY':
        return (
            f'{port} negotiated {negotiated} Mbps; this port supports {finding.local_max_mbps} '
            "Mbps (Integration API maxSpeedMbps). The far end's capability is unverified.",
            'Confirm the far end supports the faster rate, then check the cable and both '
            "ends' advertised speeds.",
        )
    if code == 'BELOW_PEER_PORTS_SAME_CAPS':
        peers = ', '.join(
            f'port {p.port_idx} at {p.negotiated_mbps} Mbps'
            for p in finding.same_caps_faster_ports
        )
        return (
            f'{port} negotiated {negotiated} Mbps while {peers} on the same switch, with an '
            'identical raw speed_caps value, linked faster. This is a comparison, not a '
            'decoded capability.',
            'The Integration API gave no capability for this port. Compare the far ends and '
            'cables of the faster ports.',
        )
    if code == 'CAPABILITY_UNKNOWN':
        return (
            f'{port} is up at {negotiated} Mbps; its capability is unknown (no Integration API '
            'maxSpeedMbps and no other port with an identical raw speed_caps to compare).',
            'Enable API-key access to the Integration API to audit this port.',
        )
    return f'{port} is up at {negotiated} Mbps.', ''


def audit_link_speeds_from_data(
    devices: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
    mac_to_dev: dict[str, dict[str, Any]],
    mac_to_user: dict[str, dict[str, Any]],
    sta_rows: list[dict[str, Any]],
    integration: Optional[IntegrationPorts],
    now: float,
    *,
    switch_mac: Optional[str] = None,
    include_ok: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> LinkSpeedAuditReport:
    """Audit every switch port's negotiated speed from already-fetched data (no I/O).

    Args:
        devices: Sanitised ``stat/device`` records (every adopted device; LLDP peers
            are looked up here).
        profiles: ``portconf`` records keyed by ``_id``.
        networks: ``networkconf`` records keyed by ``_id``.
        mac_to_dev: Adopted devices by lower-case MAC (``_build_mac_index``).
        mac_to_user: Historical clients by lower-case MAC.
        sta_rows: ``stat/sta`` rows.
        integration: The Integration API read, or None when it was not attempted.
        now: Current epoch seconds (for the freshness check).
        switch_mac: Audit only this switch (normalised MAC). None audits every switch.
        include_ok: Also list CAPABILITY_UNKNOWN findings and up ports with no finding.
        limit: Page size for ``findings``.
        offset: Page start for ``findings``.

    Returns:
        The report. ``validation_passed`` is False when any CRITICAL or HIGH
        finding exists (on any page).
    """
    validate_page(limit, offset)
    by_mac = {mac: d for d in devices if (mac := normalise_mac(d.get('mac')))}
    switches = [
        d
        for d in devices
        if d.get('type') in SWITCH_TYPES
        and (switch_mac is None or normalise_mac(d.get('mac')) == switch_mac)
    ]
    freshness = summarise_freshness_from_data(switches, now=now)
    untrusted = {normalise_mac(r.mac) for r in freshness.devices if not r.trustworthy}
    warnings = [
        f'{r.device} ({r.mac}): {r.reason}; excluded from the audit'
        for r in freshness.devices
        if not r.trustworthy
    ]

    findings: list[LinkSpeedFinding] = []
    switches_analyzed = ports_analyzed = 0
    for device in sorted(switches, key=lambda d: str(d.get('name') or '')):
        mac = normalise_mac(device.get('mac'))
        if mac in untrusted:
            continue
        switches_analyzed += 1
        entries = {
            idx: entry
            for entry in port_entries(device)
            if (idx := int_or_none(entry.get('port_idx'))) is not None
        }
        summary = summarise_ports(device, profiles, mac_to_dev, mac_to_user, sta_rows)
        local_ports = _integration_ports(integration, mac)
        for row in summary:
            if row.port_idx is None or row.enable is False:
                continue
            ports_analyzed += 1
            settings = effective_port_settings(
                device, entries.get(row.port_idx, {}), row.port_idx, profiles, networks
            )
            up = row.up is True
            negotiated = int_or_none(row.speed)
            local_max = int_or_none(local_ports.get(row.port_idx, {}).get('maxSpeedMbps'))
            peer_name = peer_max = None
            if row.lldp:
                peer_name = row.lldp.resolved_name or row.lldp.name
                peer_mac = normalise_mac(row.lldp.chassis_id)
                peer = by_mac.get(peer_mac or '')
                if peer is not None and mac:
                    peer_port = _reciprocal_port(peer, mac)
                    if peer_port is not None:
                        peer_max = int_or_none(
                            _integration_ports(integration, peer_mac)
                            .get(peer_port, {})
                            .get('maxSpeedMbps')
                        )
            comparable, faster = _faster_same_caps(row, summary)
            classified = _classify(
                up=up,
                enabled=row.enable is not False,
                full_duplex=row.full_duplex,
                autoneg=settings.autoneg is not False,
                forced=settings.forced_speed_mbps,
                negotiated=negotiated,
                local_max=local_max,
                peer_max=peer_max,
                comparable=comparable,
                faster=faster,
            )
            if classified is None:
                if not (include_ok and up):
                    continue
                classified = ('OK', 'OK')
            severity, code = classified
            if code == 'CAPABILITY_UNKNOWN' and not include_ok:
                continue
            finding = LinkSpeedFinding(
                severity=severity,
                code=code,
                switch=str(device.get('name') or mac or ''),
                switch_mac=mac,
                port_idx=row.port_idx,
                port_name=row.name,
                profile_name=row.profile_name,
                media=row.media,
                negotiated_mbps=negotiated,
                local_max_mbps=local_max,
                capability_source='integration_api' if local_max is not None else 'unavailable',
                speed_caps_raw=row.speed_caps_raw,
                same_caps_faster_ports=faster,
                peer_name=peer_name,
                peer_max_mbps=peer_max,
                autoneg=settings.autoneg,
                forced_speed_mbps=settings.forced_speed_mbps,
                full_duplex=row.full_duplex,
                sources=settings.sources,
                message='',
            )
            finding.message, finding.recommendation = _describe(code, finding, row.profile_name)
            findings.append(finding)

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.switch or '', f.port_idx))
    page = findings[offset : offset + limit]
    truncated = offset + limit < len(findings)
    return LinkSpeedAuditReport(
        generated_at=local_iso(lambda: now),
        switches_analyzed=switches_analyzed,
        ports_analyzed=ports_analyzed,
        findings_total=len(findings),
        findings=page,
        integration=LinkSpeedIntegration(
            status=integration.status if integration else 'skipped',
            base_path_used=integration.base_path_used if integration else None,
            reason=integration.reason if integration else 'no switch to audit',
        ),
        data_freshness_warnings=warnings,
        validation_passed=not any(f.severity in ('CRITICAL', 'HIGH') for f in findings),
        truncated=truncated,
        next_offset=offset + limit if truncated else None,
    )


# ---------------------------------------------------------------------------
# Fetch (sync, guarded) and the MCP handler
# ---------------------------------------------------------------------------


def collect_link_speed_audit(
    api: Any,
    site: str,
    *,
    switch: Optional[str] = None,
    include_ok: bool = False,
    limit: int = 100,
    offset: int = 0,
    now: Optional[Callable[[], float]] = None,
) -> LinkSpeedAuditReport:
    """Read the controller once per endpoint and run :func:`audit_link_speeds_from_data`.

    Reads ``stat/device``, ``rest/portconf``, ``rest/networkconf``, ``rest/user``
    (and ``stat/device`` again, inside the sibling's ``_build_mac_index``),
    ``stat/sta`` and, best effort, the Integration API for the audited switches
    and their adopted LLDP peers. All GET; failures land in ``errors``.

    Args:
        api: Authenticated ``UnifiApiClient`` behind the read-only guard.
        site: Site name.
        switch: Audit only this switch (name, MAC or IP; an exact name or MAC wins).
        include_ok: Also list CAPABILITY_UNKNOWN findings and up ports with no finding.
        limit: Page size for ``findings`` (1 to 1000).
        offset: Page start for ``findings``.
        now: Clock for the freshness check and ``generated_at``.

    Returns:
        The report.

    Raises:
        SwitchNotFound: ``switch`` matched no switch or more than one.
        ValueError: ``limit`` or ``offset`` is out of range.
    """
    validate_page(limit, offset)
    clock = now or _now
    ctx = Collection()
    response = api.get_devices(site)
    devices = [ctx.clean(d, 'device.raw') for d in rows(response)]
    if not devices:
        ctx.error('devices', 'stat/device returned no devices')
    target_mac: Optional[str] = None
    if switch is not None:
        try:
            target, _, _ = match_switch(devices, switch, device_types=SWITCH_TYPES)
        except LookupError as e:
            raise SwitchNotFound(str(e)) from e
        target_mac = normalise_mac(target.get('mac'))

    profiles = load_profiles(api, site, ctx)
    networks = _load_networks(api, site, ctx)
    mac_to_dev, mac_to_user = _build_mac_index(api, site)
    sta = _load_rows(api, api_path(api, site, 'stat/sta'), ctx, 'clients.stat_sta')

    audited = [
        d
        for d in devices
        if d.get('type') in SWITCH_TYPES
        and (target_mac is None or normalise_mac(d.get('mac')) == target_mac)
    ]
    macs: list[Optional[str]] = [normalise_mac(d.get('mac')) for d in audited]
    for device in audited:
        for entry in device.get('lldp_table') or []:
            if isinstance(entry, dict):
                macs.append(normalise_mac(entry.get('chassis_id')))
    known = {normalise_mac(d.get('mac')) for d in devices}
    integration = (
        fetch_integration_ports(api, site, [m for m in macs if m in known], ctx)
        if audited
        else None
    )

    report = audit_link_speeds_from_data(
        devices,
        profiles,
        networks,
        mac_to_dev,
        mac_to_user,
        sta,
        integration,
        clock(),
        switch_mac=target_mac,
        include_ok=include_ok,
        limit=limit,
        offset=offset,
    )
    report.errors = ctx.errors
    report.sanitised_paths = ctx.sanitised_paths
    return report


def _audit_sync(
    switch: Optional[str], include_ok: bool, limit: int, offset: int
) -> LinkSpeedAuditReport:
    validate_page(limit, offset)
    # Looked up on the module at call time, so a patched helper (tests) is used.
    with port_diagnostics_tools._readonly_sync_client() as (api, site):
        return collect_link_speed_audit(
            api, site, switch=switch, include_ok=include_ok, limit=limit, offset=offset
        )


async def audit_link_speeds(
    switch: Annotated[
        Optional[str],
        Field(description='Audit only this switch (name, MAC or IP). Omit for every switch.'),
    ] = None,
    include_ok: Annotated[
        bool,
        Field(description='Also list ports with unknown capability and healthy up ports'),
    ] = False,
    limit: Annotated[int, Field(description='Maximum findings to return (1-1000)')] = 100,
    offset: Annotated[int, Field(description='Findings to skip, for paging')] = 0,
) -> LinkSpeedAuditReport:
    """Find every switch port below its capability or forced into a speed trap. Read-only.

    When to use this tool:
    - A NAS, server or uplink links at 5G/2.5G/1G instead of 10G
    - A port on a forced-speed profile stays down or links at another rate
    - Sweeping the whole fleet for duplex and negotiation problems

    Capability is the Integration API's maxSpeedMbps only (needs UniFi OS with
    API-key auth); the raw speed_caps value is never decoded, only compared for
    equality between ports of one switch when the Integration API has no data.
    Stale devices are excluded and listed in data_freshness_warnings.

    Args:
        switch: Optional switch to audit (an exact name or MAC always wins).
        include_ok: Also list CAPABILITY_UNKNOWN and OK ports.
        limit: Page size (1-1000).
        offset: Page start.

    Returns:
        LinkSpeedAuditReport: findings (severity, code, switch, port, profile,
        negotiated and maximum speeds, capability_source, speed_caps_raw,
        same_caps_faster_ports, peer, autoneg, forced speed, duplex, per-field
        sources, message, recommendation), integration status,
        validation_passed, truncated and next_offset.

    Raises:
        ToolError: DEVICE_NOT_FOUND for an unknown or ambiguous switch;
            CONFIG_INVALID for an out-of-range limit or offset;
            CONTROLLER_UNREACHABLE or READ_ONLY_VIOLATION.
    """
    return await asyncio.to_thread(
        port_diagnostics_tools._mapped, _audit_sync, switch, include_ok, limit, offset
    )
