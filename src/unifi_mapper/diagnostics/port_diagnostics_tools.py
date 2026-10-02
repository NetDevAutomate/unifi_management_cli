"""MCP tools for read-only switch-port diagnostics.

Thin async wrappers over :mod:`unifi_mapper.port_diagnostics` and
:mod:`unifi_mapper.port_history`, the same code behind the ``unifi-mapper
ports`` commands. Each tool runs its blocking collector in a worker thread (as
``inspect_switch_port`` does), behind the read-only transport guard, and returns
the report's sanitised JSON. None of these tools can write to the controller:
the guard refuses any write before it leaves the machine.

Errors are raised as :class:`ToolError` with a specific code, so a failure is
never mislabelled by a generic exception handler:

* ``DEVICE_NOT_FOUND``: the switch or device is unknown or ambiguous
* ``INVALID_PORT``: the port does not exist on the switch
* ``PROFILE_NOT_FOUND``: a port profile name or id is unknown
* ``CONFIG_INVALID``: a parameter is out of range
* ``CONTROLLER_UNREACHABLE``: authentication failed
* ``READ_ONLY_VIOLATION``: a collector attempted a write (a bug)
"""

import asyncio
from contextlib import contextmanager
from pydantic import Field
from typing import Annotated, Any, Callable, Iterator, Optional, TypeVar
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


T = TypeVar('T')


@contextmanager
def _readonly_sync_client() -> Iterator[tuple[Any, str]]:
    """Yield an authenticated ``UnifiApiClient`` behind the read-only guard, and its site."""
    from unifi_mapper.api_client import UnifiApiClient
    from unifi_mapper.core.utils.readonly import install_read_only_guard
    from unifi_mapper.core.utils.redact import redact_text

    creds = Credentials.from_env()
    scheme = 'https' if creds.port != 80 else 'http'
    api = UnifiApiClient(
        base_url=f'{scheme}://{creds.host}:{creds.port}',
        site=creds.site,
        verify_ssl=creds.verify_ssl,
        username=creds.username,
        password=creds.password,
        api_token=creds.api_token,
    )
    suggestion = (
        'Check UNIFI_URL and UNIFI_CONSOLE_API_TOKEN (or UNIFI_USERNAME/UNIFI_PASSWORD). '
        'The account must be local to the controller, not a UniFi Cloud account.'
    )
    try:
        authenticated = api.login()
    except Exception as e:  # noqa: BLE001 - any login failure is an unreachable controller
        raise ToolError(
            message=f'Could not authenticate to the UniFi controller at {creds.host}: '
            f'{redact_text(e)}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        ) from e
    if not authenticated:
        raise ToolError(
            message=f'Could not authenticate to the UniFi controller at {creds.host}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        )
    install_read_only_guard(api, creds.site)
    try:
        yield api, creds.site
    finally:
        api.logout()


def _mapped(fn: Callable[..., T], *args: Any) -> T:
    """Run ``fn`` and convert collector failures into specific ToolErrors."""
    from unifi_mapper.core.utils.readonly import ReadOnlyViolation
    from unifi_mapper.diagnostic_reads import PortNotFound, ProfileNotFound, SwitchNotFound

    try:
        return fn(*args)
    except ToolError:
        raise
    except ReadOnlyViolation as e:
        raise ToolError(
            message=f'A controller write was refused by the read-only guard: {e}',
            error_code=ErrorCodes.READ_ONLY_VIOLATION,
            suggestion='This is a bug in the diagnostic tool; nothing was written. Report it.',
        ) from e
    except SwitchNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion='Pass the exact switch name or its MAC address (listed in the message).',
            related_tools=['find_device', 'get_switch_ports'],
        ) from e
    except PortNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.INVALID_PORT,
            suggestion='Use a port index listed in the message.',
            related_tools=['get_switch_ports'],
        ) from e
    except ProfileNotFound as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.PROFILE_NOT_FOUND,
            suggestion='Use a profile name exactly as listed in the message, or its _id.',
        ) from e
    except ValueError as e:
        raise ToolError(message=str(e), error_code=ErrorCodes.CONFIG_INVALID) from e


# ---------------------------------------------------------------------------
# Blocking implementations
# ---------------------------------------------------------------------------


