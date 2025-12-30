"""Firmware security advisor tool for UniFi networks."""

import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from unifi_mcp.models import (
    DeviceFirmwareInfo,
    FirmwareRecommendation,
    FirmwareSecurityReport,
    FirmwareStatus,
    KnownVulnerability,
    UpdatePriority,
)
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


# Known latest firmware versions by device model
# These should be updated regularly from UniFi release notes
KNOWN_LATEST_VERSIONS: dict[str, str] = {
    # UniFi Switches Gen1
    'US-8': '6.6.65',
    'US-8-60W': '6.6.65',
    'US-8-150W': '6.6.65',
    'US-16-150W': '6.6.65',
    'US-24': '6.6.65',
    'US-24-250W': '6.6.65',
    'US-24-500W': '6.6.65',
    'US-48': '6.6.65',
    'US-48-500W': '6.6.65',
    'US-48-750W': '6.6.65',
    # UniFi Switches Gen2
    'USW-Flex': '6.6.65',
    'USW-Flex-Mini': '2.2.5',
    'USW-Lite-8-PoE': '6.6.65',
    'USW-Lite-16-PoE': '6.6.65',
    'USW-Pro-24': '6.6.65',
    'USW-Pro-24-PoE': '6.6.65',
    'USW-Pro-48': '6.6.65',
    'USW-Pro-48-PoE': '6.6.65',
    'USW-Pro-Max-24': '6.6.65',
    'USW-Pro-Max-48': '6.6.65',
    # Enterprise Switches
    'USW-Enterprise-8-PoE': '6.6.65',
    'USW-Enterprise-24-PoE': '6.6.65',
    'USW-Enterprise-48-PoE': '6.6.65',
    'USW-Aggregation': '6.6.65',
    'USW-Pro-Aggregation': '6.6.65',
    # Dream Machines
    'UDM': '4.0.6',
    'UDM-Pro': '4.0.6',
    'UDM-SE': '4.0.6',
    'UDR': '4.0.6',
    'UDW': '4.0.6',
    # Gateways
    'USG': '4.4.57',
    'USG-Pro-4': '4.4.57',
    'USG-XG-8': '4.4.57',
    'UXG-Pro': '4.0.6',
    'UXG-Lite': '4.0.6',
    # WiFi 6 Access Points
    'U6-Lite': '6.6.77',
    'U6-LR': '6.6.77',
    'U6-Pro': '6.6.77',
    'U6-Enterprise': '6.6.77',
    'U6-Mesh': '6.6.77',
    'U6+': '6.6.77',
    # WiFi 5 Access Points
    'UAP-AC-Pro': '6.6.77',
    'UAP-AC-Lite': '6.6.77',
    'UAP-AC-LR': '6.6.77',
    'UAP-AC-HD': '6.6.77',
    'UAP-nanoHD': '6.6.77',
    'UAP-FlexHD': '6.6.77',
}

# Device families for consistency checking
DEVICE_FAMILIES: dict[str, list[str]] = {
    'switches_gen1': ['US-8', 'US-16-150W', 'US-24', 'US-48'],
    'switches_gen2_lite': ['USW-Lite-8-PoE', 'USW-Lite-16-PoE'],
    'switches_gen2_pro': ['USW-Pro-24', 'USW-Pro-48', 'USW-Pro-24-PoE', 'USW-Pro-48-PoE'],
    'switches_enterprise': [
        'USW-Enterprise-8-PoE',
        'USW-Enterprise-24-PoE',
        'USW-Enterprise-48-PoE',
    ],
    'dream_machines': ['UDM', 'UDM-Pro', 'UDM-SE', 'UDR'],
    'gateways': ['USG', 'USG-Pro-4', 'UXG-Pro'],
    'ap_wifi6': ['U6-Lite', 'U6-LR', 'U6-Pro', 'U6-Enterprise', 'U6-Mesh'],
    'ap_wifi5': ['UAP-AC-Pro', 'UAP-AC-Lite', 'UAP-AC-LR', 'UAP-AC-HD', 'UAP-nanoHD'],
}

# End-of-life devices that no longer receive updates
EOL_DEVICES: list[str] = [
    'UAP',
    'UAP-LR',
    'UAP-Outdoor',
    'UAP-Outdoor+',
    'US-8-60W-BETA',
]

