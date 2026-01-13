"""Tests for Network management module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.networks import (
    NetworkManager,
    NetworkStats,
    NetworkSummary,
)
from unifi_mapper.network.models import (
    DHCPConfig,
    DHCPMode,
    NetworkInfo,
    NetworkPurpose,
)
from unittest.mock import AsyncMock, MagicMock


class TestNetworkStats:
    """Tests for NetworkStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        stats = NetworkStats(
            network_id='net-1',
            network_name='Corporate',
        )
        assert stats.network_id == 'net-1'
        assert stats.network_name == 'Corporate'
        assert stats.vlan_id is None
        assert stats.purpose is None
        assert stats.has_dhcp is False
        assert stats.has_ipv6 is False
        assert stats.internet_access is True
        assert stats.is_guest is False

    def test_with_data(self) -> None:
        """Test creation with actual data."""
        stats = NetworkStats(
            network_id='net-1',
            network_name='Guest',
            vlan_id=100,
            purpose=NetworkPurpose.GUEST,
            has_dhcp=True,
            has_ipv6=True,
            internet_access=True,
            is_guest=True,
        )
        assert stats.vlan_id == 100
        assert stats.purpose == NetworkPurpose.GUEST
        assert stats.has_dhcp is True
        assert stats.is_guest is True