def _switch_ports_sync(switch: str, include_raw: bool) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_diagnostics import list_switch_ports

    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, switch)
        return list_switch_ports(api, site, target, include_raw=include_raw).to_json_dict()


def _profile_diff_sync(profile_a: str, profile_b: str) -> dict[str, Any]:
    from unifi_mapper.port_diagnostics import diff_port_profiles

    with _readonly_sync_client() as (api, site):
        return diff_port_profiles(api, site, profile_a, profile_b).to_json_dict()


def _client_history_sync(
    client: str, switch: Optional[str], port: Optional[int]
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_diagnostics import get_client_history as collect_client_history

    if port is not None and switch is None:
        raise ValueError('port needs switch: pass the switch the port belongs to')
    with _readonly_sync_client() as (api, site):
        target = resolve_device(api, site, switch)[0] if switch else None
        return collect_client_history(
            api, site, client, switch=target, port_idx=port
        ).to_json_dict()


def _device_events_sync(
    device: str,
    port: Optional[int],
    clients: Optional[list[str]],
    since_days: int,
    max_events: int,
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device, rows
    from unifi_mapper.port_history import collect_events, validate_event_window

    validate_event_window(since_days, max_events)
    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, device, device_types=None)
        names = [str(d.get('name')) for d in rows(api.get_devices(site)) if d.get('name')]
        return collect_events(
            api,
            site,
            target,
            port_idx=port,
            client_macs=clients or [],
            since_days=since_days,
            max_events=max_events,
            known_device_names=names,
        ).to_json_dict()


def _counter_rates_sync(
    switch: str, port: int, samples: int, interval_seconds: int
) -> dict[str, Any]:
    from unifi_mapper.diagnostic_reads import resolve_device
    from unifi_mapper.port_history import sample_port_counters, validate_sampling

    validate_sampling(samples, interval_seconds)
    with _readonly_sync_client() as (api, site):
        target, _, _ = resolve_device(api, site, switch)
        return sample_port_counters(
            api, site, target, port, samples=samples, interval_seconds=interval_seconds
        ).to_json_dict()


def _diagnose_sync(
    switch: str,
    port: int,
    clients: Optional[list[str]],
    compare_profiles: Optional[list[str]],
    since_days: int,
    counter_samples: int,
    max_events: int,
) -> dict[str, Any]:
    from unifi_mapper.port_diagnostics import BundleQuery, build_port_diagnostic_bundle
    from unifi_mapper.port_history import validate_event_window, validate_sampling

    if compare_profiles and len(compare_profiles) != 2:
        raise ValueError('compare_profiles needs exactly two profile names, or none')
    validate_sampling(counter_samples, 100)
    validate_event_window(since_days, max_events)
    query = BundleQuery(
        switch=switch,
        port=port,
        clients=clients or [],
        compare_profiles=compare_profiles or [],
        since_days=since_days,
        counter_samples=counter_samples,
        max_events=max_events,
    )
    with _readonly_sync_client() as (api, site):
        bundle = build_port_diagnostic_bundle(api, site, query, command='mcp diagnose_switch_port')
        return bundle.to_json_dict()


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


async def get_switch_ports(
    switch: Annotated[
        str, Field(description='Switch name, MAC or IP. An exact name or MAC always wins.')
    ],
    include_raw: Annotated[
        bool, Field(description='Include the full sanitised stat/device record')
    ] = False,
) -> dict[str, Any]:
    """List every port on one switch, with the switch's identity. Read-only.

    When to use this tool:
    - Getting an overview of a switch before drilling into one port
    - Comparing a misbehaving port with its neighbours (speed, autoneg, errors)
    - Finding which port a device or LLDP neighbour is on

    What it reports:
    - Device: model, display model, firmware (and pending upgrade, recorded
      only), uptime, state and whether it is informing, system stats, and every
      temperature/fan/power field the controller exposes
    - Per port: name, media, speed, duplex, autoneg, up, STP state, forward
      mode, effective profile and whether it comes from an override, raw
      speed_caps, PoE mode/power, LLDP neighbour resolved to an adopted device,
      clients on the port, error/drop/CRC counters and link-down count

    Args:
        switch: Switch name, MAC or IP.
        include_raw: Include the full sanitised stat/device record.

    Returns:
        SwitchPortsReport as a dict: schema_version, device, ports, errors,
        sanitised_paths.

    Raises:
        ToolError: DEVICE_NOT_FOUND, CONTROLLER_UNREACHABLE or READ_ONLY_VIOLATION.
    """
    return await asyncio.to_thread(_mapped, _switch_ports_sync, switch, include_raw)


async def diff_port_profiles(
    profile_a: Annotated[str, Field(description='First port profile name or _id')],
    profile_b: Annotated[str, Field(description='Second port profile name or _id')],
) -> dict[str, Any]:
    """Diff two port profiles key by key, and list every port using each. Read-only.

    When to use this tool:
    - Two profiles look identical in the UI but ports behave differently
    - Checking what a profile change will alter before applying it in the UI
    - Seeing whether a profile reaches its intended speed on other ports

    What it reports:
    - differences: dotted keys whose values differ, with both values
    - only_in_a / only_in_b: settings present in one profile only
    - metadata_differences: _id, name, site_id and attr_* kept separate
    - network_refs: referenced networks resolved to names and VLANs
    - used_by: every switch port running each profile, with live speed

    Args:
        profile_a: First profile name (exact, case-insensitive) or _id.
        profile_b: Second profile name or _id.

    Returns:
        ProfileDiff as a dict.

    Raises:
        ToolError: PROFILE_NOT_FOUND (the message lists every profile name).
    """
    return await asyncio.to_thread(_mapped, _profile_diff_sync, profile_a, profile_b)


async def get_client_history(
    client: Annotated[
        str, Field(description='Client MAC (any notation), IP, or a name/hostname substring')
    ],
    switch: Annotated[
        Optional[str], Field(description='Switch to check each record against')
    ] = None,
    port: Annotated[
        Optional[int], Field(description='Port to check against (needs switch)')
    ] = None,
) -> dict[str, Any]:
    """Find where the controller places a client, across every client table. Read-only.

    When to use this tool:
    - Confirming a host is really on the switch port you think it is
    - Finding a client's previous ports and link rates after it went offline
    - Explaining a client that shows on two switches

    Reads stat/sta, v2 clients/active, v2 clients/history, rest/user and
    stat/user. With switch and port, matches_target is judged from each
    record's own location fields (sw_mac/uplink_mac, sw_port), independently
    of how the record was found.

    Args:
        client: MAC, IP, or name/hostname substring.
        switch: Optional switch to check against.
        port: Optional port on that switch.

    Returns:
        ClientHistory as a dict: resolved_macs, records (per-source raw records,
        location, matches_target, link rate, network, VLAN, IP, first/last seen),
        on_target_port and per-source status.

    Raises:
        ToolError: DEVICE_NOT_FOUND for an unknown switch; CONFIG_INVALID when
            port is given without switch.
    """
    return await asyncio.to_thread(_mapped, _client_history_sync, client, switch, port)


async def get_device_events(
    device: Annotated[str, Field(description='Device name, MAC or IP (any adopted device)')],
    port: Annotated[
        Optional[int], Field(description='Only flag entries that mention this port')
    ] = None,
    clients: Annotated[
        Optional[list[str]], Field(description='Client MACs to match as well')
    ] = None,
    since_days: Annotated[int, Field(description='How far back to ask, 1-3650 days')] = 365,
    max_events: Annotated[int, Field(description='Keep at most this many matches')] = 200,
) -> dict[str, Any]:
    """Events, alarms, system log and admin audit for a device, port or client. Read-only.

    When to use this tool:
    - Correlating a link problem with what the controller logged (link
      changes, PoE events, disconnects, profile changes by an admin)
    - Finding out how far back the controller keeps history

    Pages stat/event, reads list/alarm and pages the v2 system-log classes
    device-alert, admin-activity, update-alert and client-alert. Every source
    reports status, record count, pages, truncation and the earliest/latest
    timestamps it returned; the earliest is the observed retention. Matches are
    newest first. A system-log 401/403 is reported as unavailable, not fatal.

    Args:
        device: Device name, MAC or IP.
        port: Optional port; entries must also mention the device.
        clients: Optional client MACs to match independently.
        since_days: History window in days.
        max_events: Cap on returned matches.

    Returns:
        EventHistory as a dict: window, match, sources, matched, matched_total,
        returned, truncated.

    Raises:
        ToolError: DEVICE_NOT_FOUND or CONFIG_INVALID.
    """
    return await asyncio.to_thread(
        _mapped, _device_events_sync, device, port, clients, since_days, max_events
    )


async def get_port_counter_rates(
    switch: Annotated[str, Field(description='Switch name, MAC or IP')],
    port: Annotated[int, Field(description='Port index on the switch, 1-based')],
    samples: Annotated[int, Field(description='Number of samples, 1-5')] = 2,
    interval_seconds: Annotated[int, Field(description='Seconds between samples, 30-300')] = 100,
) -> dict[str, Any]:
    """Sample one port's error counters and report per-minute rates. Read-only.

    BLOCKS for (samples - 1) x interval_seconds: about 100 s with the defaults.
    Many MCP clients time out after about 60 s, so use samples=1 for a single
    snapshot, or the `unifi-mapper ports counters` CLI for longer sampling.

    Verdicts:
    - ok: the device informed between samples, so the rates are real
    - inconclusive_not_informing: last_seen did not advance; rates withheld
      rather than reported as false zeros
    - counter_reset: uptime or a counter went down (reboot or clear)
    - single_sample: one sample, no rate

    Existing baselines (analyze link-errors --snapshot, the port-counter store)
    and the recorded counter history (analyze link-errors --record) are
    compared, never written: baselines.history gives the recorded window,
    deltas, resets and first_increase, the first sample in which each counter
    rose.

    Args:
        switch: Switch name, MAC or IP.
        port: Port index.
        samples: Number of samples.
        interval_seconds: Seconds between samples.

    Returns:
        CounterTrend as a dict.

    Raises:
        ToolError: DEVICE_NOT_FOUND, INVALID_PORT or CONFIG_INVALID.
    """
    return await asyncio.to_thread(
        _mapped, _counter_rates_sync, switch, port, samples, interval_seconds
    )


async def diagnose_switch_port(
    switch: Annotated[
        str, Field(description='Switch name, MAC or IP. An exact name or MAC always wins.')
    ],
    port: Annotated[int, Field(description='Port index on the switch, 1-based')],
    clients: Annotated[
        Optional[list[str]],
        Field(description='Clients (MAC, IP or name) to locate; default is what is on the port'),
    ] = None,
    compare_profiles: Annotated[
        Optional[list[str]], Field(description='Exactly two port profile names or ids to diff')
    ] = None,
    since_days: Annotated[int, Field(description='History window, 1-3650 days')] = 365,
    counter_samples: Annotated[
        int, Field(description='Counter samples, 1-5, 100 s apart. 1 never blocks')
    ] = 1,
    max_events: Annotated[int, Field(description='Keep at most this many history matches')] = 200,
) -> dict[str, Any]:
    """Collect a read-only evidence bundle for one switch port. Read-only.

    When to use this tool:
    - Preparing evidence for a vendor support ticket about a link that will
      not negotiate the expected speed
    - Capturing everything about a port before and after a change

    The bundle contains the switch identity and Network application version,
    the raw port_table entry with negotiation fields and raw speed_caps, the
    full port override and both profile ids side by side, a diff of
    compare_profiles, where the controller places each client, events and
    system log, counter samples, every port on the switch and the Integration
    API's documented port capability (maxSpeedMbps, connector), and the
    port's recorded counter history (counters.baselines.history). It includes
    request_audit (method and path of every request) as proof of read-only
    collection, and sanitised_paths listing the secret fields stripped. Only
    an unknown switch or port is fatal; any other source that fails (for
    example an unknown compare profile, or a system log that needs extra
    permissions) is recorded in errors and the rest is still collected.

    counter_samples > 1 blocks for (counter_samples - 1) x 100 s.

    Args:
        switch: Switch name, MAC or IP.
        port: Port index.
        clients: Clients to locate.
        compare_profiles: Two profiles to diff.
        since_days: History window.
        counter_samples: Counter samples.
        max_events: History match cap.

    Returns:
        PortDiagnosticBundle as a dict.

    Raises:
        ToolError: DEVICE_NOT_FOUND, INVALID_PORT, CONFIG_INVALID,
            CONTROLLER_UNREACHABLE or READ_ONLY_VIOLATION.
    """
    return await asyncio.to_thread(
        _mapped,
        _diagnose_sync,
        switch,
        port,
        clients,
        compare_profiles,
        since_days,
        counter_samples,
        max_events,
    )
