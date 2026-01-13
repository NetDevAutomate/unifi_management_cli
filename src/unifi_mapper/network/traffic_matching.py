"""Traffic Matching List management.

This module provides tools for managing traffic matching lists
used across firewall policy configurations including port lists
and IP address lists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unifi_mapper.network.models import (
    ACLProtocol,
    IPAddressMatching,
    PortMatching,
    TrafficMatchingList,
    TrafficMatchingListType,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class TrafficListSummary:
    """Summary of traffic matching lists on a site."""

    total_lists: int = 0
    port_lists: int = 0
    ip_address_lists: int = 0
    total_ports: int = 0
    total_ip_addresses: int = 0
    unique_ports: set[int] = field(default_factory=set)
    unique_protocols: set[str] = field(default_factory=set)


@dataclass
class PortListInfo:
    """Information about a port list."""

    list_id: str
    name: str
    ports: list[tuple[int, str]]  # (port, protocol)
    port_count: int


@dataclass
class IPAddressListInfo:
    """Information about an IP address list."""

    list_id: str
    name: str
    addresses: list[str]
    address_count: int


class TrafficMatchingListManager:
    """Manage traffic matching lists for firewall configurations.

    This class provides tools for managing port lists and IP address
    lists used across firewall policy configurations.

    Example:
        >>> manager = TrafficMatchingListManager(client)
        >>> lists = await manager.get_all_lists()
        >>> await manager.create_port_list('Web Ports', [(80, 'TCP'), (443, 'TCP')])
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the traffic matching list manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._lists_cache: dict[str, TrafficMatchingList] = {}

    async def refresh_cache(self) -> None:
        """Refresh the traffic matching lists cache."""
        lists = await self._client.list_traffic_matching_lists()
        self._lists_cache = {lst.id: lst for lst in lists}
        log.debug(f"Cached {len(self._lists_cache)} traffic matching lists")

    async def get_all_lists(self, refresh: bool = False) -> list[TrafficMatchingList]:
        """Get all traffic matching lists.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of traffic matching lists.
        """
        if refresh or not self._lists_cache:
            await self.refresh_cache()
        return list(self._lists_cache.values())

    async def get_list_by_id(self, list_id: str) -> TrafficMatchingList | None:
        """Get a traffic matching list by ID.

        Args:
            list_id: List UUID.

        Returns:
            Traffic matching list or None.
        """
        lists = await self.get_all_lists()
        for lst in lists:
            if lst.id == list_id:
                return lst
        return None

    async def get_list_by_name(self, name: str) -> TrafficMatchingList | None:
        """Get a traffic matching list by name.

        Args:
            name: List name (case-insensitive).

        Returns:
            Traffic matching list or None.
        """
        lists = await self.get_all_lists()
        for lst in lists:
            if lst.name.lower() == name.lower():
                return lst
        return None

    async def get_port_lists(self) -> list[TrafficMatchingList]:
        """Get all port lists.

        Returns:
            List of port lists.
        """
        lists = await self.get_all_lists()
        return [lst for lst in lists if lst.type == TrafficMatchingListType.PORT_LIST]

    async def get_ip_address_lists(self) -> list[TrafficMatchingList]:
        """Get all IP address lists.

        Returns:
            List of IP address lists.
        """
        lists = await self.get_all_lists()
        return [lst for lst in lists if lst.type == TrafficMatchingListType.IP_ADDRESS_LIST]

    async def search_lists(self, query: str) -> list[TrafficMatchingList]:
        """Search traffic matching lists by name.

        Args:
            query: Search query (partial match, case-insensitive).

        Returns:
            List of matching lists.
        """
        lists = await self.get_all_lists()
        query_lower = query.lower()
        return [lst for lst in lists if query_lower in lst.name.lower()]

    async def get_lists_containing_port(self, port: int) -> list[TrafficMatchingList]:
        """Get all lists containing a specific port.

        Args:
            port: Port number.

        Returns:
            List of matching lists.
        """
        lists = await self.get_port_lists()
        return [
            lst for lst in lists
            if any(p.port == port for p in lst.ports)
        ]

    async def get_lists_containing_ip(self, ip_address: str) -> list[TrafficMatchingList]:
        """Get all lists containing a specific IP address.

        Args:
            ip_address: IP address.

        Returns:
            List of matching lists.
        """
        lists = await self.get_ip_address_lists()
        return [
            lst for lst in lists
            if any(addr.ip_address == ip_address for addr in lst.ip_addresses)
        ]

    async def create_port_list(
        self,
        name: str,
        ports: list[tuple[int, str | ACLProtocol]],
    ) -> TrafficMatchingList:
        """Create a new port list.

        Args:
            name: List name.
            ports: List of (port, protocol) tuples.

        Returns:
            Created traffic matching list.
        """
        port_configs = []
        for port, protocol in ports:
            if isinstance(protocol, ACLProtocol):
                protocol_str = protocol.value
            else:
                protocol_str = protocol.upper()
            port_configs.append({
                'port': port,
                'protocol': protocol_str,
            })

        traffic_list = await self._client.create_traffic_matching_list(
            name=name,
            list_type='PORT_LIST',
            ports=port_configs,
        )
        self._lists_cache[traffic_list.id] = traffic_list
        return traffic_list

    async def create_ip_address_list(
        self,
        name: str,
        addresses: list[str | tuple[str, str | None]],
    ) -> TrafficMatchingList:
        """Create a new IP address list.

        Args:
            name: List name.
            addresses: List of IP addresses or (ip, description) tuples.

        Returns:
            Created traffic matching list.
        """
        ip_configs = []
        for addr in addresses:
            if isinstance(addr, tuple):
                ip_configs.append({
                    'ipAddress': addr[0],
                    'description': addr[1],
                })
            else:
                ip_configs.append({
                    'ipAddress': addr,
                })

        traffic_list = await self._client.create_traffic_matching_list(
            name=name,
            list_type='IP_ADDRESS_LIST',
            ip_addresses=ip_configs,
        )
        self._lists_cache[traffic_list.id] = traffic_list
        return traffic_list

    async def update_list(
        self,
        list_id: str,
        **updates,
    ) -> TrafficMatchingList:
        """Update a traffic matching list.

        Args:
            list_id: List UUID.
            **updates: Fields to update.

        Returns:
            Updated list.
        """
        traffic_list = await self._client.update_traffic_matching_list(list_id, **updates)
        self._lists_cache[traffic_list.id] = traffic_list
        return traffic_list

    async def rename_list(self, list_id: str, new_name: str) -> TrafficMatchingList:
        """Rename a traffic matching list.

        Args:
            list_id: List UUID.
            new_name: New name.

        Returns:
            Updated list.
        """
        return await self.update_list(list_id, name=new_name)

    async def add_port_to_list(
        self,
        list_id: str,
        port: int,
        protocol: str | ACLProtocol = ACLProtocol.TCP,
    ) -> TrafficMatchingList:
        """Add a port to an existing port list.

        Args:
            list_id: List UUID.
            port: Port number.
            protocol: Protocol (TCP/UDP).

        Returns:
            Updated list.
        """
        traffic_list = await self.get_list_by_id(list_id)
        if not traffic_list:
            raise ValueError(f"List not found: {list_id}")

        if traffic_list.type != TrafficMatchingListType.PORT_LIST:
            raise ValueError("Cannot add port to non-port list")

        # Get existing ports
        existing_ports = [
            {'port': p.port, 'protocol': p.protocol.value}
            for p in traffic_list.ports
        ]

        # Add new port
        if isinstance(protocol, ACLProtocol):
            protocol_str = protocol.value
        else:
            protocol_str = protocol.upper()

        existing_ports.append({
            'port': port,
            'protocol': protocol_str,
        })

        return await self.update_list(list_id, ports=existing_ports)

    async def remove_port_from_list(
        self,
        list_id: str,
        port: int,
        protocol: str | ACLProtocol | None = None,
    ) -> TrafficMatchingList:
        """Remove a port from a port list.

        Args:
            list_id: List UUID.
            port: Port number.
            protocol: Optional protocol to match.

        Returns:
            Updated list.
        """
        traffic_list = await self.get_list_by_id(list_id)
        if not traffic_list:
            raise ValueError(f"List not found: {list_id}")

        if traffic_list.type != TrafficMatchingListType.PORT_LIST:
            raise ValueError("Cannot remove port from non-port list")

        # Filter out the port
        remaining_ports = []
        for p in traffic_list.ports:
            if p.port == port:
                if protocol is not None:
                    if isinstance(protocol, ACLProtocol):
                        protocol_str = protocol.value
                    else:
                        protocol_str = protocol.upper()
                    if p.protocol.value == protocol_str:
                        continue
                else:
                    continue
            remaining_ports.append({
                'port': p.port,
                'protocol': p.protocol.value,
            })

        return await self.update_list(list_id, ports=remaining_ports)

    async def add_ip_to_list(
        self,
        list_id: str,
        ip_address: str,
        description: str | None = None,
    ) -> TrafficMatchingList:
        """Add an IP address to an existing IP address list.

        Args:
            list_id: List UUID.
            ip_address: IP address.
            description: Optional description.

        Returns:
            Updated list.
        """
        traffic_list = await self.get_list_by_id(list_id)
        if not traffic_list:
            raise ValueError(f"List not found: {list_id}")

        if traffic_list.type != TrafficMatchingListType.IP_ADDRESS_LIST:
            raise ValueError("Cannot add IP to non-IP-address list")

        # Get existing addresses
        existing_ips = [
            {'ipAddress': addr.ip_address, 'description': addr.description}
            for addr in traffic_list.ip_addresses
        ]

        # Add new IP
        new_entry = {'ipAddress': ip_address}
        if description:
            new_entry['description'] = description
        existing_ips.append(new_entry)

        return await self.update_list(list_id, ipAddresses=existing_ips)

    async def remove_ip_from_list(
        self,
        list_id: str,
        ip_address: str,
    ) -> TrafficMatchingList:
        """Remove an IP address from an IP address list.

        Args:
            list_id: List UUID.
            ip_address: IP address.

        Returns:
            Updated list.
        """
        traffic_list = await self.get_list_by_id(list_id)
        if not traffic_list:
            raise ValueError(f"List not found: {list_id}")

        if traffic_list.type != TrafficMatchingListType.IP_ADDRESS_LIST:
            raise ValueError("Cannot remove IP from non-IP-address list")

        # Filter out the IP
        remaining_ips = [
            {'ipAddress': addr.ip_address, 'description': addr.description}
            for addr in traffic_list.ip_addresses
            if addr.ip_address != ip_address
        ]

        return await self.update_list(list_id, ipAddresses=remaining_ips)

    async def delete_list(self, list_id: str) -> bool:
        """Delete a traffic matching list.

        Args:
            list_id: List UUID.

        Returns:
            True if successful.
        """
        await self._client.delete_traffic_matching_list(list_id)
        if list_id in self._lists_cache:
            del self._lists_cache[list_id]
        return True

    def get_port_list_info(self, traffic_list: TrafficMatchingList) -> PortListInfo:
        """Get detailed information about a port list.

        Args:
            traffic_list: Traffic matching list.

        Returns:
            Port list information.
        """
        ports = [(p.port, p.protocol.value) for p in traffic_list.ports]
        return PortListInfo(
            list_id=traffic_list.id,
            name=traffic_list.name,
            ports=ports,
            port_count=len(ports),
        )

    def get_ip_list_info(self, traffic_list: TrafficMatchingList) -> IPAddressListInfo:
        """Get detailed information about an IP address list.

        Args:
            traffic_list: Traffic matching list.

        Returns:
            IP address list information.
        """
        addresses = [addr.ip_address for addr in traffic_list.ip_addresses]
        return IPAddressListInfo(
            list_id=traffic_list.id,
            name=traffic_list.name,
            addresses=addresses,
            address_count=len(addresses),
        )

    async def get_summary(self) -> TrafficListSummary:
        """Get a summary of all traffic matching lists.

        Returns:
            Traffic list summary.
        """
        lists = await self.get_all_lists()

        summary = TrafficListSummary(
            total_lists=len(lists),
        )

        for traffic_list in lists:
            if traffic_list.type == TrafficMatchingListType.PORT_LIST:
                summary.port_lists += 1
                for port_match in traffic_list.ports:
                    summary.total_ports += 1
                    summary.unique_ports.add(port_match.port)
                    summary.unique_protocols.add(port_match.protocol.value)
            else:
                summary.ip_address_lists += 1
                summary.total_ip_addresses += len(traffic_list.ip_addresses)

        return summary

    async def export_lists(self) -> list[dict]:
        """Export all traffic matching lists as dictionaries.

        Returns:
            List of traffic list dictionaries.
        """
        lists = await self.get_all_lists()
        result = []
        for traffic_list in lists:
            entry = {
                'name': traffic_list.name,
                'type': traffic_list.type.value,
            }
            if traffic_list.type == TrafficMatchingListType.PORT_LIST:
                entry['ports'] = [
                    {'port': p.port, 'protocol': p.protocol.value}
                    for p in traffic_list.ports
                ]
            else:
                entry['ip_addresses'] = [
                    {'ip_address': addr.ip_address, 'description': addr.description}
                    for addr in traffic_list.ip_addresses
                ]
            result.append(entry)
        return result

    async def get_common_port_lists(self) -> dict[str, list[tuple[int, str]]]:
        """Get common port list templates.

        Returns:
            Dictionary of common port list configurations.
        """
        return {
            'Web Services': [(80, 'TCP'), (443, 'TCP')],
            'Email Services': [(25, 'TCP'), (465, 'TCP'), (587, 'TCP'), (993, 'TCP'), (995, 'TCP')],
            'DNS': [(53, 'TCP'), (53, 'UDP')],
            'SSH': [(22, 'TCP')],
            'FTP': [(20, 'TCP'), (21, 'TCP')],
            'Database': [(3306, 'TCP'), (5432, 'TCP'), (27017, 'TCP')],
            'Remote Desktop': [(3389, 'TCP'), (3389, 'UDP')],
            'VoIP': [(5060, 'TCP'), (5060, 'UDP'), (5061, 'TCP')],
        }
