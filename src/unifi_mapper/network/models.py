"""Data models for UniFi Network API integration.

This module provides Pydantic models representing UniFi Network API
resources including devices, statistics, firewall, DPI, and clients.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from typing import Annotated, Any


# =============================================================================
# Enums
# =============================================================================


class DeviceState(str, Enum):
    """Device operational state.

    Ubiquiti's Network API reference (v10.6.102) sends ``ONLINE``, ``OFFLINE``,
    ``PENDING_ADOPTION`` and ``UPDATING`` among others; ``DeviceInfo.state`` keeps a value this
    enum doesn't know as its string, so a new state can't fail the whole device list (issue
    036). The older members below predate the reference check and are kept for callers that
    compare against them; Network 10.6 is not known to send them.
    """

    ONLINE = 'ONLINE'
    OFFLINE = 'OFFLINE'
    PENDING_ADOPTION = 'PENDING_ADOPTION'
    UPDATING = 'UPDATING'
    CONNECTED = 'CONNECTED'
    DISCONNECTED = 'DISCONNECTED'
    PENDING = 'PENDING'
    ADOPTING = 'ADOPTING'
    PROVISIONING = 'PROVISIONING'
    UPGRADING = 'UPGRADING'
    UNKNOWN = 'UNKNOWN'


class DeviceFeature(str, Enum):
    """A device feature, by the name the Integration API sends (issue 082).

    The reference's ``features`` items are ``switching``, ``accessPoint`` and ``gateway``, the
    names ``DeviceInfo.feature_names`` returns, so ``DeviceFeature.SWITCHING in
    device.feature_names`` matches a live device. ``SWITCH`` and ``ROUTER`` are the members'
    pre-0.4.0 names, kept as aliases; ``PROTECT`` and ``TALK`` were removed because the API
    sends no such feature.
    """

    SWITCHING = 'switching'
    ACCESS_POINT = 'accessPoint'
    GATEWAY = 'gateway'
    # Aliases (same value, so the same member): DeviceFeature.SWITCH is DeviceFeature.SWITCHING.
    SWITCH = 'switching'
    ROUTER = 'gateway'


class ClientType(str, Enum):
    """Client connection type.

    Ubiquiti's Network API reference (v10.6.102) lists WIRED, WIRELESS, VPN and TELEPORT.
    ``ClientInfo.type`` keeps a value this enum doesn't know as its string, so a new type
    can't fail the whole client list.
    """

    WIRED = 'WIRED'
    WIRELESS = 'WIRELESS'
    VPN = 'VPN'
    TELEPORT = 'TELEPORT'


class ClientAccessType(str, Enum):
    """Client access authorization type.

    Network 10.6 sends ``GUEST`` for guest clients and ``DEFAULT`` (a placeholder Ubiquiti
    says it may refine) for every other client. ``ClientAccess.type`` keeps a value this
    enum doesn't know as its string, so a new type can't fail the whole client list.
    """

    GUEST = 'GUEST'
    USER = 'USER'
    HOTSPOT = 'HOTSPOT'
    DEFAULT = 'DEFAULT'


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


class DeviceUplinkRates(BaseModel):
    """``uplink`` of a device's latest statistics: the uplink's current rates."""

    tx_rate_bps: Annotated[int, Field(ge=0, alias='txRateBps')] = 0
    rx_rate_bps: Annotated[int, Field(ge=0, alias='rxRateBps')] = 0

    model_config = {'populate_by_name': True, 'extra': 'allow'}


class RadioStatistics(BaseModel):
    """One entry of a device's latest ``interfaces.radios`` (access points only)."""

    frequency_ghz: Annotated[str | None, Field(alias='frequencyGHz')] = None
    tx_retries_pct: Annotated[float | None, Field(alias='txRetriesPct')] = None

    model_config = {'populate_by_name': True, 'extra': 'allow'}


class DeviceStatisticsInterfaces(BaseModel):
    """``interfaces`` of a device's latest statistics: an object, empty for a switch."""

    radios: list[RadioStatistics] = Field(default_factory=list)

    model_config = {'populate_by_name': True, 'extra': 'allow'}


