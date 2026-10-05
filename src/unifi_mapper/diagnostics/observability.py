"""Read-only device statistics, AP retry rates, config objects and config-change timelines.

Four MCP tools and their CLI commands (``diagnose device-stats``, ``diagnose ap-retries``,
``controller config``, ``controller config-changes``), rebuilt from the July work: pure
``*_from_data`` cores over plain controller records, and thin async handlers that read the
controller through ``UniFiClient()`` with no explicit credentials. Under the MCP server that
client borrows the lifespan's shared, read-only-guarded connection, and under the CLI the one
``typer_cli._guarded`` installs, so no handler here can send a write.

Secrets: every device record and config object goes through ``strip_secrets`` before
anything is read from it (``x_*`` keys, passwords, PSKs, the SNMP ``community``,
``syslog_key`` and the rest of ``core/utils/redact``'s rules). Config objects report the
removed key paths in ``sanitised_paths``; values never leave this module.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pydantic import Field
from typing import Annotated, Any, Literal
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.coerce import float_or_none, int_or_none
from unifi_mapper.core.utils.counters import retry_delta, vap_counters_from_dict
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.redact import strip_secrets


# A VAP whose interval retry rate is above this is flagged as unhealthy.
RETRY_PCT_UNHEALTHY = 10.0
INTERVAL_RANGE = (10, 240)  # seconds between the two device reads of get_ap_retry_rates
SINCE_HOURS_RANGE = (1, 8760)
MAX_QUERY_LENGTH = 128

CU_TOTAL_CAVEAT = (
    'cu_total is unreliable on some AP firmware (it conflates receiver noise with airtime); '
    'prefer the per-VAP retry percentage for fault detection.'
)
RETRY_NOTE = (
    'Retry % = delta tx_retries / delta tx_packets per VAP over the sample interval '
    '(cumulative counters, reset-aware). Healthy is below 5 to 10%.'
)
CREATION_TIME_NOTE = (
    "An object's time comes from its ObjectId, which records when it was CREATED, not when "
    'it was last edited: an edit to an older object does not appear here. Edits are in the '
    "admin-activity system log, which get_device_events reads for one device's history."
)
STRIPPED_KEYS_NOTE = 'Secret keys are removed, never returned; sanitised_paths lists them by path.'

# The wait between get_ap_retry_rates' two reads: cancellable, so the runner's deadline and a
# cancelled call stop it there. Tests replace it.
_pause = asyncio.sleep

ConfigKind = Literal['wlanconf', 'networkconf', 'setting', 'apgroup']
Radio = Literal['ng', 'na', '6e']

# Config object kinds: API version, endpoint and the field that names an object.
CONFIG_KINDS: dict[str, dict[str, str]] = {
    'wlanconf': {'api': 'v1', 'endpoint': 'rest/wlanconf', 'name_field': 'name'},
    'networkconf': {'api': 'v1', 'endpoint': 'rest/networkconf', 'name_field': 'name'},
    'setting': {'api': 'v1', 'endpoint': 'rest/setting', 'name_field': 'key'},
    'apgroup': {'api': 'v2', 'endpoint': 'apgroups', 'name_field': 'name'},
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# ─── Device statistics ────────────────────────────────────────────────────────


def device_stats_from_data(dev: dict[str, Any]) -> dict[str, Any]:
    """Return a structured statistics snapshot of one controller device record.

    Pure. The record should already have gone through ``strip_secrets``; only named fields
    are read, so nothing else reaches the result.

    Args:
        dev: One ``stat/device`` record.

    Returns:
        Identity, system stats (CPU and memory percent, 1-minute load), per-radio rows and
        per-VAP rows (2.4, 5 and 6 GHz alike), and notes.
    """
    system_stats = _dict(dev.get('system-stats'))
    sys_stats = _dict(dev.get('sys_stats'))
    radios = [
        {
            'radio': r.get('radio'),
            'channel': r.get('channel'),
            'cu_total': r.get('cu_total'),
            'cu_self_tx': r.get('cu_self_tx'),
            'cu_self_rx': r.get('cu_self_rx'),
            'tx_power': r.get('tx_power'),
            'num_sta': r.get('num_sta'),
        }
        for r in _dicts(dev.get('radio_table_stats'))
    ]
    vaps = []
    for v in _dicts(dev.get('vap_table')):
        tx_packets = int_or_none(v.get('tx_packets')) or 0
        tx_retries = int_or_none(v.get('tx_retries')) or 0
        vaps.append(
            {
                'essid': v.get('essid'),
                'radio': v.get('radio'),
                'channel': v.get('channel'),
                'num_sta': int_or_none(v.get('num_sta')) or 0,
                'tx_packets': tx_packets,
                'tx_retries': tx_retries,
                'tx_dropped': int_or_none(v.get('tx_dropped')) or 0,
                'rx_packets': int_or_none(v.get('rx_packets')) or 0,
                'retry_pct_cumulative': (
                    round(100 * tx_retries / tx_packets, 1) if tx_packets > 0 else None
                ),
            }
        )
    load = sys_stats.get('loadavg_1', system_stats.get('loadavg_1'))
    return {
        'name': dev.get('name'),
        'mac': dev.get('mac'),
        'model': dev.get('model'),
        'type': dev.get('type'),
        'ip': dev.get('ip'),
        'firmware': dev.get('version'),
        'state': dev.get('state'),
        'online': dev.get('state') == 1,
        'uptime_seconds': int_or_none(dev.get('uptime')),
        'startup_timestamp': int_or_none(dev.get('startup_timestamp')),
        'system': {
            'cpu_pct': float_or_none(system_stats.get('cpu')),
            'mem_pct': float_or_none(system_stats.get('mem')),
            'loadavg_1': float_or_none(load),
        },
        'radios': radios,
        'vaps': vaps,
        'notes': [CU_TOTAL_CAVEAT] if radios else [],
    }


def _match_device(devices: list[dict[str, Any]], device: str) -> dict[str, Any]:
    from unifi_mapper.port_inspect import match_switch

    try:
        found, _, _ = match_switch(devices, device, device_types=None)
    except LookupError as e:
        raise ToolError(
            message=str(e),
            error_code=ErrorCodes.DEVICE_NOT_FOUND,
            suggestion='Give the exact device name, its MAC or its IP; find_device searches.',
            related_tools=['find_device'],
        ) from None
    return found


async def get_device_stats(
    device: Annotated[
        str,
        Field(
            description='Device name, MAC or IP (any adopted device)',
            min_length=1,
            max_length=MAX_QUERY_LENGTH,
        ),
    ],
) -> dict[str, Any]:
    """Return one device's CPU, memory, load, uptime, radio and per-VAP counters. Read-only.

    When to use this tool:
    - Investigating a slow or unhealthy AP or switch (CPU, memory, load, uptime)
    - Reading one AP's per-radio channel utilisation and per-VAP TX retry counters
    - Spotting a recent reboot (uptime, startup_timestamp)

    find_device reports the same CPU, memory, load and uptime among its fields, and
    get_radio_channel_report every AP's channel plan; use this tool for one device's radio
    and VAP counters. For an interval measurement of retries, use get_ap_retry_rates (the
    cumulative percentage here can hide a recent recovery).

    Args:
        device: Device name, MAC or IP. An exact name or MAC wins over a partial match;
            an ambiguous query is an error that lists the candidates.

    Returns:
        Identity, system, radios, vaps and notes.

    Raises:
        ToolError: DEVICE_NOT_FOUND if nothing matches or the match is ambiguous.
    """
    async with UniFiClient() as client:
        devices = await client.get_devices()
    found = _match_device(devices, device)
    clean, _ = strip_secrets(found, 'device')
    return device_stats_from_data(clean)


# ─── AP retry rates ───────────────────────────────────────────────────────────


def _radio_vaps(dev: dict[str, Any], radio: str) -> list[Any]:
    return [
        vap_counters_from_dict(v) for v in _dicts(dev.get('vap_table')) if v.get('radio') == radio
    ]


def retry_rates_from_samples(
    prev_devices: list[dict[str, Any]],
    cur_devices: list[dict[str, Any]],
    essid: str | None = None,
    radio: str = 'ng',
    threshold_pct: float = RETRY_PCT_UNHEALTHY,
) -> dict[str, Any]:
    """Return per-AP, per-VAP interval retry rates from two device reads.

    Pure. Uses ``core/utils/counters.retry_delta``, so an AP that rebooted between the reads
    (a counter went down) or a VAP missing from the first read counts from zero, never as a
    negative delta.

    Args:
        prev_devices: ``stat/device`` records at the start of the interval.
        cur_devices: ``stat/device`` records at the end.
        essid: Only report this SSID's VAPs (None: every SSID).
        radio: ``ng`` (2.4 GHz), ``na`` (5 GHz) or ``6e`` (6 GHz).
        threshold_pct: Flag a VAP whose retry percentage is above this.

    Returns:
        Per-AP VAP rows, the flagged VAPs, ``healthy`` and notes.
    """
    prev_by_mac = {d.get('mac'): d for d in prev_devices if isinstance(d, dict)}
    aps: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []
    for dev in cur_devices:
        if not isinstance(dev, dict) or dev.get('type') != 'uap':
            continue
        prev_dev = prev_by_mac.get(dev.get('mac'))
        prev_vaps = _radio_vaps(prev_dev, radio) if prev_dev else None
        rows: list[dict[str, Any]] = []
        for vap in _radio_vaps(dev, radio):
            if essid and vap.essid != essid:
                continue
            dp, dr, pct = retry_delta(prev_vaps, [vap], vap.essid)
            row = {
                'essid': vap.essid,
                'channel': vap.channel,
                'num_sta': vap.num_sta,
                'delta_tx_packets': dp,
                'delta_tx_retries': dr,
                'retry_pct': pct,
                'unhealthy': pct is not None and pct > threshold_pct,
            }
            rows.append(row)
            if row['unhealthy']:
                flagged.append(
                    {
                        'ap': dev.get('name'),
                        'ap_mac': dev.get('mac'),
                        'essid': vap.essid,
                        'retry_pct': pct,
                    }
                )
        if rows:
            aps.append(
                {
                    'ap': dev.get('name'),
                    'ap_mac': dev.get('mac'),
                    'model': dev.get('model'),
                    'radio': radio,
                    'vaps': rows,
                }
            )
    return {
        'radio': radio,
        'essid_filter': essid,
        'threshold_pct': threshold_pct,
        'aps': aps,
        'flagged': flagged,
        'healthy': not flagged,
        'notes': [RETRY_NOTE, CU_TOTAL_CAVEAT],
    }


async def get_ap_retry_rates(
    essid: Annotated[
        str | None,
        Field(description='Only this SSID (default every SSID)', max_length=MAX_QUERY_LENGTH),
    ] = None,
    radio: Annotated[
        Radio, Field(description='ng (2.4 GHz, default), na (5 GHz) or 6e (6 GHz)')
    ] = 'ng',
    interval_seconds: Annotated[
        int, Field(description='Seconds between the two device reads, 10-240', ge=10, le=240)
    ] = 30,
    threshold_pct: Annotated[
        float, Field(description='Flag a VAP above this retry percentage, 0-100', ge=0, le=100)
    ] = RETRY_PCT_UNHEALTHY,
) -> dict[str, Any]:
    """Measure every AP's per-VAP TX retry rate over a sampling interval. Read-only.

    BLOCKS for interval_seconds (default 30 s, at most 240 s) plus two device reads. An MCP
    client that stops waiting sooner than that ends the call; keep the interval short there.

    Takes two device reads interval_seconds apart and computes the reset-aware retry
    percentage per VAP, the honest Wi-Fi health metric (cu_total is unreliable on some
    firmware). Healthy VAPs run below 5 to 10%; a VAP above threshold_pct is flagged.

    When to use this tool:
    - Fleet-wide Wi-Fi health check: which APs have retry problems?
    - Confirming an AP fault, or an improvement after a channel or power change

    What to do next:
    - A flagged AP: get_device_stats for its full picture
    - All healthy: the air is fine; look at addressing, DNS or routing instead

    Args:
        essid: Only measure this SSID's VAPs.
        radio: Radio band.
        interval_seconds: Seconds between the two reads.
        threshold_pct: Retry percentage above which a VAP is flagged.

    Returns:
        Per-AP VAP retry rows, the flagged VAPs, healthy, interval_seconds and notes.
    """
    async with UniFiClient() as client:
        prev_devices = await client.get_devices()
    await _pause(interval_seconds)  # cancellation and the runner deadline stop it here
    async with UniFiClient() as client:
        cur_devices = await client.get_devices()
    prev_clean, _ = strip_secrets(prev_devices, 'devices')
    cur_clean, _ = strip_secrets(cur_devices, 'devices')
    result = retry_rates_from_samples(prev_clean, cur_clean, essid, radio, threshold_pct)
    result['interval_seconds'] = interval_seconds
    return result


# ─── Config objects ───────────────────────────────────────────────────────────


def objectid_created(oid: object) -> datetime | None:
    """Return the creation time a MongoDB ObjectId records, or None if it isn't one.

    The first 4 bytes of an ObjectId are its creation time in Unix seconds.

    Args:
        oid: An ``_id`` value.

    Returns:
        The UTC creation time, or None for anything that is not 24 hex characters.
    """
    if not isinstance(oid, str) or len(oid) != 24:
        return None
    try:
        int(oid, 16)
        return datetime.fromtimestamp(int(oid[:8], 16), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _name_of(obj: dict[str, Any], kind: str) -> Any:
    return obj.get(CONFIG_KINDS[kind]['name_field']) or obj.get('name')


def config_objects_from_data(
    kind: str, objects: list[Any], name: str | None = None
) -> dict[str, Any]:
    """Return one kind's config objects with secrets removed and creation times added.

    Pure. ``name`` keeps objects whose name field (``key`` for settings) or ``name``
    contains it, case-insensitively. Every kept object goes through
    ``strip_secrets(obj, f'{kind}[{i}]')``, where ``i`` is its index in the returned list,
    and gains ``created_utc`` (from its ``_id``, or None).

    Args:
        kind: One of ``CONFIG_KINDS``.
        objects: The controller's objects of that kind.
        name: Optional name filter.

    Returns:
        ``kind``, ``count``, ``objects``, ``sanitised_paths`` and notes.
    """
    rows = _dicts(objects)
    if name:
        needle = name.lower()
        rows = [
            o
            for o in rows
            if needle in str(_name_of(o, kind) or '').lower()
            or needle in str(o.get('name') or '').lower()
        ]
    clean_objects: list[dict[str, Any]] = []
    sanitised: list[str] = []
    for i, obj in enumerate(rows):
        clean, removed = strip_secrets(obj, f'{kind}[{i}]')
        created = objectid_created(obj.get('_id'))
        clean['created_utc'] = created.isoformat() if created else None
        clean_objects.append(clean)
        sanitised.extend(removed)
    notes = [STRIPPED_KEYS_NOTE]
    if kind == 'networkconf':
        notes.append(
            'These are the legacy rest/networkconf objects; get_networks reads the Network '
            'Integration API instead.'
        )
    return {
        'kind': kind,
        'count': len(clean_objects),
        'objects': clean_objects,
        'sanitised_paths': sanitised,
        'notes': notes,
    }


async def _fetch_config_objects(client: UniFiClient, kind: str) -> list[Any]:
    spec = CONFIG_KINDS[kind]
    if spec['api'] == 'v2':
        path = client.build_v2_path(spec['endpoint'])
    else:
        path = client.build_path(spec['endpoint'])
    data = await client.get(path)
    if isinstance(data, dict):
        data = data.get('data', [])
    return data if isinstance(data, list) else []


async def get_config_object(
    kind: Annotated[ConfigKind, Field(description='wlanconf, networkconf, setting or apgroup')],
    name: Annotated[
        str | None,
        Field(
            description='Only objects whose name (key for settings) contains this',
            max_length=MAX_QUERY_LENGTH,
        ),
    ] = None,
) -> dict[str, Any]:
    """Read the controller's config objects of one kind, with every secret removed. Read-only.

    Returns the raw legacy objects (rest/wlanconf, rest/networkconf, rest/setting, the v2
    apgroups) as the controller stores them, minus secret keys: x_* keys, passwords,
    passphrases, PSKs and pre-shared keys, the SNMP community, syslog keys. sanitised_paths
    lists what was removed by path, never a value. Each object gains created_utc, the
    creation time its _id records.

    get_networks reads networks through the Network Integration API; for the full legacy
    network object, use this tool with kind networkconf.

    When to use this tool:
    - Inspecting WLAN settings (wlanconf): band steering, DTIM, minimum rates, IoT options
    - Reading AP group membership (apgroup)
    - Reviewing controller settings (setting) or network objects (networkconf)

    Args:
        kind: The config object kind.
        name: Optional name filter (case-insensitive, partial).

    Returns:
        kind, count, objects, sanitised_paths and notes.
    """
    async with UniFiClient() as client:
        objects = await _fetch_config_objects(client, kind)
    return config_objects_from_data(kind, objects, name)


def merge_config_change_timeline(
    rows_by_kind: dict[str, list[dict[str, Any]]],
    since_hours: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Merge per-kind config objects into one timeline of objects created in the window.

    Pure. Objects without a decodable ``_id`` are skipped.

    Args:
        rows_by_kind: Config kind to its objects (secrets already removed).
        since_hours: Only objects created within this many hours of ``now``.
        now: Reference time (default the current UTC time), for deterministic tests.

    Returns:
        ``window`` (``since_hours``, ``cutoff_utc``), ``count``, ``changes`` (kind, id, name,
        created_utc, age_hours; newest first; age clamped at 0 against clock skew),
        ``by_kind`` (kinds with no change omitted) and notes.
    """
    now = now or datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=since_hours)
    changes: list[dict[str, Any]] = []
    for kind, objects in rows_by_kind.items():
        for obj in _dicts(objects):
            created = objectid_created(obj.get('_id'))
            if created is None or created < cutoff:
                continue
            changes.append(
                {
                    'kind': kind,
                    'id': obj.get('_id'),
                    'name': _name_of(obj, kind),
                    'created_utc': created.isoformat(),
                    'age_hours': round(max(0.0, (now - created).total_seconds() / 3600), 2),
                }
            )
    changes.sort(key=lambda c: c['created_utc'], reverse=True)
    by_kind: dict[str, int] = {}
    for change in changes:
        by_kind[change['kind']] = by_kind.get(change['kind'], 0) + 1
    return {
        'window': {'since_hours': since_hours, 'cutoff_utc': cutoff.isoformat()},
        'count': len(changes),
        'changes': changes,
        'by_kind': by_kind,
        'notes': [CREATION_TIME_NOTE],
    }


