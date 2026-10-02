"""Read-only diagnostics for one switch port, built as vendor-ticket evidence.

Collects what the UniFi controller knows about a switch and one of its ports,
verbatim and sanitised:

* device identity: model, firmware, uptime, state, system stats, thermal and
  power fields, and the Network application version
* the raw ``port_table`` entry, negotiation fields and the raw ``speed_caps``
* the port's full ``port_overrides`` entry and the profile assigned to it
* a key-by-key diff of two port profiles, and every port that uses each
* a client's records across every client table, and where the controller
  places it, independent of how the record was found
* a summary of every port on the switch
* a best-effort Integration API snapshot with Ubiquiti's documented port
  capability fields (``maxSpeedMbps``, ``connector``)

:func:`build_port_diagnostic_bundle` combines these with event and counter
history from :mod:`unifi_mapper.port_history`. It installs the read-only
transport guard first, so nothing it calls can write to the controller, and it
ships the list of requests it made as ``request_audit``.

Nothing is decoded without authority. ``speed_caps`` is reported raw because
Ubiquiti does not document its bit layout; ports sharing the same raw value are
listed instead, so ports can be compared without decoding anything.

Example:
    from unifi_mapper.port_diagnostics import BundleQuery, build_port_diagnostic_bundle

    bundle = build_port_diagnostic_bundle(client, 'default', BundleQuery(switch='USW Flex XG', port=5))
    evidence = bundle.to_json_dict()
"""

import re
import time
from collections import defaultdict
from importlib import metadata
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any, Callable, Iterable, Optional
from unifi_mapper.analysis.link_settings import effective_profile_id, port_override
from unifi_mapper.core.utils.readonly import (
    ReadOnlyViolation,
    assert_guarded,
    install_read_only_guard,
)
from unifi_mapper.diagnostic_reads import (
    Collection,
    DiagnosticModel,
    ProfileNotFound,
    api_path,
    bool_or_none,
    crc_errors,
    dict_or_none,
    find_port_entry,
    int_or_none,
    is_ip_address,
    iso_from_seconds,
    load_device,
    local_iso,
    normalise_mac,
    port_entries,
    resolve_device,
    rows,
    str_or_none,
    v2_path,
)
from unifi_mapper.port_history import (
    DEFAULT_LINK_ERROR_BASELINE,
    CounterTrend,
    EventHistory,
    collect_events,
    sample_port_counters,
    validate_event_window,
    validate_sampling,
)
from unifi_mapper.port_inspect import _build_mac_index, _resolve_mac, inspect_port


PORT_KEY_FIELDS = (
    'port_idx',
    'name',
    'media',
    'speed',
    'full_duplex',
    'autoneg',
    'up',
    'enable',
    'is_uplink',
    'stp_state',
    'op_mode',
    'forward',
    'portconf_id',
    'native_networkconf_id',
    'flowctrl_rx',
    'flowctrl_tx',
    'satisfaction',
    'anomalies',
)
POE_FIELDS = (
    'port_poe',
    'poe_enable',
    'poe_mode',
    'poe_good',
    'poe_class',
    'poe_power',
    'poe_voltage',
    'poe_current',
)
COUNTER_FIELDS = (
    'rx_bytes',
    'tx_bytes',
    'rx_packets',
    'tx_packets',
    'rx_errors',
    'tx_errors',
    'rx_dropped',
    'tx_dropped',
    'rx_broadcast',
    'tx_broadcast',
    'rx_multicast',
    'tx_multicast',
    'link_down_count',
)
ERROR_LIKE_KEY_RE = re.compile(r'crc|err|drop|collision|link_down|flap|pause', re.IGNORECASE)
THERMAL_KEY_RE = re.compile(r'temp|fan|overheat', re.IGNORECASE)
POWER_KEY_RE = re.compile(r'power', re.IGNORECASE)
PROFILE_METADATA_KEY_RE = re.compile(r'^(?:_id|name|site_id|attr_.*)$')
NETWORK_REF_KEYS = (
    'native_networkconf_id',
    'tagged_networkconf_ids',
    'excluded_networkconf_ids',
    'voice_networkconf_id',
)
SPEED_CAPS_STATUS = 'raw - no authoritative mapping'
POWER_SOURCE_NOTE = 'controller record has no power-source field'
# Ubiquiti's Network API spec gives the server as .../proxy/network/integration; the
# repo's network/config.py uses .../integrations. Try the documented base first.
INTEGRATION_BASES = ('/proxy/network/integration', '/proxy/network/integrations')
INTEGRATION_PAGE_SIZE = 200
INTEGRATION_MAX_PAGES = 10
MAX_RESOLVED_CLIENTS = 25
CLIENT_HISTORY_QUERY = (
    'clients/history?only_non_blocked=true&include_unifi_devices=true&within_hours=0'
)
AUDIT_SCOPE = 'requests sent after login; the authentication requests themselves are not listed'


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DeviceIdentity(BaseModel):
    """Who the device is and how healthy its telemetry looks."""

    device_id: Optional[str] = None
    name: Optional[str] = None
    mac: Optional[str] = None
    ip: Optional[str] = None
    type: Optional[str] = None
    serial: Optional[str] = None
    adopted: Optional[bool] = None
    model: Optional[str] = None
    display_model: Optional[str] = None
    display_model_source: str = 'unresolved'  # device.model_name | v2.models | unresolved
    firmware_version: Optional[str] = None
    # Recorded only. Never acted on: upgrading is a write.
    upgradable: Optional[bool] = None
    upgrade_to_firmware: Optional[str] = None
    uptime_seconds: Optional[int] = None
    state: Optional[int] = None
    informing: Optional[bool] = None
    last_seen: Optional[int] = None
    last_seen_iso: Optional[str] = None
    data_age_seconds: Optional[float] = None
    system_stats: Optional[dict[str, Any]] = None
    sys_stats: Optional[dict[str, Any]] = None
    thermal_fields: dict[str, Any] = Field(default_factory=lambda: {})
    power_fields: dict[str, Any] = Field(default_factory=lambda: {})
    power_source_note: Optional[str] = None
    uplink: Optional[dict[str, Any]] = None
    integration_statistics: Optional[dict[str, Any]] = None
    raw: Optional[dict[str, Any]] = None


class SpeedCaps(BaseModel):
    """The undocumented ``speed_caps`` value, reported raw and never decoded."""

    raw: Any = None
    hex: Optional[str] = None
    binary: Optional[str] = None
    decoded: None = None
    decode_status: str = SPEED_CAPS_STATUS
    same_value_ports: list[int] = Field(default_factory=lambda: [])


class MacTableView(BaseModel):
    """MAC addresses learned on the port."""

    source: str = 'absent'  # port_entry | device | absent
    entries: list[dict[str, Any]] = Field(default_factory=lambda: [])


class PortDetail(BaseModel):
    """The port's ``port_table`` entry, verbatim, plus the fields a ticket needs."""

    port_idx: int
    raw: dict[str, Any]
    key_fields: dict[str, Any]
    absent_keys: list[str] = Field(default_factory=lambda: [])
    speed_caps: SpeedCaps
    lldp: list[dict[str, Any]] = Field(default_factory=lambda: [])
    mac_table: MacTableView = Field(default_factory=MacTableView)
    last_connection: Optional[dict[str, Any]] = None
    integration_port: Optional[dict[str, Any]] = None


