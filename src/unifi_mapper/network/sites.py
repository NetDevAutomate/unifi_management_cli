"""Site management module.

This module provides tools for managing UniFi sites including
configuration, settings, and multi-site operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unifi_mapper.network.models import SiteInfo


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class SiteStats:
    """Statistics for a site."""

    site_id: str
    site_name: str
    device_count: int = 0
    client_count: int = 0
    total_count: int = 0
    has_gateway: bool = False
    time_zone: str | None = None


@dataclass
class SiteSummary:
    """Summary of all sites."""

    total_sites: int = 0
    total_devices: int = 0
    total_clients: int = 0
    sites_with_gateway: int = 0
    time_zones: list[str] = field(default_factory=list)


class SiteManager:
    """Manage UniFi sites.

    This class provides tools for managing and analyzing sites
    including configuration and multi-site operations.

    Example:
        >>> manager = SiteManager(client)
        >>> sites = await manager.get_all_sites()
        >>> current = await manager.get_current_site()
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the site manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._sites_cache: dict[str, SiteInfo] = {}

    async def refresh_cache(self) -> None:
        """Refresh the sites cache."""
        sites = await self._client.list_sites()
        self._sites_cache = {s.id: s for s in sites}
        log.debug(f"Cached {len(self._sites_cache)} sites")

    async def get_all_sites(self, refresh: bool = False) -> list[SiteInfo]:
        """Get all sites.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of sites.
        """
        if refresh or not self._sites_cache:
            await self.refresh_cache()
        return list(self._sites_cache.values())

    async def get_site_by_id(self, site_id: str) -> SiteInfo | None:
        """Get a site by ID.

        Args:
            site_id: Site UUID.

        Returns:
            Site or None.
        """
        sites = await self.get_all_sites()
        for site in sites:
            if site.id == site_id:
                return site
        return None

    async def get_site_by_name(self, name: str) -> SiteInfo | None:
        """Get a site by name.

        Args:
            name: Site name (case-insensitive).

        Returns:
            Site or None.
        """
        sites = await self.get_all_sites()
        name_lower = name.lower()
        for site in sites:
            if site.name.lower() == name_lower:
                return site
        return None

    async def get_current_site(self) -> SiteInfo:
        """Get the current site.

        Returns:
            Current site information.
        """
        return await self._client.get_current_site()

    async def search_sites(self, query: str) -> list[SiteInfo]:
        """Search sites by name or description.

        Args:
            query: Search query (case-insensitive).

        Returns:
            List of matching sites.
        """
        sites = await self.get_all_sites()
        query_lower = query.lower()
        results = []
        for site in sites:
            if query_lower in site.name.lower():
                results.append(site)
            elif site.description and query_lower in site.description.lower():
                results.append(site)
        return results

    async def get_sites_by_timezone(self, timezone: str) -> list[SiteInfo]:
        """Get sites by timezone.

        Args:
            timezone: Timezone string (e.g., 'America/New_York').

        Returns:
            List of sites in the specified timezone.
        """
        sites = await self.get_all_sites()
        return [
            s for s in sites
            if s.time_zone and s.time_zone.lower() == timezone.lower()
        ]

    async def get_sites_by_country(self, country_code: str) -> list[SiteInfo]:
        """Get sites by country code.

        Args:
            country_code: ISO country code (e.g., 'US', 'GB').

        Returns:
            List of sites in the specified country.
        """
        sites = await self.get_all_sites()
        code_upper = country_code.upper()
        return [
            s for s in sites
            if s.country_code and s.country_code.upper() == code_upper
        ]

    async def rename_site(self, site_id: str, new_name: str) -> SiteInfo:
        """Rename a site.

        Args:
            site_id: Site UUID.
            new_name: New site name.

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, name=new_name)
        self._sites_cache.clear()
        return result

    async def update_site_description(
        self, site_id: str, description: str
    ) -> SiteInfo:
        """Update a site's description.

        Args:
            site_id: Site UUID.
            description: New description.

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, description=description)
        self._sites_cache.clear()
        return result

    async def set_site_timezone(self, site_id: str, timezone: str) -> SiteInfo:
        """Set a site's timezone.

        Args:
            site_id: Site UUID.
            timezone: Timezone string (e.g., 'America/New_York').

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, timeZone=timezone)
        self._sites_cache.clear()
        return result

    async def set_site_country(self, site_id: str, country_code: str) -> SiteInfo:
        """Set a site's country code.

        Args:
            site_id: Site UUID.
            country_code: ISO country code.

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, countryCode=country_code)
        self._sites_cache.clear()
        return result

    async def enable_leds(self, site_id: str) -> SiteInfo:
        """Enable device LEDs for a site.

        Args:
            site_id: Site UUID.

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, ledEnabled=True)
        self._sites_cache.clear()
        return result

    async def disable_leds(self, site_id: str) -> SiteInfo:
        """Disable device LEDs for a site.

        Args:
            site_id: Site UUID.

        Returns:
            Updated site.
        """
        result = await self._client.update_site(site_id, ledEnabled=False)
        self._sites_cache.clear()
        return result

    def analyze_site(self, site: SiteInfo) -> SiteStats:
        """Analyze a site and return statistics.

        Args:
            site: Site to analyze.

        Returns:
            Site statistics.
        """
        return SiteStats(
            site_id=site.id,
            site_name=site.name,
            device_count=site.device_count,
            client_count=site.client_count,
            total_count=site.total_devices_and_clients,
            has_gateway=site.gateway_mac is not None,
            time_zone=site.time_zone,
        )

    async def get_summary(self) -> SiteSummary:
        """Get a summary of all sites.

        Returns:
            Site summary.
        """
        sites = await self.get_all_sites()

        summary = SiteSummary()
        summary.total_sites = len(sites)
        time_zones = set()

        for site in sites:
            summary.total_devices += site.device_count
            summary.total_clients += site.client_count

            if site.gateway_mac:
                summary.sites_with_gateway += 1

            if site.time_zone:
                time_zones.add(site.time_zone)

        summary.time_zones = sorted(time_zones)

        return summary

    async def export_sites(self) -> list[dict[str, Any]]:
        """Export all sites as dictionaries.

        Returns:
            List of site dictionaries.
        """
        sites = await self.get_all_sites()
        return [
            {
                'id': s.id,
                'name': s.name,
                'description': s.description,
                'time_zone': s.time_zone,
                'country_code': s.country_code,
                'device_count': s.device_count,
                'client_count': s.client_count,
                'has_gateway': s.gateway_mac is not None,
                'led_enabled': s.led_enabled,
            }
            for s in sites
        ]

    async def get_largest_sites(self, limit: int = 10) -> list[SiteInfo]:
        """Get the largest sites by total device and client count.

        Args:
            limit: Maximum number of sites to return.

        Returns:
            List of sites sorted by size (descending).
        """
        sites = await self.get_all_sites()
        sorted_sites = sorted(
            sites,
            key=lambda s: s.total_devices_and_clients,
            reverse=True
        )
        return sorted_sites[:limit]

    async def compare_sites(
        self, site_id_1: str, site_id_2: str
    ) -> dict[str, Any]:
        """Compare two sites.

        Args:
            site_id_1: First site UUID.
            site_id_2: Second site UUID.

        Returns:
            Comparison report.
        """
        site1 = await self.get_site_by_id(site_id_1)
        site2 = await self.get_site_by_id(site_id_2)

        if not site1 or not site2:
            return {'error': 'One or both sites not found'}

        return {
            'site1': {
                'name': site1.name,
                'devices': site1.device_count,
                'clients': site1.client_count,
                'total': site1.total_devices_and_clients,
                'timezone': site1.time_zone,
                'has_gateway': site1.gateway_mac is not None,
            },
            'site2': {
                'name': site2.name,
                'devices': site2.device_count,
                'clients': site2.client_count,
                'total': site2.total_devices_and_clients,
                'timezone': site2.time_zone,
                'has_gateway': site2.gateway_mac is not None,
            },
            'comparison': {
                'device_difference': site1.device_count - site2.device_count,
                'client_difference': site1.client_count - site2.client_count,
                'total_difference': (
                    site1.total_devices_and_clients - site2.total_devices_and_clients
                ),
                'same_timezone': site1.time_zone == site2.time_zone,
                'both_have_gateway': (
                    (site1.gateway_mac is not None) and
                    (site2.gateway_mac is not None)
                ),
            },
        }

    async def get_site_health_report(self) -> dict[str, Any]:
        """Generate a health report for all sites.

        Returns:
            Health report with recommendations.
        """
        sites = await self.get_all_sites()
        summary = await self.get_summary()

        issues = []
        recommendations = []

        # Check for sites without gateways
        sites_without_gateway = [s for s in sites if not s.gateway_mac]
        if sites_without_gateway:
            issues.append(
                f"{len(sites_without_gateway)} sites without gateway configured"
            )

        # Check for sites without timezone
        sites_without_tz = [s for s in sites if not s.time_zone]
        if sites_without_tz:
            recommendations.append(
                f"{len(sites_without_tz)} sites have no timezone set - "
                "consider setting for proper time-based features"
            )

        # Check for empty sites
        empty_sites = [
            s for s in sites
            if s.device_count == 0 and s.client_count == 0
        ]
        if empty_sites:
            recommendations.append(
                f"{len(empty_sites)} sites have no devices or clients"
            )

        return {
            'summary': {
                'total_sites': summary.total_sites,
                'total_devices': summary.total_devices,
                'total_clients': summary.total_clients,
                'sites_with_gateway': summary.sites_with_gateway,
            },
            'issues': issues,
            'recommendations': recommendations,
            'time_zones': summary.time_zones,
        }
