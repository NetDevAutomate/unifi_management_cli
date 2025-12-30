"""Security audit diagnostic tool for detecting unauthorized devices and anomalies."""

import re
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


class SecurityDevice(BaseModel):
    """Security information for a network device."""

    mac: str = Field(description='Device MAC address')
    name: str = Field(description='Device name/hostname')
    ip: Optional[str] = Field(description='Device IP address')
    type: str = Field(description='Device type: infrastructure, client, or unknown')
    vendor: Optional[str] = Field(description='Device vendor from OUI lookup')
    first_seen: Optional[str] = Field(description='When device was first detected')
    last_seen: Optional[str] = Field(description='When device was last active')

    # Security flags
    is_authorized: Optional[bool] = Field(description='Whether device is explicitly authorized')
    is_anomalous: bool = Field(description='Whether device exhibits anomalous behavior')
    security_flags: List[str] = Field(description='Security concerns and flags')
    risk_level: str = Field(description='Risk level: low, medium, high, critical')


class VLANSecurityInfo(BaseModel):
    """VLAN security analysis."""

    vlan_id: int = Field(description='VLAN ID')
    name: str = Field(description='VLAN name')
    devices_count: int = Field(description='Number of devices in this VLAN')
    isolation_violations: List[str] = Field(description='VLAN isolation violations')
    unauthorized_devices: List[str] = Field(description='Unauthorized devices in this VLAN')


class SecurityAuditReport(BaseModel):
    """Comprehensive network security audit report."""

    timestamp: str = Field(description='When the security audit was performed')

    # Device security summary
    total_devices: int = Field(description='Total devices analyzed')
    authorized_devices: int = Field(description='Number of authorized devices')
    unauthorized_devices: int = Field(description='Number of unauthorized devices')
    anomalous_devices: int = Field(description='Number of anomalous devices')
    unknown_devices: int = Field(description='Number of unknown/unidentified devices')

    # Security findings
    critical_risks: List[SecurityDevice] = Field(
        description='Devices with critical security risks'
    )
    high_risks: List[SecurityDevice] = Field(description='Devices with high security risks')
    medium_risks: List[SecurityDevice] = Field(description='Devices with medium security risks')

    # Specific security issues
    mac_anomalies: List[str] = Field(description='MAC address anomalies detected')
    new_devices: List[SecurityDevice] = Field(description='Recently appeared devices (last 24h)')
    rogue_aps: List[SecurityDevice] = Field(description='Potential rogue access points')
    guest_violations: List[SecurityDevice] = Field(description='Guest network violations')

    # VLAN security
    vlan_analysis: List[VLANSecurityInfo] = Field(description='VLAN security analysis')

    # Recommendations
    immediate_actions: List[str] = Field(description='Immediate security actions required')
    security_recommendations: List[str] = Field(description='General security recommendations')


