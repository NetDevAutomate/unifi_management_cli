"""STP guard and topology-change audits."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from unifi_mapper.core.models.stp import STPTopology


class STPGuardFinding(BaseModel):
    """A Root Guard or topology-change finding."""

    severity: str
    category: str
    device_name: str
    port_idx: int
    message: str
    recommendation: str


def _empty_guard_findings() -> list[STPGuardFinding]:
    return []


class STPGuardAuditReport(BaseModel):
    """STP guard audit report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    ports_analyzed: int = 0
    findings_count: int = 0
    findings: list[STPGuardFinding] = Field(default_factory=_empty_guard_findings)


def audit_stp_guard_recommendations(
    topology: STPTopology,
    tcn_threshold: int = 10,
) -> STPGuardAuditReport:
    """Audit Root Guard candidates and STP topology-change counters."""
    switches_by_id = {switch.device_id: switch for switch in topology.switches}
    findings: list[STPGuardFinding] = []
    ports_analyzed = 0

    for switch in topology.switches:
        for port in switch.port_states:
            if not port.connected_device_id:
                continue
            downstream = switches_by_id.get(port.connected_device_id)
            if downstream is None:
                continue
            ports_analyzed += 1

            if downstream.hierarchy_tier > switch.hierarchy_tier and switch.hierarchy_tier <= 1:
                severity = (
                    'WARNING'
                    if downstream.current_priority <= switch.current_priority
                    else 'INFO'
                )
                findings.append(
                    STPGuardFinding(
                        severity=severity,
                        category='Root Guard',
                        device_name=switch.name,
                        port_idx=port.port_idx,
                        message=(
                            f'{switch.name} port {port.port_idx} is a downlink to '
                            f'{downstream.name}.'
                        ),
                        recommendation=(
                            'Enable Root Guard on core/distribution downlinks so a downstream '
                            'switch cannot become STP root.'
                        ),
                    )
                )

            if port.stp_tc_count >= tcn_threshold:
                findings.append(
                    STPGuardFinding(
                        severity='WARNING',
                        category='Topology Change',
                        device_name=switch.name,
                        port_idx=port.port_idx,
                        message=(
                            f'{switch.name} port {port.port_idx} has STP topology-change '
                            f'count {port.stp_tc_count}.'
                        ),
                        recommendation='Investigate link flaps, loops, or unstable downstream devices.',
                    )
                )

    return STPGuardAuditReport(
        ports_analyzed=ports_analyzed,
        findings_count=len(findings),
        findings=findings,
    )
