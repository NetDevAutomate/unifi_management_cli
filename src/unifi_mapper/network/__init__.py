"""UniFi Network API integration package.

This package provides async integration with UniFi Network controllers
using the official Network API (10.1.68). It includes:

- Configuration management with Pydantic validation
- Async HTTP client with connection lifecycle management
- Device statistics and real-time metrics
- Firewall zone and policy management with syslog integration
- DPI (Deep Packet Inspection) analytics
- Client fingerprinting and management
- ACL rule automation
- Network/VLAN management
- Site management and multi-site operations

Example:
    >>> from unifi_mapper.network import NetworkConfig, UniFiNetworkClient
    >>>
    >>> config = NetworkConfig.from_env()
    >>> async with UniFiNetworkClient(config) as client:
    ...     stats = await client.get_device_statistics(device_id)
    ...     print(f"Uptime: {stats.uptime_seconds}s")
"""

from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.client import (
    UniFiNetworkClient,
    NetworkClientError,
    NetworkAuthenticationError,
    NetworkConnectionError,
)
from unifi_mapper.network.models import (
    # Device Statistics
    DeviceStatistics,
    PortStatistics,
    InterfaceStatistics,
    CPUMemoryStats,
    # DPI
    DPICategory,
    DPIApplication,
    DPIStats,
    # Client Fingerprinting
    ClientInfo,
    ClientType,
    ClientAccessType,
    ClientFingerprint,
    # Firewall
    FirewallZone,
    FirewallPolicy,
    FirewallAction,
    FirewallActionType,
    ConnectionStateFilter,
    IPSecFilter,
    # Device Info
    DeviceInfo,
    DeviceState,
    DeviceFeature,
    UplinkInfo,
    # Network
    NetworkInfo,
    NetworkPurpose,
    DHCPMode,
    DHCPConfig,
    DHCPGuarding,
    SiteInfo,
    # ACL Rules
    ACLActionType,
    ACLProtocol,
    ACLDeviceFilter,
    ACLTrafficFilter,
    ACLRule,
    # DNS Policies
    DNSPolicy,
    # Traffic Matching Lists
    PortMatching,
    IPAddressMatching,
    TrafficMatchingListType,
    TrafficMatchingList,
)
from unifi_mapper.network.statistics import (
    DeviceMetricsCollector,
    MetricsSnapshot,
    PortMetrics,
)
from unifi_mapper.network.dpi import (
    DPIAnalytics,
    DPICategoryStats,
    DPIApplicationStats,
    TrafficBreakdown,
)
from unifi_mapper.network.firewall import (
    FirewallManager,
    PolicyHitStats,
    ZoneTrafficStats,
)
from unifi_mapper.network.clients import (
    ClientManager,
    ClientStats,
    FingerprintResult,
    DeviceCategory,
)
from unifi_mapper.network.acl import (
    ACLManager,
    ACLRuleStats,
    ACLSummary,
)
from unifi_mapper.network.dns import (
    DNSPolicyManager,
    DNSPolicySummary,
    DNSRecordInfo,
)
from unifi_mapper.network.traffic_matching import (
    TrafficMatchingListManager,
    TrafficListSummary,
    PortListInfo,
    IPAddressListInfo,
)
from unifi_mapper.network.networks import (
    NetworkManager,
    NetworkStats,
    NetworkSummary,
)
from unifi_mapper.network.sites import (
    SiteManager,
    SiteStats,
    SiteSummary,
)


__all__ = [
    # Configuration
    'NetworkConfig',
    # Client
    'UniFiNetworkClient',
    'NetworkClientError',
    'NetworkAuthenticationError',
    'NetworkConnectionError',
    # Device Statistics Models
    'DeviceStatistics',
    'PortStatistics',
    'InterfaceStatistics',
    'CPUMemoryStats',
    # DPI Models
    'DPICategory',
    'DPIApplication',
    'DPIStats',
    # Client Models
    'ClientInfo',
    'ClientType',
    'ClientAccessType',
    'ClientFingerprint',
    # Firewall Models
    'FirewallZone',
    'FirewallPolicy',
    'FirewallAction',
    'FirewallActionType',
    'ConnectionStateFilter',
    'IPSecFilter',
    # Device Models
    'DeviceInfo',
    'DeviceState',
    'DeviceFeature',
    'UplinkInfo',
    # Network Models
    'NetworkInfo',
    'NetworkPurpose',
    'DHCPMode',
    'DHCPConfig',
    'DHCPGuarding',
    'SiteInfo',
    # Statistics Collector
    'DeviceMetricsCollector',
    'MetricsSnapshot',
    'PortMetrics',
    # DPI Analytics
    'DPIAnalytics',
    'DPICategoryStats',
    'DPIApplicationStats',
    'TrafficBreakdown',
    # Firewall Manager
    'FirewallManager',
    'PolicyHitStats',
    'ZoneTrafficStats',
    # Client Manager
    'ClientManager',
    'ClientStats',
    'FingerprintResult',
    'DeviceCategory',
    # ACL Models
    'ACLActionType',
    'ACLProtocol',
    'ACLDeviceFilter',
    'ACLTrafficFilter',
    'ACLRule',
    # DNS Models
    'DNSPolicy',
    # Traffic Matching Models
    'PortMatching',
    'IPAddressMatching',
    'TrafficMatchingListType',
    'TrafficMatchingList',
    # ACL Manager
    'ACLManager',
    'ACLRuleStats',
    'ACLSummary',
    # DNS Manager
    'DNSPolicyManager',
    'DNSPolicySummary',
    'DNSRecordInfo',
    # Traffic Matching Manager
    'TrafficMatchingListManager',
    'TrafficListSummary',
    'PortListInfo',
    'IPAddressListInfo',
    # Network Manager
    'NetworkManager',
    'NetworkStats',
    'NetworkSummary',
    # Site Manager
    'SiteManager',
    'SiteStats',
    'SiteSummary',
]
