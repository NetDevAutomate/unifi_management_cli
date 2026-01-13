"""Tests for Site management module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.sites import (
    SiteManager,
    SiteStats,
    SiteSummary,
)
from unifi_mapper.network.models import SiteInfo
from unittest.mock import AsyncMock, MagicMock


class TestSiteStats:
    """Tests for SiteStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        stats = SiteStats(
            site_id='site-1',
            site_name='Main Site',
        )
        assert stats.site_id == 'site-1'
        assert stats.site_name == 'Main Site'
        assert stats.device_count == 0
        assert stats.client_count == 0
        assert stats.total_count == 0
        assert stats.has_gateway is False
        assert stats.time_zone is None

    def test_with_data(self) -> None:
        """Test creation with actual data."""
        stats = SiteStats(
            site_id='site-1',
            site_name='Main Site',
            device_count=10,
            client_count=50,
            total_count=60,
            has_gateway=True,
            time_zone='America/New_York',
        )
        assert stats.device_count == 10
        assert stats.client_count == 50
        assert stats.total_count == 60
        assert stats.has_gateway is True
        assert stats.time_zone == 'America/New_York'


class TestSiteSummary:
    """Tests for SiteSummary dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation with defaults."""
        summary = SiteSummary()
        assert summary.total_sites == 0
        assert summary.total_devices == 0
        assert summary.total_clients == 0
        assert summary.sites_with_gateway == 0
        assert summary.time_zones == []

    def test_with_counts(self) -> None:
        """Test creation with actual counts."""
        summary = SiteSummary(
            total_sites=5,
            total_devices=100,
            total_clients=500,
            sites_with_gateway=4,
            time_zones=['America/New_York', 'America/Los_Angeles', 'Europe/London'],
        )
        assert summary.total_sites == 5
        assert summary.total_devices == 100
        assert summary.total_clients == 500
        assert summary.sites_with_gateway == 4
        assert len(summary.time_zones) == 3


