"""Tests for Network API models."""

from __future__ import annotations

from unifi_mapper.network.models import (
    ACLActionType,
    ACLDeviceFilter,
    ACLProtocol,
    ACLRule,
    ACLTrafficFilter,
    ClientFingerprint,
    ClientInfo,
    ClientType,
    DeviceInfo,
    DeviceState,
    DeviceStatistics,
    DNSPolicy,
    DPIApplication,
    DPICategory,
    DPIStats,
    FirewallAction,
    FirewallActionType,
    FirewallPolicy,
    FirewallZone,
    IPAddressMatching,
    IPSecFilter,
    NetworkInfo,
    PortMatching,
    PortStatistics,
    TrafficMatchingList,
    TrafficMatchingListType,
)


class TestDeviceStatistics:
    """Tests for DeviceStatistics model."""

    def test_basic_creation(self) -> None:
        """Test basic model creation."""
        stats = DeviceStatistics(
            deviceId='test-device',
            uptimeSeconds=3600,
        )
        assert stats.device_id == 'test-device'
        assert stats.uptime_seconds == 3600

    def test_uptime_human_property(self) -> None:
        """Test human-readable uptime."""
        # Less than a minute
        stats = DeviceStatistics(uptimeSeconds=45)
        assert stats.uptime_human == '45s'

        # Minutes
        stats = DeviceStatistics(uptimeSeconds=125)
        assert stats.uptime_human == '2m 5s'

        # Hours
        stats = DeviceStatistics(uptimeSeconds=3661)
        assert stats.uptime_human == '1h 1m 1s'

        # Days
        stats = DeviceStatistics(uptimeSeconds=90061)
        assert stats.uptime_human == '1d 1h 1m 1s'

    def test_total_bytes_properties(self) -> None:
        """Test total bytes calculation."""
        port1 = PortStatistics(portIdx=1, txBytes=100, rxBytes=200)
        port2 = PortStatistics(portIdx=2, txBytes=300, rxBytes=400)

        stats = DeviceStatistics(ports=[port1, port2])

        assert stats.total_tx_bytes == 400
        assert stats.total_rx_bytes == 600

    def test_cpu_memory_stats(self) -> None:
        """Test CPU/memory stats parsing."""
        stats = DeviceStatistics(
            cpuMemory={
                'cpuUtilizationPercent': 45.5,
                'memoryUtilizationPercent': 62.3,
                'memoryUsedBytes': 1024000,
                'memoryTotalBytes': 2048000,
            }
        )
        assert stats.cpu_memory is not None
        assert stats.cpu_memory.cpu_utilization_percent == 45.5
        assert stats.cpu_memory.memory_utilization_percent == 62.3


class TestPortStatistics:
    """Tests for PortStatistics model."""

    def test_basic_creation(self) -> None:
        """Test basic port stats creation."""
        port = PortStatistics(
            portIdx=1,
            name='Port 1',
            linkUp=True,
            speedMbps=1000,
            txBytes=1000000,
            rxBytes=2000000,
        )
        assert port.port_idx == 1
        assert port.name == 'Port 1'
        assert port.link_up is True
        assert port.speed_mbps == 1000

    def test_human_readable_bytes(self) -> None:
        """Test human-readable byte conversion."""
        port = PortStatistics(
            portIdx=1,
            txBytes=1536000,  # 1.5 MB
            rxBytes=1073741824,  # 1 GB
        )
        assert 'MB' in port.tx_bytes_human
        assert 'GB' in port.rx_bytes_human

    def test_error_rate_calculation(self) -> None:
        """Test error rate calculation."""
        # No packets
        port = PortStatistics(portIdx=1)
        assert port.error_rate == 0.0

        # With errors
        port = PortStatistics(
            portIdx=1,
            txPackets=1000,
            rxPackets=1000,
            txErrors=10,
            rxErrors=10,
        )
        assert port.error_rate == 1.0  # 20 errors out of 2000 packets = 1%


class TestDeviceInfo:
    """Tests for DeviceInfo model."""

    def test_basic_creation(self) -> None:
        """Test basic device info creation."""
        device = DeviceInfo(
            id='device-123',
            macAddress='00:11:22:33:44:55',
            ipAddress='192.168.1.100',
            name='Test Switch',
            model='USW-24-POE',
            state=DeviceState.CONNECTED,
            features=['SWITCH', 'POE'],
        )
        assert device.id == 'device-123'
        assert device.mac_address == '00:11:22:33:44:55'
        assert device.state == DeviceState.CONNECTED

    def test_feature_checks(self) -> None:
        """Test feature check properties."""
        # Switch
        device = DeviceInfo(features=['SWITCH'])
        assert device.is_switch is True
        assert device.is_router is False
        assert device.is_access_point is False

        # Router
        device = DeviceInfo(features=['ROUTER'])
        assert device.is_switch is False
        assert device.is_router is True

        # Gateway
        device = DeviceInfo(features=['GATEWAY'])
        assert device.is_router is True

        # Access Point
        device = DeviceInfo(features=['ACCESS_POINT'])
        assert device.is_access_point is True