class ProfileAssignment(BaseModel):
    """Which profile the port is configured with, and whether the device agrees."""

    id: Optional[str] = None
    name: Optional[str] = None
    source: str = 'unknown'  # override | port_table | unknown
    override_portconf_id: Optional[str] = None
    port_table_portconf_id: Optional[str] = None
    # True means configured, but the device has not applied it yet.
    ids_disagree: bool = False
    matches_compare_profile: Optional[str] = None  # a | b | None


class PortOverride(BaseModel):
    """The port's full ``port_overrides`` entry and the profile it resolves to."""

    present: bool = False
    raw: Optional[dict[str, Any]] = None
    profile_assigned: ProfileAssignment = Field(default_factory=ProfileAssignment)
    assigned_profile_raw: Optional[dict[str, Any]] = None


class PortLldpSummary(BaseModel):
    """The LLDP neighbour seen on a port."""

    name: Optional[str] = None
    chassis_id: Optional[str] = None
    port_id: Optional[str] = None
    resolved_kind: str = 'unknown'  # device | client | unknown
    resolved_name: Optional[str] = None


class PortClientRef(BaseModel):
    """A client the controller currently places on a port."""

    mac: Optional[str] = None
    name: Optional[str] = None
    ip: Optional[str] = None


class PortSummary(BaseModel):
    """One row of the all-ports view. Values are copied verbatim from the controller."""

    port_idx: Optional[int] = None
    name: Any = None
    media: Any = None
    speed: Any = None
    full_duplex: Any = None
    autoneg: Any = None
    up: Any = None
    enable: Any = None
    is_uplink: Any = None
    stp_state: Any = None
    forward: Any = None
    op_mode: Any = None
    portconf_id: Optional[str] = None
    profile_name: Optional[str] = None
    has_override: bool = False
    speed_caps_raw: Any = None
    poe_mode: Any = None
    poe_power: Any = None
    lldp: Optional[PortLldpSummary] = None
    clients: list[PortClientRef] = Field(default_factory=lambda: [])
    client_count: int = 0
    last_connection_mac: Optional[str] = None
    rx_errors: Any = None
    tx_errors: Any = None
    rx_dropped: Any = None
    tx_dropped: Any = None
    rx_crc_errors: Any = None
    link_down_count: Any = None


class SwitchPortsReport(DiagnosticModel):
    """Every port on one switch, with the switch's identity."""

    device: DeviceIdentity
    ports: list[PortSummary] = Field(default_factory=lambda: [])


class ProfileRef(BaseModel):
    """One side of a profile diff."""

    id: Optional[str] = None
    name: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=lambda: {})


class ProfileDifference(BaseModel):
    """A dotted key whose value differs between the two profiles."""

    key: str
    a: Any = None
    b: Any = None


class ProfileUsage(BaseModel):
    """A switch port running a profile, with its live link state."""

    switch: Optional[str] = None
    switch_mac: Optional[str] = None
    port_idx: Optional[int] = None
    up: Any = None
    speed: Any = None
    media: Any = None
    source: str = 'port_table'  # override | port_table


class ProfileDiff(DiagnosticModel):
    """Key-by-key comparison of two port profiles (``rest/portconf``)."""

    a: ProfileRef
    b: ProfileRef
    differences: list[ProfileDifference] = Field(default_factory=lambda: [])
    only_in_a: list[str] = Field(default_factory=lambda: [])
    only_in_b: list[str] = Field(default_factory=lambda: [])
    metadata_differences: list[ProfileDifference] = Field(default_factory=lambda: [])
    identical_key_count: int = 0
    network_refs: dict[str, dict[str, Any]] = Field(default_factory=lambda: {})
    used_by: dict[str, list[ProfileUsage]] = Field(default_factory=lambda: {'a': [], 'b': []})


class ClientLocation(BaseModel):
    """Where the controller places a client."""

    sw_mac: Optional[str] = None
    sw_name: Optional[str] = None
    sw_port: Optional[int] = None
    sw_depth: Optional[int] = None
    source: Optional[str] = None  # stat_sta | v2_active | v2_history | stat_user | rest_user


class ClientRecord(BaseModel):
    """Everything the controller holds about one client MAC."""

    mac: str
    stat_sta: Optional[dict[str, Any]] = None
    v2_active: Optional[dict[str, Any]] = None
    v2_history: Optional[dict[str, Any]] = None
    rest_user: Optional[dict[str, Any]] = None
    stat_user: Optional[dict[str, Any]] = None
    location: Optional[ClientLocation] = None
    # True/False/None, judged from the record itself, not from how it was found.
    matches_target: Optional[bool] = None
    link: dict[str, Any] = Field(default_factory=lambda: {})
    network: Optional[str] = None
    vlan: Optional[int] = None
    ip: Optional[str] = None
    uptime_seconds: Optional[int] = None
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None


class ClientHistory(DiagnosticModel):
    """A client looked up by MAC, IP or name across every client table."""

    query: str
    resolution: str = 'none'  # mac | ip | name | none
    resolved_macs: list[str] = Field(default_factory=lambda: [])
    resolved_truncated: bool = False
    target: Optional[dict[str, Any]] = None
    on_target_port: list[dict[str, Any]] = Field(default_factory=lambda: [])
    records: list[ClientRecord] = Field(default_factory=lambda: [])
    sources: dict[str, dict[str, Any]] = Field(default_factory=lambda: {})


class IntegrationSnapshot(BaseModel):
    """The official Integration API's view of the device, best effort, GET only."""

    status: str = 'skipped'  # ok | skipped | unavailable | error
    reason: str = ''
    base_path_used: Optional[str] = None
    application_version: Optional[str] = None
    site_id: Optional[str] = None
    device_id: Optional[str] = None
    device: Optional[dict[str, Any]] = None
    statistics_latest: Optional[dict[str, Any]] = None
    port: Optional[dict[str, Any]] = None


class IntegrationDevice(BaseModel):
    """One device the Integration API listing resolved, with its sanitised detail record."""

    device_id: str
    device: Optional[dict[str, Any]] = None  # None when the detail read failed


class IntegrationPorts(BaseModel):
    """The Integration API's device records for a set of MACs, best effort, GET only."""

    status: str = 'skipped'  # ok | skipped | unavailable | error
    reason: str = ''
    base_path_used: Optional[str] = None
    application_version: Optional[str] = None
    site_id: Optional[str] = None
    devices: dict[str, IntegrationDevice] = Field(default_factory=lambda: {})
    missing_macs: list[str] = Field(default_factory=lambda: [])


class ControllerInfo(BaseModel):
    """The controller and Network application the evidence came from."""

    base_url: str
    site: str
    is_unifi_os: bool = False
    auth_method: Optional[str] = None
    application_version: Optional[str] = None
    application_build: Optional[str] = None
    sysinfo: Optional[dict[str, Any]] = None


class SwitchResolution(BaseModel):
    """How the switch query was resolved."""

    query: str
    matched_by: str
    candidates: list[dict[str, Any]] = Field(default_factory=lambda: [])


class BundleQuery(BaseModel):
    """What to collect for a port diagnostic bundle."""

    switch: str
    port: int
    clients: list[str] = Field(default_factory=lambda: [])
    compare_profiles: list[str] = Field(default_factory=lambda: [])
    since_days: int = 365
    counter_samples: int = 2
    interval_seconds: int = 100
    max_events: int = 500


