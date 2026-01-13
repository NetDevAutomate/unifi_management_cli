"""Tests for Traffic Matching List management module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.traffic_matching import (
    TrafficMatchingListManager,
    TrafficListSummary,
    PortListInfo,
    IPAddressListInfo,
)
from unifi_mapper.network.models import (
    ACLProtocol,
    PortMatching,
    IPAddressMatching,
    TrafficMatchingList,
    TrafficMatchingListType,
)
from unittest.mock import AsyncMock, MagicMock


class TestTrafficListSummary:
    """Tests for TrafficListSummary dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        summary = TrafficListSummary()
        assert summary.total_lists == 0
        assert summary.port_lists == 0
        assert summary.ip_address_lists == 0
        assert summary.total_ports == 0
        assert summary.total_ip_addresses == 0
        assert summary.unique_ports == set()
        assert summary.unique_protocols == set()

    def test_with_data(self) -> None:
        """Test creation with actual data."""
        summary = TrafficListSummary(
            total_lists=5,
            port_lists=3,
            ip_address_lists=2,
            total_ports=10,
            total_ip_addresses=8,
            unique_ports={22, 80, 443},
            unique_protocols={'TCP', 'UDP'},
        )
        assert summary.total_lists == 5
        assert summary.port_lists == 3
        assert 80 in summary.unique_ports
        assert 'TCP' in summary.unique_protocols


class TestPortListInfo:
    """Tests for PortListInfo dataclass."""

    def test_creation(self) -> None:
        """Test creation with all fields."""
        info = PortListInfo(
            list_id='list-1',
            name='Web Ports',
            ports=[(80, 'TCP'), (443, 'TCP')],
            port_count=2,
        )
        assert info.list_id == 'list-1'
        assert info.name == 'Web Ports'
        assert len(info.ports) == 2
        assert info.port_count == 2


class TestIPAddressListInfo:
    """Tests for IPAddressListInfo dataclass."""

    def test_creation(self) -> None:
        """Test creation with all fields."""
        info = IPAddressListInfo(
            list_id='list-1',
            name='Blocked IPs',
            addresses=['10.0.0.1', '10.0.0.2'],
            address_count=2,
        )
        assert info.list_id == 'list-1'
        assert info.name == 'Blocked IPs'
        assert len(info.addresses) == 2
        assert info.address_count == 2


