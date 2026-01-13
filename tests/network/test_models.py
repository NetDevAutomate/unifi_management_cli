"""Tests for Network API models."""

from __future__ import annotations

from unifi_mapper.network.models import (
    ClientFingerprint,
    ClientInfo,
    ClientType,
    DeviceInfo,
    DeviceState,
    DeviceStatistics,
    DPIApplication,
    DPICategory,
    DPIStats,
    FirewallAction,
    FirewallActionType,
    FirewallPolicy,
    FirewallZone,
    IPSecFilter,
    NetworkInfo,
    PortStatistics,
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