async def security_audit() -> SecurityAuditReport:
    """Perform comprehensive network security audit to detect threats and anomalies.

    When to use this tool:
    - Regular security audits and compliance checks
    - When unauthorized network access is suspected
    - After detecting unusual network activity
    - Before and after major network changes
    - As part of incident response procedures

    Common workflow:
    1. Run security_audit() to identify security risks
    2. Focus on critical_risks and immediate_actions first
    3. Use find_device() to investigate suspicious devices in detail
    4. Use connectivity_analysis() to understand how threats accessed network
    5. Use network_topology() to assess potential impact scope

    What to do next:
    - If critical_risks found: Isolate or remove devices immediately
    - If rogue_aps detected: Locate and eliminate unauthorized access points
    - If new_devices: Verify legitimacy and authorize or block
    - If vlan_violations: Review and correct VLAN configurations
    - Document findings and update security policies

    Returns:
        SecurityAuditReport with detailed security analysis and immediate actions

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        try:
            # Get comprehensive network data
            devices_data = await client.get(client.build_path('stat/device'))
            clients_data = await client.get(client.build_path('stat/sta'))
            rogue_aps = await client.get(client.build_path('rest/rogueap'))

            # Get VLAN configuration if available
            try:
                networks_data = await client.get(client.build_path('rest/networkconf'))
            except Exception:
                networks_data = []

            # Perform security analysis
            return _perform_security_analysis(devices_data, clients_data, rogue_aps, networks_data)

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller for security audit',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                    related_tools=['network_health_check', 'find_device'],
                )
            raise ToolError(
                message=f'Error performing security audit: {str(e)}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and permissions for security data access',
                related_tools=['find_device', 'connectivity_analysis'],
            )


def _perform_security_analysis(
    devices_data: List[Dict[str, Any]],
    clients_data: List[Dict[str, Any]],
    rogue_aps: List[Dict[str, Any]],
    networks_data: List[Dict[str, Any]],
) -> SecurityAuditReport:
    """Perform comprehensive security analysis on network data."""
    security_devices = []
    mac_anomalies = []
    new_devices = []
    rogue_ap_devices = []
    guest_violations = []

    # Current time for "new device" detection (last 24 hours)
    current_time = datetime.now()
    day_ago = current_time - timedelta(days=1)

    # Analyze infrastructure devices
    for device_data in devices_data:
        security_device = _analyze_device_security(device_data, 'infrastructure')
        security_devices.append(security_device)

        # Check for recent devices
        if device_data.get('first_seen'):
            first_seen = datetime.fromtimestamp(device_data.get('first_seen', 0))
            if first_seen > day_ago:
                new_devices.append(security_device)

    # Analyze client devices
    for client_data in clients_data:
        security_device = _analyze_device_security(client_data, 'client')
        security_devices.append(security_device)

        # Check for recent clients
        if client_data.get('first_seen'):
            first_seen = datetime.fromtimestamp(client_data.get('first_seen', 0))
            if first_seen > day_ago:
                new_devices.append(security_device)

        # Check for guest network violations
        if _is_guest_violation(client_data):
            guest_violations.append(security_device)

    # Analyze rogue APs
    for rogue_data in rogue_aps:
        rogue_device = _analyze_rogue_ap(rogue_data)
        rogue_ap_devices.append(rogue_device)
        security_devices.append(rogue_device)

    # Check for MAC address anomalies
    mac_anomalies = _detect_mac_anomalies([d.mac for d in security_devices])

    # Analyze VLAN security
    vlan_analysis = _analyze_vlan_security(clients_data, networks_data)

    # Categorize devices by risk level
    critical_risks = [d for d in security_devices if d.risk_level == 'critical']
    high_risks = [d for d in security_devices if d.risk_level == 'high']
    medium_risks = [d for d in security_devices if d.risk_level == 'medium']

    # Count authorized vs unauthorized
    authorized_count = len([d for d in security_devices if d.is_authorized])
    unauthorized_count = len([d for d in security_devices if d.is_authorized is False])
    anomalous_count = len([d for d in security_devices if d.is_anomalous])
    unknown_count = len([d for d in security_devices if d.is_authorized is None])

    # Generate immediate actions and recommendations
    immediate_actions, recommendations = _generate_security_recommendations(
        critical_risks, high_risks, rogue_ap_devices, new_devices, mac_anomalies
    )

    return SecurityAuditReport(
        timestamp=current_time.isoformat(),
        total_devices=len(security_devices),
        authorized_devices=authorized_count,
        unauthorized_devices=unauthorized_count,
        anomalous_devices=anomalous_count,
        unknown_devices=unknown_count,
        critical_risks=critical_risks,
        high_risks=high_risks,
        medium_risks=medium_risks,
        mac_anomalies=mac_anomalies,
        new_devices=new_devices,
        rogue_aps=rogue_ap_devices,
        guest_violations=guest_violations,
        vlan_analysis=vlan_analysis,
        immediate_actions=immediate_actions,
        security_recommendations=recommendations,
    )


def _analyze_device_security(device_data: Dict[str, Any], device_type: str) -> SecurityDevice:
    """Analyze security characteristics of a single device."""
    mac = device_data.get('mac', '')
    name = (
        device_data.get('name')
        or device_data.get('hostname')
        or device_data.get('display_name')
        or 'Unknown'
    )
    ip = device_data.get('ip')
    vendor = device_data.get('oui', 'Unknown')

    security_flags = []
    risk_level = 'low'
    is_anomalous = False
    is_authorized = None  # None = unknown, True = authorized, False = unauthorized

    # Check for suspicious characteristics

    # Suspicious naming patterns
    suspicious_names = ['unknown', 'android', 'iphone', 'samsung', 'lg', 'sony']
    if any(sus in name.lower() for sus in suspicious_names) and device_type == 'infrastructure':
        security_flags.append('Infrastructure device with suspicious generic name')
        risk_level = 'medium'
        is_anomalous = True

    # MAC address analysis
    if _is_suspicious_mac(mac):
        security_flags.append('Suspicious MAC address pattern')
        risk_level = 'high'
        is_anomalous = True

    # Check for randomized MAC (common privacy feature, but worth noting)
    if _is_randomized_mac(mac):
        security_flags.append('Possible randomized MAC address')
        # Not necessarily high risk, many legitimate devices do this

    # Device type inconsistencies
    if device_type == 'client':
        # Check if client is behaving like infrastructure
        if device_data.get('tx_bytes', 0) > 1000000000:  # 1GB+ transmitted
            security_flags.append('Client device with unusually high traffic volume')
            risk_level = 'medium'
            is_anomalous = True

    # Check adoption status for infrastructure
    if device_type == 'infrastructure':
        if not device_data.get('adopted', False):
            security_flags.append('Infrastructure device not adopted')
            risk_level = 'high'
            is_authorized = False
        else:
            is_authorized = True

    # Check for devices with no recent activity
    last_seen_timestamp = device_data.get('last_seen', 0)
    if last_seen_timestamp:
        last_seen = datetime.fromtimestamp(last_seen_timestamp)
        if datetime.now() - last_seen > timedelta(hours=24):
            security_flags.append('Device has been inactive for >24 hours')

    # Check for unusual vendor patterns
    if vendor and _is_suspicious_vendor(vendor):
        security_flags.append(f'Device from security-sensitive vendor: {vendor}')
        risk_level = 'medium'

    # Convert timestamps
    first_seen = None
    last_seen = None
    if device_data.get('first_seen'):
        first_seen = datetime.fromtimestamp(device_data['first_seen']).isoformat()
    if device_data.get('last_seen'):
        last_seen = datetime.fromtimestamp(device_data['last_seen']).isoformat()

    # Final risk assessment
    if len(security_flags) >= 3:
        risk_level = 'critical'
    elif len(security_flags) >= 2:
        risk_level = 'high'
    elif len(security_flags) >= 1:
        risk_level = 'medium'

    return SecurityDevice(
        mac=mac,
        name=name,
        ip=ip,
        type=device_type,
        vendor=vendor,
        first_seen=first_seen,
        last_seen=last_seen,
        is_authorized=is_authorized,
        is_anomalous=is_anomalous,
        security_flags=security_flags,
        risk_level=risk_level,
    )


def _analyze_rogue_ap(rogue_data: Dict[str, Any]) -> SecurityDevice:
    """Analyze rogue access point security threat."""
    mac = rogue_data.get('bssid', '')
    name = rogue_data.get('essid', 'Rogue AP')

    security_flags = [
        'Rogue access point detected',
        'Potential security threat - unauthorized wireless access',
    ]

    # Check signal strength - closer rogues are more dangerous
    signal = rogue_data.get('signal', -100)
    if signal > -50:
        security_flags.append('Strong signal - rogue AP is very close')
    elif signal > -70:
        security_flags.append('Medium signal - rogue AP in vicinity')

    return SecurityDevice(
        mac=mac,
        name=name,
        ip=None,
        type='rogue_ap',
        vendor='Unknown',
        first_seen=None,
        last_seen=None,
        is_authorized=False,
        is_anomalous=True,
        security_flags=security_flags,
        risk_level='critical',
    )


def _is_suspicious_mac(mac: str) -> bool:
    """Check if MAC address has suspicious patterns."""
    if not mac:
        return True

    # Check for obviously fake MACs
    suspicious_patterns = [
        '00:00:00:00:00:00',  # All zeros
        'ff:ff:ff:ff:ff:ff',  # All ones
        '11:11:11:11:11:11',  # Repeating pattern
        '12:34:56:78:9a:bc',  # Sequential pattern
    ]

    return mac.lower() in suspicious_patterns


def _is_randomized_mac(mac: str) -> bool:
    """Check if MAC appears to be randomized (privacy feature)."""
    if not mac or len(mac) < 2:
        return False

    # Randomized MACs often have locally administered bit set (2nd bit of 1st octet)
    first_octet = mac.split(':')[0] if ':' in mac else mac.split('-')[0]
    try:
        octet_int = int(first_octet, 16)
        return bool(octet_int & 0x02)  # Check locally administered bit
    except ValueError:
        return False


def _is_suspicious_vendor(vendor: str) -> bool:
    """Check if vendor is associated with security tools or unknown origins."""
    if not vendor:
        return True

    suspicious_vendors = [
        'Unknown',
        'Private',
        'Espressif',  # Common in IoT/hacking devices
        'Realtek',
        'Ralink',  # Sometimes used in cheap penetration testing tools
    ]

    return any(sus.lower() in vendor.lower() for sus in suspicious_vendors)


def _is_guest_violation(client_data: Dict[str, Any]) -> bool:
    """Check if client is violating guest network policies."""
    # This is a simplified check - in practice would check against
    # guest network VLAN/SSID configurations

    # Check if device is on guest network but has been connected too long
    if client_data.get('network', '').lower() == 'guest':
        uptime = client_data.get('uptime', 0)
        if uptime > 86400:  # More than 24 hours
            return True

    return False


def _detect_mac_anomalies(mac_addresses: List[str]) -> List[str]:
    """Detect MAC address anomalies across all devices."""
    anomalies = []

    # Check for duplicate MACs (should never happen with valid devices)
    mac_counts = {}
    for mac in mac_addresses:
        if mac:
            mac_counts[mac] = mac_counts.get(mac, 0) + 1

    for mac, count in mac_counts.items():
        if count > 1:
            anomalies.append(f'Duplicate MAC address detected: {mac} (appears {count} times)')

    # Check for MAC addresses that are too similar (potential spoofing)
    sorted_macs = sorted([m for m in mac_addresses if m])
    for i in range(len(sorted_macs) - 1):
        mac1, mac2 = sorted_macs[i], sorted_macs[i + 1]
        if _macs_too_similar(mac1, mac2):
            anomalies.append(f'Suspiciously similar MACs: {mac1} and {mac2}')

    return anomalies


def _macs_too_similar(mac1: str, mac2: str) -> bool:
    """Check if two MAC addresses are suspiciously similar."""
    if not mac1 or not mac2:
        return False

    # Remove separators and compare
    clean_mac1 = re.sub(r'[:\-]', '', mac1.lower())
    clean_mac2 = re.sub(r'[:\-]', '', mac2.lower())

    if len(clean_mac1) != 12 or len(clean_mac2) != 12:
        return False

    # Count differing characters
    differences = sum(1 for a, b in zip(clean_mac1, clean_mac2) if a != b)

    # If only 1-2 characters differ, might be suspicious
    return differences <= 2 and differences > 0


def _analyze_vlan_security(
    clients_data: List[Dict[str, Any]], networks_data: List[Dict[str, Any]]
) -> List[VLANSecurityInfo]:
    """Analyze VLAN security configuration and violations."""
    vlan_info = []

    # Group clients by VLAN
    vlan_clients = {}
    for client in clients_data:
        vlan_id = client.get('vlan', 1)  # Default VLAN 1
        if vlan_id not in vlan_clients:
            vlan_clients[vlan_id] = []
        vlan_clients[vlan_id].append(client)

    # Analyze each VLAN
    for vlan_id, clients in vlan_clients.items():
        vlan_name = f'VLAN {vlan_id}'

        # Try to find VLAN name from network config
        for network in networks_data:
            if network.get('vlan', 1) == vlan_id:
                vlan_name = network.get('name', vlan_name)
                break

        isolation_violations = []
        unauthorized_devices = []

        # Simple checks for common violations
        for client in clients:
            client_name = client.get('name', client.get('mac', 'Unknown'))

            # Check if guest devices are in management VLAN
            if vlan_id == 1 and client.get('network', '').lower() == 'guest':
                isolation_violations.append(f'Guest device {client_name} in management VLAN')

            # Check for devices that might not belong in this VLAN
            # (This would need custom business logic based on organization)

        vlan_info.append(
            VLANSecurityInfo(
                vlan_id=vlan_id,
                name=vlan_name,
                devices_count=len(clients),
                isolation_violations=isolation_violations,
                unauthorized_devices=unauthorized_devices,
            )
        )

    return vlan_info


def _generate_security_recommendations(
    critical_risks: List[SecurityDevice],
    high_risks: List[SecurityDevice],
    rogue_aps: List[SecurityDevice],
    new_devices: List[SecurityDevice],
    mac_anomalies: List[str],
) -> tuple[List[str], List[str]]:
    """Generate immediate actions and general recommendations."""
    immediate_actions = []
    recommendations = []

    # Critical immediate actions
    if critical_risks:
        immediate_actions.append(
            f'CRITICAL: Investigate {len(critical_risks)} high-risk devices immediately'
        )
        immediate_actions.extend(
            [f'Isolate or remove device: {d.name} ({d.mac})' for d in critical_risks[:3]]
        )

    if rogue_aps:
        immediate_actions.append(
            f'CRITICAL: {len(rogue_aps)} rogue access points detected - locate and eliminate'
        )

    if mac_anomalies:
        immediate_actions.append('Investigate MAC address anomalies - possible spoofing detected')

    # General security recommendations
    if new_devices:
        recommendations.append(
            f'Review and authorize {len(new_devices)} new devices detected in last 24h'
        )

    if high_risks:
        recommendations.append(f'Monitor {len(high_risks)} high-risk devices closely')

    recommendations.extend(
        [
            'Implement regular security audits and monitoring',
            'Consider MAC address whitelisting for critical network segments',
            'Enable rogue AP detection on all access points',
            'Implement network access control (NAC) for device authorization',
            'Regular firmware updates for all network infrastructure',
        ]
    )

    return immediate_actions, recommendations
