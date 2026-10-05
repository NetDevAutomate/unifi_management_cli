"""AP health sampling for a vendor ticket: ``unifi-mapper diagnose ap-health``.

An AP's 2.4 GHz radio, VAP retry and load counters (and a known-good reference AP's, when
given) are read every ``interval`` seconds, ``samples`` times, and reported per sample and as
mean interval retry rates, in markdown and JSON. CLI only: a run lasts at most 60 x 600 s (10 h),
far beyond one MCP call; an MCP form waits for decision D4 (issue 060), and the MCP read side
is ``get_device_stats`` with ``get_ap_retry_rates``. The controller reads borrow the read-only
holder the CLI installs. Client pings (class B) run only with ``ping_clients=True``, in one
gateway SSH session through ``analysis/gateway_ssh.py``.

Each sample's read is bounded (:data:`SAMPLE_READ_TIMEOUT`); a sample whose read times out or
fails with any error is recorded as missing with its reason, and a ping that fails records
its redacted error: neither is fatal. The capture fills the :class:`ApHealthCapture` it is
given as it goes, so after Ctrl-C, or a failure that still ends the run, the CLI builds a
partial report from what was gathered.

Rebuilt from the July work (a local archive, not in the repo) without July's PoE power-cycle
phase (a controller write, W9 in issue 060), its job registry (issue 012), its hard-coded SSID
and its output-path default. Without ``essid`` the busiest 2.4 GHz VAP of the first sample is
tracked. A retry rate is computed only over a real interval (between two samples that both
read), never from the first sample's counters since boot.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unifi_mapper.analysis.gateway_ssh import (
    check_exit_status,
    gateway_session,
    require_bounded_int,
    require_ip,
    run_gateway_command,
    ssh_login,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.coerce import float_or_none, int_or_none
from unifi_mapper.core.utils.counters import (
    VapCounters,
    pick_vap,
    retry_delta,
    vap_counters_from_dict,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.ping_parse import parse_ping_output
from unifi_mapper.core.utils.redact import redact_text, strip_secrets
from unifi_mapper.diagnostic_reads import normalise_mac
from unifi_mapper.diagnostics.observability import CU_TOTAL_CAVEAT, MAX_QUERY_LENGTH


SAMPLES_RANGE = (1, 60)
INTERVAL_RANGE = (30, 600)
SAMPLE_READ_TIMEOUT = 45  # seconds for one sample's controller read
PING_COUNT = 10
PING_INTERVAL = 0.3
MAX_PINGED_CLIENTS = 4
MIN_INTERVAL_PACKETS = 50  # an interval with fewer TX packets gives no honest retry rate
RADIO = 'ng'  # 2.4 GHz
RADIO_CONFIG_KEYS = ('channel', 'ht', 'tx_power_mode', 'tx_power', 'min_rssi_enabled', 'min_rssi')
ROLES = ('target', 'reference')
# The tracked SSID's settings the report shows (July's list); never a secret field.
SSID_CONFIG_KEYS = (
    'wlan_bands',
    'security',
    'wpa_mode',
    'pmf_mode',
    'wpa3_support',
    'minrate_ng_enabled',
    'minrate_ng_data_rate_kbps',
    'mcastenhance_enabled',
    'bc_filter_enabled',
    'uapsd_enabled',
    'dtim_ng',
    'l2_isolation',
    'proxy_arp',
    'mdns_proxy_mode',
    'enhanced_iot',
    'iot_channel_lock',
    'hide_ssid',
    'mac_filter_enabled',
)
RETRY_NOTE = (
    'Retry % = delta tx_retries / delta tx_packets on the 2.4 GHz tracked VAP between two '
    'samples (cumulative counters, reset-aware); an interval with fewer than '
    f'{MIN_INTERVAL_PACKETS} packets has none. Pings run from the gateway to 2.4 GHz '
    'clients on each AP at sample time.'
)

# The wait between samples: cancellable, so Ctrl-C stops it. Tests replace it.
_pause = asyncio.sleep


@dataclass
class ApSample:
    """One AP's counters at one sample time; ``missing`` when the read gave none."""

    role: str
    ts: float
    missing: bool = False
    reason: str | None = None
    uptime: int | None = None
    cpu: float | None = None
    mem: float | None = None
    loadavg_1: float | None = None
    cu_total: int | None = None
    cu_self_tx: int | None = None
    cu_self_rx: int | None = None
    channel: int | None = None
    tx_power: int | None = None
    num_sta: int | None = None
    vaps: list[VapCounters] = field(default_factory=list)
    pings: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class ApHealthCapture:
    """What a capture has gathered so far; a partial report is built from it after Ctrl-C."""

    samples: list[ApSample] = field(default_factory=list)
    target: dict[str, Any] | None = None
    reference: dict[str, Any] | None = None
    essid: str | None = None
    essid_source: str | None = None
    wlan_configs: list[dict[str, Any]] = field(default_factory=list)
    samples_requested: int = 0
    interval_seconds: int = 0
    ping_clients: bool = False


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    """The dict items of a list from a record (none when it is not a list)."""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    """A record's sub-object, or ``{}`` when it is not one."""
    return value if isinstance(value, dict) else {}


