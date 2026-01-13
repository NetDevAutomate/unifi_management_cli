"""Tests for DPI Analytics module."""

from __future__ import annotations

import pytest
from unifi_mapper.network.dpi import (
    DPIAnalytics,
    DPIApplicationStats,
    DPICategoryStats,
    TrafficBreakdown,
    _bytes_to_human,
)
from unifi_mapper.network.models import (
    DPIApplication,
    DPICategory,
)
from unittest.mock import AsyncMock, MagicMock


class TestDPICategoryStats:
    """Tests for DPICategoryStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation."""
        category = DPICategory(id=1, name='Streaming Media')
        stats = DPICategoryStats(category=category)

        assert stats.category.name == 'Streaming Media'
        assert stats.application_count == 0
        assert stats.applications == []

    def test_with_applications(self) -> None:
        """Test creation with applications."""
        category = DPICategory(id=1, name='Streaming Media')
        apps = [
            DPIApplication(id=100, name='Netflix', categoryId=1),
            DPIApplication(id=101, name='YouTube', categoryId=1),
        ]
        stats = DPICategoryStats(
            category=category,
            application_count=2,
            applications=apps,
        )

        assert stats.application_count == 2
        assert len(stats.applications) == 2


class TestDPIApplicationStats:
    """Tests for DPIApplicationStats dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation."""
        app = DPIApplication(id=100, name='Netflix', categoryId=1)
        stats = DPIApplicationStats(application=app, category_name='Streaming Media')

        assert stats.application.name == 'Netflix'
        assert stats.category_name == 'Streaming Media'
        assert stats.tx_bytes == 0
        assert stats.rx_bytes == 0

    def test_total_bytes(self) -> None:
        """Test total bytes calculation."""
        app = DPIApplication(id=100, name='Netflix', categoryId=1)
        stats = DPIApplicationStats(
            application=app,
            tx_bytes=1000,
            rx_bytes=2000,
        )

        assert stats.total_bytes == 3000

    def test_total_bytes_human(self) -> None:
        """Test human-readable bytes."""
        app = DPIApplication(id=100, name='Netflix', categoryId=1)
        stats = DPIApplicationStats(
            application=app,
            tx_bytes=500000000,  # 500 MB
            rx_bytes=500000000,  # 500 MB
        )

        assert 'MB' in stats.total_bytes_human or 'GB' in stats.total_bytes_human


class TestTrafficBreakdown:
    """Tests for TrafficBreakdown dataclass."""

    def test_basic_creation(self) -> None:
        """Test basic creation."""
        breakdown = TrafficBreakdown()

        assert breakdown.total_bytes == 0
        assert breakdown.by_category == {}
        assert breakdown.by_application == {}

    def test_with_data(self) -> None:
        """Test creation with data."""
        breakdown = TrafficBreakdown(
            total_bytes=1000000,
            by_category={'Streaming': 500000, 'Web': 500000},
            by_application={'Netflix': 300000, 'YouTube': 200000},
            top_categories=[('Streaming', 500000), ('Web', 500000)],
            top_applications=[('Netflix', 300000), ('YouTube', 200000)],
        )

        assert breakdown.total_bytes == 1000000
        assert len(breakdown.by_category) == 2
        assert len(breakdown.top_categories) == 2


class TestBytesToHuman:
    """Tests for _bytes_to_human helper."""

    def test_bytes(self) -> None:
        """Test bytes display."""
        assert _bytes_to_human(500) == '500.00 B'

    def test_kilobytes(self) -> None:
        """Test kilobytes display."""
        result = _bytes_to_human(1536)  # 1.5 KB
        assert 'KB' in result

    def test_megabytes(self) -> None:
        """Test megabytes display."""
        result = _bytes_to_human(1536000)  # ~1.5 MB
        assert 'MB' in result

    def test_gigabytes(self) -> None:
        """Test gigabytes display."""
        result = _bytes_to_human(1073741824)  # 1 GB
        assert 'GB' in result

    def test_terabytes(self) -> None:
        """Test terabytes display."""
        result = _bytes_to_human(1099511627776)  # 1 TB
        assert 'TB' in result


