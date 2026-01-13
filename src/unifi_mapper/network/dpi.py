"""DPI (Deep Packet Inspection) analytics and traffic visibility.

This module provides tools for analyzing network traffic using
UniFi's DPI categories and applications without deep inspection setup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unifi_mapper.network.models import (
    DPIApplication,
    DPICategory,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class DPICategoryStats:
    """Statistics for a DPI category."""

    category: DPICategory
    application_count: int = 0
    applications: list[DPIApplication] = field(default_factory=list)


@dataclass
class DPIApplicationStats:
    """Extended statistics for a DPI application."""

    application: DPIApplication
    category_name: str = ''
    tx_bytes: int = 0
    rx_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        """Total bytes transferred."""
        return self.tx_bytes + self.rx_bytes

    @property
    def total_bytes_human(self) -> str:
        """Human-readable total bytes."""
        return _bytes_to_human(self.total_bytes)


@dataclass
class TrafficBreakdown:
    """Traffic breakdown by category and application."""

    total_bytes: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_application: dict[str, int] = field(default_factory=dict)
    top_categories: list[tuple[str, int]] = field(default_factory=list)
    top_applications: list[tuple[str, int]] = field(default_factory=list)


class DPIAnalytics:
    """Analyze network traffic using DPI data.

    This class provides tools for understanding network traffic patterns
    using UniFi's DPI categorization system.

    Example:
        >>> analytics = DPIAnalytics(client)
        >>> categories = await analytics.get_categories_with_apps()
        >>> for cat in categories:
        ...     print(f"{cat.category.name}: {cat.application_count} apps")
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize DPI analytics.

        Args:
            client: Network API client.
        """
        self._client = client
        self._categories_cache: dict[int, DPICategory] = {}
        self._applications_cache: dict[int, DPIApplication] = {}

    async def refresh_cache(self) -> None:
        """Refresh the categories and applications cache."""
        categories = await self._client.list_dpi_categories()
        self._categories_cache = {c.id: c for c in categories}

        applications = await self._client.list_dpi_applications()
        self._applications_cache = {a.id: a for a in applications}

        log.debug(
            f"Cached {len(self._categories_cache)} categories, "
            f"{len(self._applications_cache)} applications"
        )

    async def get_categories(self, refresh: bool = False) -> list[DPICategory]:
        """Get all DPI categories.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of DPI categories.
        """
        if refresh or not self._categories_cache:
            await self.refresh_cache()
        return list(self._categories_cache.values())

    async def get_applications(self, refresh: bool = False) -> list[DPIApplication]:
        """Get all DPI applications.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of DPI applications.
        """
        if refresh or not self._applications_cache:
            await self.refresh_cache()
        return list(self._applications_cache.values())

    async def get_category_by_id(self, category_id: int) -> DPICategory | None:
        """Get a category by ID.

        Args:
            category_id: Category ID.

        Returns:
            DPI category or None.
        """
        await self.get_categories()  # Ensure cache is populated
        return self._categories_cache.get(category_id)

    async def get_category_by_name(self, name: str) -> DPICategory | None:
        """Get a category by name.

        Args:
            name: Category name (case-insensitive).

        Returns:
            DPI category or None.
        """
        categories = await self.get_categories()
        for category in categories:
            if category.name.lower() == name.lower():
                return category
        return None

    async def get_applications_by_category(
        self,
        category_id: int,
    ) -> list[DPIApplication]:
        """Get all applications in a category.

        Args:
            category_id: Category ID.

        Returns:
            List of applications in the category.
        """
        applications = await self.get_applications()
        return [a for a in applications if a.category_id == category_id]

    async def get_categories_with_apps(self) -> list[DPICategoryStats]:
        """Get all categories with their applications.

        Returns:
            List of category statistics with applications.
        """
        categories = await self.get_categories()
        applications = await self.get_applications()

        # Group applications by category
        apps_by_category: dict[int, list[DPIApplication]] = {}
        for app in applications:
            if app.category_id is not None:
                if app.category_id not in apps_by_category:
                    apps_by_category[app.category_id] = []
                apps_by_category[app.category_id].append(app)

        # Build category stats
        stats = []
        for category in categories:
            category_apps = apps_by_category.get(category.id, [])
            stats.append(DPICategoryStats(
                category=category,
                application_count=len(category_apps),
                applications=category_apps,
            ))

        # Sort by application count descending
        stats.sort(key=lambda s: s.application_count, reverse=True)
        return stats

    async def search_applications(
        self,
        query: str,
        limit: int = 50,
    ) -> list[DPIApplication]:
        """Search for applications by name.

        Args:
            query: Search query (case-insensitive partial match).
            limit: Maximum results.

        Returns:
            List of matching applications.
        """
        applications = await self.get_applications()
        query_lower = query.lower()

        matching = [
            app for app in applications
            if query_lower in app.name.lower()
        ]

        return matching[:limit]

    async def get_application_details(
        self,
        application_id: int,
    ) -> DPIApplicationStats | None:
        """Get detailed information about an application.

        Args:
            application_id: Application ID.

        Returns:
            Application statistics or None.
        """
        await self.get_applications()  # Ensure cache is populated
        app = self._applications_cache.get(application_id)
        if not app:
            return None

        # Get category name
        category_name = ''
        if app.category_id is not None:
            category = self._categories_cache.get(app.category_id)
            if category:
                category_name = category.name

        return DPIApplicationStats(
            application=app,
            category_name=category_name,
        )

    async def get_summary(self) -> dict:
        """Get a summary of DPI categories and applications.

        Returns:
            Summary dictionary.
        """
        categories = await self.get_categories()
        applications = await self.get_applications()

        # Count applications per category
        apps_per_category: dict[str, int] = {}
        for app in applications:
            if app.category_id is not None:
                category = self._categories_cache.get(app.category_id)
                if category:
                    name = category.name
                    apps_per_category[name] = apps_per_category.get(name, 0) + 1

        # Sort by count
        sorted_categories = sorted(
            apps_per_category.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        return {
            'total_categories': len(categories),
            'total_applications': len(applications),
            'applications_per_category': dict(sorted_categories),
            'categories': [
                {'id': c.id, 'name': c.name}
                for c in sorted(categories, key=lambda c: c.name)
            ],
        }

    def get_common_categories(self) -> list[str]:
        """Get list of common/important DPI categories.

        Returns:
            List of category names commonly used for filtering.
        """
        return [
            'Streaming Media',
            'Social Networking',
            'Web',
            'Cloud Services',
            'Gaming',
            'Video Conferencing',
            'VPN & Proxy',
            'File Sharing',
            'Email',
            'Business',
            'Voice over IP',
            'Network Management',
        ]

    def get_common_applications(self) -> list[str]:
        """Get list of common/important DPI applications.

        Returns:
            List of application names commonly monitored.
        """
        return [
            'Netflix',
            'YouTube',
            'Spotify',
            'Facebook',
            'Instagram',
            'TikTok',
            'Zoom',
            'Microsoft Teams',
            'Slack',
            'Discord',
            'Steam',
            'Xbox Live',
            'PlayStation Network',
            'Apple iCloud',
            'Google Drive',
            'Dropbox',
            'OneDrive',
            'AWS',
            'Azure',
            'Google Cloud',
        ]


def _bytes_to_human(num_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB', 'PB'):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0  # type: ignore[assignment]
    return f"{num_bytes:.2f} EB"
