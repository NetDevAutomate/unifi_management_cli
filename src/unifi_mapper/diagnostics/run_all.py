"""Every read-only diagnostic in one run, for both surfaces (issue 078).

``unifi-mapper diagnose all`` and the MCP tool ``run_all_diagnostics`` share this core.
:data:`CHECKS` names the registered tool each check runs, so the summary points an agent or
an operator at the tool to call for detail. A check that raises is a ``FAIL`` with a redacted
one-line detail and the other checks still run. Each handler opens ``UniFiClient()`` itself,
so under the MCP server, or the CLI's guarded run, every read borrows the shared read-only
connection.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, Literal
from unifi_mapper.core.utils.redact import redact_text


Status = Literal['PASS', 'WARN', 'FAIL']


@dataclass(frozen=True)
class Check:
    """One diagnostic the composite runs.

    Attributes:
        name: The display name (``Link Quality``).
        tool: The registered MCP tool that runs the same analysis.
        module: The handler's module (the manifest's ``module``).
        handler: The handler's name (the manifest's ``handler``); called with no arguments.
    """

    name: str
    tool: str
    module: str
    handler: str


CHECKS: tuple[Check, ...] = (
    Check('Link Quality', 'analyze_link_quality', 'unifi_mapper.analysis.link_quality', 'analyze_link_quality'),
    Check('Capacity Planning', 'get_capacity_report', 'unifi_mapper.analysis.capacity_planning', 'get_capacity_report'),
    Check('Port Profiles', 'validate_port_profiles', 'unifi_mapper.analysis.port_profile_validation', 'validate_port_profiles'),
    Check('MTU Consistency', 'audit_mtu_consistency', 'unifi_mapper.analysis.mtu_audit', 'audit_mtu_consistency'),
    Check('SFP Diagnostics', 'audit_sfp_diagnostics', 'unifi_mapper.analysis.sfp_diagnostics', 'audit_sfp_diagnostics'),
    Check('Radio Optimization', 'analyze_radio_optimization', 'unifi_mapper.analysis.radio_optimization', 'analyze_radio_optimization'),
    Check('Firmware Skew', 'get_firmware_report', 'unifi_mapper.analysis.firmware_advisor', 'get_firmware_report'),
    Check('DHCP Pool', 'check_dhcp_pool_utilization', 'unifi_mapper.analysis.dhcp_pool', 'check_dhcp_pool_utilization'),
    Check('PoE Budget', 'check_poe_budget', 'unifi_mapper.analysis.poe_budget', 'check_poe_budget'),
    Check('Client Density', 'analyze_client_density', 'unifi_mapper.analysis.client_density', 'analyze_client_density'),
    Check('Uplink Redundancy', 'check_uplink_redundancy', 'unifi_mapper.analysis.uplink_redundancy', 'check_uplink_redundancy'),
    Check('Uplink VLAN Transparency', 'audit_uplink_transparency', 'unifi_mapper.analysis.uplink_transparency', 'audit_uplink_transparency'),
    Check('Device Power Budget', 'audit_power_budget', 'unifi_mapper.analysis.power_budget', 'audit_power_budget'),
    Check('Foreign Bridges', 'detect_foreign_bridges', 'unifi_mapper.analysis.foreign_bridges', 'detect_foreign_bridges'),
    Check('Telemetry Freshness', 'summarise_freshness', 'unifi_mapper.analysis.device_freshness', 'summarise_freshness'),
)  # fmt: skip


class DiagnosticCheck(BaseModel):
    """One check's verdict."""

    name: str = Field(description='The check, e.g. Link Quality')
    tool: str = Field(description='The MCP tool (and analysis) that gives the detail')
    status: Status = Field(description='PASS, WARN or FAIL')
    detail: str = Field(default='', description='Why a check could not run (redacted), else empty')


class DiagnosticsSummary(BaseModel):
    """The pass/warn/fail summary of every diagnostic (`unifi-mapper diagnose all`)."""

    timestamp: str = Field(description='When the run finished')
    checks: list[DiagnosticCheck] = Field(description='Every check, in the order run')
    passed: int = Field(description='Checks that passed')
    warned: int = Field(description='Checks with warnings or recommendations')
    failed: int = Field(description='Checks that failed or could not run')
    healthy: bool = Field(description='True when no check failed')


def extract_status(report: object) -> Status:
    """Read PASS, WARN or FAIL from a report's common fields.

    ``validation_passed`` false, ``overall_health`` ``CRITICAL`` or ``network_healthy`` false
    is a FAIL; a non-empty ``warnings`` list, ``DEGRADED`` health, a positive
    ``findings_count`` or any ``recommendations`` is a WARN; anything else is a PASS.

    Args:
        report: Any analysis report.

    Returns:
        The verdict.
    """
    if getattr(report, 'validation_passed', True) is False:
        return 'FAIL'
    warnings = getattr(report, 'warnings', None)
    if isinstance(warnings, list) and warnings:
        return 'WARN'
    health = getattr(report, 'overall_health', None)
    if health == 'CRITICAL':
        return 'FAIL'
    if health == 'DEGRADED':
        return 'WARN'
    if getattr(report, 'network_healthy', None) is False:
        return 'FAIL'
    findings = getattr(report, 'findings_count', None)
    if isinstance(findings, int) and findings > 0:
        return 'WARN'
    recommendations = getattr(report, 'recommendations', None)
    if isinstance(recommendations, list) and recommendations:
        return 'WARN'
    return 'PASS'


def _loader(check: Check) -> Callable[[], Awaitable[Any]]:
    """Import a check's handler lazily (patched by the tests)."""
    return getattr(importlib.import_module(check.module), check.handler)


async def run_diagnostics(
    progress: Callable[[DiagnosticCheck], None] | None = None,
) -> DiagnosticsSummary:
    """Run every check in :data:`CHECKS`, in order, and summarise.

    Args:
        progress: Called with each check's verdict as soon as it is known (the CLI prints it).

    Returns:
        The summary; a check that raised is a FAIL whose ``detail`` is the redacted error.
    """
    results: list[DiagnosticCheck] = []
    for check in CHECKS:
        try:
            report = await _loader(check)()
            verdict = DiagnosticCheck(
                name=check.name, tool=check.tool, status=extract_status(report)
            )
        except Exception as e:  # noqa: BLE001 - one failing check must not stop the others
            verdict = DiagnosticCheck(
                name=check.name,
                tool=check.tool,
                status='FAIL',
                detail=f'{type(e).__name__}: {redact_text(e)}',
            )
        results.append(verdict)
        if progress is not None:
            progress(verdict)
    failed = sum(1 for c in results if c.status == 'FAIL')
    return DiagnosticsSummary(
        timestamp=datetime.now().isoformat(),
        checks=results,
        passed=sum(1 for c in results if c.status == 'PASS'),
        warned=sum(1 for c in results if c.status == 'WARN'),
        failed=failed,
        healthy=failed == 0,
    )


async def run_all_diagnostics() -> DiagnosticsSummary:
    """Every read-only diagnostic in one run, with a PASS, WARN or FAIL per check. Read-only.

    Runs the fifteen infrastructure checks `unifi-mapper diagnose all` runs (link quality,
    capacity, port profiles, MTU, SFP, radio, firmware, DHCP pools, PoE and power budgets,
    client density, uplink redundancy and VLAN transparency, foreign bridges, telemetry
    freshness) and names the tool that gives each check's detail. A check that cannot run
    is a FAIL with a one-line reason; the others still run.

    Returns:
        The summary.
    """
    return await run_diagnostics()