async def find_recent_config_changes(
    since_hours: Annotated[
        int, Field(description='Hours back from now, 1-8760 (default 24)', ge=1, le=8760)
    ] = 24,
    kinds: Annotated[
        list[ConfigKind] | None,
        Field(description='Config kinds to search (default all four; [] searches none)'),
    ] = None,
) -> dict[str, Any]:
    """Timeline of config objects created in the last since_hours, newest first. Read-only.

    Reads wlanconf, networkconf, setting and apgroup objects (or the kinds given), decodes
    the creation time each _id records, and merges the objects created in the window.

    An ObjectId records when an object was CREATED, not when it was last edited, so an edit to
    an older WLAN, network or setting does not appear here; edits are in the admin-activity
    system log (get_device_events reads it for one device). An empty kinds list searches
    nothing and sends no request.

    Args:
        since_hours: How many hours back to search.
        kinds: Config kinds to search; None searches all four.

    Returns:
        window, count, changes, by_kind and notes.
    """
    requested = list(CONFIG_KINDS) if kinds is None else list(dict.fromkeys(kinds))
    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    if requested:
        async with UniFiClient() as client:
            for kind in requested:
                objects = await _fetch_config_objects(client, kind)
                rows_by_kind[kind], _ = strip_secrets(_dicts(objects), kind)
    return merge_config_change_timeline(rows_by_kind, since_hours)
