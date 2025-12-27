#!/usr/bin/env python3
"""
Comprehensive test suite for VLAN diagnostics and automation.
"""

import pytest
import unittest.mock as mock
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from unifi_mapper.vlan_diagnostics import VLANDiagnostics, VLANInfo, PortVLANConfig
from unifi_mapper.vlan_configurator import VLANConfigurator
from unifi_mapper.network_automation import NetworkAutomation, ConnectivityTest

class TestVLANDiagnostics:
    """Test VLAN diagnostic functionality."""
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client for testing."""
        client = MagicMock()
        client.is_unifi_os = True
        client.base_url = "https://test.local"
        client.timeout = 10
        client.session = MagicMock()
        client._retry_request = MagicMock()
        return client
    
    @pytest.fixture
    def diagnostics(self, mock_api_client):
        """Create VLANDiagnostics instance with mocked client."""
        return VLANDiagnostics(mock_api_client, "default")
    
    def test_vlan_existence_check_missing(self, diagnostics, mock_api_client):
        """Test VLAN existence check with missing VLANs."""
        # Mock empty VLAN configuration
        diagnostics.vlans = {}
        
        result = diagnostics._check_vlan_existence(1, 10)
        
        assert result.status == "FAIL"
        assert "Missing VLANs: [1, 10]" in result.message
        assert len(result.recommendations) > 0
    
    def test_vlan_existence_check_present(self, diagnostics, mock_api_client):
        """Test VLAN existence check with present VLANs."""
        # Mock VLAN configuration
        diagnostics.vlans = {
            1: VLANInfo(1, "Default", "192.168.1.0/24", "192.168.1.1", True, True),
            10: VLANInfo(10, "CCTV", "192.168.10.0/24", "192.168.10.1", True, False)
        }
        
        result = diagnostics._check_vlan_existence(1, 10)
        
        assert result.status == "PASS"
        assert "All VLANs exist and are enabled" in result.message
    
    def test_gateway_configuration_check_missing(self, diagnostics, mock_api_client):
        """Test gateway configuration check with missing gateway."""
        diagnostics.vlans = {
            10: VLANInfo(10, "CCTV", "192.168.10.0/24", "", True, False)
        }
        
        result = diagnostics._check_gateway_configuration(1, 10)
        
        assert result.status == "FAIL"
        assert "VLAN 10 has no gateway configured" in result.message
    
    def test_trunk_configuration_check(self, diagnostics, mock_api_client):
        """Test trunk configuration check."""
        diagnostics.port_configs = [
            PortVLANConfig(24, "device1", "Switch1", 1, [1, 10], "Trunk", True)
        ]
        
        result = diagnostics._check_trunk_configuration(1, 10)
        
        assert result.status == "PASS"
        assert "VLANs found on trunk ports" in result.message

class TestVLANConfigurator:
    """Test VLAN configuration automation."""
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client for testing."""
        client = MagicMock()
        client.is_unifi_os = True
        client.base_url = "https://test.local"
        client.timeout = 10
        client.session = MagicMock()
        client._retry_request = MagicMock()
        return client
    
    @pytest.fixture
    def configurator(self, mock_api_client):
        """Create VLANConfigurator instance with mocked client."""
        return VLANConfigurator(mock_api_client, "default")
    
    def test_create_network_success(self, configurator, mock_api_client):
        """Test successful network creation."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_api_client._retry_request.return_value = mock_response
        
        result = configurator.create_network("Test VLAN", 20, "192.168.20.0/24", "192.168.20.1")
        
        assert result is True
        mock_api_client._retry_request.assert_called_once()
    
    def test_create_network_failure(self, configurator, mock_api_client):
        """Test failed network creation."""
        # Mock failed API response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid configuration"
        mock_api_client._retry_request.return_value = mock_response
        
        result = configurator.create_network("Test VLAN", 20, "192.168.20.0/24", "192.168.20.1")
        
        assert result is False
    
    def test_update_network_gateway(self, configurator, mock_api_client):
        """Test network gateway update."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_api_client._retry_request.return_value = mock_response
        
        result = configurator.update_network_gateway("network123", "192.168.10.1")
        
        assert result is True

