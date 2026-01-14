"""QoS (Quality of Service) validation tool for UniFi networks."""

from datetime import datetime
from typing import Any
from unifi_mapper.core.models import (
    PortQoSConfig,
    QoSFinding,
    QoSSeverity,
    QoSValidationReport,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


async def validate_qos(
    device_id: str | None = None,
    check_voice_vlan: bool = True,
) -> QoSValidationReport:
    """Validate QoS configuration across the network.

    When to use this tool:
    - When VoIP call quality is poor or inconsistent
    - After enabling voice VLANs or QoS policies
    - During network audits for compliance
    - When troubleshooting latency-sensitive applications
    - Before deploying video conferencing or real-time apps

    How QoS validation works:
    - Analyzes DSCP trust settings on all ports
    - Checks for proper voice VLAN configuration
    - Validates rate limiting on uplinks (usually unwanted)
    - Ensures consistency across similar port types
    - Identifies misconfigured QoS policies

    Types of issues detected:
    - Uplink ports not trusting DSCP markings
    - Voice VLAN without proper QoS trust
    - Rate limiting on uplink/trunk ports
    - Inconsistent trust modes across network
    - Missing QoS configuration on priority ports

    Common workflow:
    1. validate_qos() - assess QoS configuration
    2. Review CRITICAL and ERROR findings first
    3. Focus on voice VLAN and uplink ports
    4. Apply consistent trust settings
    5. Re-validate after changes

    What to do next:
    - If DSCP trust missing on uplinks: Enable DSCP trust
    - If voice VLAN issues: Enable trust on phone ports
    - If rate limiting on uplinks: Remove or increase limits
    - If inconsistent config: Standardize across devices

    Args:
        device_id: Optional device ID to check. If None, checks all switches.
        check_voice_vlan: Whether to validate voice VLAN configuration.

    Returns:
        QoSValidationReport with findings and recommendations

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            networks = await client.get_networks()

            devices_analyzed = 0
            ports_analyzed = 0
            findings: list[QoSFinding] = []
            port_configs: list[PortQoSConfig] = []

            critical_count = 0
            error_count = 0
            warning_count = 0
            info_count = 0
            dscp_trust_count = 0
            voice_vlan_ports: list[str] = []

            # Track uplink configurations for consistency
            uplink_configs: list[PortQoSConfig] = []

            for device in devices:
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch', 'udm', 'udmpro'):
                    continue

                # Filter to specific device if requested
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                devices_analyzed += 1
                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))

                port_table = device.get('port_table', [])
                port_overrides = device.get('port_overrides', [])
                override_by_port = {po.get('port_idx'): po for po in port_overrides}

                for port in port_table:
                    port_idx = port.get('port_idx', 0)
                    if port_idx == 0:
                        continue

                    ports_analyzed += 1
                    port_override = override_by_port.get(port_idx, {})

                    # Extract QoS configuration
                    config = _extract_port_qos_config(port, port_override, dev_id, dev_name)
                    port_configs.append(config)

                    # Track stats
                    if config.dscp_trust:
                        dscp_trust_count += 1

                    if config.voice_vlan:
                        voice_vlan_ports.append(f'{dev_name}:{port_idx}')

                    # Collect uplinks for consistency check
                    if port.get('is_uplink', False):
                        uplink_configs.append(config)

                    # Validate this port
                    port_findings = _validate_port_qos(config, port, dev_id, dev_name)
                    findings.extend(port_findings)

                    # Count severities
                    for finding in port_findings:
                        if finding.severity == QoSSeverity.CRITICAL:
                            critical_count += 1
                        elif finding.severity == QoSSeverity.ERROR:
                            error_count += 1
                        elif finding.severity == QoSSeverity.WARNING:
                            warning_count += 1
                        else:
                            info_count += 1

                # Check if specific device was found
                if device_id and devices_analyzed > 0:
                    break

            # Handle device not found
            if device_id and devices_analyzed == 0:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_network_topology'],
                )

            # Check uplink consistency
            uplink_findings = _check_uplink_consistency(uplink_configs)
            findings.extend(uplink_findings)
            for finding in uplink_findings:
                if finding.severity == QoSSeverity.WARNING:
                    warning_count += 1

            # Check voice VLAN configuration
            if check_voice_vlan:
                voice_findings = _check_voice_vlan_config(networks, voice_vlan_ports)
                findings.extend(voice_findings)
                for finding in voice_findings:
                    if finding.severity == QoSSeverity.WARNING:
                        warning_count += 1

            # Determine overall health
            if critical_count > 0:
                overall_health = 'CRITICAL'
            elif error_count > 0:
                overall_health = 'DEGRADED'
            elif warning_count > 0:
                overall_health = 'WARNING'
            else:
                overall_health = 'HEALTHY'

            # Generate recommendations
            recommendations = _generate_recommendations(findings)

            return QoSValidationReport(
                timestamp=datetime.now().isoformat(),
                devices_analyzed=devices_analyzed,
                ports_analyzed=ports_analyzed,
                findings=findings,
                critical_count=critical_count,
                error_count=error_count,
                warning_count=warning_count,
                info_count=info_count,
                port_configs=port_configs,
                voice_vlan_configured=len(voice_vlan_ports) > 0,
                dscp_trust_enabled_count=dscp_trust_count,
                overall_health=overall_health,
                recommendations=recommendations,
            )

        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error validating QoS: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _extract_port_qos_config(
    port: dict[str, Any],
    port_override: dict[str, Any],
    device_id: str,
    device_name: str,
) -> PortQoSConfig:
    """Extract QoS configuration from port data."""
    port_idx = port.get('port_idx', 0)
    port_name = port.get('name', '') or f'Port {port_idx}'

    # Determine trust settings
    # In UniFi, QoS profile presence typically implies DSCP trust
    qos_profile = port_override.get('qos_profile')
    dscp_trust = qos_profile is not None

    # Check for explicit trust settings
    dot1x_ctrl = port_override.get('dot1x_ctrl', '')
    if 'dscp' in str(dot1x_ctrl).lower():
        dscp_trust = True

    # CoS trust (Class of Service)
    cos_trust = port_override.get('cos_override', False)

    # Storm control
    storm_control = port_override.get('storm_ctrl_enabled', False)

    # Rate limits
    rate_limit_in = port_override.get('ingress_rate_limit_kbps')
    rate_limit_out = port_override.get('egress_rate_limit_kbps')

    # Voice VLAN
    voice_vlan = port_override.get('voice_networkconf_id')
    # Convert network ID to VLAN if possible
    voice_vlan_id = None
    if voice_vlan:
        voice_vlan_id = voice_vlan  # Store the network ID

    return PortQoSConfig(
        device_id=device_id,
        device_name=device_name,
        port_idx=port_idx,
        port_name=port_name,
        dscp_trust=dscp_trust,
        cos_trust=cos_trust,
        storm_control_enabled=storm_control,
        rate_limit_in=rate_limit_in,
        rate_limit_out=rate_limit_out,
        voice_vlan=voice_vlan_id,
        qos_profile=qos_profile,
    )


def _validate_port_qos(
    config: PortQoSConfig,
    port: dict[str, Any],
    device_id: str,
    device_name: str,
) -> list[QoSFinding]:
    """Validate QoS configuration for a single port."""
    findings: list[QoSFinding] = []
    port_idx = port.get('port_idx', 0)
    is_uplink = port.get('is_uplink', False)

    # Check DSCP trust on uplinks
    if is_uplink and not config.dscp_trust:
        findings.append(
            QoSFinding(
                severity=QoSSeverity.WARNING,
                category='DSCP Trust',
                message='Uplink port not trusting DSCP markings',
                device_id=device_id,
                device_name=device_name,
                port_idx=port_idx,
                current_value='DSCP trust disabled',
                expected_value='DSCP trust enabled',
                recommendation='Enable DSCP trust on uplink ports to preserve QoS markings',
            )
        )

    # Check for rate limiting on uplinks (usually not wanted)
    if is_uplink and (config.rate_limit_in or config.rate_limit_out):
        findings.append(
            QoSFinding(
                severity=QoSSeverity.ERROR,
                category='Rate Limiting',
                message='Rate limiting configured on uplink port',
                device_id=device_id,
                device_name=device_name,
                port_idx=port_idx,
                current_value=f'In: {config.rate_limit_in}, Out: {config.rate_limit_out}',
                expected_value='No rate limiting on uplinks',
                recommendation='Remove rate limiting from uplink ports to prevent bottlenecks',
            )
        )

    # Voice VLAN without proper trust
    if config.voice_vlan and not config.dscp_trust:
        findings.append(
            QoSFinding(
                severity=QoSSeverity.ERROR,
                category='Voice VLAN',
                message='Voice VLAN enabled but DSCP trust not configured',
                device_id=device_id,
                device_name=device_name,
                port_idx=port_idx,
                current_value=f'Voice VLAN: {config.voice_vlan}, Trust: disabled',
                expected_value='DSCP trust enabled with voice VLAN',
                recommendation='Enable DSCP trust on voice VLAN ports for proper call quality',
            )
        )

    return findings


def _check_uplink_consistency(uplink_configs: list[PortQoSConfig]) -> list[QoSFinding]:
    """Check QoS consistency across uplink ports."""
    findings: list[QoSFinding] = []

    if len(uplink_configs) < 2:
        return findings

    # Group by trust mode
    trust_enabled = [c for c in uplink_configs if c.dscp_trust]
    trust_disabled = [c for c in uplink_configs if not c.dscp_trust]

    # Check for inconsistency
    if trust_enabled and trust_disabled:
        findings.append(
            QoSFinding(
                severity=QoSSeverity.WARNING,
                category='Consistency',
                message='Inconsistent DSCP trust modes across uplink ports',
                current_value=f'{len(trust_enabled)} with trust, {len(trust_disabled)} without',
                expected_value='All uplinks with same trust mode',
                recommendation='Standardize DSCP trust configuration across all uplink ports',
            )
        )

    return findings


def _check_voice_vlan_config(
    networks: list[dict[str, Any]],
    voice_vlan_ports: list[str],
) -> list[QoSFinding]:
    """Check voice VLAN configuration consistency."""
    findings: list[QoSFinding] = []

    # Find voice networks
    voice_networks = [n for n in networks if 'voice' in n.get('name', '').lower()]

    if voice_networks and not voice_vlan_ports:
        findings.append(
            QoSFinding(
                severity=QoSSeverity.WARNING,
                category='Voice VLAN',
                message='Voice network defined but no ports configured with voice VLAN',
                current_value='0 ports with voice VLAN',
                expected_value='Voice VLAN on phone ports',
                recommendation='Configure voice VLAN on ports connected to IP phones',
            )
        )

    return findings


def _generate_recommendations(findings: list[QoSFinding]) -> list[str]:
    """Generate recommendations based on findings."""
    recommendations: list[str] = []

    # Group findings by category
    categories: dict[str, int] = {}
    for finding in findings:
        categories[finding.category] = categories.get(finding.category, 0) + 1

    if 'DSCP Trust' in categories:
        recommendations.append(
            f'Enable DSCP trust on {categories["DSCP Trust"]} uplink port(s) '
            'to preserve QoS markings'
        )

    if 'Rate Limiting' in categories:
        recommendations.append(
            f'Review rate limiting on {categories["Rate Limiting"]} uplink port(s) - '
            'may cause bandwidth bottlenecks'
        )

    if 'Voice VLAN' in categories:
        recommendations.append(
            f'Fix {categories["Voice VLAN"]} voice VLAN configuration issue(s) '
            'to ensure call quality'
        )

    if 'Consistency' in categories:
        recommendations.append('Standardize QoS configuration across all similar port types')

    if not findings:
        recommendations.append('QoS configuration looks good - no issues found')

    return recommendations