def _radio_ng_row(rows: Any) -> dict[str, Any]:
    """The 2.4 GHz row of a ``radio_table`` or ``radio_table_stats`` (``{}`` without one)."""
    return next((r for r in _dict_rows(rows) if r.get('radio') == RADIO), {})


def sample_device(dev: dict[str, Any], role: str, ts: float) -> ApSample:
    """An AP's 2.4 GHz counters from one controller device record. Pure.

    Args:
        dev: One ``stat/device`` record (already through ``strip_secrets``).
        role: ``target`` or ``reference``.
        ts: The sample's Unix time.
    """
    system_stats, sys_stats = _as_dict(dev.get('system-stats')), _as_dict(dev.get('sys_stats'))
    radio = _radio_ng_row(dev.get('radio_table_stats'))
    return ApSample(
        role=role,
        ts=ts,
        uptime=int_or_none(dev.get('uptime')),
        cpu=float_or_none(system_stats.get('cpu')),
        mem=float_or_none(system_stats.get('mem')),
        loadavg_1=float_or_none(sys_stats.get('loadavg_1')),
        cu_total=int_or_none(radio.get('cu_total')),
        cu_self_tx=int_or_none(radio.get('cu_self_tx')),
        cu_self_rx=int_or_none(radio.get('cu_self_rx')),
        channel=int_or_none(radio.get('channel')),
        tx_power=int_or_none(radio.get('tx_power')),
        num_sta=int_or_none(radio.get('num_sta')),
        vaps=[
            vap_counters_from_dict(v)
            for v in _dict_rows(dev.get('vap_table'))
            if v.get('radio') == RADIO
        ],
    )


def device_block(dev: dict[str, Any]) -> dict[str, Any]:
    """The identity and settings a ticket needs from one device record. Pure."""
    uplink = _as_dict(dev.get('uplink'))
    radio = _radio_ng_row(dev.get('radio_table'))
    return {
        'name': dev.get('name'),
        'model': dev.get('model'),
        'serial': dev.get('serial'),
        'mac': dev.get('mac'),
        'firmware': dev.get('version'),
        'state': dev.get('state'),
        'uptime_seconds': int_or_none(dev.get('uptime')),
        'ip': dev.get('ip'),
        'uplink': {key: uplink.get(key) for key in ('type', 'speed', 'full_duplex')},
        'radio_ng': {key: radio.get(key) for key in RADIO_CONFIG_KEYS},
    }


