"""MTU consistency audit for UniFi inter-switch links."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


class MTUFinding(BaseModel):
    """MTU audit finding."""

    severity: str
    category: str
    device_a: str
    port_a: int
    mtu_a: int
    device_b: str
    port_b: int | None = None
    mtu_b: int | None = None
    message: str
    recommendation: str


class MTUAuditReport(BaseModel):
    """MTU consistency audit report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    links_analyzed: int = 0
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[MTUFinding] = Field(default_factory=lambda: [])


async def audit_mtu_consistency() -> MTUAuditReport:
    """Fetch UniFi devices and audit inter-switch MTU consistency."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return audit_mtu_consistency_from_data(devices)


def audit_mtu_consistency_from_data(devices: list[dict[str, Any]]) -> MTUAuditReport:
    """Audit MTU consistency from UniFi device dictionaries."""
    devices_by_mac = {
        _normalize_mac(device.get('mac')): device
        for device in devices
        if _normalize_mac(device.get('mac'))
    }
    findings: list[MTUFinding] = []
    links_analyzed = 0
    devices_analyzed = sum(1 for device in devices if _is_switch(device))

    for device in devices:
        if not _is_switch(device):
            continue
        ports = _ports_by_idx(device)
        for lldp in _dict_list(device.get('lldp_table')):
            local_port_idx = _as_int(lldp.get('local_port_idx'))
            local_port = ports.get(local_port_idx)
            remote_device = devices_by_mac.get(_normalize_mac(lldp.get('chassis_id')))
            if local_port is None or remote_device is None:
                continue
            remote_port_idx = _as_int(lldp.get('port_id'), default=0) or None
            remote_port = _ports_by_idx(remote_device).get(remote_port_idx or -1)
            local_mtu = _port_mtu(local_port, device)
            remote_mtu = _port_mtu(remote_port, remote_device) if remote_port else None
            links_analyzed += 1

            if remote_mtu is not None and local_mtu != remote_mtu:
                findings.append(
                    MTUFinding(
                        severity='WARNING',
                        category='MTU Mismatch',
                        device_a=str(device.get('name') or device.get('mac')),
                        port_a=local_port_idx,
                        mtu_a=local_mtu,
                        device_b=str(remote_device.get('name') or remote_device.get('mac')),
                        port_b=remote_port_idx,
                        mtu_b=remote_mtu,
                        message=f'Inter-switch link MTU differs: {local_mtu} vs {remote_mtu}.',
                        recommendation='Align MTU/jumbo-frame settings on both ends of the link.',
                    )
                )

    return MTUAuditReport(
        devices_analyzed=devices_analyzed,
        links_analyzed=links_analyzed,
        findings_count=len(findings),
        validation_passed=not findings,
        findings=findings,
    )


def _is_switch(device: dict[str, Any]) -> bool:
    return str(device.get('type') or '').lower() in ('usw', 'switch', 'udm', 'udmpro')


def _ports_by_idx(device: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {_as_int(port.get('port_idx')): port for port in _dict_list(device.get('port_table'))}


def _port_mtu(port: dict[str, Any] | None, device: dict[str, Any]) -> int:
    if port is not None:
        for key in ('mtu', 'port_mtu'):
            if port.get(key) is not None:
                return _as_int(port.get(key), default=1500)
    if device.get('jumbo_frame_enabled'):
        return 9000
    return _as_int(device.get('mtu'), default=1500)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


def _normalize_mac(value: Any) -> str:
    return str(value or '').lower().replace(':', '').replace('-', '')


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