class PortDiagnosticBundle(DiagnosticModel):
    """Every read-only fact about one switch port, for a vendor ticket.

    Top-level ``errors`` and ``sanitised_paths`` are the union over every
    section. Embedded reports (``events``, ``counters``, ``clients``,
    ``profiles``) also carry their own, so each stays readable on its own.
    """

    generated_at: str
    tool: dict[str, Any]
    controller: Optional[ControllerInfo] = None
    query: BundleQuery
    switch_resolution: SwitchResolution
    device: Optional[DeviceIdentity] = None
    port: Optional[PortDetail] = None
    override: Optional[PortOverride] = None
    inspection: Optional[dict[str, Any]] = None
    profiles: Optional[ProfileDiff] = None
    clients: list[ClientHistory] = Field(default_factory=lambda: [])
    clients_derived_from_port: bool = False
    events: Optional[EventHistory] = None
    counters: Optional[CounterTrend] = None
    switch_ports: Optional[list[PortSummary]] = None
    integration: Optional[IntegrationSnapshot] = None
    request_audit: list[dict[str, str]] = Field(default_factory=lambda: [])


# ---------------------------------------------------------------------------
# Controller and device identity
# ---------------------------------------------------------------------------


def collect_controller_info(client: Any, site: str, ctx: Collection) -> ControllerInfo:
    """Read ``stat/sysinfo`` for the Network application version and build."""
    fetched = ctx.fetch(client, api_path(client, site, 'stat/sysinfo'), section='controller')
    records = rows(fetched.data) if fetched.ok else []
    sysinfo = ctx.clean(records[0], 'controller.sysinfo') if records else None
    return ControllerInfo(
        base_url=str(client.base_url),
        site=site,
        is_unifi_os=bool(getattr(client, 'is_unifi_os', False)),
        auth_method=str_or_none(getattr(client, 'auth_method', None)),
        application_version=str_or_none(sysinfo.get('version')) if sysinfo else None,
        application_build=str_or_none(sysinfo.get('build')) if sysinfo else None,
        sysinfo=sysinfo,
    )


def _display_model(
    client: Any, site: str, device: dict[str, Any], ctx: Collection
) -> tuple[Optional[str], str]:
    """Return the marketing model name from controller data only, and its source."""
    if str_or_none(device.get('model_name')):
        return str(device['model_name']), 'device.model_name'
    model = str(device.get('model') or '').lower()
    if not model:
        return None, 'unresolved'
    fetched = ctx.fetch(client, v2_path(client, site, 'models'), section='device.display_model')
    if not fetched.ok:
        return None, 'unresolved'
    data = fetched.data
    entries = data.get('model_list') if isinstance(data, dict) else data
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        codes = {str(entry.get(k) or '').lower() for k in ('model', 'model_code', 'sysid', 'id')}
        if model in codes:
            for key in ('display_name', 'name', 'model_name', 'full_name', 'product_name'):
                if str_or_none(entry.get(key)):
                    return str(entry[key]), 'v2.models'
    return None, 'unresolved'


def collect_device_identity(
    client: Any,
    site: str,
    device: dict[str, Any],
    ctx: Collection,
    *,
    now: Callable[[], float] = time.time,
    include_raw: bool = True,
) -> DeviceIdentity:
    """Describe the device from its (already sanitised) ``stat/device`` record.

    Temperature, fan and power fields are captured generically: every top-level
    key matching ``temp|fan|overheat`` or ``power`` is copied verbatim, because
    the field names vary by model and firmware.
    """
    display_model, display_source = _display_model(client, site, device, ctx)
    state = int_or_none(device.get('state'))
    last_seen = int_or_none(device.get('last_seen'))
    return DeviceIdentity(
        device_id=str_or_none(device.get('_id')),
        name=str_or_none(device.get('name')),
        mac=str_or_none(device.get('mac')),
        ip=str_or_none(device.get('ip')),
        type=str_or_none(device.get('type')),
        serial=str_or_none(device.get('serial')),
        adopted=bool_or_none(device.get('adopted')),
        model=str_or_none(device.get('model')),
        display_model=display_model,
        display_model_source=display_source,
        firmware_version=str_or_none(device.get('version')),
        upgradable=bool_or_none(device.get('upgradable')),
        upgrade_to_firmware=str_or_none(device.get('upgrade_to_firmware')),
        uptime_seconds=int_or_none(device.get('uptime')),
        state=state,
        # Same rule as analysis/device_freshness.py: state 1 means connected and informing.
        informing=(state == 1) if state is not None else None,
        last_seen=last_seen,
        last_seen_iso=iso_from_seconds(last_seen),
        data_age_seconds=round(now() - last_seen, 1) if last_seen else None,
        system_stats=dict_or_none(device.get('system-stats')),
        sys_stats=dict_or_none(device.get('sys_stats')),
        thermal_fields={k: v for k, v in device.items() if THERMAL_KEY_RE.search(str(k))},
        power_fields={k: v for k, v in device.items() if POWER_KEY_RE.search(str(k))},
        power_source_note=(
            None if any('power_source' in str(k).lower() for k in device) else POWER_SOURCE_NOTE
        ),
        uplink=dict_or_none(device.get('uplink')),
        raw=device if include_raw else None,
    )


# ---------------------------------------------------------------------------
# Port detail and override
# ---------------------------------------------------------------------------


def _lldp_port(entry: dict[str, Any]) -> Optional[int]:
    for key in ('local_port_idx', 'port_idx', 'lldp_local_port_idx'):
        value = int_or_none(entry.get(key))
        if value is not None:
            return value
    return None


def _speed_caps(entry: dict[str, Any], table: list[dict[str, Any]], port_idx: int) -> SpeedCaps:
    raw = entry.get('speed_caps')
    if isinstance(raw, bool) or not isinstance(raw, int):
        return SpeedCaps(raw=raw)
    same = sorted(
        idx
        for idx, other in ((int_or_none(p.get('port_idx')), p) for p in table)
        if idx is not None and idx != port_idx and other.get('speed_caps') == raw
    )
    return SpeedCaps(raw=raw, hex=hex(raw), binary=bin(raw), same_value_ports=same)