# Known vulnerabilities (example - should be updated from security advisories)
KNOWN_VULNERABILITIES: list[KnownVulnerability] = [
    KnownVulnerability(
        cve_id='CVE-2024-42025',
        severity='high',
        description='Command injection vulnerability in UniFi OS',
        affected_versions=['3.*', '2.*'],
        fixed_version='4.0.0',
        disclosure_date='2024-08-01',
        references=['https://community.ui.com/releases'],
    ),
]


async def get_firmware_report(
    device_id: str | None = None,
) -> FirmwareSecurityReport:
    """Analyze firmware status across all network devices.

    When to use this tool:
    - During security audits to assess firmware exposure
    - When planning maintenance windows for updates
    - After security advisories are released
    - To ensure consistency across device families
    - When onboarding new equipment

    How firmware analysis works:
    - Compares installed firmware against known latest versions
    - Checks for known security vulnerabilities by version
    - Identifies end-of-life devices requiring replacement
    - Tracks version consistency within device families
    - Generates prioritized upgrade recommendations

    Types of issues detected:
    - Devices running outdated firmware
    - Critical security vulnerabilities
    - End-of-life devices without security updates
    - Version inconsistency across same device family
    - Devices with auto-upgrade disabled

    Common workflow:
    1. get_firmware_report() - assess firmware security
    2. Review devices with CRITICAL or HIGH priority
    3. Schedule maintenance window for updates
    4. Update highest priority devices first
    5. Re-run report to verify updates

    What to do next:
    - If critical vulnerabilities: Update immediately
    - If EOL devices: Plan hardware replacement
    - If version mismatch in family: Standardize versions
    - If auto-upgrade disabled: Consider enabling or schedule updates

    Args:
        device_id: Optional device ID to check. If None, checks all devices.

    Returns:
        FirmwareSecurityReport with device status and recommendations

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            devices_checked = 0
            device_infos: list[DeviceFirmwareInfo] = []
            recommendations: list[FirmwareRecommendation] = []

            # Tracking for statistics
            current_count = 0
            update_available_count = 0
            security_update_count = 0
            critical_count = 0
            eol_count = 0

            critical_priority = 0
            high_priority = 0
            medium_priority = 0

            total_vulnerabilities = 0
            critical_vulnerabilities = 0

            # Family version tracking
            family_versions: dict[str, set[str]] = defaultdict(set)

            for device in devices:
                # Filter to specific device if requested
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                devices_checked += 1
                device_info = _analyze_device(device)
                device_infos.append(device_info)

                # Update status counts
                if device_info.status == FirmwareStatus.CURRENT:
                    current_count += 1
                elif device_info.status == FirmwareStatus.UPDATE_AVAILABLE:
                    update_available_count += 1
                elif device_info.status == FirmwareStatus.SECURITY_UPDATE:
                    security_update_count += 1
                elif device_info.status == FirmwareStatus.CRITICAL:
                    critical_count += 1
                elif device_info.status == FirmwareStatus.EOL:
                    eol_count += 1

                # Update priority counts
                if device_info.update_priority == UpdatePriority.CRITICAL:
                    critical_priority += 1
                elif device_info.update_priority == UpdatePriority.HIGH:
                    high_priority += 1
                elif device_info.update_priority == UpdatePriority.MEDIUM:
                    medium_priority += 1

                # Track vulnerabilities
                total_vulnerabilities += len(device_info.vulnerabilities)
                critical_vulnerabilities += sum(
                    1 for v in device_info.vulnerabilities if v.severity == 'critical'
                )

                # Track family versions
                if device_info.family:
                    family_versions[device_info.family].add(device_info.current_version)

                # Check if specific device was found
                if device_id and devices_checked > 0:
                    break

            # Handle device not found
            if device_id and devices_checked == 0:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_network_topology'],
                )

            # Check family consistency
            inconsistent_families: list[str] = []
            for family, versions in family_versions.items():
                if len(versions) > 1:
                    inconsistent_families.append(family)
                    # Mark devices with mismatched versions
                    for info in device_infos:
                        if info.family == family:
                            info.family_version_mismatch = True

            # Generate recommendations
            recommendations = _generate_recommendations(device_infos, inconsistent_families)

            # Calculate security score
            security_score = _calculate_security_score(
                devices_checked=devices_checked,
                critical_count=critical_count,
                security_update_count=security_update_count,
                update_available_count=update_available_count,
                eol_count=eol_count,
                critical_vulnerabilities=critical_vulnerabilities,
                inconsistent_families=len(inconsistent_families),
            )

            return FirmwareSecurityReport(
                timestamp=datetime.now().isoformat(),
                devices_checked=devices_checked,
                security_score=security_score,
                current_count=current_count,
                update_available_count=update_available_count,
                security_update_count=security_update_count,
                critical_count=critical_count,
                eol_count=eol_count,
                critical_priority=critical_priority,
                high_priority=high_priority,
                medium_priority=medium_priority,
                total_vulnerabilities=total_vulnerabilities,
                critical_vulnerabilities=critical_vulnerabilities,
                devices=device_infos,
                inconsistent_families=inconsistent_families,
                recommendations=recommendations,
                network_healthy=critical_count == 0 and eol_count == 0,
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
                message=f'Error analyzing firmware: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _analyze_device(device: dict[str, Any]) -> DeviceFirmwareInfo:
    """Analyze firmware status for a single device."""
    device_id = device.get('_id', '')
    model = device.get('model', 'Unknown')
    device_name = device.get('name', model)
    device_type = device.get('type', 'unknown')
    current_version = device.get('version', '')

    # Get latest known version
    latest_version = KNOWN_LATEST_VERSIONS.get(model, '')

    # Get device family
    family = _get_device_family(model)

    # Create firmware info
    info = DeviceFirmwareInfo(
        device_id=device_id,
        device_name=device_name,
        model=model,
        device_type=device_type,
        current_version=current_version,
        latest_version=latest_version,
        family=family,
        uptime_days=int(device.get('uptime', 0) / 86400),
        auto_upgrade_enabled=device.get('auto_upgrade', False),
    )

    # Check EOL status
    if model in EOL_DEVICES:
        info.status = FirmwareStatus.EOL
        info.update_priority = UpdatePriority.HIGH
        info.needs_update = True
        return info

    # Check for vulnerabilities
    vulnerabilities = _check_vulnerabilities(current_version)
    info.vulnerabilities = vulnerabilities
    info.has_critical_vulns = any(v.severity == 'critical' for v in vulnerabilities)

    # Determine status
    if not latest_version:
        info.status = FirmwareStatus.UNKNOWN
        info.update_priority = UpdatePriority.NONE
    else:
        version_cmp = _compare_versions(current_version, latest_version)

        if version_cmp >= 0:
            # Current or newer
            info.status = FirmwareStatus.CURRENT
            info.update_priority = UpdatePriority.NONE
        elif vulnerabilities:
            # Has known vulnerabilities
            if info.has_critical_vulns:
                info.status = FirmwareStatus.CRITICAL
                info.update_priority = UpdatePriority.CRITICAL
                info.needs_update = True
            else:
                info.status = FirmwareStatus.SECURITY_UPDATE
                info.update_priority = UpdatePriority.HIGH
                info.needs_update = True
        else:
            # Just needs regular update
            info.status = FirmwareStatus.UPDATE_AVAILABLE
            info.update_priority = UpdatePriority.MEDIUM
            info.needs_update = True

    return info


def _get_device_family(model: str) -> str:
    """Get the device family for a model."""
    for family, models in DEVICE_FAMILIES.items():
        if model in models:
            return family
    return ''


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple."""
    if not version_str:
        return (0,)

    match = re.search(r'(\d+(?:\.\d+)*)', version_str)
    if match:
        parts = match.group(1).split('.')
        return tuple(int(p) for p in parts)
    return (0,)


