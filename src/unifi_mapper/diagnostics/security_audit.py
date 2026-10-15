"""Security audit: what the controller's own data can show about devices and the air.

The risks are exactly the things the controller has a source of truth for: an infrastructure
device pending adoption (``stat/device`` ``adopted``), a client on the guest network for more
than a day (``stat/sta`` ``is_guest``/``network`` and ``uptime``), and the rogue classes of
issue 079 (``stat/rogueap`` against this site's own radios and SSIDs). Vendor, MAC pattern,
randomised MAC, device name and traffic volume are not risks (issue 080): a vendor is a
chipset, a randomised MAC is the platform default, and the site's own switches have
sequential batch MACs. A check that could not run is reported as not assessed, never as zero.
"""

import re
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from unifi_mapper.analysis.neighbour_scan import MAX_ROGUE_AGE_SECONDS, own_bssids_from_devices
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# A neighbour AP heard this loud is probably inside the building (issue 079).
STRONG_SIGNAL_DBM = -60
# Neighbours listed for interference context; the rest are counted only.
STRONGEST_NEIGHBOURS = 3
# A client on the guest network longer than this is an overstay.
GUEST_OVERSTAY_SECONDS = 86400

# Every report carries these; a check that could not run adds a "not assessed" line.
STANDING_LIMITATIONS: tuple[str, ...] = (
    "Findings are signals derived from the controller's own data (stat/device, stat/sta, "
    'stat/rogueap, rest/wlanconf, rest/networkconf). They are not proof that a device is '
    'authorised, nor proof of the absence of compromise.',
    'A device is authorised or unauthorised only where the controller says so: an adopted or '
    'pending device, a client it has blocked or noted, a rogue AP. Every other client is not '
    'assessed. Vendor, MAC pattern, randomised MAC, name and traffic volume are not risks.',
    'A check that could not run is listed below as not assessed; it is not a zero.',
)


class SecurityDevice(BaseModel):
    """Security information for a network device."""

    mac: str = Field(description='Device MAC address')
    name: str = Field(description='Device name/hostname')
    ip: Optional[str] = Field(description='Device IP address')
    type: str = Field(description='Device type: infrastructure, client, or rogue_ap')
    vendor: Optional[str] = Field(
        description='Vendor from the OUI lookup (clients) or the model (adopted devices)'
    )
    first_seen: Optional[str] = Field(description='When device was first detected')
    last_seen: Optional[str] = Field(description='When device was last active')

    # Security flags
    is_authorized: Optional[bool] = Field(
        description=(
            "The controller's verdict where it has one: True for an adopted device or a noted "
            'client, False for a device pending adoption, a blocked client or a rogue AP. '
            'None means not assessed (the controller has no source of truth for this device).'
        )
    )
    is_anomalous: bool = Field(description='Whether device exhibits anomalous behavior')
    security_flags: List[str] = Field(
        description='Findings and information about the device (information does not raise risk)'
    )
    risk_level: str = Field(description='Risk level: low, medium, high, critical')


class VLANSecurityInfo(BaseModel):
    """VLAN security analysis."""

    vlan_id: int = Field(description='VLAN ID')
    name: str = Field(description='VLAN name')
    devices_count: int = Field(description='Number of devices in this VLAN')
    isolation_violations: List[str] = Field(description='VLAN isolation violations')
    unauthorized_devices: List[str] = Field(description='Unauthorized devices in this VLAN')


class NeighbourAP(BaseModel):
    """A neighbouring access point the passive scan hears: context, not a threat."""

    bssid: str = Field(description='The BSSID heard')
    essid: str = Field(description='The SSID it broadcasts (empty when hidden)')
    channel: int = Field(description='Channel')
    band: str = Field(description="Band as the controller names it ('ng', 'na', '6e')")
    signal: int = Field(description='Signal in dBm at the AP that heard it')
    security: str = Field(description='Security as the controller reports it')
    heard_by: str = Field(description='The AP of this site that heard it')