class DeviceStatistics(BaseModel):
    """Latest statistics for an adopted device (``.../devices/{id}/statistics/latest``).

    The aliases are the keys the endpoint sends, as Ubiquiti's Network API reference documents
    and a live switch answered on 2026-10-15 (issue 081). A figure the device did not send is
    ``None``, not 0, so a missing CPU reading cannot pass for an idle CPU; a key this model does
    not know is kept in ``model_extra``. ``device_id`` is not part of the answer: the client
    sets it from the request. ``ports`` and ``temperature_celsius`` are not part of it either;
    they stay empty for an answer the client parses and are filled only by a caller that builds
    the model itself. Both are deprecated and removed in 0.5.0 (issue 095); per-port counters
    come from the classic ``stat/device`` path.
    """

    device_id: Annotated[str, Field(alias='deviceId')] = ''
    uptime_seconds: Annotated[int, Field(ge=0, alias='uptimeSec')] = 0
    last_heartbeat_at: Annotated[datetime | None, Field(alias='lastHeartbeatAt')] = None
    next_heartbeat_at: Annotated[datetime | None, Field(alias='nextHeartbeatAt')] = None
    cpu_utilization_pct: Annotated[
        float | None, Field(ge=0, le=100, alias='cpuUtilizationPct')
    ] = None
    memory_utilization_pct: Annotated[
        float | None, Field(ge=0, le=100, alias='memoryUtilizationPct')
    ] = None
    load_average_1m: Annotated[float | None, Field(alias='loadAverage1Min')] = None
    load_average_5m: Annotated[float | None, Field(alias='loadAverage5Min')] = None
    load_average_15m: Annotated[float | None, Field(alias='loadAverage15Min')] = None
    uplink: DeviceUplinkRates | None = None
    interfaces: DeviceStatisticsInterfaces = Field(default_factory=DeviceStatisticsInterfaces)
    ports: list[PortStatistics] = Field(default_factory=list)
    temperature_celsius: Annotated[float | None, Field(alias='temperatureCelsius')] = None

    model_config = {'populate_by_name': True, 'extra': 'allow'}

    @property
    def uptime_human(self) -> str:
        """Human-readable uptime."""
        seconds = self.uptime_seconds
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f'{days}d')
        if hours:
            parts.append(f'{hours}h')
        if minutes:
            parts.append(f'{minutes}m')
        if secs or not parts:
            parts.append(f'{secs}s')
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


class DevicePortInterface(BaseModel):
    """One entry of a device detail's ``interfaces.ports``.

    The fields are the ones the port diagnostics read from the live Integration API
    (``idx``, ``state``, ``connector``, ``maxSpeedMbps``, ``speedMbps``); any other key the
    console sends is kept in ``model_extra`` rather than dropped (issue 036).
    """

    idx: int | None = None
    state: str | None = None
    connector: str | None = None
    max_speed_mbps: Annotated[int | None, Field(alias='maxSpeedMbps')] = None
    speed_mbps: Annotated[int | None, Field(alias='speedMbps')] = None

    model_config = {'populate_by_name': True, 'extra': 'allow'}


class DeviceInterfaces(BaseModel):
    """A device detail's ``interfaces`` object: ``ports``, plus whatever else the console sends."""

    ports: list[DevicePortInterface] = Field(default_factory=list)

    model_config = {'populate_by_name': True, 'extra': 'allow'}


class DeviceInfo(BaseModel):
    """Information about an adopted UniFi device.

    ``features`` and ``interfaces`` take both shapes the reference sends (issue 036): the
    device list sends lists of names (``features: ["accessPoint"]``), the device detail sends
    objects (``features: {"switching": {...}}``, ``interfaces: {"ports": [...]}``).
    """

    id: str = ''
    mac_address: Annotated[str, Field(alias='macAddress')] = ''
    ip_address: Annotated[str | None, Field(alias='ipAddress')] = None
    name: str = ''
    model: str = ''
    # left_to_right, as for ClientAccess.type: known states are members, unknown ones a str.
    state: Annotated[DeviceState | str, Field(union_mode='left_to_right')] = DeviceState.UNKNOWN
    firmware_version: Annotated[str | None, Field(alias='firmwareVersion')] = None
    firmware_updatable: Annotated[bool, Field(alias='firmwareUpdatable')] = False
    features: list[str] | dict[str, Any] = Field(default_factory=list)
    interfaces: list[str] | DeviceInterfaces = Field(default_factory=list)
    uplink: UplinkInfo | None = None
    supported: bool = True

    model_config = {'populate_by_name': True}

    @property
    def feature_names(self) -> list[str]:
        """The device's features by the reference's names, from either shape.

        A list is returned as sent; for an object, the keys whose value is not null (a key
        with a null value is a feature the device does not have).
        """
        if isinstance(self.features, dict):
            return [name for name, value in self.features.items() if value is not None]
        return list(self.features)

    @property
    def is_switch(self) -> bool:
        """Check if device is a switch (the reference's ``switching`` feature)."""
        return 'switching' in self.feature_names

    @property
    def is_router(self) -> bool:
        """Check if device is a gateway (the reference's ``gateway`` feature)."""
        return 'gateway' in self.feature_names

    @property
    def is_access_point(self) -> bool:
        """Check if device is an access point (the reference's ``accessPoint`` feature)."""
        return 'accessPoint' in self.feature_names


