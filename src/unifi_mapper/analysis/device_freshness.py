"""Device telemetry freshness checks -- is the controller serving live data or a snapshot?

`stat/device` will happily return a complete, plausible port table for a switch that stopped
informing hours ago. Every field in it describes the moment it last reported. Acting on that
data is the single most expensive trap in UniFi diagnosis.

Motivating incident (2026-07-29): `Mike2 USW Lite 16 PoE` had `last_seen` frozen at
07:17:47Z and was still returning `p13: forwarding`. Peers advanced normally in the same
samples. Several hours went into interpreting a three-hour-old snapshot as current state.

Two modes:

* :func:`summarise_freshness_from_data` -- cheap, single sample. Uses `state` and the age of
  `last_seen` to classify which devices' data can be trusted at all.
* :func:`check_device_freshness_from_samples` -- authoritative, two samples. Verifies that
  `last_seen`, `uptime` and cumulative counters actually advance, **using healthy peers as
  the control**. If no peer advanced either, the sample gap was shorter than the inform
  interval (~75-90s on typical fleets) and the result is inconclusive rather than alarming --
  a distinction the original hand-rolled checks got wrong.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


# Devices inform roughly every 75-90s; sample well beyond that or deltas read as false zeros.
DEFAULT_SAMPLE_GAP_SECONDS = 200
DEFAULT_STALE_AFTER_SECONDS = 1800


class DeviceFreshness(BaseModel):
    """Single-sample freshness verdict for one device."""

    device: str
    mac: str = ''
    state: int | None = None
    data_age_seconds: float | None = None
    trustworthy: bool = True
    reason: str = ''


class FreshnessSummary(BaseModel):
    """Single-sample freshness summary."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices: list[DeviceFreshness] = Field(default_factory=lambda: [])
    not_informing: list[str] = Field(default_factory=lambda: [])
    stale_data: list[str] = Field(default_factory=lambda: [])
    validation_passed: bool = True


class FreshnessFinding(BaseModel):
    """A device whose telemetry is not advancing while peers are."""

    severity: str = Field(description='WARNING or CRITICAL')
    device: str
    mac: str = ''
    last_seen_delta: int = 0
    uptime_delta: int = 0
    rx_bytes_delta: int = 0
    peers_advancing: bool = False
    message: str
    recommendation: str


class FreshnessReport(BaseModel):
    """Two-sample freshness report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_compared: int = 0
    fresh_count: int = 0
    stale_count: int = 0
    no_peer_advanced: bool = False
    disappeared: list[str] = Field(default_factory=lambda: [])
    rebooted: list[str] = Field(default_factory=lambda: [])
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[FreshnessFinding] = Field(default_factory=lambda: [])
    message: str = ''


async def check_device_freshness(
    sample_gap_seconds: int = DEFAULT_SAMPLE_GAP_SECONDS,
) -> FreshnessReport:
    """Take two device samples `sample_gap_seconds` apart and compare them."""
    async with UniFiClient() as client:
        first = await client.get_devices()
        await asyncio.sleep(sample_gap_seconds)
        second = await client.get_devices()
    return check_device_freshness_from_samples(first, second)


async def summarise_freshness() -> FreshnessSummary:
    """Cheap single-sample freshness classification."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return summarise_freshness_from_data(devices)