class TestTrafficMatchingListManager:
    """Tests for TrafficMatchingListManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_traffic_matching_lists = AsyncMock()
        client.create_traffic_matching_list = AsyncMock()
        client.update_traffic_matching_list = AsyncMock()
        client.delete_traffic_matching_list = AsyncMock()
        return client

    @pytest.fixture
    def sample_lists(self) -> list[TrafficMatchingList]:
        """Create sample traffic matching lists."""
        return [
            TrafficMatchingList(
                id='list-1',
                type=TrafficMatchingListType.PORT_LIST,
                name='Web Services',
                ports=[
                    PortMatching(port=80, protocol=ACLProtocol.TCP),
                    PortMatching(port=443, protocol=ACLProtocol.TCP),
                ],
            ),
            TrafficMatchingList(
                id='list-2',
                type=TrafficMatchingListType.PORT_LIST,
                name='DNS',
                ports=[
                    PortMatching(port=53, protocol=ACLProtocol.TCP),
                    PortMatching(port=53, protocol=ACLProtocol.UDP),
                ],
            ),
            TrafficMatchingList(
                id='list-3',
                type=TrafficMatchingListType.IP_ADDRESS_LIST,
                name='Blocked IPs',
                ipAddresses=[
                    IPAddressMatching(ipAddress='10.0.0.100', description='Malicious host'),
                    IPAddressMatching(ipAddress='10.0.0.101'),
                ],
            ),
            TrafficMatchingList(
                id='list-4',
                type=TrafficMatchingListType.IP_ADDRESS_LIST,
                name='Allowed Servers',
                ipAddresses=[
                    IPAddressMatching(ipAddress='192.168.1.1', description='Gateway'),
                    IPAddressMatching(ipAddress='192.168.1.10', description='NAS'),
                    IPAddressMatching(ipAddress='192.168.1.20', description='Server'),
                ],
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_lists(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting all traffic matching lists."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)
        lists = await manager.get_all_lists()

        assert len(lists) == 4
        assert any(lst.name == 'Web Services' for lst in lists)

    @pytest.mark.asyncio
    async def test_get_list_by_id(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting list by ID."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        lst = await manager.get_list_by_id('list-1')
        assert lst is not None
        assert lst.name == 'Web Services'

        lst = await manager.get_list_by_id('nonexistent')
        assert lst is None

    @pytest.mark.asyncio
    async def test_get_list_by_name(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting list by name."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        # Case-insensitive search
        lst = await manager.get_list_by_name('web services')
        assert lst is not None
        assert lst.id == 'list-1'

        lst = await manager.get_list_by_name('nonexistent')
        assert lst is None

    @pytest.mark.asyncio
    async def test_get_port_lists(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting port lists."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)
        lists = await manager.get_port_lists()

        assert len(lists) == 2
        assert all(lst.type == TrafficMatchingListType.PORT_LIST for lst in lists)

    @pytest.mark.asyncio
    async def test_get_ip_address_lists(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting IP address lists."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)
        lists = await manager.get_ip_address_lists()

        assert len(lists) == 2
        assert all(lst.type == TrafficMatchingListType.IP_ADDRESS_LIST for lst in lists)

    @pytest.mark.asyncio
    async def test_search_lists(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test searching lists by name."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        # Partial match
        results = await manager.search_lists('IP')
        assert len(results) == 1
        assert results[0].name == 'Blocked IPs'

        results = await manager.search_lists('server')
        assert len(results) == 1
        assert results[0].name == 'Allowed Servers'

    @pytest.mark.asyncio
    async def test_get_lists_containing_port(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting lists containing a port."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        # Port 80 in Web Services
        results = await manager.get_lists_containing_port(80)
        assert len(results) == 1
        assert results[0].name == 'Web Services'

        # Port 53 in DNS
        results = await manager.get_lists_containing_port(53)
        assert len(results) == 1
        assert results[0].name == 'DNS'

        # Non-existent port
        results = await manager.get_lists_containing_port(12345)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_lists_containing_ip(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting lists containing an IP address."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        results = await manager.get_lists_containing_ip('10.0.0.100')
        assert len(results) == 1
        assert results[0].name == 'Blocked IPs'

        results = await manager.get_lists_containing_ip('192.168.1.1')
        assert len(results) == 1
        assert results[0].name == 'Allowed Servers'

        # Non-existent IP
        results = await manager.get_lists_containing_ip('8.8.8.8')
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_create_port_list(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating a port list."""
        mock_client.list_traffic_matching_lists.return_value = []

        new_list = TrafficMatchingList(
            id='new-list',
            type=TrafficMatchingListType.PORT_LIST,
            name='New Ports',
            ports=[PortMatching(port=22, protocol=ACLProtocol.TCP)],
        )
        mock_client.create_traffic_matching_list.return_value = new_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.create_port_list(
            name='New Ports',
            ports=[(22, 'TCP')],
        )

        assert result.name == 'New Ports'
        mock_client.create_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_port_list_with_protocol_enum(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating a port list with ACLProtocol enum."""
        mock_client.list_traffic_matching_lists.return_value = []

        new_list = TrafficMatchingList(
            id='new-list',
            type=TrafficMatchingListType.PORT_LIST,
            name='New Ports',
            ports=[PortMatching(port=22, protocol=ACLProtocol.TCP)],
        )
        mock_client.create_traffic_matching_list.return_value = new_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.create_port_list(
            name='New Ports',
            ports=[(22, ACLProtocol.TCP)],
        )

        assert result.name == 'New Ports'

    @pytest.mark.asyncio
    async def test_create_ip_address_list(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating an IP address list."""
        mock_client.list_traffic_matching_lists.return_value = []

        new_list = TrafficMatchingList(
            id='new-list',
            type=TrafficMatchingListType.IP_ADDRESS_LIST,
            name='New IPs',
            ipAddresses=[IPAddressMatching(ipAddress='10.0.0.50')],
        )
        mock_client.create_traffic_matching_list.return_value = new_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.create_ip_address_list(
            name='New IPs',
            addresses=['10.0.0.50'],
        )

        assert result.name == 'New IPs'
        mock_client.create_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_ip_address_list_with_descriptions(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test creating an IP address list with descriptions."""
        mock_client.list_traffic_matching_lists.return_value = []

        new_list = TrafficMatchingList(
            id='new-list',
            type=TrafficMatchingListType.IP_ADDRESS_LIST,
            name='New IPs',
            ipAddresses=[IPAddressMatching(ipAddress='10.0.0.50', description='Test server')],
        )
        mock_client.create_traffic_matching_list.return_value = new_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.create_ip_address_list(
            name='New IPs',
            addresses=[('10.0.0.50', 'Test server')],
        )

        assert result.name == 'New IPs'

    @pytest.mark.asyncio
    async def test_rename_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test renaming a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        updated_list = TrafficMatchingList(
            id='list-1',
            type=TrafficMatchingListType.PORT_LIST,
            name='Renamed List',
        )
        mock_client.update_traffic_matching_list.return_value = updated_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.rename_list('list-1', 'Renamed List')

        assert result.name == 'Renamed List'
        mock_client.update_traffic_matching_list.assert_called_once_with('list-1', name='Renamed List')

    @pytest.mark.asyncio
    async def test_add_port_to_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test adding a port to a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        updated_list = TrafficMatchingList(
            id='list-1',
            type=TrafficMatchingListType.PORT_LIST,
            name='Web Services',
            ports=[
                PortMatching(port=80, protocol=ACLProtocol.TCP),
                PortMatching(port=443, protocol=ACLProtocol.TCP),
                PortMatching(port=8080, protocol=ACLProtocol.TCP),
            ],
        )
        mock_client.update_traffic_matching_list.return_value = updated_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.add_port_to_list('list-1', 8080, ACLProtocol.TCP)

        assert len(result.ports) == 3
        mock_client.update_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_port_to_non_port_list_raises(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test adding port to non-port list raises error."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        with pytest.raises(ValueError, match='Cannot add port to non-port list'):
            await manager.add_port_to_list('list-3', 22, ACLProtocol.TCP)

    @pytest.mark.asyncio
    async def test_remove_port_from_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test removing a port from a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        updated_list = TrafficMatchingList(
            id='list-1',
            type=TrafficMatchingListType.PORT_LIST,
            name='Web Services',
            ports=[PortMatching(port=443, protocol=ACLProtocol.TCP)],
        )
        mock_client.update_traffic_matching_list.return_value = updated_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.remove_port_from_list('list-1', 80)

        assert len(result.ports) == 1
        mock_client.update_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_ip_to_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test adding an IP to a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        updated_list = TrafficMatchingList(
            id='list-3',
            type=TrafficMatchingListType.IP_ADDRESS_LIST,
            name='Blocked IPs',
            ipAddresses=[
                IPAddressMatching(ipAddress='10.0.0.100', description='Malicious host'),
                IPAddressMatching(ipAddress='10.0.0.101'),
                IPAddressMatching(ipAddress='10.0.0.102', description='New blocked'),
            ],
        )
        mock_client.update_traffic_matching_list.return_value = updated_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.add_ip_to_list('list-3', '10.0.0.102', 'New blocked')

        assert len(result.ip_addresses) == 3
        mock_client.update_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_ip_to_non_ip_list_raises(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test adding IP to non-IP list raises error."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        with pytest.raises(ValueError, match='Cannot add IP to non-IP-address list'):
            await manager.add_ip_to_list('list-1', '10.0.0.50')

    @pytest.mark.asyncio
    async def test_remove_ip_from_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test removing an IP from a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        updated_list = TrafficMatchingList(
            id='list-3',
            type=TrafficMatchingListType.IP_ADDRESS_LIST,
            name='Blocked IPs',
            ipAddresses=[IPAddressMatching(ipAddress='10.0.0.101')],
        )
        mock_client.update_traffic_matching_list.return_value = updated_list

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.remove_ip_from_list('list-3', '10.0.0.100')

        assert len(result.ip_addresses) == 1
        mock_client.update_traffic_matching_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_list(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test deleting a list."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists
        mock_client.delete_traffic_matching_list.return_value = None

        manager = TrafficMatchingListManager(mock_client)
        result = await manager.delete_list('list-1')

        assert result is True
        mock_client.delete_traffic_matching_list.assert_called_once_with('list-1')

    def test_get_port_list_info(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting port list info."""
        manager = TrafficMatchingListManager(mock_client)

        info = manager.get_port_list_info(sample_lists[0])
        assert info.list_id == 'list-1'
        assert info.name == 'Web Services'
        assert len(info.ports) == 2
        assert info.port_count == 2
        assert (80, 'TCP') in info.ports

    def test_get_ip_list_info(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting IP list info."""
        manager = TrafficMatchingListManager(mock_client)

        info = manager.get_ip_list_info(sample_lists[2])
        assert info.list_id == 'list-3'
        assert info.name == 'Blocked IPs'
        assert len(info.addresses) == 2
        assert info.address_count == 2
        assert '10.0.0.100' in info.addresses

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test getting traffic list summary."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)
        summary = await manager.get_summary()

        assert summary.total_lists == 4
        assert summary.port_lists == 2
        assert summary.ip_address_lists == 2
        assert summary.total_ports == 4  # 80, 443, 53, 53
        assert summary.total_ip_addresses == 5
        assert 80 in summary.unique_ports
        assert 443 in summary.unique_ports
        assert 53 in summary.unique_ports
        assert 'TCP' in summary.unique_protocols
        assert 'UDP' in summary.unique_protocols

    @pytest.mark.asyncio
    async def test_export_lists(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test exporting lists."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)
        exported = await manager.export_lists()

        assert len(exported) == 4
        assert exported[0]['name'] == 'Web Services'
        assert exported[0]['type'] == 'PORT_LIST'
        assert 'ports' in exported[0]
        assert exported[2]['name'] == 'Blocked IPs'
        assert exported[2]['type'] == 'IP_ADDRESS_LIST'
        assert 'ip_addresses' in exported[2]

    @pytest.mark.asyncio
    async def test_get_common_port_lists(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test getting common port list templates."""
        manager = TrafficMatchingListManager(mock_client)
        templates = await manager.get_common_port_lists()

        assert 'Web Services' in templates
        assert 'Email Services' in templates
        assert 'DNS' in templates
        assert 'SSH' in templates
        assert 'Database' in templates

        # Verify Web Services content
        assert (80, 'TCP') in templates['Web Services']
        assert (443, 'TCP') in templates['Web Services']

        # Verify DNS content
        assert (53, 'TCP') in templates['DNS']
        assert (53, 'UDP') in templates['DNS']

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_lists: list[TrafficMatchingList],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_traffic_matching_lists.return_value = sample_lists

        manager = TrafficMatchingListManager(mock_client)

        # First call should fetch
        await manager.get_all_lists()
        assert mock_client.list_traffic_matching_lists.call_count == 1

        # Second call should use cache
        await manager.get_all_lists()
        assert mock_client.list_traffic_matching_lists.call_count == 1

        # Force refresh
        await manager.get_all_lists(refresh=True)
        assert mock_client.list_traffic_matching_lists.call_count == 2

    @pytest.mark.asyncio
    async def test_get_list_not_found_raises(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test getting non-existent list raises error for modifications."""
        mock_client.list_traffic_matching_lists.return_value = []

        manager = TrafficMatchingListManager(mock_client)

        with pytest.raises(ValueError, match='List not found'):
            await manager.add_port_to_list('nonexistent', 80)