class TestSiteManager:
    """Tests for SiteManager."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_sites = AsyncMock()
        client.get_site = AsyncMock()
        client.get_current_site = AsyncMock()
        client.update_site = AsyncMock()
        return client

    @pytest.fixture
    def sample_sites(self) -> list[SiteInfo]:
        """Create sample sites."""
        return [
            SiteInfo(
                id='site-1',
                name='Headquarters',
                description='Main office',
                time_zone='America/New_York',
                country_code='US',
                device_count=50,
                client_count=200,
                gateway_mac='00:11:22:33:44:55',
                led_enabled=True,
            ),
            SiteInfo(
                id='site-2',
                name='West Coast Office',
                description='LA office',
                time_zone='America/Los_Angeles',
                country_code='US',
                device_count=30,
                client_count=100,
                gateway_mac='AA:BB:CC:DD:EE:FF',
                led_enabled=True,
            ),
            SiteInfo(
                id='site-3',
                name='London Office',
                description='UK office',
                time_zone='Europe/London',
                country_code='GB',
                device_count=20,
                client_count=75,
                gateway_mac='11:22:33:44:55:66',
                led_enabled=False,
            ),
            SiteInfo(
                id='site-4',
                name='Remote Site',
                description='Small remote location',
                device_count=5,
                client_count=10,
                gateway_mac=None,  # No gateway
                led_enabled=True,
            ),
            SiteInfo(
                id='site-5',
                name='Empty Site',
                description='Inactive site',
                time_zone='America/New_York',
                device_count=0,
                client_count=0,
                gateway_mac=None,
                led_enabled=True,
            ),
        ]

    @pytest.mark.asyncio
    async def test_get_all_sites(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting all sites."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        sites = await manager.get_all_sites()

        assert len(sites) == 5
        assert any(s.name == 'Headquarters' for s in sites)

    @pytest.mark.asyncio
    async def test_get_site_by_id(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting site by ID."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)

        site = await manager.get_site_by_id('site-1')
        assert site is not None
        assert site.name == 'Headquarters'

        site = await manager.get_site_by_id('nonexistent')
        assert site is None

    @pytest.mark.asyncio
    async def test_get_site_by_name(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting site by name."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)

        # Case-insensitive search
        site = await manager.get_site_by_name('headquarters')
        assert site is not None
        assert site.id == 'site-1'

        site = await manager.get_site_by_name('nonexistent')
        assert site is None

    @pytest.mark.asyncio
    async def test_get_current_site(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting current site."""
        mock_client.get_current_site.return_value = sample_sites[0]

        manager = SiteManager(mock_client)
        site = await manager.get_current_site()

        assert site.name == 'Headquarters'
        mock_client.get_current_site.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_sites(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test searching sites."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)

        # Search by name
        results = await manager.search_sites('office')
        assert len(results) == 3

        # Search by description
        results = await manager.search_sites('main')
        assert len(results) == 1
        assert results[0].name == 'Headquarters'

    @pytest.mark.asyncio
    async def test_get_sites_by_timezone(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting sites by timezone."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        sites = await manager.get_sites_by_timezone('America/New_York')

        assert len(sites) == 2
        assert all(
            s.time_zone == 'America/New_York'
            for s in sites
        )

    @pytest.mark.asyncio
    async def test_get_sites_by_country(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting sites by country."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)

        # Case-insensitive
        us_sites = await manager.get_sites_by_country('us')
        assert len(us_sites) == 2

        uk_sites = await manager.get_sites_by_country('GB')
        assert len(uk_sites) == 1
        assert uk_sites[0].name == 'London Office'

    @pytest.mark.asyncio
    async def test_rename_site(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test renaming a site."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-1',
            name='Main Headquarters',
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.rename_site('site-1', 'Main Headquarters')

        assert result.name == 'Main Headquarters'
        mock_client.update_site.assert_called_once_with('site-1', name='Main Headquarters')

    @pytest.mark.asyncio
    async def test_update_site_description(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test updating site description."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-1',
            name='Headquarters',
            description='Corporate headquarters',
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.update_site_description('site-1', 'Corporate headquarters')

        assert result.description == 'Corporate headquarters'
        mock_client.update_site.assert_called_once_with(
            'site-1', description='Corporate headquarters'
        )

    @pytest.mark.asyncio
    async def test_set_site_timezone(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test setting site timezone."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-4',
            name='Remote Site',
            time_zone='America/Chicago',
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.set_site_timezone('site-4', 'America/Chicago')

        assert result.time_zone == 'America/Chicago'
        mock_client.update_site.assert_called_once_with(
            'site-4', timeZone='America/Chicago'
        )

    @pytest.mark.asyncio
    async def test_set_site_country(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test setting site country code."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-4',
            name='Remote Site',
            country_code='CA',
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.set_site_country('site-4', 'CA')

        assert result.country_code == 'CA'
        mock_client.update_site.assert_called_once_with('site-4', countryCode='CA')

    @pytest.mark.asyncio
    async def test_enable_leds(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test enabling LEDs."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-3',
            name='London Office',
            led_enabled=True,
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.enable_leds('site-3')

        assert result.led_enabled is True
        mock_client.update_site.assert_called_once_with('site-3', ledEnabled=True)

    @pytest.mark.asyncio
    async def test_disable_leds(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test disabling LEDs."""
        mock_client.list_sites.return_value = sample_sites

        updated_site = SiteInfo(
            id='site-1',
            name='Headquarters',
            led_enabled=False,
        )
        mock_client.update_site.return_value = updated_site

        manager = SiteManager(mock_client)
        result = await manager.disable_leds('site-1')

        assert result.led_enabled is False
        mock_client.update_site.assert_called_once_with('site-1', ledEnabled=False)

    def test_analyze_site(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test analyzing a site."""
        manager = SiteManager(mock_client)
        stats = manager.analyze_site(sample_sites[0])

        assert stats.site_id == 'site-1'
        assert stats.site_name == 'Headquarters'
        assert stats.device_count == 50
        assert stats.client_count == 200
        assert stats.total_count == 250
        assert stats.has_gateway is True
        assert stats.time_zone == 'America/New_York'

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting site summary."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        summary = await manager.get_summary()

        assert summary.total_sites == 5
        assert summary.total_devices == 105  # 50+30+20+5+0
        assert summary.total_clients == 385  # 200+100+75+10+0
        assert summary.sites_with_gateway == 3  # sites 1, 2, 3 have gateways
        assert 'America/New_York' in summary.time_zones
        assert 'America/Los_Angeles' in summary.time_zones
        assert 'Europe/London' in summary.time_zones

    @pytest.mark.asyncio
    async def test_export_sites(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test exporting sites."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        exported = await manager.export_sites()

        assert len(exported) == 5
        assert exported[0]['name'] == 'Headquarters'
        assert exported[0]['device_count'] == 50
        assert exported[0]['has_gateway'] is True
        assert exported[3]['has_gateway'] is False

    @pytest.mark.asyncio
    async def test_get_largest_sites(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test getting largest sites."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        largest = await manager.get_largest_sites(limit=3)

        assert len(largest) == 3
        # Should be sorted by total count descending
        assert largest[0].name == 'Headquarters'  # 250 total
        assert largest[1].name == 'West Coast Office'  # 130 total
        assert largest[2].name == 'London Office'  # 95 total

    @pytest.mark.asyncio
    async def test_compare_sites(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test comparing two sites."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        comparison = await manager.compare_sites('site-1', 'site-2')

        assert 'site1' in comparison
        assert 'site2' in comparison
        assert 'comparison' in comparison

        assert comparison['site1']['name'] == 'Headquarters'
        assert comparison['site2']['name'] == 'West Coast Office'
        assert comparison['comparison']['device_difference'] == 20  # 50 - 30
        assert comparison['comparison']['client_difference'] == 100  # 200 - 100
        assert comparison['comparison']['same_timezone'] is False
        assert comparison['comparison']['both_have_gateway'] is True

    @pytest.mark.asyncio
    async def test_compare_sites_not_found(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test comparing sites when one is not found."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        comparison = await manager.compare_sites('site-1', 'nonexistent')

        assert 'error' in comparison

    @pytest.mark.asyncio
    async def test_get_site_health_report(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test site health report generation."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)
        report = await manager.get_site_health_report()

        assert 'summary' in report
        assert 'issues' in report
        assert 'recommendations' in report
        assert 'time_zones' in report

        summary = report['summary']
        assert summary['total_sites'] == 5
        assert summary['total_devices'] == 105
        assert summary['sites_with_gateway'] == 3

        # Should detect sites without gateways
        assert len(report['issues']) > 0

        # Should recommend timezone for sites without one
        assert len(report['recommendations']) > 0

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_sites: list[SiteInfo],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_sites.return_value = sample_sites

        manager = SiteManager(mock_client)

        # First call should fetch
        await manager.get_all_sites()
        assert mock_client.list_sites.call_count == 1

        # Second call should use cache
        await manager.get_all_sites()
        assert mock_client.list_sites.call_count == 1

        # Force refresh
        await manager.get_all_sites(refresh=True)
        assert mock_client.list_sites.call_count == 2