class SecurityAuditReport(BaseModel):
    """Comprehensive network security audit report."""

    timestamp: str = Field(description='When the security audit was performed')

    # Device security summary
    total_devices: int = Field(description='Total devices analyzed')
    authorized_devices: int = Field(
        description='Devices the controller vouches for: adopted devices and noted clients'
    )
    unauthorized_devices: int = Field(
        description=(
            'Devices the controller rules out: pending adoption, blocked clients, rogue APs'
        )
    )
    anomalous_devices: int = Field(description='Number of anomalous devices')

    # Security findings
    critical_risks: List[SecurityDevice] = Field(
        description='Devices with critical security risks'
    )
    high_risks: List[SecurityDevice] = Field(description='Devices with high security risks')
    medium_risks: List[SecurityDevice] = Field(description='Devices with medium security risks')

    # Specific security issues
    mac_anomalies: List[str] = Field(description='MAC address anomalies detected')
    new_devices: List[SecurityDevice] = Field(description='Recently appeared devices (last 24h)')
    rogue_aps: List[SecurityDevice] = Field(
        description=(
            'Access points that threaten this site: broadcasting one of its SSIDs from '
            'hardware that is not ours (critical), flagged by the controller as seen on the '
            'wired network (high), or UniFi hardware not adopted here heard on the premises '
            '(medium). Neighbours are counted in neighbour_aps, not listed here.'
        )
    )
    guest_violations: List[SecurityDevice] = Field(description='Guest network violations')
    neighbour_aps: int = Field(
        default=0, description='Neighbouring APs heard by the passive scan that are no threat'
    )
    strongest_neighbours: List[NeighbourAP] = Field(
        default_factory=list,
        description='The three loudest neighbours, for interference context (see analyze neighbours)',
    )

    # VLAN security
    vlan_analysis: List[VLANSecurityInfo] = Field(description='VLAN security analysis')

    # Recommendations
    immediate_actions: List[str] = Field(description='Immediate security actions required')
    security_recommendations: List[str] = Field(description='General security recommendations')

    # What this report can and cannot say
    limitations: List[str] = Field(
        default_factory=lambda: list(STANDING_LIMITATIONS),
        description=(
            'What the findings are (controller-derived signals, not proof of authorisation or '
            'of the absence of compromise) and every check that could not run, as "not '
            'assessed"'
        ),
    )


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
    5. Use discover_stp_topology() to assess potential impact scope

    What to do next:
    - If critical_risks found: Isolate or remove devices immediately
    - If rogue_aps lists an impersonator (our SSID from foreign hardware) or a wired rogue:
      locate it with the AP that heard it and the port the controller saw it on
    - neighbour_aps are the neighbours' own networks: no action; analyze neighbours shows
      the interference picture
    - If new_devices: Verify legitimacy and authorize or block
    - If vlan_violations: Review and correct VLAN configurations
    - Document findings and update security policies

    Returns:
        SecurityAuditReport with detailed security analysis and immediate actions. A read the
        audit could do without (the passive scan, the WLAN list, the network list) that fails
        is reported in ``limitations`` as not assessed; the audit still runs on the rest.

    Raises:
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
        ToolError: API_ERROR for other API-related issues
    """
    async with UniFiClient() as client:
        try:
            # Get comprehensive network data
            devices_data = await client.get(client.build_path('stat/device'))
            clients_data = await client.get(client.build_path('stat/sta'))
            read_errors: Dict[str, str] = {}

            # The passive neighbour list is stat/rogueap; rest/rogueap is not an object the
            # controller serves (HTTP 400 api.err.InvalidObject), which failed every audit.
            rogue_aps: Optional[List[Dict[str, Any]]]
            try:
                rogue_aps = await client.get_rogue_aps()
            except Exception as e:
                rogue_aps, read_errors['stat/rogueap'] = None, str(e)

            # The site's WLAN names (to spot an impersonated SSID) and VLANs, when readable.
            wlans_data: Optional[List[Dict[str, Any]]]
            try:
                wlans_data = await client.get(client.build_path('rest/wlanconf'))
            except Exception as e:
                wlans_data, read_errors['rest/wlanconf'] = None, str(e)
            networks_data: Optional[List[Dict[str, Any]]]
            try:
                networks_data = await client.get(client.build_path('rest/networkconf'))
            except Exception as e:
                networks_data, read_errors['rest/networkconf'] = None, str(e)

            # Perform security analysis
            return _perform_security_analysis(
                devices_data,
                clients_data,
                rogue_aps,
                networks_data,
                wlans_data=wlans_data,
                read_errors=read_errors,
            )

        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller for security audit',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
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
    rogue_aps: Optional[List[Dict[str, Any]]],
    networks_data: Optional[List[Dict[str, Any]]],
    wlans_data: Optional[List[Dict[str, Any]]] = None,
    *,
    read_errors: Optional[Dict[str, str]] = None,
) -> SecurityAuditReport:
    """Perform the security analysis on the controller's data.

    Args:
        devices_data: ``stat/device`` records; membership is adoption (pending when
            ``adopted`` is false), never inferred from a missing ``oui``.
        clients_data: ``stat/sta`` records.
        rogue_aps: ``stat/rogueap`` records, the passive neighbour scan; None when it could
            not be read (rogue APs and neighbours are then not assessed).
        networks_data: ``rest/networkconf`` records (VLANs); None when not read.
        wlans_data: ``rest/wlanconf`` records (this site's SSIDs); None when not read.
        read_errors: The error text per endpoint that could not be read, for the
            ``limitations`` lines.

    Returns:
        The report.
    """
    security_devices = []
    new_devices = []
    guest_violations = []
    limitations: List[str] = list(STANDING_LIMITATIONS)
    errors = read_errors or {}

    def reason(endpoint: str) -> str:
        return errors.get(endpoint) or 'could not be read'

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

        # Guest-network overstay is one of the risks _analyze_device_security sets.
        if _is_guest_violation(client_data):
            guest_violations.append(security_device)

    # Rogue APs versus neighbours: only a rogue is a security device.
    rogue_ap_devices: List[SecurityDevice] = []
    neighbours: List[NeighbourAP] = []
    if rogue_aps is None:
        limitations.append(
            f'Rogue APs and neighbours: not assessed (stat/rogueap {reason("stat/rogueap")})'
        )
    else:
        own_bssids = own_bssids_from_devices(devices_data)
        own_ssids = _own_ssids(devices_data, wlans_data or [])
        rogue_ap_devices, neighbours = classify_rogue_aps(
            rogue_aps, own_bssids=own_bssids, own_ssids=own_ssids
        )
        security_devices.extend(rogue_ap_devices)
    if wlans_data is None:
        limitations.append(
            'SSID impersonation against the WLAN list: not assessed (rest/wlanconf '
            f'{reason("rest/wlanconf")}); only the SSIDs the radios broadcast now were checked'
        )
    if networks_data is None:
        limitations.append(
            'VLAN names: not assessed (rest/networkconf '
            f'{reason("rest/networkconf")}); VLANs are listed by number'
        )
    strongest = sorted(neighbours, key=lambda n: n.signal, reverse=True)[:STRONGEST_NEIGHBOURS]

    # MAC anomalies within the client population only: adopted devices come from the same
    # production batch and have sequential MACs; neighbour BSSIDs are a few digits apart.
    mac_anomalies = _detect_mac_anomalies([str(c.get('mac') or '') for c in clients_data])

    # Analyze VLAN security
    vlan_analysis = _analyze_vlan_security(clients_data, networks_data or [])

    # Categorize devices by risk level
    critical_risks = [d for d in security_devices if d.risk_level == 'critical']
    high_risks = [d for d in security_devices if d.risk_level == 'high']
    medium_risks = [d for d in security_devices if d.risk_level == 'medium']

    # The controller's verdicts only; a device it has no verdict on is not counted either way.
    authorized_count = len([d for d in security_devices if d.is_authorized is True])
    unauthorized_count = len([d for d in security_devices if d.is_authorized is False])
    anomalous_count = len([d for d in security_devices if d.is_anomalous])

    # Generate immediate actions and recommendations
    immediate_actions, recommendations = _generate_security_recommendations(
        critical_risks,
        high_risks,
        rogue_ap_devices,
        new_devices,
        mac_anomalies,
        neighbour_count=len(neighbours),
    )

    return SecurityAuditReport(
        timestamp=current_time.isoformat(),
        total_devices=len(security_devices),
        authorized_devices=authorized_count,
        unauthorized_devices=unauthorized_count,
        anomalous_devices=anomalous_count,
        critical_risks=critical_risks,
        high_risks=high_risks,
        medium_risks=medium_risks,
        mac_anomalies=mac_anomalies,
        new_devices=new_devices,
        rogue_aps=rogue_ap_devices,
        guest_violations=guest_violations,
        neighbour_aps=len(neighbours),
        strongest_neighbours=strongest,
        vlan_analysis=vlan_analysis,
        immediate_actions=immediate_actions,
        security_recommendations=recommendations,
        limitations=limitations,
    )


def _own_ssids(devices_data: List[Dict[str, Any]], wlans_data: List[Dict[str, Any]]) -> set[str]:
    """The SSIDs this site owns: every WLAN's name plus every ESSID its radios broadcast."""
    ssids = {str(w.get('name')) for w in wlans_data if w.get('name')}
    for device in devices_data:
        if device.get('type') != 'uap':
            continue
        for vap in device.get('vap_table', []):
            if vap.get('essid'):
                ssids.add(str(vap['essid']))
    return ssids


def classify_rogue_aps(
    rogue_aps: List[Dict[str, Any]], *, own_bssids: set[str], own_ssids: set[str]
) -> tuple[List[SecurityDevice], List[NeighbourAP]]:
    """Split the passive scan into rogues (a threat to this site) and neighbours (pure).

    A rogue, in order of certainty: it broadcasts one of this site's SSIDs from a BSSID that is
    not one of ours (an impersonator; critical); the controller flags it ``is_rogue``, meaning
    it was also seen on our wired network (high); or it is UniFi hardware (``is_ubnt`` or
    ``is_unifi``) not adopted here, heard at :data:`STRONG_SIGNAL_DBM` or louder, so probably
    on the premises (medium). The rules are cumulative: the strongest sets the risk, the others
    are still listed as flags. Our own radios (heard by another of our APs) and entries older
    than :data:`MAX_ROGUE_AGE_SECONDS` are ignored. Everything else is a neighbour.

    Args:
        rogue_aps: ``stat/rogueap`` records.
        own_bssids: The BSSIDs this site's radios broadcast (any case).
        own_ssids: The SSIDs this site owns.

    Returns:
        ``(rogues, neighbours)``.
    """
    own = {b.lower() for b in own_bssids}
    rogues: List[SecurityDevice] = []
    neighbours: List[NeighbourAP] = []
    for entry in rogue_aps:
        bssid = str(entry.get('bssid') or '').lower()
        if not bssid or bssid in own or (entry.get('age') or 0) > MAX_ROGUE_AGE_SECONDS:
            continue
        essid = str(entry.get('essid') or '')
        signal = int(entry.get('signal') or -100)
        heard_by = str(entry.get('ap_name') or entry.get('ap_mac') or 'an AP of this site')
        flags: List[str] = []
        risk = ''
        if essid and essid in own_ssids:
            risk = 'critical'
            flags.append(
                f"Broadcasts this site's SSID '{essid}' from {bssid}, which is not one of "
                "this site's radios: a possible evil twin"
            )
        if entry.get('is_rogue'):
            risk = risk or 'high'
            flags.append("Flagged by the controller as seen on this site's wired network")
        unifi_hardware = bool(entry.get('is_ubnt') or entry.get('is_unifi'))
        if unifi_hardware and signal >= STRONG_SIGNAL_DBM:
            risk = risk or 'medium'
            flags.append(
                f'UniFi hardware not adopted by this controller, heard at {signal} dBm '
                f"(probably on the premises): adopt it, or confirm it is a neighbour's"
            )
        if not risk:
            neighbours.append(
                NeighbourAP(
                    bssid=bssid,
                    essid=essid,
                    channel=int(entry.get('channel') or 0),
                    band=str(entry.get('band') or ''),
                    signal=signal,
                    security=str(entry.get('security') or ''),
                    heard_by=heard_by,
                )
            )
            continue
        flags.append(f'Heard by {heard_by} at {signal} dBm on channel {entry.get("channel", "?")}')
        vendor = str(entry.get('model_display') or entry.get('oui') or 'Unknown')
        rogues.append(
            SecurityDevice(
                mac=bssid,
                name=essid or '<hidden SSID>',
                ip=None,
                type='rogue_ap',
                vendor=vendor,
                first_seen=None,
                last_seen=None,
                is_authorized=False,
                is_anomalous=True,
                security_flags=flags,
                risk_level=risk,
            )
        )
    return rogues, neighbours


def _analyze_device_security(device_data: Dict[str, Any], device_type: str) -> SecurityDevice:
    """Read one ``stat/device`` or ``stat/sta`` record for what the controller can show.

    Risks: an infrastructure device pending adoption (high) and a client overstaying the guest
    network (medium). Verdicts: adopted (authorised), pending (unauthorised), a client the
    controller has ``blocked`` (unauthorised) or ``noted`` (authorised); any other client is
    not assessed. Information, never a risk: a randomised MAC (the platform default on phones)
    and a day without activity. Vendor, name, traffic volume and MAC pattern are not read.
    """
    mac = device_data.get('mac', '')
    name = (
        device_data.get('name')
        or device_data.get('hostname')
        or device_data.get('display_name')
        or 'Unknown'
    )
    ip = device_data.get('ip')
    # Adopted devices carry no oui; their model is the vendor information worth showing.
    vendor = device_data.get('oui') or device_data.get('model') or None

    security_flags: List[str] = []
    risk_level = 'low'
    is_anomalous = False
    is_authorized: Optional[bool] = None  # None: the controller has no verdict

    if device_type == 'infrastructure':
        # Membership of stat/device is adoption; 'adopted' false is a device waiting for it.
        if device_data.get('adopted', False):
            is_authorized = True
        else:
            security_flags.append('Infrastructure device not adopted (pending adoption)')
            risk_level = 'high'
            is_authorized = False
    else:
        if device_data.get('blocked'):
            security_flags.append('Blocked by the controller')
            is_authorized = False
        elif device_data.get('noted'):
            is_authorized = True
        if _is_guest_violation(device_data):
            hours = int(device_data.get('uptime', 0)) // 3600
            security_flags.append(f'On the guest network for {hours} hours (more than a day)')
            risk_level = 'medium'
            is_anomalous = True

    # Information only (issue 080): the platform default on every current phone.
    if _is_randomized_mac(mac):
        security_flags.append('Randomised (locally administered) MAC address: information only')

    # Information only: a day without activity.
    last_seen_timestamp = device_data.get('last_seen', 0)
    if last_seen_timestamp:
        last_seen = datetime.fromtimestamp(last_seen_timestamp)
        if datetime.now() - last_seen > timedelta(hours=24):
            security_flags.append('Device has been inactive for >24 hours')

    # Convert timestamps
    first_seen = None
    last_seen_iso = None
    if device_data.get('first_seen'):
        first_seen = datetime.fromtimestamp(device_data['first_seen']).isoformat()
    if device_data.get('last_seen'):
        last_seen_iso = datetime.fromtimestamp(device_data['last_seen']).isoformat()

    return SecurityDevice(
        mac=mac,
        name=name,
        ip=ip,
        type=device_type,
        vendor=vendor,
        first_seen=first_seen,
        last_seen=last_seen_iso,
        is_authorized=is_authorized,
        is_anomalous=is_anomalous,
        security_flags=security_flags,
        risk_level=risk_level,
    )


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


def _is_guest_violation(client_data: Dict[str, Any]) -> bool:
    """A guest-network overstay.

    The client is on the guest network (the controller's ``is_guest``, or a network named
    guest) and has been connected longer than :data:`GUEST_OVERSTAY_SECONDS`.
    """
    on_guest = bool(client_data.get('is_guest')) or (
        str(client_data.get('network') or '').lower() == 'guest'
    )
    return on_guest and int(client_data.get('uptime') or 0) > GUEST_OVERSTAY_SECONDS


def _detect_mac_anomalies(mac_addresses: List[str]) -> List[str]:
    """MAC anomalies within one population (the clients): duplicates and near-duplicates."""
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
    *,
    neighbour_count: int = 0,
) -> tuple[List[str], List[str]]:
    """Generate immediate actions and general recommendations."""
    immediate_actions = []
    recommendations = []
    rogue_macs = {r.mac for r in rogue_aps}

    # Critical immediate actions (rogue APs have their own, more specific lines below)
    critical_devices = [d for d in critical_risks if d.mac not in rogue_macs]
    if critical_devices:
        immediate_actions.append(
            f'CRITICAL: Investigate {len(critical_devices)} high-risk devices immediately'
        )
        immediate_actions.extend(
            [f'Isolate or remove device: {d.name} ({d.mac})' for d in critical_devices[:3]]
        )

    for rogue in rogue_aps:
        where = next((f for f in rogue.security_flags if f.startswith('Heard by')), '')
        if rogue.risk_level == 'critical':
            immediate_actions.append(
                f"CRITICAL: '{rogue.name}' is broadcast by {rogue.mac}, which is not one of "
                f"this site's APs (a possible evil twin). Locate it: {where or 'see flags'}"
            )
        elif rogue.risk_level == 'high':
            immediate_actions.append(
                f"HIGH: '{rogue.name}' ({rogue.mac}) is a neighbouring AP the controller also "
                f'saw on the wired network. Find the switch port it is plugged into'
            )
        else:
            immediate_actions.append(
                f"MEDIUM: UniFi hardware {rogue.vendor} ({rogue.mac}, '{rogue.name}') is not "
                f"adopted here but heard on the premises. Adopt it or confirm it is a neighbour's"
            )

    if mac_anomalies:
        immediate_actions.append('Investigate MAC address anomalies - possible spoofing detected')

    # General security recommendations
    if neighbour_count:
        recommendations.append(
            f'{neighbour_count} neighbouring APs heard, none a threat to this site; '
            '`unifi-mapper analyze neighbours` (MCP scan_neighbour_aps) shows the interference'
        )

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