def _error_like_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Copy every other counter-like key, including those nested in ``port_stats``."""
    found = {
        str(k): v
        for k, v in entry.items()
        if ERROR_LIKE_KEY_RE.search(str(k)) and k not in COUNTER_FIELDS and k != 'port_stats'
    }
    stats = entry.get('port_stats')
    if isinstance(stats, dict):
        found.update(
            {f'port_stats.{k}': v for k, v in stats.items() if ERROR_LIKE_KEY_RE.search(str(k))}
        )
    return found


def _mac_table_view(entry: dict[str, Any], device: dict[str, Any], port_idx: int) -> MacTableView:
    if isinstance(entry.get('mac_table'), list):
        return MacTableView(
            source='port_entry', entries=[e for e in entry['mac_table'] if isinstance(e, dict)]
        )
    table = device.get('mac_table')
    if isinstance(table, list):
        return MacTableView(
            source='device',
            entries=[
                e
                for e in table
                if isinstance(e, dict) and int_or_none(e.get('port_idx')) == port_idx
            ],
        )
    return MacTableView(source='absent')


def collect_port_detail(device: dict[str, Any], port_idx: int) -> PortDetail:
    """Return the port's raw entry and key fields from a sanitised device record.

    Raises:
        PortNotFound: The port does not exist on the device.
    """
    entry = find_port_entry(device, port_idx)
    crc, _ = crc_errors(entry)
    counters: dict[str, Any] = {key: entry.get(key) for key in COUNTER_FIELDS}
    counters['rx_crc_errors'] = crc
    counters['other'] = _error_like_fields(entry)
    key_fields: dict[str, Any] = {key: entry.get(key) for key in PORT_KEY_FIELDS}
    key_fields['poe'] = {key: entry.get(key) for key in POE_FIELDS}
    key_fields['counters'] = counters
    absent = [k for k in (*PORT_KEY_FIELDS, *POE_FIELDS, *COUNTER_FIELDS) if k not in entry]
    if crc is None:
        absent.append('rx_crc_errors')
    return PortDetail(
        port_idx=port_idx,
        raw=entry,
        key_fields=key_fields,
        absent_keys=absent,
        speed_caps=_speed_caps(entry, port_entries(device), port_idx),
        lldp=[
            e
            for e in device.get('lldp_table') or []
            if isinstance(e, dict) and _lldp_port(e) == port_idx
        ],
        mac_table=_mac_table_view(entry, device, port_idx),
        last_connection=dict_or_none(entry.get('last_connection')),
    )


# Kept as a name so nothing importing it breaks; the rule lives in analysis/link_settings.
_override_for = port_override


def collect_override(
    device: dict[str, Any],
    port_idx: int,
    profiles: dict[str, dict[str, Any]],
    compare_ids: Optional[tuple[Optional[str], Optional[str]]] = None,
) -> PortOverride:
    """Return the full ``port_overrides`` entry and the profile it resolves to.

    The override's ``portconf_id`` wins over the port table's, as in
    ``ports inspect``. When the two disagree, ``ids_disagree`` is True: the
    profile has been configured but the device has not applied it yet.
    """
    entry = find_port_entry(device, port_idx)
    override = port_override(device, port_idx)
    override_id = str_or_none(override.get('portconf_id')) if override else None
    table_id = str_or_none(entry.get('portconf_id'))
    assigned, source = effective_profile_id(device, entry, port_idx)
    profile = profiles.get(assigned or '')
    matches: Optional[str] = None
    if compare_ids and assigned:
        if assigned == compare_ids[0]:
            matches = 'a'
        elif assigned == compare_ids[1]:
            matches = 'b'
    return PortOverride(
        present=override is not None,
        raw=override,
        profile_assigned=ProfileAssignment(
            id=assigned,
            name=str_or_none(profile.get('name')) if profile else None,
            source=source,
            override_portconf_id=override_id,
            port_table_portconf_id=table_id,
            ids_disagree=bool(override_id and table_id and override_id != table_id),
            matches_compare_profile=matches,
        ),
        assigned_profile_raw=profile,
    )


# ---------------------------------------------------------------------------
# All ports
# ---------------------------------------------------------------------------


def _clients_by_port(
    device: dict[str, Any], sta_rows: list[dict[str, Any]]
) -> dict[int, list[PortClientRef]]:
    mac = normalise_mac(device.get('mac'))
    by_port: dict[int, list[PortClientRef]] = defaultdict(list)
    for client in sta_rows:
        port = int_or_none(client.get('sw_port'))
        if port is None or not mac or normalise_mac(client.get('sw_mac')) != mac:
            continue
        by_port[port].append(
            PortClientRef(
                mac=normalise_mac(client.get('mac')),
                name=str_or_none(client.get('name') or client.get('hostname')),
                ip=str_or_none(client.get('ip')),
            )
        )
    return by_port


def summarise_ports(
    device: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    mac_to_dev: dict[str, dict[str, Any]],
    mac_to_user: dict[str, dict[str, Any]],
    sta_rows: list[dict[str, Any]],
) -> list[PortSummary]:
    """Build one summary row per port from already-fetched data (no I/O)."""
    lldp_by_port: dict[int, dict[str, Any]] = {}
    for entry in device.get('lldp_table') or []:
        if isinstance(entry, dict):
            port = _lldp_port(entry)
            if port is not None:
                lldp_by_port.setdefault(port, entry)
    clients = _clients_by_port(device, sta_rows)

    summaries: list[PortSummary] = []
    for entry in sorted(port_entries(device), key=lambda p: int_or_none(p.get('port_idx')) or 0):
        idx = int_or_none(entry.get('port_idx'))
        override = port_override(device, idx)
        profile_id, _ = effective_profile_id(device, entry, idx)
        profile = profiles.get(profile_id or '') or {}
        lldp_summary = None
        lldp = lldp_by_port.get(idx) if idx is not None else None
        if lldp:
            chassis = str_or_none(lldp.get('chassis_id'))
            identity = _resolve_mac(chassis, mac_to_dev, mac_to_user)
            lldp_summary = PortLldpSummary(
                name=str_or_none(lldp.get('system_name') or lldp.get('chassis_name'))
                or identity.name,
                chassis_id=chassis,
                port_id=str_or_none(lldp.get('port_id')),
                resolved_kind=identity.kind,
                resolved_name=identity.name,
            )
        on_port = clients.get(idx, []) if idx is not None else []
        last_connection = entry.get('last_connection')
        summaries.append(
            PortSummary(
                port_idx=idx,
                name=entry.get('name'),
                media=entry.get('media'),
                speed=entry.get('speed'),
                full_duplex=entry.get('full_duplex'),
                autoneg=entry.get('autoneg'),
                up=entry.get('up'),
                enable=entry.get('enable'),
                is_uplink=entry.get('is_uplink'),
                stp_state=entry.get('stp_state'),
                forward=entry.get('forward'),
                op_mode=entry.get('op_mode'),
                portconf_id=profile_id,
                profile_name=str_or_none(profile.get('name')),
                has_override=override is not None,
                speed_caps_raw=entry.get('speed_caps'),
                poe_mode=entry.get('poe_mode'),
                poe_power=entry.get('poe_power'),
                lldp=lldp_summary,
                clients=on_port,
                client_count=len(on_port),
                last_connection_mac=(
                    normalise_mac(last_connection.get('mac'))
                    if isinstance(last_connection, dict)
                    else None
                ),
                rx_errors=entry.get('rx_errors'),
                tx_errors=entry.get('tx_errors'),
                rx_dropped=entry.get('rx_dropped'),
                tx_dropped=entry.get('tx_dropped'),
                rx_crc_errors=crc_errors(entry)[0],
                link_down_count=entry.get('link_down_count'),
            )
        )
    return summaries


def load_profiles(client: Any, site: str, ctx: Collection) -> dict[str, dict[str, Any]]:
    """Return sanitised port profiles (``rest/portconf``) keyed by ``_id``."""
    fetched = ctx.fetch(client, api_path(client, site, 'rest/portconf'), section='profiles')
    cleaned = ctx.clean(rows(fetched.data), 'portconf') if fetched.ok else []
    return {str(p['_id']): p for p in cleaned if isinstance(p, dict) and p.get('_id')}


def _load_rows(client: Any, path: str, ctx: Collection, section: str) -> list[dict[str, Any]]:
    fetched = ctx.fetch(client, path, section=section)
    return rows(fetched.data) if fetched.ok else []


def list_switch_ports(
    client: Any,
    site: str,
    switch: dict[str, Any],
    *,
    include_raw: bool = False,
    now: Callable[[], float] = time.time,
) -> SwitchPortsReport:
    """Summarise every port on one switch, with the switch's identity."""
    ctx = Collection()
    device = ctx.clean(load_device(client, site, switch), 'device.raw')
    identity = collect_device_identity(client, site, device, ctx, now=now, include_raw=include_raw)
    profiles = load_profiles(client, site, ctx)
    mac_to_dev, mac_to_user = _build_mac_index(client, site)
    sta = _load_rows(client, api_path(client, site, 'stat/sta'), ctx, 'clients.stat_sta')
    return SwitchPortsReport(
        device=identity,
        ports=summarise_ports(device, profiles, mac_to_dev, mac_to_user, sta),
        errors=ctx.errors,
        sanitised_paths=ctx.sanitised_paths,
    )


