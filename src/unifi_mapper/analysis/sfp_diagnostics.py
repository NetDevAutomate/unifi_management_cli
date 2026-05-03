"""SFP and SFP+ transceiver diagnostics from UniFi port tables."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


class SFPModuleReading(BaseModel):
    """Observed SFP module metadata and diagnostics for a switch port."""

    device_name: str
    port_idx: int
    port_name: str = ''
    media: str = ''
    speed_mbps: int = 0
    vendor: str = ''
    part: str = ''
    serial: str = ''
    temperature_c: float | None = None
    tx_power_dbm: float | None = None
    rx_power_dbm: float | None = None
    voltage_v: float | None = None
    current_ma: float | None = None
    rx_los: bool = False
    tx_fault: bool = False


class SFPDiagnosticFinding(BaseModel):
    """A health finding for an SFP module."""

    severity: str
    category: str
    device_name: str
    port_idx: int
    message: str
    recommendation: str


def _empty_module_readings() -> list[SFPModuleReading]:
    return []


def _empty_sfp_findings() -> list[SFPDiagnosticFinding]:
    return []


class SFPDiagnosticReport(BaseModel):
    """SFP diagnostics report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    ports_analyzed: int = 0
    modules_found: int = 0
    findings_count: int = 0
    modules: list[SFPModuleReading] = Field(default_factory=_empty_module_readings)
    findings: list[SFPDiagnosticFinding] = Field(default_factory=_empty_sfp_findings)
    diagnostics_available: bool = False


async def audit_sfp_diagnostics() -> SFPDiagnosticReport:
    """Fetch UniFi devices and audit SFP diagnostics."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return audit_sfp_diagnostics_from_data(devices)


def audit_sfp_diagnostics_from_data(devices: list[dict[str, Any]]) -> SFPDiagnosticReport:
    """Audit SFP modules from UniFi device dictionaries."""
    modules: list[SFPModuleReading] = []
    findings: list[SFPDiagnosticFinding] = []
    ports_analyzed = 0

    for device in devices:
        device_name = str(device.get('name') or device.get('mac') or 'Unknown')
        for port in _port_table(device):
            if not _is_sfp_port(port):
                continue
            ports_analyzed += 1
            if port.get('sfp_found') is False:
                continue
            if not _has_sfp_identity_or_dom(port):
                continue

            reading = SFPModuleReading(
                device_name=device_name,
                port_idx=_as_int(port.get('port_idx')),
                port_name=str(port.get('name') or ''),
                media=str(port.get('media') or ''),
                speed_mbps=_as_int(port.get('speed')),
                vendor=str(port.get('sfp_vendor') or ''),
                part=str(port.get('sfp_part') or ''),
                serial=str(port.get('sfp_serial') or ''),
                temperature_c=_as_float_or_none(port.get('sfp_temperature')),
                tx_power_dbm=_as_float_or_none(port.get('sfp_txpower')),
                rx_power_dbm=_as_float_or_none(port.get('sfp_rxpower')),
                voltage_v=_as_float_or_none(port.get('sfp_voltage')),
                current_ma=_as_float_or_none(port.get('sfp_current')),
                rx_los=_as_bool(port.get('sfp_rx_los')),
                tx_fault=_as_bool(port.get('sfp_tx_fault')),
            )
            modules.append(reading)
            findings.extend(_find_module_issues(reading))

    return SFPDiagnosticReport(
        ports_analyzed=ports_analyzed,
        modules_found=len(modules),
        findings_count=len(findings),
        modules=modules,
        findings=findings,
        diagnostics_available=any(
            module.temperature_c is not None
            or module.tx_power_dbm is not None
            or module.rx_power_dbm is not None
            for module in modules
        ),
    )


def _find_module_issues(reading: SFPModuleReading) -> list[SFPDiagnosticFinding]:
    findings: list[SFPDiagnosticFinding] = []
    if reading.rx_los:
        findings.append(
            SFPDiagnosticFinding(
                severity='CRITICAL',
                category='Optical Signal',
                device_name=reading.device_name,
                port_idx=reading.port_idx,
                message=f'{reading.device_name} port {reading.port_idx} reports SFP RX loss of signal.',
                recommendation='Check fibre/copper module seating, patching, and the far-end transceiver.',
            )
        )
    if reading.tx_fault:
        findings.append(
            SFPDiagnosticFinding(
                severity='CRITICAL',
                category='Transceiver Fault',
                device_name=reading.device_name,
                port_idx=reading.port_idx,
                message=f'{reading.device_name} port {reading.port_idx} reports SFP TX fault.',
                recommendation='Reseat or replace the transceiver and verify the far-end link.',
            )
        )
    if reading.rx_power_dbm is not None and reading.rx_power_dbm < -10:
        findings.append(
            SFPDiagnosticFinding(
                severity='WARNING',
                category='Optical Power',
                device_name=reading.device_name,
                port_idx=reading.port_idx,
                message=(
                    f'{reading.device_name} port {reading.port_idx} RX power is '
                    f'{reading.rx_power_dbm:.2f} dBm.'
                ),
                recommendation='Inspect fibre path, patch leads, optics, and connector cleanliness.',
            )
        )
    if reading.rx_power_dbm is not None and reading.rx_power_dbm > -3:
        findings.append(
            SFPDiagnosticFinding(
                severity='INFO',
                category='Optical Power',
                device_name=reading.device_name,
                port_idx=reading.port_idx,
                message=(
                    f'{reading.device_name} port {reading.port_idx} RX power is '
                    f'{reading.rx_power_dbm:.2f} dBm.'
                ),
                recommendation='Verify this is within the module vendor receive-power range.',
            )
        )
    if reading.temperature_c is not None and reading.temperature_c >= 75:
        findings.append(
            SFPDiagnosticFinding(
                severity='WARNING',
                category='Temperature',
                device_name=reading.device_name,
                port_idx=reading.port_idx,
                message=(
                    f'{reading.device_name} port {reading.port_idx} module temperature is '
                    f'{reading.temperature_c:.1f} C.'
                ),
                recommendation='Check airflow and module temperature limits.',
            )
        )
    return findings


def _is_sfp_port(port: dict[str, Any]) -> bool:
    media = str(port.get('media') or '').lower()
    return media.startswith('sfp') or any(str(key).startswith('sfp_') for key in port)


def _has_sfp_identity_or_dom(port: dict[str, Any]) -> bool:
    return any(
        port.get(key) is not None
        for key in (
            'sfp_vendor',
            'sfp_part',
            'sfp_serial',
            'sfp_temperature',
            'sfp_txpower',
            'sfp_rxpower',
        )
    )


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


def _as_float_or_none(value: Any) -> float | None:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ('', '0', 'false', 'no', 'off')
    return bool(value)
