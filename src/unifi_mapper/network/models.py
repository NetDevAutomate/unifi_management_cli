"""Data models for UniFi Network API integration.

This module provides Pydantic models representing UniFi Network API
resources including devices, statistics, firewall, DPI, and clients.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Annotated


# =============================================================================
# Enums
# =============================================================================


class DeviceState(str, Enum):
    """Device operational state."""

    CONNECTED = 'CONNECTED'
    DISCONNECTED = 'DISCONNECTED'
    PENDING = 'PENDING'
    ADOPTING = 'ADOPTING'
    PROVISIONING = 'PROVISIONING'
    UPGRADING = 'UPGRADING'
    UNKNOWN = 'UNKNOWN'


class DeviceFeature(str, Enum):
    """Device feature capabilities."""

    SWITCH = 'SWITCH'
    ROUTER = 'ROUTER'
    ACCESS_POINT = 'ACCESS_POINT'
    GATEWAY = 'GATEWAY'
    PROTECT = 'PROTECT'
    TALK = 'TALK'


class ClientType(str, Enum):
    """Client connection type."""

    WIRED = 'WIRED'
    WIRELESS = 'WIRELESS'
    VPN = 'VPN'


class ClientAccessType(str, Enum):
    """Client access authorization type."""

    GUEST = 'GUEST'
    USER = 'USER'
    HOTSPOT = 'HOTSPOT'


class FirewallActionType(str, Enum):
    """Firewall policy action type."""

    ALLOW = 'ALLOW'
    BLOCK = 'BLOCK'
    REJECT = 'REJECT'


class ConnectionStateFilter(str, Enum):
    """Connection state matching filter."""

    NEW = 'NEW'
    ESTABLISHED = 'ESTABLISHED'
    RELATED = 'RELATED'
    INVALID = 'INVALID'


class IPSecFilter(str, Enum):
    """IPsec traffic matching filter."""

    MATCH_ENCRYPTED = 'MATCH_ENCRYPTED'
    MATCH_NOT_ENCRYPTED = 'MATCH_NOT_ENCRYPTED'


# =============================================================================
# Base Models
# =============================================================================


class PaginatedResponse(BaseModel):
    """Base model for paginated API responses."""

    offset: int = 0
    limit: int = 25
    count: int = 0
    total_count: int = Field(0, alias='totalCount')


# =============================================================================
# Device Statistics Models
# =============================================================================


class CPUMemoryStats(BaseModel):
    """CPU and memory utilization statistics."""

    cpu_utilization_percent: Annotated[
        float, Field(ge=0, le=100, alias='cpuUtilizationPercent')
    ] = 0.0
    memory_utilization_percent: Annotated[
        float, Field(ge=0, le=100, alias='memoryUtilizationPercent')
    ] = 0.0
    memory_used_bytes: Annotated[int, Field(ge=0, alias='memoryUsedBytes')] = 0
    memory_total_bytes: Annotated[int, Field(ge=0, alias='memoryTotalBytes')] = 0

    model_config = {'populate_by_name': True}


class PortStatistics(BaseModel):
    """Statistics for a single switch/device port."""

    port_idx: Annotated[int, Field(ge=0, alias='portIdx')] = 0
    name: str = ''
    enabled: bool = True
    link_up: Annotated[bool, Field(alias='linkUp')] = False
    speed_mbps: Annotated[int, Field(ge=0, alias='speedMbps')] = 0
    full_duplex: Annotated[bool, Field(alias='fullDuplex')] = True
    poe_enabled: Annotated[bool, Field(alias='poeEnabled')] = False
    poe_power_watts: Annotated[float, Field(ge=0, alias='poePowerWatts')] = 0.0
    tx_bytes: Annotated[int, Field(ge=0, alias='txBytes')] = 0
    rx_bytes: Annotated[int, Field(ge=0, alias='rxBytes')] = 0
    tx_packets: Annotated[int, Field(ge=0, alias='txPackets')] = 0
    rx_packets: Annotated[int, Field(ge=0, alias='rxPackets')] = 0
    tx_errors: Annotated[int, Field(ge=0, alias='txErrors')] = 0
    rx_errors: Annotated[int, Field(ge=0, alias='rxErrors')] = 0
    tx_dropped: Annotated[int, Field(ge=0, alias='txDropped')] = 0
    rx_dropped: Annotated[int, Field(ge=0, alias='rxDropped')] = 0
    tx_rate_bps: Annotated[int, Field(ge=0, alias='txRateBps')] = 0
    rx_rate_bps: Annotated[int, Field(ge=0, alias='rxRateBps')] = 0

    model_config = {'populate_by_name': True}

    @property
    def tx_bytes_human(self) -> str:
        """Human-readable transmitted bytes."""
        return _bytes_to_human(self.tx_bytes)

    @property
    def rx_bytes_human(self) -> str:
        """Human-readable received bytes."""
        return _bytes_to_human(self.rx_bytes)

    @property
    def error_rate(self) -> float:
        """Calculate error rate as percentage of total packets."""
        total = self.tx_packets + self.rx_packets
        errors = self.tx_errors + self.rx_errors
        return (errors / total * 100) if total > 0 else 0.0


class InterfaceStatistics(BaseModel):
    """Statistics for a network interface (WAN, LAN, etc.)."""

    name: str = ''
    mac_address: Annotated[str, Field(alias='macAddress')] = ''
    ip_address: Annotated[str | None, Field(alias='ipAddress')] = None
    tx_bytes: Annotated[int, Field(ge=0, alias='txBytes')] = 0
    rx_bytes: Annotated[int, Field(ge=0, alias='rxBytes')] = 0
    tx_rate_bps: Annotated[int, Field(ge=0, alias='txRateBps')] = 0
    rx_rate_bps: Annotated[int, Field(ge=0, alias='rxRateBps')] = 0

    model_config = {'populate_by_name': True}


class DeviceStatistics(BaseModel):
    """Real-time statistics for an adopted device."""

    device_id: Annotated[str, Field(alias='deviceId')] = ''
    uptime_seconds: Annotated[int, Field(ge=0, alias='uptimeSeconds')] = 0
    last_seen: Annotated[datetime | None, Field(alias='lastSeen')] = None
    cpu_memory: Annotated[CPUMemoryStats | None, Field(alias='cpuMemory')] = None
    ports: list[PortStatistics] = Field(default_factory=list)
    interfaces: list[InterfaceStatistics] = Field(default_factory=list)
    temperature_celsius: Annotated[float | None, Field(alias='temperatureCelsius')] = None
    load_average_1m: Annotated[float | None, Field(alias='loadAverage1m')] = None
    load_average_5m: Annotated[float | None, Field(alias='loadAverage5m')] = None
    load_average_15m: Annotated[float | None, Field(alias='loadAverage15m')] = None

    model_config = {'populate_by_name': True}

    @property
    def uptime_human(self) -> str:
        """Human-readable uptime."""
        seconds = self.uptime_seconds
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or not parts:
            parts.append(f"{secs}s")
        return ' '.join(parts)

    @property
    def total_tx_bytes(self) -> int:
        """Total transmitted bytes across all ports."""
        return sum(p.tx_bytes for p in self.ports)

    @property
    def total_rx_bytes(self) -> int:
        """Total received bytes across all ports."""
        return sum(p.rx_bytes for p in self.ports)


# =============================================================================
# Device Info Models
# =============================================================================


class UplinkInfo(BaseModel):
    """Device uplink connection information."""

    device_id: Annotated[str | None, Field(alias='deviceId')] = None
    port_idx: Annotated[int | None, Field(alias='portIdx')] = None
    type: str = ''  # 'WIRED', 'WIRELESS'
    speed_mbps: Annotated[int | None, Field(alias='speedMbps')] = None

    model_config = {'populate_by_name': True}


class DeviceInfo(BaseModel):
    """Information about an adopted UniFi device."""

    id: str = ''
    mac_address: Annotated[str, Field(alias='macAddress')] = ''
    ip_address: Annotated[str | None, Field(alias='ipAddress')] = None
    name: str = ''
    model: str = ''
    state: DeviceState = DeviceState.UNKNOWN
    firmware_version: Annotated[str | None, Field(alias='firmwareVersion')] = None
    firmware_updatable: Annotated[bool, Field(alias='firmwareUpdatable')] = False
    features: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    uplink: UplinkInfo | None = None
    supported: bool = True

    model_config = {'populate_by_name': True}

    @property
    def is_switch(self) -> bool:
        """Check if device is a switch."""
        return 'SWITCH' in self.features

    @property
    def is_router(self) -> bool:
        """Check if device is a router/gateway."""
        return 'ROUTER' in self.features or 'GATEWAY' in self.features

    @property
    def is_access_point(self) -> bool:
        """Check if device is an access point."""
        return 'ACCESS_POINT' in self.features


# =============================================================================
# Network Models
# =============================================================================


class DHCPGuarding(BaseModel):
    """DHCP Guarding configuration for a network."""

    enabled: bool = False
    trusted_servers: Annotated[
        list[str], Field(alias='trustedServers', default_factory=list)
    ]

    model_config = {'populate_by_name': True}


class NetworkInfo(BaseModel):
    """Information about a network/VLAN."""

    id: str = ''
    name: str = ''
    enabled: bool = True
    vlan_id: Annotated[int | None, Field(alias='vlanId')] = None
    management: str = ''  # 'INTERNAL', 'EXTERNAL'
    dhcp_guarding: Annotated[DHCPGuarding | None, Field(alias='dhcpGuarding')] = None

    model_config = {'populate_by_name': True}


# =============================================================================
# DPI Models
# =============================================================================


class DPICategory(BaseModel):
    """DPI application category."""

    id: int = 0
    name: str = ''

    model_config = {'populate_by_name': True}


class DPIApplication(BaseModel):
    """DPI application definition."""

    id: int = 0
    name: str = ''
    category_id: Annotated[int | None, Field(alias='categoryId')] = None

    model_config = {'populate_by_name': True}


class DPIStats(BaseModel):
    """DPI traffic statistics for an application or category."""

    id: int = 0
    name: str = ''
    rx_bytes: Annotated[int, Field(ge=0, alias='rxBytes')] = 0
    tx_bytes: Annotated[int, Field(ge=0, alias='txBytes')] = 0
    rx_packets: Annotated[int, Field(ge=0, alias='rxPackets')] = 0
    tx_packets: Annotated[int, Field(ge=0, alias='txPackets')] = 0

    model_config = {'populate_by_name': True}

    @property
    def total_bytes(self) -> int:
        """Total bytes transferred."""
        return self.rx_bytes + self.tx_bytes

    @property
    def total_bytes_human(self) -> str:
        """Human-readable total bytes."""
        return _bytes_to_human(self.total_bytes)


# =============================================================================
# Client Models
# =============================================================================


class ClientFingerprint(BaseModel):
    """Client device fingerprint information."""

    os_name: Annotated[str | None, Field(alias='osName')] = None
    os_class: Annotated[str | None, Field(alias='osClass')] = None
    dev_family: Annotated[str | None, Field(alias='devFamily')] = None
    dev_vendor: Annotated[str | None, Field(alias='devVendor')] = None
    dev_cat: Annotated[str | None, Field(alias='devCat')] = None
    dev_id: Annotated[int | None, Field(alias='devId')] = None

    model_config = {'populate_by_name': True}

    @property
    def device_description(self) -> str:
        """Human-readable device description."""
        parts = []
        if self.dev_vendor:
            parts.append(self.dev_vendor)
        if self.dev_family:
            parts.append(self.dev_family)
        if self.os_name:
            parts.append(f"({self.os_name})")
        return ' '.join(parts) if parts else 'Unknown Device'


class ClientAccess(BaseModel):
    """Client access information."""

    type: ClientAccessType = ClientAccessType.USER
    authorized: bool = True
    authorized_at: Annotated[datetime | None, Field(alias='authorizedAt')] = None
    expires_at: Annotated[datetime | None, Field(alias='expiresAt')] = None

    model_config = {'populate_by_name': True}


class ClientInfo(BaseModel):
    """Information about a connected network client."""

    id: str = ''
    mac_address: Annotated[str | None, Field(alias='macAddress')] = None
    ip_address: Annotated[str | None, Field(alias='ipAddress')] = None
    hostname: str | None = None
    name: str | None = None
    type: ClientType = ClientType.WIRED
    connected_at: Annotated[datetime | None, Field(alias='connectedAt')] = None
    access: ClientAccess | None = None
    fingerprint: ClientFingerprint | None = None
    uplink_device_id: Annotated[str | None, Field(alias='uplinkDeviceId')] = None
    uplink_port_idx: Annotated[int | None, Field(alias='uplinkPortIdx')] = None
    network_id: Annotated[str | None, Field(alias='networkId')] = None
    ssid: str | None = None
    signal_strength_dbm: Annotated[int | None, Field(alias='signalStrengthDbm')] = None
    tx_bytes: Annotated[int, Field(ge=0, alias='txBytes')] = 0
    rx_bytes: Annotated[int, Field(ge=0, alias='rxBytes')] = 0

    model_config = {'populate_by_name': True}

    @property
    def display_name(self) -> str:
        """Get the best available display name."""
        return self.name or self.hostname or self.mac_address or self.id

    @property
    def is_guest(self) -> bool:
        """Check if client is a guest."""
        return self.access.type == ClientAccessType.GUEST if self.access else False


# =============================================================================
# Firewall Models
# =============================================================================


class FirewallZone(BaseModel):
    """Firewall zone definition."""

    id: str = ''
    name: str = ''
    network_ids: Annotated[list[str], Field(alias='networkIds', default_factory=list)]
    configurable: bool = True
    origin: str = ''  # 'SYSTEM', 'USER'

    model_config = {'populate_by_name': True}


class FirewallAction(BaseModel):
    """Firewall policy action."""

    type: FirewallActionType = FirewallActionType.BLOCK

    model_config = {'populate_by_name': True}


class FirewallSource(BaseModel):
    """Firewall policy source specification."""

    firewall_zone_id: Annotated[str | None, Field(alias='firewallZoneId')] = None
    ip_addresses: Annotated[list[str], Field(alias='ipAddresses', default_factory=list)]
    port_ranges: Annotated[list[str], Field(alias='portRanges', default_factory=list)]

    model_config = {'populate_by_name': True}


class FirewallDestination(BaseModel):
    """Firewall policy destination specification."""

    firewall_zone_id: Annotated[str | None, Field(alias='firewallZoneId')] = None
    ip_addresses: Annotated[list[str], Field(alias='ipAddresses', default_factory=list)]
    port_ranges: Annotated[list[str], Field(alias='portRanges', default_factory=list)]

    model_config = {'populate_by_name': True}


class FirewallSchedule(BaseModel):
    """Firewall policy schedule."""

    enabled: bool = True
    days_of_week: Annotated[list[str], Field(alias='daysOfWeek', default_factory=list)]
    start_time: Annotated[str | None, Field(alias='startTime')] = None  # "HH:MM"
    end_time: Annotated[str | None, Field(alias='endTime')] = None  # "HH:MM"

    model_config = {'populate_by_name': True}


class FirewallPolicy(BaseModel):
    """Firewall policy definition."""

    id: str = ''
    name: str = ''
    description: str | None = None
    enabled: bool = True
    action: FirewallAction = Field(default_factory=FirewallAction)
    source: FirewallSource | None = None
    destination: FirewallDestination | None = None
    connection_state_filter: Annotated[
        list[ConnectionStateFilter] | None, Field(alias='connectionStateFilter')
    ] = None
    ipsec_filter: Annotated[IPSecFilter | None, Field(alias='ipsecFilter')] = None
    logging_enabled: Annotated[bool, Field(alias='loggingEnabled')] = False
    schedule: FirewallSchedule | None = None
    index: int = 0  # Order in policy chain
    origin: str = ''  # 'SYSTEM', 'USER'

    model_config = {'populate_by_name': True}


# =============================================================================
# ACL Rule Models
# =============================================================================


class ACLActionType(str, Enum):
    """ACL rule action type."""

    ALLOW = 'ALLOW'
    BLOCK = 'BLOCK'


class ACLProtocol(str, Enum):
    """ACL protocol filter."""

    TCP = 'TCP'
    UDP = 'UDP'


class ACLDeviceFilter(BaseModel):
    """ACL rule device filter for switch enforcement."""

    device_ids: Annotated[
        list[str] | None, Field(alias='deviceIds', default=None)
    ]

    model_config = {'populate_by_name': True}


class ACLTrafficFilter(BaseModel):
    """ACL traffic source or destination filter."""

    type: str | None = None
    ip_addresses_or_subnets: Annotated[
        list[str], Field(alias='ipAddressesOrSubnets', default_factory=list)
    ]
    ports_filter: Annotated[
        list[int], Field(alias='portsFilter', default_factory=list)
    ]
    network_ids: Annotated[
        list[str], Field(alias='networkIds', default_factory=list)
    ]
    mac_addresses: Annotated[
        list[str], Field(alias='macAddresses', default_factory=list)
    ]
    prefix_length: Annotated[int | None, Field(alias='prefixLength')] = None

    model_config = {'populate_by_name': True}


class ACLRule(BaseModel):
    """Access Control List rule for traffic filtering."""

    id: str = ''
    type: str = ''
    enabled: bool = True
    name: str = ''
    description: str | None = None
    action: ACLActionType = ACLActionType.BLOCK
    enforcing_device_filter: Annotated[
        ACLDeviceFilter | None, Field(alias='enforcingDeviceFilter')
    ] = None
    index: int = 0
    source_filter: Annotated[
        ACLTrafficFilter | None, Field(alias='sourceFilter')
    ] = None
    destination_filter: Annotated[
        ACLTrafficFilter | None, Field(alias='destinationFilter')
    ] = None
    protocol_filter: Annotated[
        list[ACLProtocol] | None, Field(alias='protocolFilter')
    ] = None
    network_id: Annotated[str | None, Field(alias='networkId')] = None
    origin: str = ''  # 'SYSTEM', 'USER'

    model_config = {'populate_by_name': True}


# =============================================================================
# DNS Policy Models
# =============================================================================


class DNSRecordType(str, Enum):
    """DNS record type."""

    A = 'A'
    AAAA = 'AAAA'
    CNAME = 'CNAME'
    MX = 'MX'
    TXT = 'TXT'
    SRV = 'SRV'


class DNSPolicy(BaseModel):
    """DNS policy for domain resolution."""

    id: str = ''
    type: str = ''
    enabled: bool = True
    domain: Annotated[str, Field(min_length=1, max_length=127)] = ''
    ipv4_address: Annotated[str | None, Field(alias='ipv4Address')] = None
    ipv6_address: Annotated[str | None, Field(alias='ipv6Address')] = None
    target_domain: Annotated[str | None, Field(alias='targetDomain')] = None
    mail_server_domain: Annotated[str | None, Field(alias='mailServerDomain')] = None
    text: str | None = None
    server_domain: Annotated[str | None, Field(alias='serverDomain')] = None
    ip_address: Annotated[str | None, Field(alias='ipAddress')] = None
    ttl_seconds: Annotated[int, Field(ge=0, le=604800, alias='ttlSeconds')] = 3600
    priority: int | None = None
    service: str | None = None
    protocol: str | None = None
    port: int | None = None
    weight: int | None = None

    model_config = {'populate_by_name': True}


# =============================================================================
# Traffic Matching List Models
# =============================================================================


class PortMatching(BaseModel):
    """Port matching configuration for traffic lists."""

    port: int = Field(ge=1, le=65535)
    protocol: ACLProtocol = ACLProtocol.TCP

    model_config = {'populate_by_name': True}


class IPAddressMatching(BaseModel):
    """IP address matching configuration for traffic lists."""

    ip_address: Annotated[str, Field(alias='ipAddress')] = ''
    description: str | None = None

    model_config = {'populate_by_name': True}


class TrafficMatchingListType(str, Enum):
    """Traffic matching list type."""

    PORT_LIST = 'PORT_LIST'
    IP_ADDRESS_LIST = 'IP_ADDRESS_LIST'


class TrafficMatchingList(BaseModel):
    """Traffic matching list for firewall configurations."""

    id: str = ''
    type: TrafficMatchingListType = TrafficMatchingListType.PORT_LIST
    name: str = ''
    ports: list[PortMatching] = Field(default_factory=list)
    ip_addresses: Annotated[
        list[IPAddressMatching], Field(alias='ipAddresses', default_factory=list)
    ]

    model_config = {'populate_by_name': True}


# =============================================================================
# Utility Functions
# =============================================================================


def _bytes_to_human(num_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0  # type: ignore[assignment]
    return f"{num_bytes:.2f} EB"