# ---------------------------------------------------------------------------
# Profile diff
# ---------------------------------------------------------------------------


def find_profile(profiles: dict[str, dict[str, Any]], query: str) -> dict[str, Any]:
    """Find a profile by ``_id`` or exact name (case-insensitive).

    Raises:
        ProfileNotFound: No profile matched, or several share the name. The
            message lists every profile name.
    """
    wanted = query.strip()
    if wanted in profiles:
        return profiles[wanted]
    named = [
        p for p in profiles.values() if str(p.get('name') or '').strip().lower() == wanted.lower()
    ]
    if len(named) == 1:
        return named[0]
    names = ', '.join(sorted(repr(str(p.get('name'))) for p in profiles.values())) or '(none)'
    if named:
        raise ProfileNotFound(
            f'{len(named)} port profiles are named {query!r}; pass the _id instead. '
            f'Known profiles: {names}'
        )
    raise ProfileNotFound(f'No port profile named {query!r}. Known profiles: {names}')


def _flatten(value: dict[str, Any], prefix: str = '') -> dict[str, Any]:
    """Flatten nested dicts to dotted keys. Lists are compared as whole values."""
    flat: dict[str, Any] = {}
    for key, item in value.items():
        dotted = f'{prefix}.{key}' if prefix else str(key)
        if isinstance(item, dict) and item:
            flat.update(_flatten(item, dotted))
        else:
            flat[dotted] = item
    return flat


def _network_ids(profile: dict[str, Any], side: str) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = defaultdict(list)
    for key in NETWORK_REF_KEYS:
        value = profile.get(key)
        ids = value if isinstance(value, list) else [value]
        for network_id in ids:
            if isinstance(network_id, str) and network_id:
                refs[network_id].append(f'{side}.{key}')
    return refs


def profile_usage(devices: Iterable[dict[str, Any]], profile_id: str) -> list[ProfileUsage]:
    """List every device port whose effective profile is ``profile_id``."""
    usage: list[ProfileUsage] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        for entry in port_entries(device):
            idx = int_or_none(entry.get('port_idx'))
            if idx is None:
                continue
            effective, source = effective_profile_id(device, entry, idx)
            if effective != profile_id:
                continue
            usage.append(
                ProfileUsage(
                    switch=str_or_none(device.get('name')),
                    switch_mac=normalise_mac(device.get('mac')),
                    port_idx=idx,
                    up=entry.get('up'),
                    speed=entry.get('speed'),
                    media=entry.get('media'),
                    source=source,
                )
            )
    return sorted(usage, key=lambda u: (u.switch or '', u.port_idx or 0))


def build_profile_diff(
    a: dict[str, Any],
    b: dict[str, Any],
    networks: dict[str, dict[str, Any]],
    devices: Iterable[dict[str, Any]],
) -> ProfileDiff:
    """Diff two sanitised profiles key by key (no I/O).

    Identity and bookkeeping keys (``_id``, ``name``, ``site_id``, ``attr_*``)
    are reported separately in ``metadata_differences`` so they do not hide
    the settings that actually differ.
    """
    flat_a, flat_b = _flatten(a), _flatten(b)
    differences: list[ProfileDifference] = []
    metadata: list[ProfileDifference] = []
    only_a: list[str] = []
    only_b: list[str] = []
    identical = 0
    for key in sorted(set(flat_a) | set(flat_b)):
        in_a, in_b = key in flat_a, key in flat_b
        if PROFILE_METADATA_KEY_RE.match(key):
            if not (in_a and in_b and flat_a[key] == flat_b[key]):
                metadata.append(ProfileDifference(key=key, a=flat_a.get(key), b=flat_b.get(key)))
            continue
        if in_a and in_b:
            if flat_a[key] == flat_b[key]:
                identical += 1
            else:
                differences.append(ProfileDifference(key=key, a=flat_a[key], b=flat_b[key]))
        elif in_a:
            only_a.append(key)
        else:
            only_b.append(key)

    referenced: dict[str, list[str]] = defaultdict(list)
    for side, profile in (('a', a), ('b', b)):
        for network_id, keys in _network_ids(profile, side).items():
            referenced[network_id].extend(keys)
    network_refs = {
        network_id: {
            'name': (networks.get(network_id) or {}).get('name'),
            'vlan': (networks.get(network_id) or {}).get('vlan'),
            'referenced_by': keys,
        }
        for network_id, keys in sorted(referenced.items())
    }

    device_list = list(devices)
    a_id, b_id = str(a.get('_id') or ''), str(b.get('_id') or '')
    return ProfileDiff(
        a=ProfileRef(id=a_id or None, name=str_or_none(a.get('name')), raw=a),
        b=ProfileRef(id=b_id or None, name=str_or_none(b.get('name')), raw=b),
        differences=differences,
        only_in_a=only_a,
        only_in_b=only_b,
        metadata_differences=metadata,
        identical_key_count=identical,
        network_refs=network_refs,
        used_by={
            'a': profile_usage(device_list, a_id) if a_id else [],
            'b': profile_usage(device_list, b_id) if b_id else [],
        },
    )


def _load_networks(client: Any, site: str, ctx: Collection) -> dict[str, dict[str, Any]]:
    """Return ``{network_id: {name, vlan}}``. Only those two fields are kept."""
    records = _load_rows(client, api_path(client, site, 'rest/networkconf'), ctx, 'networks')
    return {
        str(r['_id']): {'name': r.get('name'), 'vlan': r.get('vlan')}
        for r in records
        if r.get('_id')
    }


def _device_rows(client: Any, site: str) -> list[dict[str, Any]]:
    response = client.get_devices(site)
    return rows(response) if isinstance(response, dict) else []


def diff_port_profiles(
    client: Any,
    site: str,
    profile_a: str,
    profile_b: str,
    *,
    ctx: Optional[Collection] = None,
    profiles: Optional[dict[str, dict[str, Any]]] = None,
    devices: Optional[list[dict[str, Any]]] = None,
) -> ProfileDiff:
    """Diff two port profiles by name or ``_id``, and show where each is used.

    Raises:
        ProfileNotFound: Either profile is missing. The message lists every name.
    """
    ctx = ctx or Collection()
    first_error, first_path = len(ctx.errors), len(ctx.sanitised_paths)
    if profiles is None:
        profiles = load_profiles(client, site, ctx)
    a = find_profile(profiles, profile_a)
    b = find_profile(profiles, profile_b)
    diff = build_profile_diff(
        a,
        b,
        _load_networks(client, site, ctx),
        devices if devices is not None else _device_rows(client, site),
    )
    diff.errors = ctx.errors[first_error:]
    diff.sanitised_paths = ctx.sanitised_paths[first_path:]
    return diff