class TestClientInfo:
    """Tests for ClientInfo model."""

    def test_basic_creation(self) -> None:
        """Test basic client info creation."""
        client = ClientInfo(
            id='client-123',
            macAddress='AA:BB:CC:DD:EE:FF',
            ipAddress='192.168.1.50',
            hostname='my-laptop',
            type=ClientType.WIRELESS,
        )
        assert client.id == 'client-123'
        assert client.mac_address == 'AA:BB:CC:DD:EE:FF'
        assert client.type == ClientType.WIRELESS

    def test_display_name_property(self) -> None:
        """Test display name selection priority."""
        # Name takes priority
        client = ClientInfo(
            id='123',
            name='Named Device',
            hostname='hostname',
            macAddress='AA:BB:CC:DD:EE:FF',
        )
        assert client.display_name == 'Named Device'

        # Hostname as fallback
        client = ClientInfo(
            id='123',
            hostname='hostname',
            macAddress='AA:BB:CC:DD:EE:FF',
        )
        assert client.display_name == 'hostname'

        # MAC as fallback
        client = ClientInfo(
            id='123',
            macAddress='AA:BB:CC:DD:EE:FF',
        )
        assert client.display_name == 'AA:BB:CC:DD:EE:FF'

        # ID as last resort
        client = ClientInfo(id='123')
        assert client.display_name == '123'


class TestClientFingerprint:
    """Tests for ClientFingerprint model."""

    def test_device_description(self) -> None:
        """Test device description generation."""
        # Full info
        fp = ClientFingerprint(
            devVendor='Apple',
            devFamily='iPhone',
            osName='iOS 17',
        )
        assert 'Apple' in fp.device_description
        assert 'iPhone' in fp.device_description
        assert 'iOS 17' in fp.device_description

        # Partial info
        fp = ClientFingerprint(devVendor='Samsung')
        assert fp.device_description == 'Samsung'

        # No info
        fp = ClientFingerprint()
        assert fp.device_description == 'Unknown Device'


class TestFirewallModels:
    """Tests for firewall-related models."""

    def test_firewall_zone(self) -> None:
        """Test FirewallZone model."""
        zone = FirewallZone(
            id='zone-123',
            name='IoT Zone',
            networkIds=['net-1', 'net-2'],
            configurable=True,
            origin='USER',
        )
        assert zone.id == 'zone-123'
        assert zone.name == 'IoT Zone'
        assert len(zone.network_ids) == 2

    def test_firewall_policy(self) -> None:
        """Test FirewallPolicy model."""
        policy = FirewallPolicy(
            id='policy-123',
            name='Block IoT to WAN',
            enabled=True,
            action=FirewallAction(type=FirewallActionType.BLOCK),
            loggingEnabled=True,
        )
        assert policy.id == 'policy-123'
        assert policy.action.type == FirewallActionType.BLOCK
        assert policy.logging_enabled is True


class TestDPIModels:
    """Tests for DPI-related models."""

    def test_dpi_category(self) -> None:
        """Test DPICategory model."""
        category = DPICategory(id=1, name='Streaming Media')
        assert category.id == 1
        assert category.name == 'Streaming Media'

    def test_dpi_application(self) -> None:
        """Test DPIApplication model."""
        app = DPIApplication(
            id=100,
            name='Netflix',
            categoryId=1,
        )
        assert app.id == 100
        assert app.name == 'Netflix'
        assert app.category_id == 1

    def test_dpi_stats(self) -> None:
        """Test DPIStats model."""
        stats = DPIStats(
            id=100,
            name='Netflix',
            rxBytes=1073741824,  # 1 GB
            txBytes=536870912,   # 512 MB
        )
        assert stats.total_bytes == 1073741824 + 536870912
        assert 'GB' in stats.total_bytes_human


