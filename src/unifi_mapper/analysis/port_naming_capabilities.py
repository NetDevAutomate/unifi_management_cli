"""Port-naming support per device, for both surfaces (issue 078).

``unifi-mapper capabilities`` and the MCP tool ``get_port_naming_capabilities`` share this
core: the :class:`DeviceCapabilityDetector` verdict for each gateway and switch (the devices
the port-naming workflow writes to), structured, with the text report the CLI prints.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.device_capabilities import DeviceCapabilityDetector, PortNamingSupport


# The controller type codes the port-naming workflow targets (no APs: it names switch ports).
NETWORK_DEVICE_TYPES: frozenset[str] = frozenset({'ugw', 'usg', 'udm', 'usw'})

_VERDICT_LINE: dict[PortNamingSupport, str] = {
    PortNamingSupport.FULL_SUPPORT: '  ✅ FULL SUPPORT - Reliable API port naming',
    PortNamingSupport.RESETS_AUTOMATICALLY: "  🚨 AUTO-RESETS - Changes don't persist",
    PortNamingSupport.UI_ONLY: '  ⚠️  UI ONLY - API unreliable',
    PortNamingSupport.LIMITED: '  ⚠️  LIMITED - Partial support',
    PortNamingSupport.NOT_SUPPORTED: '  ❌ NOT SUPPORTED',
}


class DevicePortNamingCapability(BaseModel):
    """The detector's verdict for one device."""

    name: str = Field(description='Device name')
    model: str = Field(description='Model code as the controller reports it')
    firmware_version: str = Field(description='Installed firmware version')
    support: str = Field(description='full, ui_only, limited, resets or none')
    known_issues: list[str] = Field(default_factory=list, description='Known issues')
    workarounds: list[str] = Field(default_factory=list, description='Workarounds')
    api_endpoint_restrictions: list[str] = Field(
        default_factory=list, description='API restrictions'
    )
    max_port_name_length: int | None = Field(description='Longest accepted port name')
    supports_port_profiles: bool = Field(description='Whether port profiles can be set')


class PortNamingCapabilityReport(BaseModel):
    """Port-naming support across the network's gateways and switches."""

    timestamp: str = Field(description='When the devices were read')
    devices_analyzed: int = Field(description='Gateways and switches assessed')
    compatible: int = Field(description='Devices with full API support')
    problematic: int = Field(description='Devices that reset, are UI-only or limited')
    unsupported: int = Field(description='Devices with no custom port naming')
    automated_naming_recommended: bool = Field(
        description='True when every device has full support'
    )
    devices: list[DevicePortNamingCapability] = Field(description='Per device, by name')
    recommendations: list[str] = Field(default_factory=list, description='Recommendations')


def assess_port_naming(
    devices: list[dict[str, Any]], *, timestamp: str
) -> PortNamingCapabilityReport:
    """Assess every gateway and switch for port-naming support (pure).

    Args:
        devices: The controller's ``stat/device`` records.
        timestamp: When they were read.

    Returns:
        The report, devices sorted by name.
    """
    detector = DeviceCapabilityDetector()
    assessed: list[DevicePortNamingCapability] = []
    for device in devices:
        if device.get('type') not in NETWORK_DEVICE_TYPES:
            continue
        model = str(device.get('model', 'Unknown'))
        firmware = str(device.get('version', 'Unknown'))
        capability = detector.detect_capabilities(model, firmware)
        assessed.append(
            DevicePortNamingCapability(
                name=str(device.get('name', 'Unknown')),
                model=model,
                firmware_version=firmware,
                support=capability.port_naming_support.value,
                known_issues=list(capability.known_issues),
                workarounds=list(capability.workarounds),
                api_endpoint_restrictions=list(capability.api_endpoint_restrictions),
                max_port_name_length=capability.max_port_name_length,
                supports_port_profiles=capability.supports_port_profiles,
            )
        )
    assessed.sort(key=lambda d: d.name.lower())
    compatible = sum(1 for d in assessed if d.support == PortNamingSupport.FULL_SUPPORT.value)
    unsupported = sum(1 for d in assessed if d.support == PortNamingSupport.NOT_SUPPORTED.value)
    problematic = len(assessed) - compatible - unsupported
    recommendations: list[str] = []
    for d in assessed:
        if d.support != PortNamingSupport.FULL_SUPPORT.value:
            recommendations.append(
                f'{d.name} ({d.model}, {d.firmware_version}): {d.support}; '
                + (d.workarounds[0] if d.workarounds else 'name its ports in the UI')
            )
    if problematic or unsupported:
        recommendations.append(
            'Automated port naming is not recommended for this network: name the flagged '
            "devices' ports in the UI, or upgrade them first"
        )
    return PortNamingCapabilityReport(
        timestamp=timestamp,
        devices_analyzed=len(assessed),
        compatible=compatible,
        problematic=problematic,
        unsupported=unsupported,
        automated_naming_recommended=not (problematic or unsupported),
        devices=assessed,
        recommendations=recommendations,
    )


def render_text(report: PortNamingCapabilityReport) -> str:
    """Render the report as the compatibility text the CLI prints.

    Args:
        report: An assessment.

    Returns:
        The text, one block per device and a summary.
    """
    lines = ['=' * 80, 'UNIFI DEVICE PORT NAMING COMPATIBILITY REPORT', '=' * 80]
    for d in report.devices:
        lines.append(f'\n📍 {d.name} ({d.model}) - Firmware {d.firmware_version}')
        lines.append(_VERDICT_LINE[PortNamingSupport(d.support)])
        lines.extend(f'    • {issue}' for issue in d.known_issues)
        if d.workarounds:
            lines.append('    Workarounds:')
            lines.extend(f'      - {w}' for w in d.workarounds)
    lines += [
        f'\n{"=" * 80}',
        'COMPATIBILITY SUMMARY',
        '=' * 80,
        f'Total devices analyzed: {report.devices_analyzed}',
        f'✅ Compatible devices: {report.compatible}',
        f'⚠️  Problematic devices: {report.problematic}',
        f'❌ Unsupported devices: {report.unsupported}',
    ]
    if not report.automated_naming_recommended:
        flagged = report.problematic + report.unsupported
        lines += [
            f'\n🚨 CRITICAL: {flagged} devices have port naming issues',
            'Automated port naming not recommended for this network.',
            'Consider manual UI-based configuration or device upgrades.',
        ]
    return '\n'.join(lines)


async def get_port_naming_capabilities() -> PortNamingCapabilityReport:
    """Port-naming support per gateway and switch, from model and firmware. Read-only.

    The verdict the port-naming workflow (`unifi-mapper discover`, `ports refresh`) uses:
    full API support, UI-only, limited, auto-resetting firmware or unsupported, with the
    known issues and workarounds for each flagged device.

    Returns:
        The report.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE or API_ERROR when the devices cannot be read.
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                ) from e
            raise ToolError(
                message=f'Error reading devices: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            ) from e
    return assess_port_naming(devices, timestamp=datetime.now().isoformat())