def summarise_freshness_from_data(
    devices: list[dict[str, Any]],
    now: float | None = None,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> FreshnessSummary:
    """Classify each device's data as trustworthy or not, from one sample."""
    current = time.time() if now is None else now
    records: list[DeviceFreshness] = []
    not_informing: list[str] = []
    stale: list[str] = []

    for device in devices:
        if not _port_table(device):
            continue
        name = str(device.get('name') or device.get('mac') or 'Unknown')
        state = device.get('state')
        age = _age_seconds(device.get('last_seen'), current)
        informing = state is None or _as_int(state, default=1) == 1
        old = age is not None and age > stale_after_seconds

        reason = ''
        if not informing:
            reason = f'state={state} (not connected)'
            not_informing.append(name)
        if old:
            reason = (reason + '; ' if reason else '') + f'last_seen {age / 3600:.1f}h ago'
            stale.append(name)

        records.append(DeviceFreshness(
            device=name, mac=str(device.get('mac') or ''), state=_as_int(state) if state is not None else None,
            data_age_seconds=age, trustworthy=informing and not old, reason=reason,
        ))

    return FreshnessSummary(
        devices=records,
        not_informing=not_informing,
        stale_data=stale,
        validation_passed=not not_informing and not stale,
    )


def check_device_freshness_from_samples(
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> FreshnessReport:
    """Compare two device samples and report which are not advancing."""
    a = {str(d.get('mac') or '').lower(): d for d in first if d.get('mac')}
    b = {str(d.get('mac') or '').lower(): d for d in second if d.get('mac')}

    disappeared = [
        str(a[m].get('name') or m) for m in a if m not in b
    ]

    deltas: dict[str, dict[str, int]] = {}
    rebooted: list[str] = []
    for mac in a.keys() & b.keys():
        before, after = a[mac], b[mac]
        d_uptime = _as_int(after.get('uptime')) - _as_int(before.get('uptime'))
        d_seen = _as_int(after.get('last_seen')) - _as_int(before.get('last_seen'))
        d_rx = _total_rx(after) - _total_rx(before)
        name = str(after.get('name') or mac)
        if d_uptime < 0:
            # uptime went backwards: a reboot, not staleness. Do not conflate the two.
            rebooted.append(name)
            continue
        deltas[mac] = {'uptime': d_uptime, 'last_seen': d_seen, 'rx': d_rx}

    advanced = {m for m, d in deltas.items() if d['last_seen'] > 0 or d['uptime'] > 0}
    no_peer_advanced = bool(deltas) and not advanced

    findings: list[FreshnessFinding] = []
    if not no_peer_advanced:
        for mac, d in sorted(deltas.items()):
            if mac in advanced:
                continue
            device = b[mac]
            name = str(device.get('name') or mac)
            findings.append(FreshnessFinding(
                severity='CRITICAL',
                device=name,
                mac=mac,
                last_seen_delta=d['last_seen'],
                uptime_delta=d['uptime'],
                rx_bytes_delta=d['rx'],
                peers_advancing=True,
                message=(
                    f'{name} telemetry is NOT advancing between samples '
                    f'(Δlast_seen={d["last_seen"]}s, Δuptime={d["uptime"]}s, Δrx={d["rx"]}B) '
                    f'while other devices are. Every field the controller reports for this '
                    f'device — including its port table and STP states — is a stale snapshot '
                    f'and must not be treated as current.'
                ),
                recommendation=(
                    'Do not diagnose from this device\'s reported port state. Check physical '
                    'connectivity and its management path; if its management VLAN is severed it '
                    'cannot be repaired over the API and needs physical intervention.'
                ),
            ))

    message = ''
    if no_peer_advanced:
        message = (
            'No device advanced between the two samples, so the result is inconclusive rather '
            'than alarming: the sample gap was probably shorter than the controller inform '
            f'interval (~75-90s typical). Re-run with a gap of at least '
            f'{DEFAULT_SAMPLE_GAP_SECONDS}s.'
        )
    elif findings:
        message = f'{len(findings)} device(s) serving stale telemetry while peers advance.'
    else:
        message = 'All devices are reporting live telemetry.'

    return FreshnessReport(
        devices_compared=len(deltas),
        fresh_count=len(advanced),
        stale_count=len(findings),
        no_peer_advanced=no_peer_advanced,
        disappeared=disappeared,
        rebooted=rebooted,
        findings_count=len(findings),
        validation_passed=not findings,
        findings=findings,
        message=message,
    )


def _total_rx(device: dict[str, Any]) -> int:
    return sum(_as_int(p.get('rx_bytes')) for p in _port_table(device))


def _age_seconds(raw: Any, now: float) -> float | None:
    if raw is None:
        return None
    try:
        seen = float(raw)
    except (TypeError, ValueError):
        return None
    if seen > 10_000_000_000:
        seen /= 1000.0
    age = now - seen
    return age if age >= 0 else 0.0


def _port_table(device: dict[str, Any]) -> list[dict[str, Any]]:
    value = device.get('port_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