class TestNetworkInfo:
    """Tests for NetworkInfo model."""

    def test_basic_creation(self) -> None:
        """Test basic network info creation."""
        network = NetworkInfo(
            id='net-123',
            name='IoT VLAN',
            enabled=True,
            vlanId=100,
            management='INTERNAL',
        )
        assert network.id == 'net-123'
        assert network.name == 'IoT VLAN'
        assert network.vlan_id == 100

    def test_dhcp_guarding(self) -> None:
        """Test DHCP guarding config."""
        network = NetworkInfo(
            id='net-123',
            name='Test',
            dhcpGuarding={
                'enabled': True,
                'trustedServers': ['192.168.1.1', '192.168.1.2'],
            },
        )
        assert network.dhcp_guarding is not None
        assert network.dhcp_guarding.enabled is True
        assert len(network.dhcp_guarding.trusted_servers) == 2


class TestEnums:
    """Tests for enum types."""

    def test_device_state(self) -> None:
        """Test DeviceState enum."""
        assert DeviceState.CONNECTED.value == 'CONNECTED'
        assert DeviceState.DISCONNECTED.value == 'DISCONNECTED'
        assert DeviceState.PENDING.value == 'PENDING'

    def test_client_type(self) -> None:
        """Test ClientType enum."""
        assert ClientType.WIRED.value == 'WIRED'
        assert ClientType.WIRELESS.value == 'WIRELESS'
        assert ClientType.VPN.value == 'VPN'

    def test_firewall_action_type(self) -> None:
        """Test FirewallActionType enum."""
        assert FirewallActionType.ALLOW.value == 'ALLOW'
        assert FirewallActionType.BLOCK.value == 'BLOCK'
        assert FirewallActionType.REJECT.value == 'REJECT'

    def test_ipsec_filter(self) -> None:
        """Test IPSecFilter enum."""
        assert IPSecFilter.MATCH_ENCRYPTED.value == 'MATCH_ENCRYPTED'
        assert IPSecFilter.MATCH_NOT_ENCRYPTED.value == 'MATCH_NOT_ENCRYPTED'

    def test_acl_action_type(self) -> None:
        """Test ACLActionType enum."""
        assert ACLActionType.ALLOW.value == 'ALLOW'
        assert ACLActionType.BLOCK.value == 'BLOCK'

    def test_acl_protocol(self) -> None:
        """Test ACLProtocol enum."""
        assert ACLProtocol.TCP.value == 'TCP'
        assert ACLProtocol.UDP.value == 'UDP'

    def test_traffic_matching_list_type(self) -> None:
        """Test TrafficMatchingListType enum."""
        assert TrafficMatchingListType.PORT_LIST.value == 'PORT_LIST'
        assert TrafficMatchingListType.IP_ADDRESS_LIST.value == 'IP_ADDRESS_LIST'


class TestACLModels:
    """Tests for ACL-related models."""

    def test_acl_traffic_filter(self) -> None:
        """Test ACLTrafficFilter model."""
        filter_ = ACLTrafficFilter(
            type='SOURCE',
            ipAddressesOrSubnets=['192.168.1.0/24', '10.0.0.0/8'],
            portsFilter=[22, 80, 443],
            macAddresses=['AA:BB:CC:DD:EE:FF'],
            networkIds=['net-1', 'net-2'],
        )
        assert len(filter_.ip_addresses_or_subnets) == 2
        assert 22 in filter_.ports_filter
        assert len(filter_.mac_addresses) == 1
        assert len(filter_.network_ids) == 2

    def test_acl_device_filter(self) -> None:
        """Test ACLDeviceFilter model."""
        filter_ = ACLDeviceFilter(
            deviceIds=['device-1', 'device-2'],
        )
        assert len(filter_.device_ids) == 2

    def test_acl_rule_basic(self) -> None:
        """Test ACLRule model basic creation."""
        rule = ACLRule(
            id='rule-123',
            type='INTER_NETWORK',
            enabled=True,
            name='Block SSH',
            action=ACLActionType.BLOCK,
            origin='USER',
        )
        assert rule.id == 'rule-123'
        assert rule.name == 'Block SSH'
        assert rule.action == ACLActionType.BLOCK
        assert rule.enabled is True
        assert rule.origin == 'USER'

    def test_acl_rule_with_filters(self) -> None:
        """Test ACLRule model with source/destination filters."""
        rule = ACLRule(
            id='rule-123',
            type='INTER_NETWORK',
            name='Complex Rule',
            enabled=True,
            action=ACLActionType.BLOCK,
            sourceFilter=ACLTrafficFilter(
                ipAddressesOrSubnets=['192.168.1.0/24'],
                portsFilter=[22],
            ),
            destinationFilter=ACLTrafficFilter(
                ipAddressesOrSubnets=['10.0.0.0/8'],
            ),
            protocolFilter=[ACLProtocol.TCP],
            enforcingDeviceFilter=ACLDeviceFilter(
                deviceIds=['switch-1'],
            ),
        )
        assert rule.source_filter is not None
        assert rule.destination_filter is not None
        assert len(rule.protocol_filter) == 1
        assert rule.enforcing_device_filter is not None

    def test_acl_rule_defaults(self) -> None:
        """Test ACLRule model default values."""
        rule = ACLRule()
        assert rule.id == ''
        assert rule.enabled is True
        assert rule.action == ACLActionType.BLOCK
        assert rule.source_filter is None
        assert rule.destination_filter is None
        assert rule.protocol_filter is None


