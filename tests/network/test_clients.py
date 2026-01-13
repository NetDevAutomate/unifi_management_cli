"""Tests for Client management and fingerprinting module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.clients import (
    ClientManager,
    ClientStats,
    DeviceCategory,
    FingerprintResult,
)
from unifi_mapper.network.models import (
    ClientAccess,
    ClientAccessType,
    ClientFingerprint,
    ClientInfo,
    ClientType,
)
from unittest.mock import AsyncMock, MagicMock


class TestFingerprintResult:
    """Tests for FingerprintResult dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation."""
        result = FingerprintResult(
            client_id='client-1',
            mac_address='AA:BB:CC:DD:EE:FF',
            category=DeviceCategory.COMPUTER,
        )

        assert result.client_id == 'client-1'
        assert result.mac_address == 'AA:BB:CC:DD:EE:FF'
        assert result.category == DeviceCategory.COMPUTER
        assert result.confidence == 0.0

    def test_description_full(self) -> None:
        """Test description with all fields."""
        result = FingerprintResult(
            client_id='client-1',
            mac_address='AA:BB:CC:DD:EE:FF',
            category=DeviceCategory.COMPUTER,
            vendor='Apple',
            device_family='MacBook Pro',
            os_name='macOS 14',
        )

        desc = result.description
        assert 'Apple' in desc
        assert 'MacBook Pro' in desc
        assert 'macOS 14' in desc

    def test_description_partial(self) -> None:
        """Test description with partial fields."""
        result = FingerprintResult(
            client_id='client-1',
            mac_address='AA:BB:CC:DD:EE:FF',
            category=DeviceCategory.MOBILE,
            vendor='Samsung',
        )

        assert result.description == 'Samsung'

    def test_description_unknown(self) -> None:
        """Test description when unknown."""
        result = FingerprintResult(
            client_id='client-1',
            mac_address='AA:BB:CC:DD:EE:FF',
            category=DeviceCategory.UNKNOWN,
        )

        assert 'Unknown' in result.description


class TestClientStats:
    """Tests for ClientStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        stats = ClientStats()

        assert stats.total_clients == 0
        assert stats.wired_clients == 0
        assert stats.wireless_clients == 0
        assert stats.vpn_clients == 0
        assert stats.guest_clients == 0
        assert stats.by_category == {}
        assert stats.by_vendor == {}
        assert stats.by_os == {}

    def test_with_data(self) -> None:
        """Test creation with data."""
        stats = ClientStats(
            total_clients=10,
            wired_clients=3,
            wireless_clients=6,
            vpn_clients=1,
            guest_clients=2,
            by_category={DeviceCategory.COMPUTER: 5, DeviceCategory.MOBILE: 5},
            by_vendor={'Apple': 4, 'Samsung': 3, 'Dell': 3},
            by_os={'Windows': 3, 'macOS': 3, 'iOS': 2, 'Android': 2},
            total_tx_bytes=1000000,
            total_rx_bytes=2000000,
        )

        assert stats.total_clients == 10
        assert len(stats.by_category) == 2
        assert len(stats.by_vendor) == 3


class TestDeviceCategory:
    """Tests for DeviceCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that expected categories exist."""
        expected = [
            'computer', 'mobile', 'tablet', 'smart_tv', 'gaming',
            'iot', 'network', 'printer', 'voip', 'camera',
            'smart_home', 'media_player', 'wearable', 'unknown',
        ]

        for cat in expected:
            assert hasattr(DeviceCategory, cat.upper())

    def test_category_values(self) -> None:
        """Test category string values."""
        assert DeviceCategory.COMPUTER.value == 'computer'
        assert DeviceCategory.MOBILE.value == 'mobile'
        assert DeviceCategory.UNKNOWN.value == 'unknown'