# ---------------------------------------------------------------------------
# Client history
# ---------------------------------------------------------------------------


def _client_ips(record: dict[str, Any]) -> set[str]:
    return {
        str(record[k]).strip()
        for k in ('ip', 'last_ip', 'fixed_ip')
        if isinstance(record.get(k), str) and record.get(k)
    }


def _client_names(record: dict[str, Any]) -> list[str]:
    return [
        str(record[k]).lower()
        for k in ('name', 'hostname', 'display_name')
        if isinstance(record.get(k), str) and record.get(k)
    ]


def _resolve_client_macs(
    identifier: str, sources: Iterable[list[dict[str, Any]]]
) -> tuple[list[str], str]:
    mac = normalise_mac(identifier)
    if mac:
        return [mac], 'mac'
    wanted = identifier.strip()
    records = [r for source in sources for r in source]
    if is_ip_address(wanted):
        found = {normalise_mac(r.get('mac')) for r in records if wanted in _client_ips(r)}
        kind = 'ip'
    else:
        needle = wanted.lower()
        found = {
            normalise_mac(r.get('mac'))
            for r in records
            if needle and any(needle in name for name in _client_names(r))
        }
        kind = 'name'
    return sorted(m for m in found if m), kind


def _first_value(records: list[Optional[dict[str, Any]]], keys: tuple[str, ...]) -> Any:
    for record in records:
        if not record:
            continue
        for key in keys:
            value = record.get(key)
            if value not in (None, ''):
                return value
    return None


def _location(
    sources: list[tuple[str, Optional[dict[str, Any]]]], device_names: dict[str, str]
) -> Optional[ClientLocation]:
    for name, record in sources:
        if not record:
            continue
        sw_mac = normalise_mac(
            record.get('sw_mac') or record.get('uplink_mac') or record.get('last_uplink_mac')
        )
        sw_port = int_or_none(record.get('sw_port'))
        if sw_mac is None and sw_port is None:
            continue
        return ClientLocation(
            sw_mac=sw_mac,
            sw_name=device_names.get(sw_mac or '')
            or str_or_none(record.get('sw_name') or record.get('last_uplink_name')),
            sw_port=sw_port,
            sw_depth=int_or_none(record.get('sw_depth')),
            source=name,
        )
    return None