class TestDNSPolicyModel:
    """Tests for DNSPolicy model."""

    def test_basic_a_record(self) -> None:
        """Test basic A record DNS policy."""
        policy = DNSPolicy(
            id='policy-123',
            type='A',
            enabled=True,
            domain='server.local',
            ipv4Address='192.168.1.100',
            ttlSeconds=3600,
        )
        assert policy.id == 'policy-123'
        assert policy.type == 'A'
        assert policy.domain == 'server.local'
        assert policy.ipv4_address == '192.168.1.100'
        assert policy.ttl_seconds == 3600

    def test_aaaa_record(self) -> None:
        """Test AAAA record DNS policy."""
        policy = DNSPolicy(
            id='policy-123',
            type='AAAA',
            enabled=True,
            domain='server.local',
            ipv6Address='fd00::100',
            ttlSeconds=3600,
        )
        assert policy.ipv6_address == 'fd00::100'

    def test_cname_record(self) -> None:
        """Test CNAME record DNS policy."""
        policy = DNSPolicy(
            id='policy-123',
            type='CNAME',
            enabled=True,
            domain='www.local',
            targetDomain='server.local',
            ttlSeconds=3600,
        )
        assert policy.target_domain == 'server.local'

    def test_txt_record(self) -> None:
        """Test TXT record DNS policy."""
        policy = DNSPolicy(
            id='policy-123',
            type='TXT',
            enabled=True,
            domain='_dmarc.local',
            text='v=DMARC1; p=none',
            ttlSeconds=86400,
        )
        assert policy.text == 'v=DMARC1; p=none'

    def test_defaults(self) -> None:
        """Test DNSPolicy defaults."""
        policy = DNSPolicy()
        assert policy.enabled is True
        assert policy.ttl_seconds == 3600


class TestTrafficMatchingModels:
    """Tests for Traffic Matching List models."""

    def test_port_matching(self) -> None:
        """Test PortMatching model."""
        port = PortMatching(
            port=443,
            protocol=ACLProtocol.TCP,
        )
        assert port.port == 443
        assert port.protocol == ACLProtocol.TCP

    def test_ip_address_matching(self) -> None:
        """Test IPAddressMatching model."""
        addr = IPAddressMatching(
            ipAddress='192.168.1.100',
            description='Main server',
        )
        assert addr.ip_address == '192.168.1.100'
        assert addr.description == 'Main server'

    def test_ip_address_matching_no_description(self) -> None:
        """Test IPAddressMatching without description."""
        addr = IPAddressMatching(ipAddress='10.0.0.1')
        assert addr.ip_address == '10.0.0.1'
        assert addr.description is None

    def test_traffic_matching_list_port_list(self) -> None:
        """Test TrafficMatchingList as port list."""
        lst = TrafficMatchingList(
            id='list-123',
            type=TrafficMatchingListType.PORT_LIST,
            name='Web Services',
            ports=[
                PortMatching(port=80, protocol=ACLProtocol.TCP),
                PortMatching(port=443, protocol=ACLProtocol.TCP),
            ],
        )
        assert lst.id == 'list-123'
        assert lst.type == TrafficMatchingListType.PORT_LIST
        assert lst.name == 'Web Services'
        assert len(lst.ports) == 2
        assert lst.ip_addresses == []

    def test_traffic_matching_list_ip_list(self) -> None:
        """Test TrafficMatchingList as IP address list."""
        lst = TrafficMatchingList(
            id='list-123',
            type=TrafficMatchingListType.IP_ADDRESS_LIST,
            name='Blocked IPs',
            ipAddresses=[
                IPAddressMatching(ipAddress='10.0.0.100', description='Bad host'),
                IPAddressMatching(ipAddress='10.0.0.101'),
            ],
        )
        assert lst.type == TrafficMatchingListType.IP_ADDRESS_LIST
        assert len(lst.ip_addresses) == 2
        assert lst.ports == []

    def test_traffic_matching_list_defaults(self) -> None:
        """Test TrafficMatchingList default values."""
        lst = TrafficMatchingList()
        assert lst.id == ''
        assert lst.type == TrafficMatchingListType.PORT_LIST
        assert lst.ports == []
        assert lst.ip_addresses == []