class TestNetworkAutomation:
    """Test network automation functionality."""
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client for testing."""
        client = MagicMock()
        client.is_unifi_os = True
        client.base_url = "https://test.local"
        client.timeout = 10
        client.session = MagicMock()
        client._retry_request = MagicMock()
        client.get_devices = MagicMock()
        client.get_lldp_info = MagicMock()
        return client
    
    @pytest.fixture
    def automation(self, mock_api_client):
        """Create NetworkAutomation instance with mocked client."""
        return NetworkAutomation(mock_api_client, "default")
    
    def test_find_uplink_ports(self, automation, mock_api_client):
        """Test uplink port discovery."""
        # Mock device data
        mock_api_client.get_devices.return_value = {
            'data': [
                {
                    '_id': 'device1',
                    'name': 'Switch1',
                    'type': 'usw'
                }
            ]
        }
        
        # Mock LLDP data
        mock_api_client.get_lldp_info.return_value = {
            '24': {'system_name': 'Switch2'}
        }
        
        uplinks = automation.find_uplink_ports()
        
        assert len(uplinks) == 1
        assert uplinks[0]['device_name'] == 'Switch1'
        assert uplinks[0]['port_idx'] == 24
        assert uplinks[0]['connected_to'] == 'Switch2'
    
    @patch('subprocess.run')
    def test_ping_test_success(self, mock_subprocess, automation):
        """Test successful ping test."""
        # Mock successful ping output
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """
PING 192.168.10.1 (192.168.10.1): 56 data bytes
64 bytes from 192.168.10.1: icmp_seq=0 time=1.234 ms
64 bytes from 192.168.10.1: icmp_seq=1 time=2.345 ms
64 bytes from 192.168.10.1: icmp_seq=2 time=1.567 ms

--- 192.168.10.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss
"""
        mock_subprocess.return_value = mock_result
        
        result = automation.ping_test("192.168.10.1", count=3)
        
        assert result.success is True
        assert result.packet_loss == 0.0
        assert result.avg_latency is not None
        assert result.packets_received == 3
    
    @patch('subprocess.run')
    def test_ping_test_failure(self, mock_subprocess, automation):
        """Test failed ping test."""
        # Mock failed ping
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "ping: cannot resolve 192.168.10.1: Unknown host"
        mock_subprocess.return_value = mock_result
        
        result = automation.ping_test("192.168.10.1", count=3)
        
        assert result.success is False
        assert result.packet_loss == 100.0
        assert result.packets_received == 0

class TestIntegration:
    """Integration tests for complete workflows."""
    
    @pytest.fixture
    def mock_api_client(self):
        """Mock API client for integration testing."""
        client = MagicMock()
        client.is_unifi_os = True
        client.base_url = "https://test.local"
        client.timeout = 10
        client.session = MagicMock()
        client._retry_request = MagicMock()
        client.login = MagicMock(return_value=True)
        client.logout = MagicMock()
        return client
    
    def test_full_vlan_fix_workflow(self, mock_api_client):
        """Test complete VLAN fix workflow."""
        # Mock network configuration responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_api_client._retry_request.return_value = mock_response
        
        configurator = VLANConfigurator(mock_api_client, "default")
        
        # Test auto-fix workflow
        results = configurator.auto_fix_vlan_connectivity(
            source_vlan=1,
            dest_vlan=10,
            source_subnet="192.168.125.0/24",
            dest_subnet="192.168.10.0/24",
            source_gateway="192.168.125.1",
            dest_gateway="192.168.10.1"
        )
        
        # Should have attempted all three fixes
        assert len(results) == 3
        assert 'source_vlan_handled' in results
        assert 'dest_vlan_gateway_fixed' in results
        assert 'trunk_profile_created' in results

# Performance and load tests
class TestPerformance:
    """Performance and load testing."""
    
    def test_diagnostic_performance(self):
        """Test diagnostic performance with large datasets."""
        # This would test with large numbers of VLANs and ports
        pass
    
    def test_concurrent_operations(self):
        """Test concurrent API operations."""
        # This would test multiple simultaneous operations
        pass

# Test data fixtures
@pytest.fixture
def sample_vlan_config():
    """Sample VLAN configuration data."""
    return {
        'data': [
            {
                '_id': 'net1',
                'name': 'Default',
                'purpose': 'corporate',
                'ip_subnet': '192.168.125.0/24',
                'gateway_ip': '192.168.125.1',
                'enabled': True
            },
            {
                '_id': 'net2',
                'name': 'CCTV',
                'purpose': 'corporate',
                'vlan_enabled': True,
                'vlan': 10,
                'ip_subnet': '192.168.10.0/24',
                'gateway_ip': '192.168.10.1',
                'enabled': True
            }
        ]
    }

@pytest.fixture
def sample_device_config():
    """Sample device configuration data."""
    return {
        'data': [
            {
                '_id': 'device1',
                'name': 'Core Switch',
                'type': 'usw',
                'port_overrides': [
                    {
                        'port_idx': 24,
                        'portconf_id': 'trunk_profile_id'
                    }
                ]
            }
        ]
    }

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