def _compare_versions(current: str, latest: str) -> int:
    """Compare two versions. Returns -1 if current < latest, 0 if equal, 1 if greater."""
    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest)

    # Pad to same length
    max_len = max(len(current_parts), len(latest_parts))
    current_parts = current_parts + (0,) * (max_len - len(current_parts))
    latest_parts = latest_parts + (0,) * (max_len - len(latest_parts))

    if current_parts < latest_parts:
        return -1
    elif current_parts > latest_parts:
        return 1
    return 0


def _version_matches_pattern(version: str, pattern: str) -> bool:
    """Check if version matches a pattern (e.g., '6.5.*')."""
    pattern_regex = pattern.replace('.', r'\.').replace('*', r'.*')
    return bool(re.match(f'^{pattern_regex}$', version))


def _check_vulnerabilities(version: str) -> list[KnownVulnerability]:
    """Check version against known vulnerabilities."""
    affected: list[KnownVulnerability] = []
    for vuln in KNOWN_VULNERABILITIES:
        for pattern in vuln.affected_versions:
            if _version_matches_pattern(version, pattern):
                # Also check if it's been fixed
                if _compare_versions(version, vuln.fixed_version) < 0:
                    affected.append(vuln)
                break
    return affected


def _calculate_security_score(
    devices_checked: int,
    critical_count: int,
    security_update_count: int,
    update_available_count: int,
    eol_count: int,
    critical_vulnerabilities: int,
    inconsistent_families: int,
) -> int:
    """Calculate overall security score (0-100)."""
    if devices_checked == 0:
        return 100

    score = 100

    # Deduct for critical issues
    score -= critical_count * 20
    score -= security_update_count * 10
    score -= update_available_count * 5
    score -= eol_count * 15
    score -= critical_vulnerabilities * 15

    # Deduct for inconsistency
    score -= inconsistent_families * 5

    return max(0, min(100, score))