def clients_on_ap(clients: list[Any], ap_mac: str) -> list[str]:
    """The addresses of up to :data:`MAX_PINGED_CLIENTS` wireless clients an AP pings. Pure.

    Only clients on the radio the report measures are pinged, as in July: ``radio`` ``ng``
    (2.4 GHz), or not reported, since an unknown radio may be 2.4 GHz; a 5 or 6 GHz client
    is left out, and so is a wired one or one without an address.

    Args:
        clients: The controller's client records (``stat/sta``).
        ap_mac: The AP's MAC, in any notation.

    Returns:
        The clients' addresses, in the controller's order, at most
        :data:`MAX_PINGED_CLIENTS` of them.
    """
    wanted = normalise_mac(ap_mac)
    found = [
        str(c['ip'])
        for c in _dict_rows(clients)
        if c.get('ip')
        and not c.get('is_wired')
        and c.get('radio') in (RADIO, None)
        and wanted is not None
        and normalise_mac(c.get('ap_mac')) == wanted
    ]
    return found[:MAX_PINGED_CLIENTS]


def interval_rows(samples: list[ApSample], essid: str | None) -> list[dict[str, Any]]:
    """One row per sample, with the retry delta since that AP's previous sample read. Pure.

    A missing sample has no counters; the next sample's delta runs from the last one that
    read. The first sample read of each AP has no interval, so no delta.
    """
    rows: list[dict[str, Any]] = []
    last: dict[str, ApSample] = {}
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.role] = counts.get(s.role, 0) + 1
        dp = dr = pct = None
        prev = last.get(s.role)
        if not s.missing and prev is not None and essid:
            dp, dr, pct = retry_delta(prev.vaps, s.vaps, essid)
            if dp < MIN_INTERVAL_PACKETS:
                pct = None
        if not s.missing:
            last[s.role] = s
        rows.append(
            {
                'role': s.role,
                'index': counts[s.role],
                'utc': datetime.fromtimestamp(s.ts, tz=UTC).isoformat(timespec='seconds'),
                'missing': s.missing,
                'reason': s.reason,
                'uptime': s.uptime,
                'cpu': s.cpu,
                'loadavg_1': s.loadavg_1,
                'channel': s.channel,
                'cu_total': s.cu_total,
                'cu_self_tx': s.cu_self_tx,
                'num_sta': s.num_sta,
                'delta_tx_packets': dp,
                'delta_tx_retries': dr,
                'retry_pct': pct,
                'pings': s.pings,
            }
        )
    return rows


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def summarize_samples(samples: list[ApSample], essid: str | None) -> list[dict[str, Any]]:
    """Per AP: samples read and missing, mean interval retry % and mean ping loss. Pure."""
    rows = interval_rows(samples, essid)
    summary = []
    for role in ROLES:
        mine = [r for r in rows if r['role'] == role]
        if not mine:
            continue
        rates = [r['retry_pct'] for r in mine if r['retry_pct'] is not None]
        losses = [
            float(p['loss_pct'])
            for r in mine
            for p in r['pings'].values()
            if isinstance(p.get('loss_pct'), int | float)
        ]
        summary.append(
            {
                'role': role,
                'samples': sum(1 for r in mine if not r['missing']),
                'missing': sum(1 for r in mine if r['missing']),
                'mean_retry_pct': _mean(rates),
                'retry_intervals': len(rates),
                'mean_ping_loss_pct': _mean(losses),
            }
        )
    return summary


def build_report(capture: ApHealthCapture, *, partial: bool) -> dict[str, Any]:
    """The JSON report of a capture, finished or interrupted (``partial``). Pure."""
    wlan = next((w for w in capture.wlan_configs if w.get('name') == capture.essid), None)
    by_role: dict[str, list[ApSample]] = {
        role: [s for s in capture.samples if s.role == role] for role in ROLES
    }
    return {
        'target': capture.target,
        'reference': capture.reference,
        'essid': capture.essid,
        'essid_source': capture.essid_source,
        'samples_requested': capture.samples_requested,
        'interval_seconds': capture.interval_seconds,
        'ping_clients': capture.ping_clients,
        'partial': partial,
        'samples_taken': {
            role: sum(1 for s in found if not s.missing)
            for role, found in by_role.items()
            if found
        },
        'samples_missing': {
            role: sum(1 for s in found if s.missing) for role, found in by_role.items() if found
        },
        'rows': interval_rows(capture.samples, capture.essid),
        'summary': summarize_samples(capture.samples, capture.essid),
        'ssid_config': {key: wlan.get(key) for key in SSID_CONFIG_KEYS} if wlan else None,
        'notes': [RETRY_NOTE, CU_TOTAL_CAVEAT],
    }


