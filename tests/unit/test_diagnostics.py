"""Unit tests for diagnostic tools."""

import pytest
from unifi_mcp.tools.diagnostics import (
    connectivity_analysis,
    network_health_check,
    performance_analysis,
    security_audit,
)
from unittest.mock import AsyncMock, patch


class TestDiagnosticTools:
    """Test diagnostic tool functionality."""

    @pytest.mark.asyncio
    async def test_network_health_check_import(self):
        """Test that network health check can be imported."""
        assert callable(network_health_check)

    @pytest.mark.asyncio
    async def test_performance_analysis_import(self):
        """Test that performance analysis can be imported."""
        assert callable(performance_analysis)

    @pytest.mark.asyncio
    async def test_security_audit_import(self):
        """Test that security audit can be imported."""
        assert callable(security_audit)

    @pytest.mark.asyncio
    async def test_connectivity_analysis_import(self):
        """Test that connectivity analysis can be imported."""
        assert callable(connectivity_analysis)

    @pytest.mark.asyncio
    @patch('unifi_mcp.tools.diagnostics.network_health.UniFiClient')
    async def test_network_health_check_with_mock_data(self, mock_client):
        """Test network health check with mock data."""
        # Mock client data
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance

        # Mock API responses
        mock_instance.get.side_effect = [
            # devices_data
            [
                {
                    'mac': '00:11:22:33:44:55',
                    'name': 'Test Switch',
                    'model': 'US-24-250W',
                    'ip': '192.168.1.10',
                    'state': 1,  # Online
                    'adopted': True,
                    'system-stats': {'cpu': 25.0, 'mem': 45.0, 'loadavg_1': 0.5},
                    'uplink': {'up': True, 'uplink_mac': '00:11:22:33:44:66'},
                }
            ],
            # clients_data
            [
                {
                    'mac': 'aa:bb:cc:dd:ee:ff',
                    'name': 'Test Client',
                    'ip': '192.168.1.100',
                    'ap_mac': '00:11:22:33:44:55',
                }
            ],
            # health_data
            [],
        ]

        # Execute the function
        result = await network_health_check()

        # Verify result structure
        assert hasattr(result, 'overall_score')
        assert hasattr(result, 'status')
        assert hasattr(result, 'total_devices')
        assert hasattr(result, 'devices_online')
        assert hasattr(result, 'clients_connected')
        assert hasattr(result, 'recommendations')

        # Verify basic values
        assert result.total_devices == 1
        assert result.devices_online == 1
        assert result.clients_connected == 1
        assert result.overall_score > 0
        assert isinstance(result.recommendations, list)

    @pytest.mark.asyncio
    @patch('unifi_mcp.tools.diagnostics.performance_analysis.UniFiClient')
    async def test_performance_analysis_with_mock_data(self, mock_client):
        """Test performance analysis with mock data."""
        # Mock client data
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance

        # Mock API responses
        mock_instance.get.return_value = [
            {
                'mac': '00:11:22:33:44:55',
                'name': 'Test Switch',
                'model': 'US-24-250W',
                'type': 'usw',
                'system-stats': {'cpu': 25.0, 'mem': 45.0, 'loadavg_1': 0.5},
                'stat': {
                    'sw': {
                        'tx_bytes': 1000000,
                        'rx_bytes': 2000000,
                        'tx_packets': 1000,
                        'rx_packets': 2000,
                        'tx_dropped': 0,
                        'rx_dropped': 0,
                    }
                },
                'uptime': 86400,  # 1 day
            }
        ]

        # Execute the function
        result = await performance_analysis()

        # Verify result structure
        assert hasattr(result, 'total_devices_analyzed')
        assert hasattr(result, 'high_performers')
        assert hasattr(result, 'average_performers')
        assert hasattr(result, 'poor_performers')
        assert hasattr(result, 'optimization_recommendations')

        # Verify basic values
        assert result.total_devices_analyzed >= 0
        assert isinstance(result.optimization_recommendations, list)

    @pytest.mark.asyncio
    @patch('unifi_mcp.tools.diagnostics.security_audit.UniFiClient')
    async def test_security_audit_with_mock_data(self, mock_client):
        """Test security audit with mock data."""
        # Mock client data
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance

        # Mock API responses
        mock_instance.get.side_effect = [
            # devices_data
            [
                {
                    'mac': '00:11:22:33:44:55',
                    'name': 'Test Switch',
                    'adopted': True,
                    'first_seen': 1234567890,
                    'last_seen': 1234567890,
                }
            ],
            # clients_data
            [
                {
                    'mac': 'aa:bb:cc:dd:ee:ff',
                    'name': 'Test Client',
                    'ip': '192.168.1.100',
                    'first_seen': 1234567890,
                    'last_seen': 1234567890,
                }
            ],
            # rogue_aps
            [],
            # networks_data
            [],
        ]

        # Execute the function
        result = await security_audit()

        # Verify result structure
        assert hasattr(result, 'total_devices')
        assert hasattr(result, 'critical_risks')
        assert hasattr(result, 'high_risks')
        assert hasattr(result, 'medium_risks')
        assert hasattr(result, 'immediate_actions')
        assert hasattr(result, 'security_recommendations')

        # Verify basic values
        assert result.total_devices >= 0
        assert isinstance(result.immediate_actions, list)
        assert isinstance(result.security_recommendations, list)

    @pytest.mark.asyncio
    @patch('unifi_mcp.tools.diagnostics.connectivity_analysis.UniFiClient')
    async def test_connectivity_analysis_with_mock_data(self, mock_client):
        """Test connectivity analysis with mock data."""
        # Mock client data
        mock_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_instance

        # Mock API responses
        mock_instance.get.side_effect = [
            # devices_data
            [
                {
                    'mac': '00:11:22:33:44:55',
                    'name': 'Test Switch',
                    'type': 'usw',
                    'model': 'US-24-250W',
                    'state': 1,
                    'adopted': True,
                    'uplink': {'up': True, 'uplink_mac': '00:11:22:33:44:66'},
                    'system-stats': {'cpu': 25.0},
                }
            ],
            # clients_data
            [
                {
                    'mac': 'aa:bb:cc:dd:ee:ff',
                    'name': 'Test Client',
                    'ip': '192.168.1.100',
                    'sw_mac': '00:11:22:33:44:55',
                    'uptime': 3600,
                }
            ],
        ]

        # Execute the function
        result = await connectivity_analysis()

        # Verify result structure
        assert hasattr(result, 'network_connectivity_score')
        assert hasattr(result, 'total_paths_analyzed')
        assert hasattr(result, 'connectivity_issues')
        assert hasattr(result, 'optimization_opportunities')

        # Verify basic values
        assert 0 <= result.network_connectivity_score <= 100
        assert result.total_paths_analyzed >= 0
        assert isinstance(result.connectivity_issues, list)
        assert isinstance(result.optimization_opportunities, list)