class TestClientManager:
    """Tests for ClientManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_clients = AsyncMock()
        client.authorize_guest = AsyncMock()
        client.unauthorize_guest = AsyncMock()
        return client

    @pytest.fixture
    def sample_clients(self) -> list[ClientInfo]:
        """Create sample client info objects."""
        return [
            ClientInfo(
                id='client-1',
                macAddress='00:11:24:AA:BB:CC',  # Apple OUI
                ipAddress='192.168.1.100',
                hostname='macbook-pro',
                name='John MacBook',
                type=ClientType.WIRELESS,
                txBytes=1000,
                rxBytes=2000,
                fingerprint=ClientFingerprint(
                    devVendor='Apple',
                    devFamily='MacBook Pro',
                    osName='macOS 14',
                ),
            ),
            ClientInfo(
                id='client-2',
                macAddress='AC:5F:3E:DD:EE:FF',  # Samsung OUI
                ipAddress='192.168.1.101',
                hostname='galaxy-phone',
                type=ClientType.WIRELESS,
                txBytes=500,
                rxBytes=1500,
                fingerprint=ClientFingerprint(
                    devVendor='Samsung',
                    osName='Android 14',
                ),
            ),
            ClientInfo(
                id='client-3',
                macAddress='00:14:22:11:22:33',  # Dell OUI
                ipAddress='192.168.1.102',
                hostname='dell-workstation',
                type=ClientType.WIRED,
                txBytes=5000,
                rxBytes=10000,
                fingerprint=ClientFingerprint(
                    devVendor='Dell',
                    osName='Windows 11',
                ),
            ),
            ClientInfo(
                id='client-4',
                macAddress='00:11:22:33:44:55',
                ipAddress='192.168.1.103',
                type=ClientType.WIRELESS,
                access=ClientAccess(type=ClientAccessType.GUEST),
            ),
            ClientInfo(
                id='client-5',
                macAddress='00:50:56:AA:BB:CC',  # VMware OUI
                ipAddress='10.0.0.50',
                hostname='vpn-client',
                type=ClientType.VPN,
                txBytes=100,
                rxBytes=200,
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_clients(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting all clients."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)
        clients = await manager.get_all_clients()

        assert len(clients) == 5
        mock_client.list_clients.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_client_by_mac(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting client by MAC address."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)

        # Exact match
        client = await manager.get_client_by_mac('00:11:24:AA:BB:CC')
        assert client is not None
        assert client.id == 'client-1'

        # Case-insensitive with dashes
        client = await manager.get_client_by_mac('ac-5f-3e-dd-ee-ff')
        assert client is not None
        assert client.id == 'client-2'

        # Not found
        client = await manager.get_client_by_mac('FF:FF:FF:FF:FF:FF')
        assert client is None

    @pytest.mark.asyncio
    async def test_get_client_by_ip(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting client by IP address."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)

        client = await manager.get_client_by_ip('192.168.1.100')
        assert client is not None
        assert client.id == 'client-1'

        client = await manager.get_client_by_ip('10.10.10.10')
        assert client is None

    @pytest.mark.asyncio
    async def test_get_clients_by_type(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting clients by connection type."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)

        wireless = await manager.get_clients_by_type(ClientType.WIRELESS)
        assert len(wireless) == 3

        wired = await manager.get_clients_by_type(ClientType.WIRED)
        assert len(wired) == 1

        vpn = await manager.get_clients_by_type(ClientType.VPN)
        assert len(vpn) == 1

    @pytest.mark.asyncio
    async def test_get_guest_clients(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting guest clients."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)
        guests = await manager.get_guest_clients()

        assert len(guests) == 1
        assert guests[0].id == 'client-4'

    def test_fingerprint_client_with_fingerprint(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test fingerprinting client with fingerprint data."""
        manager = ClientManager(mock_client)

        # Client with full fingerprint
        result = manager.fingerprint_client(sample_clients[0])

        assert result.client_id == 'client-1'
        assert result.category == DeviceCategory.COMPUTER
        assert result.vendor == 'Apple'
        assert result.os_name == 'macOS 14'
        assert result.device_family == 'MacBook Pro'
        assert result.confidence > 0.5

    def test_fingerprint_client_mobile(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test fingerprinting mobile device."""
        manager = ClientManager(mock_client)

        result = manager.fingerprint_client(sample_clients[1])

        assert result.category == DeviceCategory.MOBILE
        assert result.vendor == 'Samsung'
        assert result.os_name == 'Android 14'

    def test_fingerprint_client_oui_fallback(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test fingerprinting using OUI lookup."""
        manager = ClientManager(mock_client)

        # Client with Apple OUI but no fingerprint
        client = ClientInfo(
            id='client-x',
            macAddress='00:11:24:11:22:33',  # Apple OUI
        )

        result = manager.fingerprint_client(client)
        assert result.vendor == 'Apple'
        assert result.confidence > 0

    def test_fingerprint_client_unknown(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test fingerprinting unknown device."""
        manager = ClientManager(mock_client)

        client = ClientInfo(
            id='client-x',
            macAddress='XX:XX:XX:XX:XX:XX',  # Invalid/unknown OUI
        )

        result = manager.fingerprint_client(client)
        assert result.category == DeviceCategory.UNKNOWN
        assert result.confidence == 0.0

    def test_fingerprint_client_hostname_fallback(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test fingerprinting using hostname patterns."""
        manager = ClientManager(mock_client)

        # Device with recognizable hostname
        client = ClientInfo(
            id='client-x',
            macAddress='11:22:33:44:55:66',
            hostname='iphone-johns',
        )

        result = manager.fingerprint_client(client)
        assert result.category == DeviceCategory.MOBILE

    @pytest.mark.asyncio
    async def test_fingerprint_all_clients(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test fingerprinting all clients."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)
        results = await manager.fingerprint_all_clients()

        assert len(results) == 5
        assert all(isinstance(r, FingerprintResult) for r in results)

    @pytest.mark.asyncio
    async def test_get_client_stats(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test getting client statistics."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)
        stats = await manager.get_client_stats()

        assert stats.total_clients == 5
        assert stats.wireless_clients == 3
        assert stats.wired_clients == 1
        assert stats.vpn_clients == 1
        assert stats.guest_clients == 1

        # Check traffic totals
        assert stats.total_tx_bytes > 0
        assert stats.total_rx_bytes > 0

        # Check category breakdown
        assert len(stats.by_category) > 0
        assert DeviceCategory.COMPUTER in stats.by_category

    @pytest.mark.asyncio
    async def test_authorize_guest(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test guest authorization."""
        mock_client.authorize_guest.return_value = {'success': True}

        manager = ClientManager(mock_client)
        result = await manager.authorize_guest(
            client_id='client-4',
            minutes=120,
            down_kbps=10000,
            up_kbps=5000,
        )

        assert result == {'success': True}
        mock_client.authorize_guest.assert_called_once()

    @pytest.mark.asyncio
    async def test_unauthorize_guest(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Test guest unauthorization."""
        mock_client.unauthorize_guest.return_value = {'success': True}

        manager = ClientManager(mock_client)
        result = await manager.unauthorize_guest('client-4')

        assert result == {'success': True}
        mock_client.unauthorize_guest.assert_called_once_with('client-4')

    @pytest.mark.asyncio
    async def test_cache_refresh(
        self,
        mock_client: MagicMock,
        sample_clients: list[ClientInfo],
    ) -> None:
        """Test cache refresh behavior."""
        mock_client.list_clients.return_value = sample_clients

        manager = ClientManager(mock_client)

        # First call fetches
        await manager.get_all_clients()
        assert mock_client.list_clients.call_count == 1

        # Second call uses cache
        await manager.get_all_clients()
        assert mock_client.list_clients.call_count == 1

        # Force refresh
        await manager.get_all_clients(refresh=True)
        assert mock_client.list_clients.call_count == 2


class TestOUILookup:
    """Tests for OUI vendor lookup."""

    @pytest.fixture
    def manager(self) -> ClientManager:
        """Create a ClientManager for testing."""
        mock_client = MagicMock()
        return ClientManager(mock_client)

    def test_apple_oui(self, manager: ClientManager) -> None:
        """Test Apple OUI lookup."""
        result = manager._lookup_vendor('00:11:24:AA:BB:CC')
        assert result == 'Apple'

    def test_samsung_oui(self, manager: ClientManager) -> None:
        """Test Samsung OUI lookup."""
        result = manager._lookup_vendor('AC:5F:3E:AA:BB:CC')
        assert result == 'Samsung'

    def test_dell_oui(self, manager: ClientManager) -> None:
        """Test Dell OUI lookup."""
        result = manager._lookup_vendor('00:14:22:AA:BB:CC')
        assert result == 'Dell'

    def test_intel_oui(self, manager: ClientManager) -> None:
        """Test Intel OUI lookup."""
        result = manager._lookup_vendor('00:50:F2:AA:BB:CC')
        assert result == 'Intel'

    def test_vmware_oui(self, manager: ClientManager) -> None:
        """Test VMware OUI lookup."""
        result = manager._lookup_vendor('00:50:56:AA:BB:CC')
        assert result == 'VMware'

    def test_microsoft_oui(self, manager: ClientManager) -> None:
        """Test Microsoft OUI lookup."""
        result = manager._lookup_vendor('00:15:5D:AA:BB:CC')
        assert result == 'Microsoft'

    def test_unknown_oui(self, manager: ClientManager) -> None:
        """Test unknown OUI."""
        result = manager._lookup_vendor('FF:FF:FF:AA:BB:CC')
        assert result is None

    def test_normalize_mac_dashes(self, manager: ClientManager) -> None:
        """Test MAC normalization with dashes."""
        result = manager._lookup_vendor('00-11-24-AA-BB-CC')
        assert result == 'Apple'

    def test_lowercase_mac(self, manager: ClientManager) -> None:
        """Test lowercase MAC address."""
        result = manager._lookup_vendor('00:11:24:aa:bb:cc')
        assert result == 'Apple'

    def test_empty_mac(self, manager: ClientManager) -> None:
        """Test empty MAC address."""
        result = manager._lookup_vendor('')
        assert result is None

    def test_none_mac(self, manager: ClientManager) -> None:
        """Test None MAC address."""
        result = manager._lookup_vendor(None)  # type: ignore[arg-type]
        assert result is None