# The sample table's columns before the retry % and the pings, in order.
_SAMPLE_COLUMNS = (
    'index',
    'utc',
    'uptime',
    'cpu',
    'loadavg_1',
    'channel',
    'cu_total',
    'cu_self_tx',
    'num_sta',
    'delta_tx_packets',
    'delta_tx_retries',
)


def _cell(value: Any) -> str:
    return '-' if value is None or value == '' else str(value).replace('|', '/')


def _block_lines(block: dict[str, Any]) -> list[str]:
    uplink, radio = block['uplink'], block['radio_ng']
    return [
        f'- **Model**: {_cell(block["model"])} | **Serial**: {_cell(block["serial"])} | '
        f'**MAC**: {_cell(block["mac"])}',
        f'- **Firmware**: {_cell(block["firmware"])} | **State**: {_cell(block["state"])} | '
        f'**Uptime**: {_cell(block["uptime_seconds"])}s',
        f'- **IP**: {_cell(block["ip"])} | **Uplink**: {_cell(uplink["type"])} '
        f'{_cell(uplink["speed"])} Mbps, full duplex {_cell(uplink["full_duplex"])}',
        '- **2.4 GHz**: ' + ', '.join(f'{key} {_cell(value)}' for key, value in radio.items()),
        '',
    ]


def _pings_cell(pings: dict[str, dict[str, Any]]) -> str:
    parts = []
    for ip, ping in pings.items():
        if 'error' in ping:
            detail = f' ({_cell(ping["detail"])})' if ping.get('detail') else ''
            parts.append(f'{ip}: {ping["error"]}{detail}')
        else:
            parts.append(f'{ip}: {_cell(ping.get("loss_pct"))}% loss')
    return '; '.join(parts) or '-'


def render_markdown(report: dict[str, Any]) -> str:
    """The report as markdown, for a vendor ticket. Pure."""
    target = report['target'] or {}
    name = target.get('name') or 'unknown AP'
    lines = [f'# AP Health Report — {name}', '']
    if report['partial']:
        lines += ['**Partial**: the capture stopped early; these are the samples it took.', '']
    lines += [
        f'Method: {report["samples_requested"]} samples, {report["interval_seconds"]} s apart'
        f'{", with gateway pings to clients" if report["ping_clients"] else ""}; '
        f'tracking the 2.4 GHz VAP of {_cell(report["essid"])} '
        f'({_cell(report["essid_source"])}).',
        '',
    ]
    if report['target']:
        lines += ['## Suspect device', *_block_lines(report['target'])]
    if report['reference']:
        lines += ['## Reference device (known-good control)', *_block_lines(report['reference'])]
    if report['ssid_config'] is not None:
        lines += [f'## SSID configuration ({_cell(report["essid"])})', '']
        lines += [f'- {key}: {_cell(value)}' for key, value in report['ssid_config'].items()]
        lines.append('')
    header = (
        '| # | UTC | Uptime (s) | CPU % | load1 | Channel | CU total % | CU self-tx % '
        '| Clients | Δtx packets | Δretries | **Retry %** | Gateway pings |'
    )
    for role, title in (('target', 'suspect'), ('reference', 'reference')):
        rows = [r for r in report['rows'] if r['role'] == role]
        if not rows:
            continue
        lines += [f'## Samples ({title})', '', header, '|' + '---|' * 13]
        for r in rows:
            if r['missing']:
                lines.append(f'| {r["index"]} | {r["utc"]} | missing: {_cell(r["reason"])} |')
                continue
            pct = f'{r["retry_pct"]}%' if r['retry_pct'] is not None else '-'
            cells = [r[key] for key in _SAMPLE_COLUMNS]
            lines.append(
                '| '
                + ' | '.join(_cell(c) for c in cells)
                + f' | **{pct}** | {_pings_cell(r["pings"])} |'
            )
        lines.append('')
    lines += ['## Summary', '']
    for row in report['summary']:
        retry = f'{row["mean_retry_pct"]}%' if row['mean_retry_pct'] is not None else 'n/a'
        loss = f'{row["mean_ping_loss_pct"]}%' if row['mean_ping_loss_pct'] is not None else 'n/a'
        lines.append(
            f'- **{row["role"]}**: mean 2.4 GHz retry rate {retry} '
            f'(n={row["retry_intervals"]} intervals), mean ping loss {loss}, '
            f'{row["samples"]} sample(s) read, {row["missing"]} missing'
        )
    lines += ['', *(f'*{note}*' for note in report['notes'])]
    return '\n'.join(lines)