# =============================================================================
# Network Models
# =============================================================================


class DHCPGuarding(BaseModel):
    """DHCP Guarding configuration for a network."""

    enabled: bool = False
    trusted_servers: Annotated[list[str], Field(alias='trustedServers', default_factory=list)]

    model_config = {'populate_by_name': True}


class NetworkPurpose(str, Enum):
    """Network purpose type."""

    CORPORATE = 'CORPORATE'
    GUEST = 'GUEST'
    REMOTE_ACCESS = 'REMOTE_ACCESS'
    WAN = 'WAN'
    VLAN_ONLY = 'VLAN_ONLY'
    HOTSPOT = 'HOTSPOT'
    VPN_CLIENT = 'VPN_CLIENT'


class DHCPMode(str, Enum):
    """DHCP server mode."""

    DHCP_SERVER = 'DHCP_SERVER'
    DHCP_RELAY = 'DHCP_RELAY'
    NONE = 'NONE'


class DHCPConfig(BaseModel):
    """DHCP configuration for a network."""

    mode: DHCPMode = DHCPMode.DHCP_SERVER
    start: str | None = None
    stop: str | None = None
    lease_time: Annotated[int | None, Field(alias='leaseTime')] = None
    dns_enabled: Annotated[bool, Field(alias='dnsEnabled')] = True

    model_config = {'populate_by_name': True}


class NetworkInfo(BaseModel):
    """Information about a network/VLAN."""

    id: str = ''
    name: str = ''
    enabled: bool = True
    vlan_id: Annotated[int | None, Field(alias='vlanId')] = None
    management: str = ''  # 'INTERNAL', 'EXTERNAL'
    purpose: NetworkPurpose | None = None
    subnet: str | None = None
    gateway_ip: Annotated[str | None, Field(alias='gatewayIp')] = None
    gateway_ip6: Annotated[str | None, Field(alias='gatewayIp6')] = None
    domain_name: Annotated[str | None, Field(alias='domainName')] = None
    ipv6_enabled: Annotated[bool, Field(alias='ipv6Enabled')] = False
    nat_mode: Annotated[str | None, Field(alias='natMode')] = None
    internet_access_enabled: Annotated[bool, Field(alias='internetAccessEnabled')] = True
    dhcp_config: Annotated[DHCPConfig | None, Field(alias='dhcpConfig')] = None
    dhcp_guarding: Annotated[DHCPGuarding | None, Field(alias='dhcpGuarding')] = None
    igmp_snooping_enabled: Annotated[bool, Field(alias='igmpSnoopingEnabled')] = False
    multicast_dns_enabled: Annotated[bool, Field(alias='multicastDnsEnabled')] = False
    auto_scale_enabled: Annotated[bool, Field(alias='autoScaleEnabled')] = False
    configurable: bool = True
    origin: str = 'USER'  # 'USER' or 'SYSTEM'

    model_config = {'populate_by_name': True}

    @property
    def is_vlan(self) -> bool:
        """Check if network has a VLAN ID configured."""
        return self.vlan_id is not None

    @property
    def is_guest_network(self) -> bool:
        """Check if this is a guest network."""
        return self.purpose == NetworkPurpose.GUEST

    @property
    def has_dhcp(self) -> bool:
        """Check if DHCP is enabled on this network."""
        if self.dhcp_config is None:
            return False
        return self.dhcp_config.mode == DHCPMode.DHCP_SERVER


class SiteInfo(BaseModel):
    """Information about a UniFi site."""

    id: str = ''
    name: str = ''
    description: str = ''
    time_zone: Annotated[str | None, Field(alias='timeZone')] = None
    locale: str | None = None
    country_code: Annotated[str | None, Field(alias='countryCode')] = None
    device_count: Annotated[int, Field(alias='deviceCount')] = 0
    client_count: Annotated[int, Field(alias='clientCount')] = 0
    gateway_mac: Annotated[str | None, Field(alias='gatewayMac')] = None
    led_enabled: Annotated[bool, Field(alias='ledEnabled')] = True
    uplink_enabled: Annotated[bool, Field(alias='uplinkEnabled')] = True

    model_config = {'populate_by_name': True}

    @property
    def total_devices_and_clients(self) -> int:
        """Total count of devices and clients."""
        return self.device_count + self.client_count


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
            parts.append(f'({self.os_name})')
        return ' '.join(parts) if parts else 'Unknown Device'