class TestNetworkSummary:
    """Tests for NetworkSummary dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        summary = NetworkSummary()
        assert summary.total_networks == 0
        assert summary.enabled_networks == 0
        assert summary.disabled_networks == 0
        assert summary.vlan_networks == 0
        assert summary.corporate_networks == 0
        assert summary.guest_networks == 0
        assert summary.dhcp_enabled_networks == 0
        assert summary.ipv6_enabled_networks == 0
        assert summary.user_networks == 0
        assert summary.system_networks == 0
        assert summary.vlans_in_use == []

    def test_with_counts(self) -> None:
        """Test creation with actual counts."""
        summary = NetworkSummary(
            total_networks=10,
            enabled_networks=8,
            disabled_networks=2,
            vlan_networks=6,
            corporate_networks=4,
            guest_networks=2,
            dhcp_enabled_networks=7,
            ipv6_enabled_networks=3,
            user_networks=8,
            system_networks=2,
            vlans_in_use=[10, 20, 30, 40, 100, 200],
        )
        assert summary.total_networks == 10
        assert summary.vlan_networks == 6
        assert len(summary.vlans_in_use) == 6


class TestNetworkManager:
    """Tests for NetworkManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_networks = AsyncMock()
        client.get_network = AsyncMock()
        client.create_network = AsyncMock()
        client.update_network = AsyncMock()
        client.delete_network = AsyncMock()
        return client

    @pytest.fixture
    def sample_networks(self) -> list[NetworkInfo]:
        """Create sample networks."""
        return [
            NetworkInfo(
                id='net-1',
                name='Default',
                enabled=True,
                purpose=NetworkPurpose.CORPORATE,
                subnet='192.168.1.0/24',
                gateway_ip='192.168.1.1',
                dhcp_config=DHCPConfig(
                    mode=DHCPMode.DHCP_SERVER,
                    start='192.168.1.100',
                    stop='192.168.1.254',
                ),
                origin='SYSTEM',
            ),
            NetworkInfo(
                id='net-2',
                name='IoT VLAN',
                enabled=True,
                vlan_id=10,
                purpose=NetworkPurpose.CORPORATE,
                subnet='192.168.10.0/24',
                gateway_ip='192.168.10.1',
                dhcp_config=DHCPConfig(mode=DHCPMode.DHCP_SERVER),
                internet_access_enabled=True,
                origin='USER',
            ),
            NetworkInfo(
                id='net-3',
                name='Guest Network',
                enabled=True,
                vlan_id=100,
                purpose=NetworkPurpose.GUEST,
                subnet='192.168.100.0/24',
                gateway_ip='192.168.100.1',
                dhcp_config=DHCPConfig(mode=DHCPMode.DHCP_SERVER),
                internet_access_enabled=True,
                origin='USER',
            ),
            NetworkInfo(
                id='net-4',
                name='Disabled Network',
                enabled=False,
                vlan_id=50,
                purpose=NetworkPurpose.CORPORATE,
                origin='USER',
            ),
            NetworkInfo(
                id='net-5',
                name='IPv6 Network',
                enabled=True,
                vlan_id=200,
                purpose=NetworkPurpose.CORPORATE,
                ipv6_enabled=True,
                dhcp_config=DHCPConfig(mode=DHCPMode.DHCP_SERVER),
                origin='USER',
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting all networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_all_networks()

        assert len(networks) == 5
        assert any(n.name == 'Default' for n in networks)

    @pytest.mark.asyncio
    async def test_get_network_by_id(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting network by ID."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)

        network = await manager.get_network_by_id('net-1')
        assert network is not None
        assert network.name == 'Default'

        network = await manager.get_network_by_id('nonexistent')
        assert network is None

    @pytest.mark.asyncio
    async def test_get_network_by_name(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting network by name."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)

        # Case-insensitive search
        network = await manager.get_network_by_name('iot vlan')
        assert network is not None
        assert network.id == 'net-2'

        network = await manager.get_network_by_name('nonexistent')
        assert network is None

    @pytest.mark.asyncio
    async def test_get_network_by_vlan(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting network by VLAN ID."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)

        network = await manager.get_network_by_vlan(100)
        assert network is not None
        assert network.name == 'Guest Network'

        network = await manager.get_network_by_vlan(999)
        assert network is None

    @pytest.mark.asyncio
    async def test_get_enabled_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting enabled networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_enabled_networks()

        assert len(networks) == 4
        assert all(n.enabled for n in networks)

    @pytest.mark.asyncio
    async def test_get_disabled_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting disabled networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_disabled_networks()

        assert len(networks) == 1
        assert networks[0].name == 'Disabled Network'

    @pytest.mark.asyncio
    async def test_get_vlan_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting VLAN networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_vlan_networks()

        assert len(networks) == 4
        assert all(n.vlan_id is not None for n in networks)

    @pytest.mark.asyncio
    async def test_get_guest_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting guest networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_guest_networks()

        assert len(networks) == 1
        assert networks[0].name == 'Guest Network'

    @pytest.mark.asyncio
    async def test_get_corporate_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting corporate networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_corporate_networks()

        assert len(networks) == 4

    @pytest.mark.asyncio
    async def test_get_dhcp_enabled_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting DHCP-enabled networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_dhcp_enabled_networks()

        assert len(networks) == 4
        assert all(n.has_dhcp for n in networks)

    @pytest.mark.asyncio
    async def test_get_ipv6_enabled_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting IPv6-enabled networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        networks = await manager.get_ipv6_enabled_networks()

        assert len(networks) == 1
        assert networks[0].name == 'IPv6 Network'

    @pytest.mark.asyncio
    async def test_search_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test searching networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)

        # Search by name
        results = await manager.search_networks('guest')
        assert len(results) == 1
        assert results[0].name == 'Guest Network'

        # Search by subnet (use full subnet to be specific)
        results = await manager.search_networks('192.168.10.0')
        assert len(results) == 1
        assert results[0].name == 'IoT VLAN'

    @pytest.mark.asyncio
    async def test_get_available_vlan_ids(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting available VLAN IDs."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        available = await manager.get_available_vlan_ids(start=10, end=110)

        # VLANs 10, 50, 100, 200 are used (but 200 is outside our range)
        assert 10 not in available  # Used by IoT VLAN
        assert 50 not in available  # Used by Disabled Network
        assert 100 not in available  # Used by Guest Network
        assert 11 in available
        assert 99 in available

    @pytest.mark.asyncio
    async def test_create_vlan_network(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating a VLAN network."""
        mock_client.list_networks.return_value = []

        new_network = NetworkInfo(
            id='new-net',
            name='New VLAN',
            enabled=True,
            vlan_id=30,
            purpose=NetworkPurpose.CORPORATE,
        )
        mock_client.create_network.return_value = new_network

        manager = NetworkManager(mock_client)
        result = await manager.create_vlan_network(
            name='New VLAN',
            vlan_id=30,
            subnet='192.168.30.0/24',
            gateway_ip='192.168.30.1',
            dhcp_start='192.168.30.100',
            dhcp_stop='192.168.30.254',
        )

        assert result.name == 'New VLAN'
        assert result.vlan_id == 30
        mock_client.create_network.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_guest_network(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating a guest network."""
        mock_client.list_networks.return_value = []

        new_network = NetworkInfo(
            id='guest-net',
            name='New Guest',
            enabled=True,
            vlan_id=150,
            purpose=NetworkPurpose.GUEST,
        )
        mock_client.create_network.return_value = new_network

        manager = NetworkManager(mock_client)
        result = await manager.create_guest_network(
            name='New Guest',
            vlan_id=150,
            subnet='192.168.150.0/24',
            gateway_ip='192.168.150.1',
        )

        assert result.name == 'New Guest'
        mock_client.create_network.assert_called_once()
        # Verify purpose is GUEST
        call_kwargs = mock_client.create_network.call_args
        assert call_kwargs.kwargs.get('purpose') == 'GUEST'

    @pytest.mark.asyncio
    async def test_enable_network(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test enabling a network."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-4',
            name='Disabled Network',
            enabled=True,
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.enable_network('net-4')

        assert result.enabled is True
        mock_client.update_network.assert_called_once_with('net-4', enabled=True)

    @pytest.mark.asyncio
    async def test_disable_network(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test disabling a network."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-1',
            name='Default',
            enabled=False,
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.disable_network('net-1')

        assert result.enabled is False
        mock_client.update_network.assert_called_once_with('net-1', enabled=False)

    @pytest.mark.asyncio
    async def test_update_dhcp_range(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test updating DHCP range."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-1',
            name='Default',
            dhcp_config=DHCPConfig(
                mode=DHCPMode.DHCP_SERVER,
                start='192.168.1.50',
                stop='192.168.1.200',
            ),
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.update_dhcp_range(
            'net-1', '192.168.1.50', '192.168.1.200'
        )

        assert result.dhcp_config is not None
        mock_client.update_network.assert_called_once()

    @pytest.mark.asyncio
    async def test_enable_ipv6(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test enabling IPv6."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-1',
            name='Default',
            ipv6_enabled=True,
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.enable_ipv6('net-1')

        assert result.ipv6_enabled is True
        mock_client.update_network.assert_called_once_with('net-1', ipv6Enabled=True)

    @pytest.mark.asyncio
    async def test_disable_ipv6(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test disabling IPv6."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-5',
            name='IPv6 Network',
            ipv6_enabled=False,
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.disable_ipv6('net-5')

        assert result.ipv6_enabled is False
        mock_client.update_network.assert_called_once_with('net-5', ipv6Enabled=False)

    @pytest.mark.asyncio
    async def test_set_internet_access(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test setting internet access."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-2',
            name='IoT VLAN',
            internet_access_enabled=False,
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.set_internet_access('net-2', False)

        assert result.internet_access_enabled is False
        mock_client.update_network.assert_called_once_with(
            'net-2', internetAccessEnabled=False
        )

    @pytest.mark.asyncio
    async def test_rename_network(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test renaming a network."""
        mock_client.list_networks.return_value = sample_networks

        updated_network = NetworkInfo(
            id='net-2',
            name='Smart Home VLAN',
        )
        mock_client.update_network.return_value = updated_network

        manager = NetworkManager(mock_client)
        result = await manager.rename_network('net-2', 'Smart Home VLAN')

        assert result.name == 'Smart Home VLAN'
        mock_client.update_network.assert_called_once_with(
            'net-2', name='Smart Home VLAN'
        )

    @pytest.mark.asyncio
    async def test_delete_network(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test deleting a network."""
        mock_client.list_networks.return_value = sample_networks
        mock_client.delete_network.return_value = None

        manager = NetworkManager(mock_client)
        result = await manager.delete_network('net-4')

        assert result is True
        mock_client.delete_network.assert_called_once_with('net-4')

    def test_analyze_network(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test analyzing a network."""
        manager = NetworkManager(mock_client)
        stats = manager.analyze_network(sample_networks[2])  # Guest Network

        assert stats.network_id == 'net-3'
        assert stats.network_name == 'Guest Network'
        assert stats.vlan_id == 100
        assert stats.purpose == NetworkPurpose.GUEST
        assert stats.has_dhcp is True
        assert stats.is_guest is True

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test getting network summary."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        summary = await manager.get_summary()

        assert summary.total_networks == 5
        assert summary.enabled_networks == 4
        assert summary.disabled_networks == 1
        assert summary.vlan_networks == 4
        assert summary.corporate_networks == 4
        assert summary.guest_networks == 1
        assert summary.dhcp_enabled_networks == 4
        assert summary.ipv6_enabled_networks == 1
        assert summary.user_networks == 4
        assert summary.system_networks == 1
        assert 10 in summary.vlans_in_use
        assert 100 in summary.vlans_in_use

    @pytest.mark.asyncio
    async def test_export_networks(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test exporting networks."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        exported = await manager.export_networks()

        assert len(exported) == 5
        assert exported[0]['name'] == 'Default'
        assert exported[1]['vlan_id'] == 10
        assert exported[2]['purpose'] == 'GUEST'

    @pytest.mark.asyncio
    async def test_get_network_health_report(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test network health report generation."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)
        report = await manager.get_network_health_report()

        assert 'summary' in report
        assert 'issues' in report
        assert 'recommendations' in report
        assert 'vlans_in_use' in report

        summary = report['summary']
        assert summary['total_networks'] == 5

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_networks: list[NetworkInfo],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_networks.return_value = sample_networks

        manager = NetworkManager(mock_client)

        # First call should fetch
        await manager.get_all_networks()
        assert mock_client.list_networks.call_count == 1

        # Second call should use cache
        await manager.get_all_networks()
        assert mock_client.list_networks.call_count == 1

        # Force refresh
        await manager.get_all_networks(refresh=True)
        assert mock_client.list_networks.call_count == 2
