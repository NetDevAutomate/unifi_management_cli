"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError
from unifi_mcp.models import VLAN, Device, FirewallRule, NetworkPath, PathHop, Port


class TestDevice:
    """Test Device model."""

    def test_device_creation_valid(self, sample_device):
        """Test creating device with valid data."""
        assert sample_device.mac == 'aa:bb:cc:dd:ee:ff'
        assert sample_device.name == 'Test Switch'
        assert sample_device.type == 'switch'

    def test_device_is_infrastructure(self, sample_device):
        """Test infrastructure device identification."""
        assert sample_device.is_infrastructure is True

        client_device = Device(
            mac='11:22:33:44:55:66',
            name='Test Client',
            model='Laptop',
            type='client',
        )
        assert client_device.is_infrastructure is False

    def test_device_display_name(self):
        """Test display name property."""
        device_with_name = Device(
            mac='aa:bb:cc:dd:ee:ff',
            name='Switch1',
            model='USW-24',
            type='switch',
        )
        assert device_with_name.display_name == 'Switch1'

        device_without_name = Device(
            mac='aa:bb:cc:dd:ee:ff',
            name='',
            model='USW-24',
            type='switch',
        )
        assert device_without_name.display_name == 'aa:bb:cc:dd:ee:ff'

    def test_device_invalid_type(self):
        """Test device with invalid type."""
        with pytest.raises(ValidationError):
            Device(
                mac='aa:bb:cc:dd:ee:ff',
                name='Invalid',
                model='Unknown',
                type='invalid_type',  # Not in Literal
            )


class TestPort:
    """Test Port model."""

    def test_port_creation_valid(self, sample_port):
        """Test creating port with valid data."""
        assert sample_port.port_idx == 24
        assert sample_port.name == 'Server Connection'
        assert sample_port.duplex == 'full'

    def test_port_has_errors_false(self, sample_port):
        """Test port with no errors."""
        assert sample_port.has_errors is False

    def test_port_has_errors_true(self):
        """Test port with errors."""
        port = Port(
            port_idx=1,
            rx_errors=10,
            tx_dropped=5,
        )
        assert port.has_errors is True

    def test_port_is_half_duplex_false(self, sample_port):
        """Test full duplex port."""
        assert sample_port.is_half_duplex is False

    def test_port_is_half_duplex_true(self):
        """Test half duplex port (problematic)."""
        port = Port(
            port_idx=1,
            duplex='half',
            up=True,
        )
        assert port.is_half_duplex is True

    def test_port_display_label(self, sample_port):
        """Test port display label."""
        assert sample_port.display_label == 'Server Connection (port 24)'

        unnamed_port = Port(port_idx=5)
        assert unnamed_port.display_label == 'Port 5'

    def test_port_invalid_speed(self):
        """Test port with invalid speed."""
        # This should not raise an error - speed is just an int field
        port = Port(port_idx=1, speed=999)
        assert port.speed == 999


class TestVLAN:
    """Test VLAN model."""

    def test_vlan_creation_valid(self, sample_vlan):
        """Test creating VLAN with valid data."""
        assert sample_vlan.id == 10
        assert sample_vlan.name == 'Corporate'
        assert sample_vlan.subnet == '192.168.10.0/24'

    def test_vlan_is_default_true(self):
        """Test default VLAN identification."""
        default_vlan = VLAN(id=1, name='Default')
        assert default_vlan.is_default is True

    def test_vlan_is_default_false(self, sample_vlan):
        """Test non-default VLAN."""
        assert sample_vlan.is_default is False

    def test_vlan_display_name(self, sample_vlan):
        """Test VLAN display name."""
        assert sample_vlan.display_name == 'Corporate (VLAN 10)'

    def test_vlan_invalid_id(self):
        """Test VLAN with invalid ID."""
        # VLAN ID should be 1-4094, but Pydantic doesn't enforce this
        # (validation happens at API level)
        vlan = VLAN(id=5000, name='Invalid')
        assert vlan.id == 5000