def expected_duration_seconds(samples: int, interval: int) -> int:
    """About how long a capture runs: one interval per sample (up to 10 h at the bounds)."""
    return samples * interval


def _not_found(message: str) -> ToolError:
    return ToolError(
        message=message,
        error_code=ErrorCodes.DEVICE_NOT_FOUND,
        suggestion='Give the exact AP name, its MAC or its IP; find_device searches.',
        related_tools=['find_device'],
    )


def _match_ap(devices: list[Any], query: str) -> dict[str, Any]:
    from unifi_mapper.port_inspect import match_switch

    if not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ToolError(
            message=f'an AP must be named in 1-{MAX_QUERY_LENGTH} characters',
            error_code=ErrorCodes.CONFIG_INVALID,
        )
    try:
        found, _, _ = match_switch(devices, query, device_types=('uap',))
    except LookupError as e:
        raise _not_found(str(e)) from None
    return found


async def _discover() -> tuple[list[Any], list[Any]]:
    """The device list and the WLAN configs, bounded like a sample read."""
    async with asyncio.timeout(SAMPLE_READ_TIMEOUT), UniFiClient() as client:
        devices = await client.get_devices()
        wlans = await client.get(client.build_path('rest/wlanconf'))
    if isinstance(wlans, dict):
        wlans = wlans.get('data', [])
    return devices, _dict_rows(wlans)


async def _read_sample(ping_clients: bool) -> tuple[list[Any], list[Any]]:
    """One sample's device list (and client list, for pings)."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
        clients = await client.get_clients() if ping_clients else []
    return devices, clients


def _failure_text(error: object) -> str:
    """A failure's redacted text, or its class name when it has none."""
    return redact_text(error) or type(error).__name__


async def _ping_clients(conn: Any, ips: list[str]) -> dict[str, dict[str, Any]]:
    """Ping each address from the gateway: loss and round trips, or the error.

    A ping that fails (a ``ToolError``, or anything else, such as the connection reset of a
    dropped SSH session) records its error code and redacted text; the others still run.
    """
    results: dict[str, dict[str, Any]] = {}
    for ip in ips:
        try:
            address = require_ip(ip)
            argv = ['ping', '-c', str(PING_COUNT), '-i', f'{PING_INTERVAL:g}', '-W', '2', address]
            out = await run_gateway_command(conn, argv, timeout=PING_COUNT * PING_INTERVAL + 12)
            check_exit_status(out, 'ping', (0, 1))  # 1 is no reply; anything else: not run
        except ToolError as e:
            results[ip] = {'error': e.error_code, 'detail': _failure_text(e.message)}
            continue
        except Exception as e:  # noqa: BLE001 - a failed ping is its result, never fatal
            results[ip] = {'error': ErrorCodes.API_ERROR, 'detail': _failure_text(e)}
            continue
        stats = parse_ping_output(out.stdout)
        results[address] = {
            'loss_pct': stats.loss_pct,
            'avg_ms': stats.rtt_avg,
            'max_ms': stats.rtt_max,
        }
    return results


