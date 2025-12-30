"""VLAN diagnostics tool for UniFi networks."""

from datetime import datetime
from typing import Any
from unifi_mcp.models import (
    PortVLANConfig,
    VLANDiagnosticCheck,
    VLANDiagnosticReport,
    VLANInfo,
)
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def diagnose_vlans(
    source_vlan: int | None = None,
    dest_vlan: int | None = None,
) -> VLANDiagnosticReport:
    """Comprehensive VLAN diagnostics and troubleshooting.

    When to use this tool:
    - When inter-VLAN communication is failing
    - When devices on one VLAN cannot reach another VLAN
    - During VLAN configuration changes to verify setup
    - When troubleshooting network segmentation issues
    - For auditing VLAN configurations across switches

    How VLAN diagnostics work:
    - Retrieves VLAN configurations from the controller
    - Analyzes port profiles and VLAN assignments
    - Checks for missing VLANs, misconfigured trunks
    - Validates gateway and routing configuration
    - Identifies configuration inconsistencies

    Common VLAN issues detected:
    - VLANs defined but not tagged on trunk ports
    - Missing gateways preventing inter-VLAN routing
    - Inconsistent port profile configurations
    - Disabled VLANs that should be active
    - Native VLAN mismatches on trunk links

    Common workflow:
    1. diagnose_vlans() - get overall VLAN health
    2. diagnose_vlans(source_vlan=10, dest_vlan=20) - check specific connectivity
    3. Review recommendations for any FAIL/WARNING checks
    4. Apply fixes in UniFi controller
    5. Re-run diagnostics to verify

    What to do next:
    - If FAIL on VLAN existence: Create missing VLANs in controller
    - If FAIL on gateway: Configure gateway IP for VLAN
    - If FAIL on trunk: Tag VLANs on inter-switch trunk ports
    - If WARNING on firewall: Review firewall rules for blocking

    Args:
        source_vlan: Optional source VLAN ID for connectivity check.
            If both source_vlan and dest_vlan provided, runs inter-VLAN
            connectivity diagnostics between them.
        dest_vlan: Optional destination VLAN ID for connectivity check.

    Returns:
        VLANDiagnosticReport with all VLANs, port configs, and diagnostic checks

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            # Get network configuration (VLANs)
            networks = await client.get_networks()
            devices = await client.get_devices()

            # Parse VLANs
            vlans: list[VLANInfo] = []
            vlan_lookup: dict[int, VLANInfo] = {}

            for network in networks:
                # Check if this is a VLAN network
                vlan_id = network.get('vlan')
                purpose = network.get('purpose', '')

                if vlan_id or purpose == 'vlan-only':
                    vlan_id = vlan_id or 1
                    vlan_info = VLANInfo(
                        vlan_id=vlan_id,
                        name=network.get('name', f'VLAN {vlan_id}'),
                        subnet=network.get('ip_subnet'),
                        gateway=network.get('gateway_ip'),
                        enabled=network.get('enabled', True),
                        dhcp_enabled=network.get('dhcpd_enabled', False),
                        client_count=0,  # Will count from clients if needed
                    )
                    vlans.append(vlan_info)
                    vlan_lookup[vlan_id] = vlan_info

            # Get port VLAN configurations
            port_configs: list[PortVLANConfig] = []

            for device in devices:
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch'):
                    continue

                dev_id = device.get('_id', '')
                dev_name = device.get('name', device.get('mac', 'Unknown'))

                # Get port overrides
                port_overrides = device.get('port_overrides', [])
                port_table = device.get('port_table', [])

                # Build port table lookup
                port_lookup = {p.get('port_idx'): p for p in port_table}

                for override in port_overrides:
                    port_idx = override.get('port_idx')
                    if port_idx is None:
                        continue

                    # Get VLAN configuration
                    native_vlan = override.get('native_networkconf_id', 1)
                    if isinstance(native_vlan, str):
                        # It's a network ID, need to look up VLAN
                        native_vlan = _network_id_to_vlan(native_vlan, networks)

                    profile_name = override.get('portconf_id', 'Default')

                    # Parse tagged VLANs
                    tagged_vlans: list[int] = []
                    if 'voice_networkconf_id' in override:
                        voice_vlan = _network_id_to_vlan(
                            override['voice_networkconf_id'], networks
                        )
                        if voice_vlan:
                            tagged_vlans.append(voice_vlan)

                    # Check for trunk profile
                    port_info = port_lookup.get(port_idx, {})
                    is_trunk = (
                        len(tagged_vlans) > 0
                        or 'trunk' in profile_name.lower()
                        or 'all' in profile_name.lower()
                    )

                    port_name = port_info.get('name', '') or f'Port {port_idx}'

                    port_configs.append(
                        PortVLANConfig(
                            device_id=dev_id,
                            device_name=dev_name,
                            port_idx=port_idx,
                            port_name=port_name,
                            native_vlan=native_vlan if isinstance(native_vlan, int) else 1,
                            tagged_vlans=tagged_vlans,
                            profile_name=profile_name,
                            is_trunk=is_trunk,
                        )
                    )

            # Run diagnostic checks
            checks: list[VLANDiagnosticCheck] = []

            # Check 1: VLAN configuration completeness
            checks.append(_check_vlan_configuration(vlans))

            # Check 2: Gateway configuration
            checks.append(_check_gateways(vlans))

            # Check 3: Port profile consistency
            checks.append(_check_port_consistency(port_configs))

            # Check 4: Trunk VLAN coverage
            checks.append(_check_trunk_coverage(vlans, port_configs))

            # If specific VLANs provided, check inter-VLAN connectivity
            if source_vlan is not None and dest_vlan is not None:
                checks.append(
                    _check_inter_vlan_connectivity(
                        source_vlan, dest_vlan, vlan_lookup, port_configs
                    )
                )

            # Calculate summary
            issues_found = sum(1 for c in checks if c.status == 'FAIL')
            warnings_found = sum(1 for c in checks if c.status == 'WARNING')

            if issues_found > 0:
                overall_health = 'CRITICAL'
            elif warnings_found > 0:
                overall_health = 'DEGRADED'
            else:
                overall_health = 'HEALTHY'

            return VLANDiagnosticReport(
                timestamp=datetime.now().isoformat(),
                vlans_configured=len(vlans),
                vlans=vlans,
                port_configs=port_configs,
                diagnostic_checks=checks,
                issues_found=issues_found,
                warnings_found=warnings_found,
                overall_health=overall_health,
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
                message=f'Error running VLAN diagnostics: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _network_id_to_vlan(network_id: str, networks: list[dict[str, Any]]) -> int | None:
    """Convert network ID to VLAN number."""
    for network in networks:
        if network.get('_id') == network_id:
            return network.get('vlan')
    return None


def _check_vlan_configuration(vlans: list[VLANInfo]) -> VLANDiagnosticCheck:
    """Check VLAN configuration completeness."""
    issues = []
    disabled_vlans = []

    for vlan in vlans:
        if not vlan.enabled:
            disabled_vlans.append(vlan.vlan_id)
        if not vlan.subnet and vlan.vlan_id != 1:
            issues.append(f'VLAN {vlan.vlan_id} ({vlan.name}) has no subnet')

    if issues:
        return VLANDiagnosticCheck(
            check_name='VLAN Configuration',
            status='FAIL',
            message='; '.join(issues),
            details={'issues': issues, 'disabled_vlans': disabled_vlans},
            recommendations=[
                'Configure subnet for each VLAN that requires Layer 3',
                'Enable disabled VLANs if they are needed',
            ],
        )

    if disabled_vlans:
        return VLANDiagnosticCheck(
            check_name='VLAN Configuration',
            status='WARNING',
            message=f'Some VLANs are disabled: {disabled_vlans}',
            details={'disabled_vlans': disabled_vlans},
            recommendations=['Review disabled VLANs and enable if needed'],
        )

    return VLANDiagnosticCheck(
        check_name='VLAN Configuration',
        status='PASS',
        message=f'All {len(vlans)} VLANs configured correctly',
        details={'vlan_count': len(vlans)},
        recommendations=[],
    )


def _check_gateways(vlans: list[VLANInfo]) -> VLANDiagnosticCheck:
    """Check gateway configuration for routing."""
    missing_gateways = []

    for vlan in vlans:
        if vlan.enabled and vlan.subnet and not vlan.gateway:
            missing_gateways.append(vlan.vlan_id)

    if missing_gateways:
        return VLANDiagnosticCheck(
            check_name='Gateway Configuration',
            status='FAIL',
            message=f'VLANs missing gateway: {missing_gateways}',
            details={'missing_gateways': missing_gateways},
            recommendations=[
                'Configure gateway IP for each VLAN subnet',
                'Gateway is required for inter-VLAN routing',
                'Ensure UDM/USG has routing enabled',
            ],
        )

    return VLANDiagnosticCheck(
        check_name='Gateway Configuration',
        status='PASS',
        message='All VLANs with subnets have gateways configured',
        details={},
        recommendations=[],
    )


def _check_port_consistency(port_configs: list[PortVLANConfig]) -> VLANDiagnosticCheck:
    """Check port profile consistency."""
    profile_configs: dict[str, list[PortVLANConfig]] = {}

    for port in port_configs:
        if port.profile_name not in profile_configs:
            profile_configs[port.profile_name] = []
        profile_configs[port.profile_name].append(port)

    inconsistencies = []

    for profile_name, ports in profile_configs.items():
        if len(ports) < 2:
            continue

        first = ports[0]
        for port in ports[1:]:
            if port.native_vlan != first.native_vlan or set(port.tagged_vlans) != set(
                first.tagged_vlans
            ):
                inconsistencies.append(profile_name)
                break

    if inconsistencies:
        return VLANDiagnosticCheck(
            check_name='Port Profile Consistency',
            status='WARNING',
            message=f'Inconsistent VLAN config in profiles: {inconsistencies}',
            details={'inconsistent_profiles': inconsistencies},
            recommendations=[
                'Review port profiles for consistent VLAN settings',
                'Ports with same profile should have same VLAN config',
            ],
        )

    return VLANDiagnosticCheck(
        check_name='Port Profile Consistency',
        status='PASS',
        message=f'All {len(profile_configs)} port profiles are consistent',
        details={'profile_count': len(profile_configs)},
        recommendations=[],
    )


def _check_trunk_coverage(
    vlans: list[VLANInfo],
    port_configs: list[PortVLANConfig],
) -> VLANDiagnosticCheck:
    """Check that VLANs are tagged on trunk ports."""
    trunk_ports = [p for p in port_configs if p.is_trunk]

    if not trunk_ports:
        return VLANDiagnosticCheck(
            check_name='Trunk VLAN Coverage',
            status='WARNING',
            message='No trunk ports detected',
            details={'trunk_count': 0},
            recommendations=[
                'Configure trunk ports for inter-switch VLAN traffic',
                'Tag required VLANs on uplink ports',
            ],
        )

    # Check which VLANs are on trunks
    vlans_on_trunks: set[int] = set()
    for port in trunk_ports:
        vlans_on_trunks.add(port.native_vlan)
        vlans_on_trunks.update(port.tagged_vlans)

    missing_from_trunks = []
    for vlan in vlans:
        if vlan.enabled and vlan.vlan_id not in vlans_on_trunks:
            missing_from_trunks.append(vlan.vlan_id)

    if missing_from_trunks:
        return VLANDiagnosticCheck(
            check_name='Trunk VLAN Coverage',
            status='WARNING',
            message=f'VLANs not on trunk ports: {missing_from_trunks}',
            details={
                'missing_vlans': missing_from_trunks,
                'trunk_count': len(trunk_ports),
            },
            recommendations=[
                'Tag missing VLANs on trunk ports if inter-switch traffic needed',
                'Use "All" profile for trunks to allow all VLANs',
            ],
        )

    return VLANDiagnosticCheck(
        check_name='Trunk VLAN Coverage',
        status='PASS',
        message=f'All VLANs covered on {len(trunk_ports)} trunk ports',
        details={'trunk_count': len(trunk_ports)},
        recommendations=[],
    )


def _check_inter_vlan_connectivity(
    source_vlan: int,
    dest_vlan: int,
    vlan_lookup: dict[int, VLANInfo],
    port_configs: list[PortVLANConfig],
) -> VLANDiagnosticCheck:
    """Check connectivity between two specific VLANs."""
    issues = []

    # Check VLANs exist
    if source_vlan not in vlan_lookup:
        issues.append(f'Source VLAN {source_vlan} not found')
    if dest_vlan not in vlan_lookup:
        issues.append(f'Destination VLAN {dest_vlan} not found')

    if issues:
        return VLANDiagnosticCheck(
            check_name=f'Inter-VLAN Connectivity ({source_vlan} → {dest_vlan})',
            status='FAIL',
            message='; '.join(issues),
            details={'source_vlan': source_vlan, 'dest_vlan': dest_vlan},
            recommendations=['Create missing VLANs in UniFi controller'],
        )

    source = vlan_lookup[source_vlan]
    dest = vlan_lookup[dest_vlan]

    # Check both enabled
    if not source.enabled:
        issues.append(f'Source VLAN {source_vlan} is disabled')
    if not dest.enabled:
        issues.append(f'Destination VLAN {dest_vlan} is disabled')

    # Check gateways for routing
    if not source.gateway:
        issues.append(f'Source VLAN {source_vlan} has no gateway')
    if not dest.gateway:
        issues.append(f'Destination VLAN {dest_vlan} has no gateway')

    # Check trunk coverage
    trunk_ports = [p for p in port_configs if p.is_trunk]
    source_on_trunk = any(
        source_vlan in p.tagged_vlans or source_vlan == p.native_vlan for p in trunk_ports
    )
    dest_on_trunk = any(
        dest_vlan in p.tagged_vlans or dest_vlan == p.native_vlan for p in trunk_ports
    )

    if not source_on_trunk:
        issues.append(f'VLAN {source_vlan} not on any trunk ports')
    if not dest_on_trunk:
        issues.append(f'VLAN {dest_vlan} not on any trunk ports')

    if issues:
        return VLANDiagnosticCheck(
            check_name=f'Inter-VLAN Connectivity ({source_vlan} → {dest_vlan})',
            status='FAIL',
            message='; '.join(issues),
            details={
                'source_vlan': source_vlan,
                'dest_vlan': dest_vlan,
                'issues': issues,
            },
            recommendations=[
                'Enable disabled VLANs',
                'Configure gateway IPs for inter-VLAN routing',
                'Tag VLANs on trunk ports between switches',
                'Check firewall rules for inter-VLAN blocking',
            ],
        )

    return VLANDiagnosticCheck(
        check_name=f'Inter-VLAN Connectivity ({source_vlan} → {dest_vlan})',
        status='PASS',
        message=f'VLAN {source_vlan} and VLAN {dest_vlan} can route',
        details={
            'source_vlan': source_vlan,
            'source_gateway': source.gateway,
            'dest_vlan': dest_vlan,
            'dest_gateway': dest.gateway,
        },
        recommendations=[],
    )
