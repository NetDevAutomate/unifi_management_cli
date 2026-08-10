"""Wireless radio channel and transmit power optimisation analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


class RadioFinding(BaseModel):
    """Wireless radio optimisation finding."""

    severity: str
    category: str
    ap_name: str
    band: str
    channel: int | None = None
    message: str
    recommendation: str


class RadioOptimizationReport(BaseModel):
    """Wireless radio optimisation report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    aps_analyzed: int = 0
    radios_analyzed: int = 0
    findings_count: int = 0
    findings: list[RadioFinding] = Field(default_factory=lambda: [])
    recommendations: list[str] = Field(default_factory=list)


async def analyze_radio_optimization() -> RadioOptimizationReport:
    """Fetch UniFi AP data and analyse channel/power settings."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return analyze_radio_optimization_from_data(devices)


def analyze_radio_optimization_from_data(
    devices: list[dict[str, Any]],
) -> RadioOptimizationReport:
    """Analyse AP radio channel reuse and transmit power from device data."""
    aps = [device for device in devices if str(device.get('type') or '').lower() == 'uap']
    findings: list[RadioFinding] = []
    radios_by_band_channel: dict[tuple[str, int], list[tuple[str, dict[str, Any]]]] = defaultdict(
        list
    )
    radios_analyzed = 0

    for ap in aps:
        ap_name = str(ap.get('name') or ap.get('mac') or 'Unknown AP')
        client_count = _as_int(ap.get('num_sta') or ap.get('user-num_sta'))
        for radio in _radio_table(ap):
            radios_analyzed += 1
            band = _band_name(radio)
            channel = _as_int(radio.get('channel'), default=0)
            if channel:
                radios_by_band_channel[(band, channel)].append((ap_name, radio))
            power = str(radio.get('tx_power_mode') or radio.get('tx_power') or '').lower()
            if power == 'high' and client_count >= 25:
                findings.append(
                    RadioFinding(
                        severity='INFO',
                        category='Transmit Power',
                        ap_name=ap_name,
                        band=band,
                        channel=channel or None,
                        message=f'{ap_name} uses high transmit power with {client_count} clients.',
                        recommendation='Review whether medium power improves roaming and cell balance.',
                    )
                )

    for (band, channel), radios in radios_by_band_channel.items():
        if len(radios) < 2:
            continue
        ap_names = ', '.join(name for name, _ in radios)
        findings.append(
            RadioFinding(
                severity='WARNING',
                category='Channel Reuse',
                ap_name=ap_names,
                band=band,
                channel=channel,
                message=f'{len(radios)} AP radios share {band} channel {channel}.',
                recommendation='Use non-overlapping channels or reduce channel width/power where APs overlap.',
            )
        )

    recommendations = [
        'Use this as an audit: verify RF changes with client experience and spectrum scans.',
        'Prefer fixed 2.4 GHz channels 1/6/11 and avoid unnecessarily high power in dense areas.',
    ]
    return RadioOptimizationReport(
        aps_analyzed=len(aps),
        radios_analyzed=radios_analyzed,
        findings_count=len(findings),
        findings=findings,
        recommendations=recommendations,
    )


def _radio_table(ap: dict[str, Any]) -> list[dict[str, Any]]:
    value = ap.get('radio_table') or ap.get('radio_table_stats') or ap.get('vap_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _band_name(radio: dict[str, Any]) -> str:
    radio_id = str(radio.get('radio') or radio.get('band') or radio.get('name') or '').lower()
    channel = _as_int(radio.get('channel'))
    if radio_id in ('ng', '2g', '2.4g') or 1 <= channel <= 14:
        return '2.4GHz'
    if radio_id in ('na', '5g') or 32 <= channel < 180:
        return '5GHz'
    if radio_id in ('6g', '6e') or channel >= 180:
        return '6GHz'
    return radio_id or 'unknown'


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