def _generate_recommendations(
    devices: list[DeviceFirmwareInfo],
    inconsistent_families: list[str],
) -> list[FirmwareRecommendation]:
    """Generate prioritized recommendations."""
    recommendations: list[FirmwareRecommendation] = []

    # Critical priority - devices with critical vulnerabilities
    for device in devices:
        if device.status == FirmwareStatus.CRITICAL:
            recommendations.append(
                FirmwareRecommendation(
                    priority='critical',
                    message=f'{device.device_name} has critical vulnerabilities',
                    device_name=device.device_name,
                    action=f'Upgrade from {device.current_version} to {device.latest_version} immediately',
                )
            )

    # High priority - EOL devices
    for device in devices:
        if device.status == FirmwareStatus.EOL:
            recommendations.append(
                FirmwareRecommendation(
                    priority='high',
                    message=f'{device.device_name} ({device.model}) is end-of-life',
                    device_name=device.device_name,
                    action='Plan hardware replacement - device no longer receives security updates',
                )
            )

    # High priority - security updates
    for device in devices:
        if device.status == FirmwareStatus.SECURITY_UPDATE:
            recommendations.append(
                FirmwareRecommendation(
                    priority='high',
                    message=f'{device.device_name} needs security update',
                    device_name=device.device_name,
                    action=f'Upgrade from {device.current_version} to {device.latest_version}',
                )
            )

    # Medium priority - family inconsistency
    for family in inconsistent_families:
        recommendations.append(
            FirmwareRecommendation(
                priority='medium',
                message=f'Inconsistent firmware versions in {family} device family',
                action='Standardize firmware versions across device family for consistency',
            )
        )

    # Low priority - regular updates
    for device in devices:
        if device.status == FirmwareStatus.UPDATE_AVAILABLE:
            recommendations.append(
                FirmwareRecommendation(
                    priority='low',
                    message=f'{device.device_name} has update available',
                    device_name=device.device_name,
                    action=f'Upgrade from {device.current_version} to {device.latest_version} at convenience',
                )
            )

    # Info - auto-upgrade disabled
    devices_need_update = [d for d in devices if d.needs_update and not d.auto_upgrade_enabled]
    if devices_need_update:
        recommendations.append(
            FirmwareRecommendation(
                priority='info',
                message=f'{len(devices_need_update)} devices need updates but have auto-upgrade disabled',
                action='Consider enabling auto-upgrade or schedule maintenance window',
            )
        )

    if not recommendations:
        recommendations.append(
            FirmwareRecommendation(
                priority='info',
                message='All devices are running current firmware',
                action='No action required - continue monitoring',
            )
        )

    return recommendations
