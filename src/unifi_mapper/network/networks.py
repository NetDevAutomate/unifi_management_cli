"""Network management module.

This module provides tools for managing UniFi networks including
VLANs, subnets, DHCP configuration, and network policies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unifi_mapper.network.models import (
    DHCPMode,
    NetworkInfo,
    NetworkPurpose,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class NetworkStats:
    """Statistics for a network."""

    network_id: str
    network_name: str
    vlan_id: int | None = None
    purpose: NetworkPurpose | None = None
    has_dhcp: bool = False
    has_ipv6: bool = False
    internet_access: bool = True
    is_guest: bool = False


@dataclass
class NetworkSummary:
    """Summary of networks on a site."""

    total_networks: int = 0
    enabled_networks: int = 0
    disabled_networks: int = 0
    vlan_networks: int = 0
    corporate_networks: int = 0
    guest_networks: int = 0
    dhcp_enabled_networks: int = 0
    ipv6_enabled_networks: int = 0
    user_networks: int = 0
    system_networks: int = 0
    vlans_in_use: list[int] = field(default_factory=list)


class NetworkManager:
    """Manage UniFi networks.

    This class provides tools for managing and analyzing networks
    including VLANs, subnets, and DHCP configuration.

    Example:
        >>> manager = NetworkManager(client)
        >>> networks = await manager.get_all_networks()
        >>> summary = await manager.get_summary()
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the network manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._networks_cache: dict[str, NetworkInfo] = {}

    async def refresh_cache(self) -> None:
        """Refresh the networks cache."""
        networks = await self._client.list_networks()
        self._networks_cache = {n.id: n for n in networks}
        log.debug(f"Cached {len(self._networks_cache)} networks")

    async def get_all_networks(self, refresh: bool = False) -> list[NetworkInfo]:
        """Get all networks.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of networks.
        """
        if refresh or not self._networks_cache:
            await self.refresh_cache()
        return list(self._networks_cache.values())

    async def get_network_by_id(self, network_id: str) -> NetworkInfo | None:
        """Get a network by ID.

        Args:
            network_id: Network UUID.

        Returns:
            Network or None.
        """
        networks = await self.get_all_networks()
        for network in networks:
            if network.id == network_id:
                return network
        return None

    async def get_network_by_name(self, name: str) -> NetworkInfo | None:
        """Get a network by name.

        Args:
            name: Network name (case-insensitive).

        Returns:
            Network or None.
        """
        networks = await self.get_all_networks()
        name_lower = name.lower()
        for network in networks:
            if network.name.lower() == name_lower:
                return network
        return None

    async def get_network_by_vlan(self, vlan_id: int) -> NetworkInfo | None:
        """Get a network by VLAN ID.

        Args:
            vlan_id: VLAN ID.

        Returns:
            Network or None.
        """
        networks = await self.get_all_networks()
        for network in networks:
            if network.vlan_id == vlan_id:
                return network
        return None

    async def get_enabled_networks(self) -> list[NetworkInfo]:
        """Get all enabled networks.

        Returns:
            List of enabled networks.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if n.enabled]

    async def get_disabled_networks(self) -> list[NetworkInfo]:
        """Get all disabled networks.

        Returns:
            List of disabled networks.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if not n.enabled]

    async def get_vlan_networks(self) -> list[NetworkInfo]:
        """Get all networks with VLAN IDs.

        Returns:
            List of VLAN networks.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if n.vlan_id is not None]

    async def get_networks_by_purpose(
        self, purpose: NetworkPurpose
    ) -> list[NetworkInfo]:
        """Get networks by purpose.

        Args:
            purpose: Network purpose.

        Returns:
            List of networks with the specified purpose.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if n.purpose == purpose]

    async def get_guest_networks(self) -> list[NetworkInfo]:
        """Get all guest networks.

        Returns:
            List of guest networks.
        """
        return await self.get_networks_by_purpose(NetworkPurpose.GUEST)

    async def get_corporate_networks(self) -> list[NetworkInfo]:
        """Get all corporate networks.

        Returns:
            List of corporate networks.
        """
        return await self.get_networks_by_purpose(NetworkPurpose.CORPORATE)

    async def get_dhcp_enabled_networks(self) -> list[NetworkInfo]:
        """Get all networks with DHCP enabled.

        Returns:
            List of networks with DHCP.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if n.has_dhcp]

    async def get_ipv6_enabled_networks(self) -> list[NetworkInfo]:
        """Get all networks with IPv6 enabled.

        Returns:
            List of IPv6-enabled networks.
        """
        networks = await self.get_all_networks()
        return [n for n in networks if n.ipv6_enabled]

    async def search_networks(self, query: str) -> list[NetworkInfo]:
        """Search networks by name or subnet.

        Args:
            query: Search query (case-insensitive).

        Returns:
            List of matching networks.
        """
        networks = await self.get_all_networks()
        query_lower = query.lower()
        results = []
        for network in networks:
            if query_lower in network.name.lower():
                results.append(network)
            elif network.subnet and query_lower in network.subnet.lower():
                results.append(network)
        return results

    async def get_available_vlan_ids(
        self, start: int = 2, end: int = 4094
    ) -> list[int]:
        """Get available VLAN IDs.

        Args:
            start: Start of VLAN range.
            end: End of VLAN range.

        Returns:
            List of unused VLAN IDs.
        """
        networks = await self.get_all_networks()
        used_vlans = {n.vlan_id for n in networks if n.vlan_id is not None}
        return [v for v in range(start, end + 1) if v not in used_vlans]

    async def create_vlan_network(
        self,
        name: str,
        vlan_id: int,
        subnet: str,
        gateway_ip: str,
        dhcp_start: str | None = None,
        dhcp_stop: str | None = None,
        purpose: str = 'CORPORATE',
        internet_access: bool = True,
    ) -> NetworkInfo:
        """Create a new VLAN network.

        Args:
            name: Network name.
            vlan_id: VLAN ID.
            subnet: Network subnet (e.g., '192.168.10.0/24').
            gateway_ip: Gateway IP address.
            dhcp_start: DHCP range start IP.
            dhcp_stop: DHCP range end IP.
            purpose: Network purpose.
            internet_access: Allow internet access.

        Returns:
            Created network.
        """
        result = await self._client.create_network(
            name=name,
            purpose=purpose,
            vlan_id=vlan_id,
            subnet=subnet,
            gateway_ip=gateway_ip,
            dhcp_enabled=True,
            dhcp_start=dhcp_start,
            dhcp_stop=dhcp_stop,
            internet_access_enabled=internet_access,
        )

        # Invalidate cache
        self._networks_cache.clear()

        return result

    async def create_guest_network(
        self,
        name: str,
        vlan_id: int,
        subnet: str,
        gateway_ip: str,
        dhcp_start: str | None = None,
        dhcp_stop: str | None = None,
    ) -> NetworkInfo:
        """Create a new guest network.

        Args:
            name: Network name.
            vlan_id: VLAN ID.
            subnet: Network subnet.
            gateway_ip: Gateway IP address.
            dhcp_start: DHCP range start IP.
            dhcp_stop: DHCP range end IP.

        Returns:
            Created guest network.
        """
        return await self.create_vlan_network(
            name=name,
            vlan_id=vlan_id,
            subnet=subnet,
            gateway_ip=gateway_ip,
            dhcp_start=dhcp_start,
            dhcp_stop=dhcp_stop,
            purpose='GUEST',
            internet_access=True,
        )

    async def enable_network(self, network_id: str) -> NetworkInfo:
        """Enable a network.

        Args:
            network_id: Network UUID.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(network_id, enabled=True)
        self._networks_cache.clear()
        return result

    async def disable_network(self, network_id: str) -> NetworkInfo:
        """Disable a network.

        Args:
            network_id: Network UUID.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(network_id, enabled=False)
        self._networks_cache.clear()
        return result

    async def update_dhcp_range(
        self,
        network_id: str,
        start: str,
        stop: str,
    ) -> NetworkInfo:
        """Update DHCP range for a network.

        Args:
            network_id: Network UUID.
            start: DHCP range start IP.
            stop: DHCP range end IP.

        Returns:
            Updated network.
        """
        dhcp_config = {
            'mode': 'DHCP_SERVER',
            'start': start,
            'stop': stop,
        }
        result = await self._client.update_network(network_id, dhcpConfig=dhcp_config)
        self._networks_cache.clear()
        return result

    async def enable_ipv6(self, network_id: str) -> NetworkInfo:
        """Enable IPv6 on a network.

        Args:
            network_id: Network UUID.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(network_id, ipv6Enabled=True)
        self._networks_cache.clear()
        return result

    async def disable_ipv6(self, network_id: str) -> NetworkInfo:
        """Disable IPv6 on a network.

        Args:
            network_id: Network UUID.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(network_id, ipv6Enabled=False)
        self._networks_cache.clear()
        return result

    async def set_internet_access(
        self, network_id: str, enabled: bool
    ) -> NetworkInfo:
        """Set internet access for a network.

        Args:
            network_id: Network UUID.
            enabled: Enable/disable internet access.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(
            network_id, internetAccessEnabled=enabled
        )
        self._networks_cache.clear()
        return result

    async def rename_network(self, network_id: str, new_name: str) -> NetworkInfo:
        """Rename a network.

        Args:
            network_id: Network UUID.
            new_name: New network name.

        Returns:
            Updated network.
        """
        result = await self._client.update_network(network_id, name=new_name)
        self._networks_cache.clear()
        return result

    async def delete_network(self, network_id: str) -> bool:
        """Delete a network.

        Args:
            network_id: Network UUID.

        Returns:
            True if deleted successfully.
        """
        await self._client.delete_network(network_id)
        self._networks_cache.clear()
        return True

    def analyze_network(self, network: NetworkInfo) -> NetworkStats:
        """Analyze a network and return statistics.

        Args:
            network: Network to analyze.

        Returns:
            Network statistics.
        """
        return NetworkStats(
            network_id=network.id,
            network_name=network.name,
            vlan_id=network.vlan_id,
            purpose=network.purpose,
            has_dhcp=network.has_dhcp,
            has_ipv6=network.ipv6_enabled,
            internet_access=network.internet_access_enabled,
            is_guest=network.is_guest_network,
        )

    async def get_summary(self) -> NetworkSummary:
        """Get a summary of all networks.

        Returns:
            Network summary.
        """
        networks = await self.get_all_networks()

        summary = NetworkSummary()
        summary.total_networks = len(networks)
        vlans_in_use = []

        for network in networks:
            if network.enabled:
                summary.enabled_networks += 1
            else:
                summary.disabled_networks += 1

            if network.vlan_id is not None:
                summary.vlan_networks += 1
                vlans_in_use.append(network.vlan_id)

            if network.purpose == NetworkPurpose.CORPORATE:
                summary.corporate_networks += 1
            elif network.purpose == NetworkPurpose.GUEST:
                summary.guest_networks += 1

            if network.has_dhcp:
                summary.dhcp_enabled_networks += 1

            if network.ipv6_enabled:
                summary.ipv6_enabled_networks += 1

            if network.origin == 'USER':
                summary.user_networks += 1
            else:
                summary.system_networks += 1

        summary.vlans_in_use = sorted(vlans_in_use)

        return summary

    async def export_networks(self) -> list[dict[str, Any]]:
        """Export all networks as dictionaries.

        Returns:
            List of network dictionaries.
        """
        networks = await self.get_all_networks()
        return [
            {
                'id': n.id,
                'name': n.name,
                'enabled': n.enabled,
                'vlan_id': n.vlan_id,
                'purpose': n.purpose.value if n.purpose else None,
                'subnet': n.subnet,
                'gateway_ip': n.gateway_ip,
                'dhcp_enabled': n.has_dhcp,
                'ipv6_enabled': n.ipv6_enabled,
                'internet_access': n.internet_access_enabled,
            }
            for n in networks
        ]

    async def get_network_health_report(self) -> dict[str, Any]:
        """Generate a network health report.

        Returns:
            Health report with recommendations.
        """
        networks = await self.get_all_networks()
        summary = await self.get_summary()

        issues = []
        recommendations = []

        # Check for networks without DHCP
        non_dhcp = [n for n in networks if not n.has_dhcp and n.enabled]
        if non_dhcp:
            issues.append(f"{len(non_dhcp)} enabled networks without DHCP")

        # Check for duplicate VLAN IDs (should not happen, but validate)
        vlan_counts: dict[int, int] = {}
        for network in networks:
            if network.vlan_id is not None:
                vlan_counts[network.vlan_id] = vlan_counts.get(network.vlan_id, 0) + 1

        duplicate_vlans = [v for v, c in vlan_counts.items() if c > 1]
        if duplicate_vlans:
            issues.append(f"Duplicate VLAN IDs found: {duplicate_vlans}")

        # Check for networks with internet access that might need isolation
        guest_with_internet = [
            n for n in networks
            if n.is_guest_network and n.internet_access_enabled
        ]
        if guest_with_internet:
            recommendations.append(
                f"{len(guest_with_internet)} guest networks have internet access - "
                "ensure proper firewall rules are in place"
            )

        # Check IPv6 adoption
        ipv6_ratio = summary.ipv6_enabled_networks / max(summary.total_networks, 1)
        if ipv6_ratio < 0.5:
            recommendations.append(
                f"Only {summary.ipv6_enabled_networks}/{summary.total_networks} "
                "networks have IPv6 enabled - consider enabling for dual-stack support"
            )

        return {
            'summary': {
                'total_networks': summary.total_networks,
                'enabled_networks': summary.enabled_networks,
                'disabled_networks': summary.disabled_networks,
                'vlan_networks': summary.vlan_networks,
                'dhcp_enabled': summary.dhcp_enabled_networks,
                'ipv6_enabled': summary.ipv6_enabled_networks,
            },
            'issues': issues,
            'recommendations': recommendations,
            'vlans_in_use': summary.vlans_in_use,
        }