class TestDPIAnalytics:
    """Tests for DPIAnalytics."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Network API client."""
        client = MagicMock()
        client.list_dpi_categories = AsyncMock()
        client.list_dpi_applications = AsyncMock()
        return client

    @pytest.fixture
    def sample_categories(self) -> list[DPICategory]:
        """Create sample DPI categories."""
        return [
            DPICategory(id=1, name='Streaming Media'),
            DPICategory(id=2, name='Social Networking'),
            DPICategory(id=3, name='Gaming'),
        ]

    @pytest.fixture
    def sample_applications(self) -> list[DPIApplication]:
        """Create sample DPI applications."""
        return [
            DPIApplication(id=100, name='Netflix', categoryId=1),
            DPIApplication(id=101, name='YouTube', categoryId=1),
            DPIApplication(id=102, name='Spotify', categoryId=1),
            DPIApplication(id=200, name='Facebook', categoryId=2),
            DPIApplication(id=201, name='Instagram', categoryId=2),
            DPIApplication(id=300, name='Steam', categoryId=3),
        ]

    @pytest.mark.asyncio
    async def test_get_categories(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting DPI categories."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        categories = await analytics.get_categories()

        assert len(categories) == 3
        assert any(c.name == 'Streaming Media' for c in categories)

    @pytest.mark.asyncio
    async def test_get_applications(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting DPI applications."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        applications = await analytics.get_applications()

        assert len(applications) == 6
        assert any(a.name == 'Netflix' for a in applications)

    @pytest.mark.asyncio
    async def test_get_category_by_id(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting category by ID."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        category = await analytics.get_category_by_id(1)

        assert category is not None
        assert category.name == 'Streaming Media'

        # Non-existent
        category = await analytics.get_category_by_id(999)
        assert category is None

    @pytest.mark.asyncio
    async def test_get_category_by_name(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting category by name."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)

        # Case-insensitive
        category = await analytics.get_category_by_name('streaming media')
        assert category is not None
        assert category.name == 'Streaming Media'

        # Non-existent
        category = await analytics.get_category_by_name('Nonexistent')
        assert category is None

    @pytest.mark.asyncio
    async def test_get_applications_by_category(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting applications by category."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        apps = await analytics.get_applications_by_category(1)  # Streaming

        assert len(apps) == 3  # Netflix, YouTube, Spotify
        assert all(a.category_id == 1 for a in apps)

    @pytest.mark.asyncio
    async def test_get_categories_with_apps(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting categories with application counts."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        stats = await analytics.get_categories_with_apps()

        assert len(stats) == 3

        # Sorted by application count descending
        assert stats[0].category.name == 'Streaming Media'
        assert stats[0].application_count == 3

        assert stats[1].category.name == 'Social Networking'
        assert stats[1].application_count == 2

        assert stats[2].category.name == 'Gaming'
        assert stats[2].application_count == 1

    @pytest.mark.asyncio
    async def test_search_applications(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test searching applications."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)

        # Partial match
        results = await analytics.search_applications('net')
        assert len(results) == 1
        assert results[0].name == 'Netflix'

        # Case-insensitive
        results = await analytics.search_applications('STEAM')
        assert len(results) == 1
        assert results[0].name == 'Steam'

        # Multiple matches
        results = await analytics.search_applications('a')  # Facebook, Instagram, Steam
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_applications_limit(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test search limit."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        results = await analytics.search_applications('', limit=2)  # Match all

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_get_application_details(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting application details."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        details = await analytics.get_application_details(100)  # Netflix

        assert details is not None
        assert details.application.name == 'Netflix'
        assert details.category_name == 'Streaming Media'

        # Non-existent
        details = await analytics.get_application_details(999)
        assert details is None

    @pytest.mark.asyncio
    async def test_get_summary(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test getting DPI summary."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)
        summary = await analytics.get_summary()

        assert summary['total_categories'] == 3
        assert summary['total_applications'] == 6
        assert 'applications_per_category' in summary
        assert 'categories' in summary

        # Applications per category should be sorted
        apps_per_cat = summary['applications_per_category']
        values = list(apps_per_cat.values())
        assert values == sorted(values, reverse=True)

    def test_get_common_categories(self, mock_client: MagicMock) -> None:
        """Test getting common categories list."""
        analytics = DPIAnalytics(mock_client)
        categories = analytics.get_common_categories()

        assert len(categories) > 0
        assert 'Streaming Media' in categories
        assert 'Social Networking' in categories
        assert 'Gaming' in categories

    def test_get_common_applications(self, mock_client: MagicMock) -> None:
        """Test getting common applications list."""
        analytics = DPIAnalytics(mock_client)
        applications = analytics.get_common_applications()

        assert len(applications) > 0
        assert 'Netflix' in applications
        assert 'YouTube' in applications
        assert 'Spotify' in applications

    @pytest.mark.asyncio
    async def test_cache_usage(
        self,
        mock_client: MagicMock,
        sample_categories: list[DPICategory],
        sample_applications: list[DPIApplication],
    ) -> None:
        """Test that cache is used properly."""
        mock_client.list_dpi_categories.return_value = sample_categories
        mock_client.list_dpi_applications.return_value = sample_applications

        analytics = DPIAnalytics(mock_client)

        # First call should fetch
        await analytics.get_categories()
        assert mock_client.list_dpi_categories.call_count == 1

        # Second call should use cache
        await analytics.get_categories()
        assert mock_client.list_dpi_categories.call_count == 1

        # Force refresh
        await analytics.get_categories(refresh=True)
        assert mock_client.list_dpi_categories.call_count == 2