class ClientAccess(BaseModel):
    """Client access information."""

    # left_to_right: a known value becomes the enum member, an unknown one stays a str. The
    # default smart union would match every str input to ``str`` and drop the members.
    type: Annotated[ClientAccessType | str, Field(union_mode='left_to_right')] = (
        ClientAccessType.USER
    )
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
    # left_to_right, as for ClientAccess.type: known values are members, unknown ones a str.
    type: Annotated[ClientType | str, Field(union_mode='left_to_right')] = ClientType.WIRED
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

    device_ids: Annotated[list[str] | None, Field(alias='deviceIds', default=None)]

    model_config = {'populate_by_name': True}


class ACLTrafficFilter(BaseModel):
    """ACL traffic source or destination filter."""

    type: str | None = None
    ip_addresses_or_subnets: Annotated[
        list[str], Field(alias='ipAddressesOrSubnets', default_factory=list)
    ]
    # The reference's key is ``portFilter`` (singular); ``portsFilter`` was never sent (issue 036).
    port_filter: Annotated[list[int], Field(alias='portFilter', default_factory=list)]
    network_ids: Annotated[list[str], Field(alias='networkIds', default_factory=list)]
    mac_addresses: Annotated[list[str], Field(alias='macAddresses', default_factory=list)]
    prefix_length: Annotated[int | None, Field(alias='prefixLength')] = None

    model_config = {'populate_by_name': True}


class ACLRuleOrigin(str, Enum):
    """Where an ACL rule came from, as the reference's ``metadata.origin`` names it."""

    USER_DEFINED = 'USER_DEFINED'
    DERIVED = 'DERIVED'


class ACLRuleMetadata(BaseModel):
    """The reference's ``metadata`` object on an ACL rule."""

    # left_to_right, as for ClientAccess.type: known origins are members, unknown ones a str.
    origin: Annotated[ACLRuleOrigin | str | None, Field(union_mode='left_to_right')] = None

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
    source_filter: Annotated[ACLTrafficFilter | None, Field(alias='sourceFilter')] = None
    destination_filter: Annotated[ACLTrafficFilter | None, Field(alias='destinationFilter')] = None
    protocol_filter: Annotated[list[ACLProtocol] | None, Field(alias='protocolFilter')] = None
    network_id: Annotated[str | None, Field(alias='networkId')] = None
    # The reference nests the origin as ``metadata.origin``; a top-level ``origin`` is never
    # sent (issue 036). ``origin`` below reads through to it.
    metadata: ACLRuleMetadata | None = None

    model_config = {'populate_by_name': True}

    @property
    def origin(self) -> str:
        """``metadata.origin`` as a string (``USER_DEFINED``, ``DERIVED``), or ``''`` if unset."""
        if self.metadata is None or self.metadata.origin is None:
            return ''
        origin = self.metadata.origin
        return origin.value if isinstance(origin, ACLRuleOrigin) else origin


# =============================================================================
# DNS Policy Models
# =============================================================================


class DNSRecordType(str, Enum):
    """DNS policy type, as the reference names it (issue 036).

    The console sends and expects ``A_RECORD``, not ``A``; ``FORWARD_DOMAIN`` forwards a
    domain to a DNS server rather than answering a record.
    """

    A_RECORD = 'A_RECORD'
    AAAA_RECORD = 'AAAA_RECORD'
    CNAME_RECORD = 'CNAME_RECORD'
    MX_RECORD = 'MX_RECORD'
    TXT_RECORD = 'TXT_RECORD'
    SRV_RECORD = 'SRV_RECORD'
    FORWARD_DOMAIN = 'FORWARD_DOMAIN'


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
    # The same ``metadata.origin`` object an ACL rule carries (issue 084), so a user-defined
    # policy can be told from a derived one; ``origin`` below reads through to it.
    metadata: ACLRuleMetadata | None = None

    model_config = {'populate_by_name': True}

    @property
    def origin(self) -> str:
        """``metadata.origin`` as a string (``USER_DEFINED``, ``DERIVED``), or ``''`` if unset."""
        if self.metadata is None or self.metadata.origin is None:
            return ''
        origin = self.metadata.origin
        return origin.value if isinstance(origin, ACLRuleOrigin) else origin


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
            return f'{num_bytes:.2f} {unit}'
        num_bytes /= 1024.0  # type: ignore[assignment]
    return f'{num_bytes:.2f} EB'