class TestFirewallRule:
    """Test FirewallRule model."""

    def test_firewall_rule_creation_valid(self, sample_firewall_rule):
        """Test creating firewall rule with valid data."""
        assert sample_firewall_rule.action == 'deny'
        assert sample_firewall_rule.source == 'IoT VLAN'
        assert sample_firewall_rule.destination == 'Corporate VLAN'

    def test_firewall_rule_is_blocking_true(self, sample_firewall_rule):
        """Test blocking rule identification."""
        assert sample_firewall_rule.is_blocking is True

    def test_firewall_rule_is_blocking_false(self):
        """Test non-blocking rule."""
        allow_rule = FirewallRule(
            id='test',
            name='Allow All',
            action='allow',
            order=200,
        )
        assert allow_rule.is_blocking is False

    def test_firewall_rule_display_summary(self, sample_firewall_rule):
        """Test rule display summary."""
        expected = '❌ Block IoT to Corporate: IoT VLAN → Corporate VLAN (all)'
        assert sample_firewall_rule.display_summary == expected

    def test_firewall_rule_display_summary_with_port(self):
        """Test rule display summary with port."""
        rule = FirewallRule(
            id='test',
            name='Allow HTTP',
            action='allow',
            source='any',
            destination='web server',
            dest_port='80',
            protocol='tcp',
            order=100,
        )
        expected = '✅ Allow HTTP: any → web server:80 (tcp)'
        assert rule.display_summary == expected


class TestNetworkPath:
    """Test NetworkPath and PathHop models."""

    def test_path_hop_creation(self):
        """Test creating path hop."""
        hop = PathHop(
            hop_number=1,
            device_mac='aa:bb:cc:dd:ee:ff',
            device_name='Switch1',
            device_type='switch',
            interface='port24',
            vlan=10,
            latency_ms=1.5,
        )
        assert hop.hop_number == 1
        assert hop.device_type == 'switch'
        assert hop.is_blocked is False

    def test_path_hop_is_blocked_true(self):
        """Test blocked hop."""
        hop = PathHop(
            hop_number=1,
            device_mac='aa:bb:cc:dd:ee:ff',
            device_name='Firewall',
            device_type='gateway',
            interface='eth0',
            firewall_checked=True,
            firewall_result='deny',
            blocking_rule='Block All',
        )
        assert hop.is_blocked is True

    def test_path_hop_display_label(self):
        """Test hop display label."""
        hop = PathHop(
            hop_number=1,
            device_mac='aa:bb:cc:dd:ee:ff',
            device_name='Switch1',
            device_type='switch',
            interface='port24',
            vlan=10,
        )
        assert hop.display_label == 'Switch1:port24 [VLAN 10]'

    def test_network_path_creation(self):
        """Test creating network path."""
        path = NetworkPath(
            source='192.168.1.10',
            source_resolved='aa:bb:cc:dd:ee:ff',
            destination='192.168.1.20',
            destination_resolved='11:22:33:44:55:66',
        )
        assert path.hop_count == 0
        assert path.is_blocked is False
        assert path.vlan_crossing_count == 0

    def test_network_path_properties(self):
        """Test network path computed properties."""
        hop1 = PathHop(
            hop_number=1,
            device_mac='aa:bb:cc:dd:ee:ff',
            device_name='Switch1',
            device_type='switch',
            interface='port24',
            vlan=10,
        )
        hop2 = PathHop(
            hop_number=2,
            device_mac='11:22:33:44:55:66',
            device_name='Switch2',
            device_type='switch',
            interface='port1',
            vlan=20,
        )

        path = NetworkPath(
            source='test1',
            source_resolved='aa:bb:cc:dd:ee:ff',
            destination='test2',
            destination_resolved='11:22:33:44:55:66',
            hops=[hop1, hop2],
            crosses_vlans=True,
            vlans_traversed=[10, 20],
            firewall_verdict='allow',
        )

        assert path.hop_count == 2
        assert path.vlan_crossing_count == 1  # 10 → 20
