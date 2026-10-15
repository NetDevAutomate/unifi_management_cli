"""VLAN diagnostics tool for UniFi networks."""

from datetime import datetime
from typing import Any, cast
from unifi_mapper.analysis.link_settings import effective_profile_id, port_override
from unifi_mapper.core.models import (
    PortVLANConfig,
    VLANDiagnosticCheck,
    VLANDiagnosticReport,
    VLANInfo,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


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
            # Get network configuration (VLANs), the switches and the port profiles
            networks = await client.get_networks()
            devices = await client.get_devices()
            profiles = cast(
                list[dict[str, Any]], await client.get(client.build_path('rest/portconf'))
            )
            return diagnose_vlans_from_data(
                networks, devices, profiles, source_vlan=source_vlan, dest_vlan=dest_vlan
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


def diagnose_vlans_from_data(
    networks: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    port_profiles: list[dict[str, Any]] | None,
    *,
    source_vlan: int | None = None,
    dest_vlan: int | None = None,
) -> VLANDiagnosticReport:
    """Build the VLAN diagnostic report from already-fetched records (pure; no I/O).

    Every port of every switch is audited. A port's profile is the one
    ``link_settings.effective_profile_id`` picks (the override's id, else the port table's),
    looked up in ``port_profiles`` (``rest/portconf``); the override's own VLAN settings
    (``native_networkconf_id``, ``tagged_networkconf_ids``, ``excluded_networkconf_ids``,
    ``voice_networkconf_id``, ``forward``, ``tagged_vlan_mgmt``) win over the profile's.
    Trunk-ness is judged by :func:`is_trunk_profile`; ``profile_name`` is the profile's
    name, the raw id only when no profile has it, and ``Default`` when a port has none.

    Args:
        networks: The legacy ``rest/networkconf`` records.
        devices: The ``stat/device`` records.
        port_profiles: The ``rest/portconf`` records (None reads as none).
        source_vlan: With ``dest_vlan``, run the inter-VLAN connectivity check.
        dest_vlan: See ``source_vlan``.
    """
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

    profiles_by_id = {
        str(profile.get('_id')): profile
        for profile in port_profiles or []
        if profile.get('_id') is not None
    }
    all_vlan_ids = set(vlan_lookup)

    # Get port VLAN configurations
    port_configs: list[PortVLANConfig] = []

    for device in devices:
        device_type = device.get('type', '')
        if device_type not in ('usw', 'switch'):
            continue

        dev_id = str(device.get('_id', ''))
        dev_name = str(device.get('name', device.get('mac', 'Unknown')))

        for port_entry in _dict_list(device.get('port_table')):
            port_idx = port_entry.get('port_idx')
            if not isinstance(port_idx, int):
                continue
            profile_id, _source = effective_profile_id(device, port_entry, port_idx)
            profile = profiles_by_id.get(profile_id or '')
            settings = running_vlan_settings(port_entry, profile, port_override(device, port_idx))

            native_vlan = _network_id_to_vlan(settings.get('native_networkconf_id'), networks)
            tagged_vlans = _tagged_vlans(settings, networks, all_vlan_ids)
            if profile is not None:
                profile_name = str(profile.get('name') or profile_id)
            else:
                profile_name = profile_id or 'Default'

            port_configs.append(
                PortVLANConfig(
                    device_id=dev_id,
                    device_name=dev_name,
                    port_idx=port_idx,
                    port_name=port_entry.get('name', '') or f'Port {port_idx}',
                    native_vlan=native_vlan if isinstance(native_vlan, int) else 1,
                    tagged_vlans=sorted(tagged_vlans),
                    profile_name=profile_name,
                    # One rule for every analysis (issue 089); it reads every field that
                    # puts a VLAN in tagged_vlans, so a port tagging one is a trunk
                    is_trunk=is_trunk_profile(settings),
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
            _check_inter_vlan_connectivity(source_vlan, dest_vlan, vlan_lookup, port_configs)
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


#: VLAN-list keys a hand-built port record (a planned uplink, a test fixture) can carry in
#: place of the controller's ``forward`` / ``tagged_vlan_mgmt``. ``vlan_coverage`` reads the
#: VLANs from them; :func:`is_trunk_profile` reads their presence.
VLAN_LIST_KEYS = (
    'allowed_vlans',
    'allowed_vlan_ids',
    'tagged_vlans',
    'tagged_vlan_ids',
    'trunk_vlans',
    'vlan_ids',
    'native_vlan',
    'native_vlan_id',
    'untagged_vlan',
    'vlan',
)

#: The port settings a profile (and an override on top of it) decides, so the switch runs
#: them from there, not from the port table's copies (issue 089: on a live controller 100 port
#: table entries said ``forward: 'all'`` under access profiles).
PROFILE_VLAN_FIELDS = (
    'forward',
    'tagged_vlan_mgmt',
    'native_networkconf_id',
    'tagged_networkconf_ids',
    'excluded_networkconf_ids',
    'voice_networkconf_id',
)


def running_vlan_settings(
    port_entry: dict[str, Any],
    profile: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    """The VLAN settings a port runs: profile, then override; the row only when no profile applies.

    A port with a profile runs the profile's VLAN fields with the override's on top, and the
    port table row's own copies are ignored: a live controller reports ``forward: 'all'`` on
    rows under access profiles. A port with NO profile has no other source of its running mode,
    so its row's :data:`PROFILE_VLAN_FIELDS` are the base and the override, if any, sits on top
    (issue 097). Every analysis that judges a port's VLANs reads this one function, so they
    agree (issue 089).
    """
    settings: dict[str, Any] = {}
    if profile is None:
        settings.update({k: port_entry[k] for k in PROFILE_VLAN_FIELDS if k in port_entry})
    else:
        settings.update(profile)
    settings.update(override or {})
    return settings


def is_trunk_profile(settings: dict[str, Any]) -> bool:
    """Whether a port's settings make it a trunk: the one rule every analysis uses (issue 089).

    ``settings`` is the port's profile with its override on top (``link_settings``), and, for
    a hand-built port record, the record itself. In order:

    1. An explicit flag: ``is_trunk`` / ``trunk`` true is a trunk; ``is_access`` / ``access``
       true is not.
    2. The controller's fields, as :func:`_tagged_vlans` reads them: ``forward: 'all'``
       carries every VLAN unless ``tagged_vlan_mgmt`` is ``block_all``; a port that lists
       ``tagged_networkconf_ids`` tags them unless ``block_all``; a ``voice_networkconf_id``
       is always tagged.
    3. A profile name (``portconf_name``, ``profile_name`` or ``name``) that says ``trunk``
       is taken at its word.
    4. With a ``forward``, nothing else makes a trunk. Without one (a record with none of the
       controller's fields): a name that says ``access`` or ``client`` is not a trunk, and
       one that lists VLANs (:data:`VLAN_LIST_KEYS`) is.

    A raw profile id can say none of this, which is what issue 030 was about.
    """
    if _first_flag(settings, ('is_trunk', 'trunk')) is True:
        return True
    if _first_flag(settings, ('is_access', 'access')) is True:
        return False
    forward = str(settings.get('forward') or '').lower()
    mgmt = str(settings.get('tagged_vlan_mgmt') or '').lower()
    if forward == 'all' and mgmt != 'block_all':
        return True
    if _str_list(settings.get('tagged_networkconf_ids')) and mgmt != 'block_all':
        return True
    if settings.get('voice_networkconf_id'):
        return True
    name = str(
        settings.get('portconf_name') or settings.get('profile_name') or settings.get('name') or ''
    ).lower()
    if 'trunk' in name:
        return True
    if forward:
        return False
    if 'access' in name or 'client' in name:
        return False
    return any(settings.get(key) is not None for key in VLAN_LIST_KEYS)


def _first_flag(settings: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    """The first of ``keys`` present in ``settings``, read as a boolean (``'false'`` is false)."""
    for key in keys:
        if key in settings:
            value = settings[key]
            if isinstance(value, str):
                return value.strip().lower() not in ('', '0', 'false', 'no', 'off')
            return bool(value)
    return None


def _tagged_vlans(
    settings: dict[str, Any], networks: list[dict[str, Any]], all_vlan_ids: set[int]
) -> set[int]:
    """The VLANs a port tags: every one but the excluded on ``auto``, the listed on custom."""
    tagged: set[int] = set()
    forward = str(settings.get('forward') or '').lower()
    mgmt = str(settings.get('tagged_vlan_mgmt') or '').lower()
    if forward == 'all' and mgmt != 'block_all':
        tagged.update(all_vlan_ids)
        for network_id in _str_list(settings.get('excluded_networkconf_ids')):
            excluded = _network_id_to_vlan(network_id, networks)
            if excluded is not None:
                tagged.discard(excluded)
    elif mgmt != 'block_all':
        for network_id in _str_list(settings.get('tagged_networkconf_ids')):
            vlan = _network_id_to_vlan(network_id, networks)
            if vlan is not None:
                tagged.add(vlan)
    voice_vlan = _network_id_to_vlan(settings.get('voice_networkconf_id'), networks)
    if voice_vlan is not None:
        tagged.add(voice_vlan)
    native = _network_id_to_vlan(settings.get('native_networkconf_id'), networks)
    tagged.discard(native if isinstance(native, int) else 1)
    return tagged


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    values = cast(list[Any], value)
    return [cast(dict[str, Any], item) for item in values if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    values = cast(list[Any], value)
    return [str(item) for item in values if item]


def _network_id_to_vlan(network_id: Any, networks: list[dict[str, Any]]) -> int | None:
    """Convert network ID to VLAN number."""
    if not network_id:
        return None
    for network in networks:
        if network.get('_id') == network_id:
            vlan = network.get('vlan')
            return int(vlan) if isinstance(vlan, int) else None
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