def _by_mac(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        mac = normalise_mac(record.get('mac'))
        if mac:
            indexed.setdefault(mac, record)
    return indexed


def get_client_history(
    client: Any,
    site: str,
    identifier: str,
    *,
    switch: Optional[dict[str, Any]] = None,
    port_idx: Optional[int] = None,
    ctx: Optional[Collection] = None,
    devices: Optional[list[dict[str, Any]]] = None,
) -> ClientHistory:
    """Look a client up by MAC, IP or name across every client table.

    Reads ``stat/sta``, v2 ``clients/active``, v2 ``clients/history``,
    ``rest/user`` and ``stat/user/{mac}``. The location reported for each
    record is read from the record itself, so ``matches_target`` is an
    independent check of where the controller places the client, not a
    restatement of how it was found.

    Args:
        client: Authenticated, read-only-guarded ``UnifiApiClient``.
        site: Site name.
        identifier: Client MAC (any notation), IP, or a name/hostname substring.
        switch: Resolved target switch, to check each record against.
        port_idx: Target port on ``switch``.
        ctx: Shared collection context.
        devices: Adopted devices, to name the switch a client sits on.
    """
    ctx = ctx or Collection()
    first_error, first_path = len(ctx.errors), len(ctx.sanitised_paths)
    reads = {
        'stat_sta': api_path(client, site, 'stat/sta'),
        'v2_active': v2_path(client, site, 'clients/active'),
        'v2_history': v2_path(client, site, CLIENT_HISTORY_QUERY),
        'rest_user': api_path(client, site, 'rest/user'),
    }
    tables: dict[str, list[dict[str, Any]]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for name, path in reads.items():
        fetched = ctx.fetch(client, path, section=f'clients.{name}')
        tables[name] = ctx.clean(rows(fetched.data), f'clients.{name}') if fetched.ok else []
        sources[name] = {
            'status': 'ok' if fetched.ok else 'error',
            'http_status': fetched.status,
            'records': len(tables[name]),
        }

    macs, resolution = _resolve_client_macs(identifier, tables.values())
    truncated = len(macs) > MAX_RESOLVED_CLIENTS
    macs = macs[:MAX_RESOLVED_CLIENTS]
    if not macs:
        resolution = 'none'

    device_list = devices if devices is not None else _device_rows(client, site)
    device_names = {
        mac: str(d.get('name') or '')
        for d in device_list
        if (mac := normalise_mac(d.get('mac'))) is not None
    }
    target_mac = normalise_mac(switch.get('mac')) if switch else None
    target = (
        {
            'switch_mac': target_mac,
            'switch_name': str_or_none(switch.get('name')),
            'port': port_idx,
        }
        if switch
        else None
    )
    indexed = {name: _by_mac(table) for name, table in tables.items()}

    records: list[ClientRecord] = []
    stat_user_ok = 0
    for mac in macs:
        fetched = ctx.fetch(
            client, api_path(client, site, f'stat/user/{mac}'), section='clients.stat_user'
        )
        stat_user_rows = rows(fetched.data) if fetched.ok else []
        stat_user = (
            ctx.clean(stat_user_rows[0], f'clients.stat_user[{mac}]') if stat_user_rows else None
        )
        stat_user_ok += int(fetched.ok)
        sta = indexed['stat_sta'].get(mac)
        active = indexed['v2_active'].get(mac)
        history = indexed['v2_history'].get(mac)
        user = indexed['rest_user'].get(mac)
        location = _location(
            [
                ('stat_sta', sta),
                ('v2_active', active),
                ('v2_history', history),
                ('stat_user', stat_user),
                ('rest_user', user),
            ],
            device_names,
        )
        matches: Optional[bool] = None
        if target_mac and location and location.sw_mac:
            matches = location.sw_mac == target_mac and (
                port_idx is None or location.sw_port == port_idx
            )
        ordered = [sta, active, history, stat_user, user]
        records.append(
            ClientRecord(
                mac=mac,
                stat_sta=sta,
                v2_active=active,
                v2_history=history,
                rest_user=user,
                stat_user=stat_user,
                location=location,
                matches_target=matches,
                link={
                    'wired_rate_mbps': _first_value([active, history, sta], ('wired_rate_mbps',)),
                    'is_wired': _first_value(ordered, ('is_wired',)),
                },
                network=str_or_none(
                    _first_value(
                        ordered, ('network', 'network_name', 'last_connection_network_name')
                    )
                ),
                vlan=int_or_none(_first_value(ordered, ('vlan',))),
                ip=str_or_none(_first_value(ordered, ('ip', 'last_ip', 'fixed_ip'))),
                uptime_seconds=int_or_none(_first_value([sta, active], ('uptime',))),
                first_seen=int_or_none(_first_value(ordered, ('first_seen',))),
                last_seen=int_or_none(_first_value(ordered, ('last_seen',))),
            )
        )
    sources['stat_user'] = {
        'status': 'ok' if stat_user_ok == len(macs) else 'error',
        'records': stat_user_ok,
        'queried': len(macs),
    }

    on_target: list[dict[str, Any]] = []
    if target_mac:
        for source_name, table in (
            ('stat_sta', tables['stat_sta']),
            ('v2_active', tables['v2_active']),
        ):
            for record in table:
                sw_mac = normalise_mac(
                    record.get('sw_mac')
                    or record.get('uplink_mac')
                    or record.get('last_uplink_mac')
                )
                if sw_mac == target_mac and (
                    port_idx is None or int_or_none(record.get('sw_port')) == port_idx
                ):
                    on_target.append({'source': source_name, 'raw': record})

    return ClientHistory(
        query=identifier,
        resolution=resolution,
        resolved_macs=macs,
        resolved_truncated=truncated,
        target=target,
        on_target_port=on_target,
        records=records,
        sources=sources,
        errors=ctx.errors[first_error:],
        sanitised_paths=ctx.sanitised_paths[first_path:],
    )


# ---------------------------------------------------------------------------
# Integration API (official, documented, GET only)
# ---------------------------------------------------------------------------


def fetch_integration_ports(
    client: Any, site: str, macs: Iterable[Optional[str]], ctx: Collection
) -> IntegrationPorts:
    """Read the official Integration API's device records for ``macs``, best effort.

    Only runs on UniFi OS with API-key auth, which is what the Integration API
    accepts. Probes ``{base}/v1/info`` over :data:`INTEGRATION_BASES` (the
    documented base first, the plural variant on a 404) and records
    ``base_path_used``; then reads ``/v1/sites`` once, pages the site's device
    listing until every requested MAC is found or a page is short, and reads
    ``/devices/{deviceId}`` once per found MAC. GET only; never raises on an
    HTTP failure (each one is recorded in ``ctx`` as the snapshot always did).

    Args:
        client: Authenticated, guarded ``UnifiApiClient``.
        site: Legacy site name (matched to ``internalReference``).
        macs: Device MACs to resolve, in any notation. Invalid ones are ignored.
        ctx: The collection that records failures and stripped secret paths.

    Returns:
        The :class:`IntegrationPorts` result. ``devices`` is keyed by normalised
        MAC; MACs the listing did not return are in ``missing_macs``.
    """
    wanted: list[str] = []
    for mac in macs:
        normalised = normalise_mac(mac)
        if normalised and normalised not in wanted:
            wanted.append(normalised)

    if not getattr(client, 'is_unifi_os', False):
        return IntegrationPorts(
            status='skipped', reason='controller is not UniFi OS', missing_macs=wanted
        )
    if getattr(client, 'auth_method', None) != 'token':
        return IntegrationPorts(
            status='skipped',
            reason='the Integration API needs API-key (token) authentication',
            missing_macs=wanted,
        )

    base: Optional[str] = None
    info: Any = None
    for candidate in INTEGRATION_BASES:
        fetched = ctx.fetch(
            client, f'{candidate}/v1/info', section='integration.info', record_error=False
        )
        if fetched.status == 404:
            continue
        if not fetched.ok:
            ctx.error('integration.info', f'GET {candidate}/v1/info: {fetched.error}')
            return IntegrationPorts(
                status='unavailable' if fetched.status in (401, 403) else 'error',
                reason=fetched.error or 'request failed',
                base_path_used=candidate,
                missing_macs=wanted,
            )
        base, info = candidate, fetched.data
        break
    if base is None:
        return IntegrationPorts(
            status='unavailable',
            reason=f'Integration API not found at {" or ".join(INTEGRATION_BASES)}',
            missing_macs=wanted,
        )

    result = IntegrationPorts(
        status='ok',
        base_path_used=base,
        application_version=str_or_none((info or {}).get('applicationVersion'))
        if isinstance(info, dict)
        else None,
        missing_macs=wanted,
    )
    sites = ctx.fetch(client, f'{base}/v1/sites', section='integration.sites')
    if not sites.ok:
        result.status, result.reason = 'error', sites.error or 'GET /v1/sites failed'
        return result
    site_id = next(
        (
            str_or_none(s.get('id'))
            for s in rows(sites.data)
            if str(s.get('internalReference') or '') == site
        ),
        None,
    )
    if site_id is None:
        result.status, result.reason = 'error', f'site {site!r} not found in /v1/sites'
        return result
    result.site_id = site_id

    found: dict[str, str] = {}
    for page in range(INTEGRATION_MAX_PAGES):
        listed = ctx.fetch(
            client,
            f'{base}/v1/sites/{site_id}/devices',
            section='integration.devices',
            params={'offset': page * INTEGRATION_PAGE_SIZE, 'limit': INTEGRATION_PAGE_SIZE},
        )
        page_rows = rows(listed.data)
        for record in page_rows:
            mac = normalise_mac(record.get('macAddress'))
            device_id = str_or_none(record.get('id'))
            if mac in wanted and mac not in found and device_id:
                found[mac] = device_id
        if (wanted and len(found) == len(wanted)) or len(page_rows) < INTEGRATION_PAGE_SIZE:
            break
    result.missing_macs = [mac for mac in wanted if mac not in found]

    for mac in wanted:
        device_id = found.get(mac)
        if device_id is None:
            continue
        detail = ctx.fetch(
            client, f'{base}/v1/sites/{site_id}/devices/{device_id}', section='integration.device'
        )
        device = (
            ctx.clean(detail.data, 'integration.device')
            if detail.ok and isinstance(detail.data, dict)
            else None
        )
        result.devices[mac] = IntegrationDevice(device_id=device_id, device=device)
    return result


def collect_integration_snapshot(
    client: Any, site: str, switch_mac: Optional[str], port_idx: int, ctx: Collection
) -> IntegrationSnapshot:
    """Read the official Integration API's view of the device, best effort.

    Only runs on UniFi OS with API-key auth, which is what the Integration API
    accepts. Tries the documented base path, then the repo's plural variant on
    a 404, and records ``base_path_used``. The device lookup is
    :func:`fetch_integration_ports` for one MAC.
    """
    fetched = fetch_integration_ports(client, site, [switch_mac], ctx)
    snapshot = IntegrationSnapshot(
        status=fetched.status,
        reason=fetched.reason,
        base_path_used=fetched.base_path_used,
        application_version=fetched.application_version,
        site_id=fetched.site_id,
    )
    if fetched.status != 'ok':
        return snapshot
    found = fetched.devices.get(normalise_mac(switch_mac) or '')
    if found is None:
        snapshot.status, snapshot.reason = 'error', 'device not found in the Integration API'
        return snapshot
    snapshot.device_id = found.device_id
    snapshot.device = found.device
    if found.device is not None:
        ports = (found.device.get('interfaces') or {}).get('ports') or []
        snapshot.port = next(
            (p for p in ports if isinstance(p, dict) and int_or_none(p.get('idx')) == port_idx),
            None,
        )
    stats = ctx.fetch(
        client,
        f'{fetched.base_path_used}/v1/sites/{fetched.site_id}/devices/{found.device_id}'
        '/statistics/latest',
        section='integration.statistics',
    )
    if stats.ok and isinstance(stats.data, dict):
        snapshot.statistics_latest = ctx.clean(stats.data, 'integration.statistics_latest')
    return snapshot


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


def _package_version() -> str:
    try:
        return metadata.version('unifi-management-cli')
    except metadata.PackageNotFoundError:
        return 'unknown'


def _section(name: str, ctx: Collection, client: Any, collect: Callable[[], Any]) -> Any:
    """Run one collector, recording any failure instead of losing the bundle.

    A ReadOnlyViolation is never swallowed: it means a collector tried to write.
    The guard is re-checked after every section, as a backstop for anything that
    assigned ``client.session`` directly (a re-login keeps the guard).
    """
    try:
        result = collect()
    except ReadOnlyViolation:
        raise
    except Exception as e:  # noqa: BLE001 - one failed section must not lose the rest
        ctx.error(name, f'{type(e).__name__}: {e}')
        result = None
    assert_guarded(client)
    return result


def _candidate_summary(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{'name': d.get('name'), 'mac': d.get('mac'), 'model': d.get('model')} for d in devices]


def _derived_client_macs(
    port_entry: dict[str, Any], inspection: Optional[dict[str, Any]]
) -> list[str]:
    """MACs seen on the port, for when no --client was given."""
    found: list[Optional[str]] = []
    last = port_entry.get('last_connection')
    if isinstance(last, dict):
        found.append(normalise_mac(last.get('mac')))
    if inspection:
        found.append(normalise_mac((inspection.get('connected_device') or {}).get('mac')))
    unique: list[str] = []
    for mac in found:
        if mac and mac not in unique:
            unique.append(mac)
    return unique


def build_port_diagnostic_bundle(
    client: Any,
    site: str,
    query: BundleQuery,
    *,
    command: str = 'unifi-mapper ports diagnose',
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
    link_error_baseline_path: str = DEFAULT_LINK_ERROR_BASELINE,
    port_counter_store_path: Optional[Path] = None,
) -> PortDiagnosticBundle:
    """Collect every read-only fact about one switch port into one bundle.

    The read-only guard is installed before the first request. Only "switch
    not found" and "port not found" are fatal; every other section failure is
    recorded in ``errors`` and collection continues.

    Raises:
        SwitchNotFound: The switch query matched nothing or several switches.
        PortNotFound: The port does not exist on the switch.
        ValueError: ``compare_profiles`` is not empty or exactly two names, or a
            sampling or event-window parameter is out of range.
        ReadOnlyViolation: A collector attempted a write (a bug).
    """
    if len(query.compare_profiles) not in (0, 2):
        raise ValueError('compare_profiles needs exactly two profile names, or none')
    validate_sampling(query.counter_samples, query.interval_seconds)
    validate_event_window(query.since_days, query.max_events)
    audit = install_read_only_guard(client, site)
    ctx = Collection()

    switch, matched_by, candidates = resolve_device(client, site, query.switch)
    device = ctx.clean(load_device(client, site, switch), 'device.raw')
    port_entry = find_port_entry(device, query.port)
    devices = _device_rows(client, site)
    known_names = [str(d.get('name')) for d in devices if d.get('name')]

    controller = _section(
        'controller', ctx, client, lambda: collect_controller_info(client, site, ctx)
    )
    identity = _section(
        'device', ctx, client, lambda: collect_device_identity(client, site, device, ctx, now=now)
    )
    port = _section('port', ctx, client, lambda: collect_port_detail(device, query.port))
    profiles = _section('profiles', ctx, client, lambda: load_profiles(client, site, ctx)) or {}

    profile_diff: Optional[ProfileDiff] = None
    compare_ids: Optional[tuple[Optional[str], Optional[str]]] = None
    if query.compare_profiles:
        a_name, b_name = query.compare_profiles
        profile_diff = _section(
            'profiles.diff',
            ctx,
            client,
            lambda: diff_port_profiles(
                client, site, a_name, b_name, ctx=ctx, profiles=profiles, devices=devices
            ),
        )
        if profile_diff is not None:
            compare_ids = (profile_diff.a.id, profile_diff.b.id)

    override = _section(
        'override',
        ctx,
        client,
        lambda: collect_override(device, query.port, profiles, compare_ids),
    )
    inspection = _section(
        'inspection',
        ctx,
        client,
        lambda: ctx.clean(inspect_port(client, site, switch, query.port).to_dict(), 'inspection'),
    )

    client_queries = list(query.clients)
    derived = not client_queries
    if derived:
        client_queries = _derived_client_macs(port_entry, inspection)
    histories: list[ClientHistory] = []
    for index, identifier in enumerate(client_queries):
        history = _section(
            f'clients[{index}]',
            ctx,
            client,
            lambda identifier=identifier: get_client_history(
                client,
                site,
                identifier,
                switch=switch,
                port_idx=query.port,
                ctx=ctx,
                devices=devices,
            ),
        )
        if history is not None:
            histories.append(history)
    client_macs = sorted({mac for h in histories for mac in h.resolved_macs})

    events = _section(
        'events',
        ctx,
        client,
        lambda: collect_events(
            client,
            site,
            device,
            port_idx=query.port,
            client_macs=client_macs,
            since_days=query.since_days,
            max_events=query.max_events,
            known_device_names=known_names,
            now=now,
            ctx=ctx,
        ),
    )
    counters = _section(
        'counters',
        ctx,
        client,
        lambda: sample_port_counters(
            client,
            site,
            switch,
            query.port,
            samples=query.counter_samples,
            interval_seconds=query.interval_seconds,
            sleep=sleep,
            now=now,
            link_error_baseline_path=link_error_baseline_path,
            port_counter_store_path=port_counter_store_path,
            ctx=ctx,
        ),
    )

    def _all_ports() -> list[PortSummary]:
        mac_to_dev, mac_to_user = _build_mac_index(client, site)
        sta = _load_rows(client, api_path(client, site, 'stat/sta'), ctx, 'switch_ports.stat_sta')
        return summarise_ports(device, profiles, mac_to_dev, mac_to_user, sta)

    switch_ports = _section('switch_ports', ctx, client, _all_ports)
    integration = _section(
        'integration',
        ctx,
        client,
        lambda: collect_integration_snapshot(
            client, site, normalise_mac(device.get('mac')), query.port, ctx
        ),
    )
    if integration is not None:
        if port is not None:
            port.integration_port = integration.port
        if identity is not None and integration.statistics_latest:
            stats = integration.statistics_latest
            identity.integration_statistics = {
                key: stats.get(key)
                for key in (
                    'cpuUtilizationPct',
                    'memoryUtilizationPct',
                    'uptimeSec',
                    'lastHeartbeatAt',
                )
            }

    return PortDiagnosticBundle(
        generated_at=local_iso(now),
        tool={
            'command': command,
            'package_version': _package_version(),
            'audit_scope': AUDIT_SCOPE,
        },
        controller=controller,
        query=query,
        switch_resolution=SwitchResolution(
            query=query.switch, matched_by=matched_by, candidates=_candidate_summary(candidates)
        ),
        device=identity,
        port=port,
        override=override,
        inspection=inspection,
        profiles=profile_diff,
        clients=histories,
        clients_derived_from_port=derived and bool(client_queries),
        events=events,
        counters=counters,
        switch_ports=switch_ports,
        integration=integration,
        errors=ctx.errors,
        sanitised_paths=ctx.sanitised_paths,
        request_audit=list(audit),
    )