async def run_ap_health_capture(
    target: str,
    reference: str | None = None,
    essid: str | None = None,
    samples: int = 6,
    interval: int = 60,
    ping_clients: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
    *,
    sink: ApHealthCapture,
) -> dict[str, Any]:
    """Sample an AP (and a reference AP) ``samples`` times, ``interval`` seconds apart.

    Args:
        target: The suspect AP's name, MAC or IP.
        reference: A known-good AP to sample alongside it.
        essid: The SSID whose 2.4 GHz VAP to track (None: the busiest at the first sample).
        samples: Samples to take, 1-60.
        interval: Seconds between samples, 30-600.
        ping_clients: Also ping up to 4 wireless clients of each AP from the gateway, in one
            SSH session for the run (class B).
        progress: Called after each sample with ``{sample, of, missing}``.
        sink: Filled as the capture goes, so an interrupted run still has its samples.

    Returns:
        The report (:func:`build_report`), not partial.

    Raises:
        ToolError: ``CONFIG_INVALID`` for a bound or a reference equal to the target,
            ``DEVICE_NOT_FOUND`` for an AP that matches nothing or more than one, and the
            first read's controller errors.
    """
    samples = require_bounded_int('samples', samples, *SAMPLES_RANGE)
    interval = require_bounded_int('interval', interval, *INTERVAL_RANGE)
    if ping_clients:
        ssh_login()  # a missing SSH password fails before the controller is asked
    sink.samples_requested, sink.interval_seconds = samples, interval
    sink.ping_clients = ping_clients
    devices, wlans = await _discover()
    macs = {'target': normalise_mac(_match_ap(devices, target).get('mac'))}
    if reference is not None:
        macs['reference'] = normalise_mac(_match_ap(devices, reference).get('mac'))
        if macs['reference'] == macs['target']:
            raise ToolError(
                message='the reference must be another AP than the target',
                error_code=ErrorCodes.CONFIG_INVALID,
            )
    sink.wlan_configs = [strip_secrets(w)[0] for w in wlans]
    if essid is not None:
        sink.essid, sink.essid_source = essid, 'given'

    async with contextlib.AsyncExitStack() as stack:
        conn = await stack.enter_async_context(gateway_session()) if ping_clients else None
        for index in range(samples):
            if index:
                await _pause(interval)
            await _take_sample(sink, macs, conn, ping_clients)
            if progress is not None:
                missing = any(s.missing for s in sink.samples[-len(macs) :])
                progress({'sample': index + 1, 'of': samples, 'missing': missing})
    return build_report(sink, partial=False)


async def _take_sample(
    sink: ApHealthCapture, macs: dict[str, str | None], conn: Any, ping_clients: bool
) -> None:
    """Read once and append one sample per AP to ``sink`` (missing when the read gave none).

    A read that times out or fails with any error is a missing sample with its reason.
    """
    ts = time.time()
    reason: str | None = None
    devices: list[Any] = []
    clients: list[Any] = []
    try:
        async with asyncio.timeout(SAMPLE_READ_TIMEOUT):
            devices, clients = await _read_sample(ping_clients)
    except TimeoutError:
        reason = f'read timed out after {SAMPLE_READ_TIMEOUT:g} s'
    except ToolError as e:
        reason = e.error_code
    except Exception as e:  # noqa: BLE001 - a failed read is a missing sample, never fatal
        reason = f'read failed: {_failure_text(e)}'
    if reason is not None:
        sink.samples += [ApSample(role=role, ts=ts, missing=True, reason=reason) for role in macs]
        return
    by_mac = {normalise_mac(d.get('mac')): d for d in _dict_rows(devices)}
    for role, mac in macs.items():
        dev = by_mac.get(mac)
        if dev is None:
            sink.samples.append(ApSample(role=role, ts=ts, missing=True, reason='not reported'))
            continue
        clean = strip_secrets(dev, 'device')[0]
        sample = sample_device(clean, role, ts)
        if role == 'target' and sink.essid is None and sample.vaps:
            busiest = pick_vap(sample.vaps, '')
            sink.essid, sink.essid_source = (busiest.essid if busiest else None), 'busiest'
        if conn is not None and mac is not None:
            sample.pings = await _ping_clients(conn, clients_on_ap(clients, mac))
        setattr(sink, role, device_block(clean))
        sink.samples.append(sample)
