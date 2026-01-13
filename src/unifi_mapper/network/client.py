"""Async HTTP client for UniFi Network API.

This module provides an async HTTP client for interacting with the
UniFi Network API (10.1.68) with proper connection lifecycle management.
"""

from __future__ import annotations

import asyncio
import httpx
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, TypeVar
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.models import (
    ACLRule,
    ClientInfo,
    DeviceInfo,
    DeviceStatistics,
    DNSPolicy,
    DPIApplication,
    DPICategory,
    FirewallPolicy,
    FirewallZone,
    NetworkInfo,
    SiteInfo,
    TrafficMatchingList,
)


log = logging.getLogger(__name__)

T = TypeVar('T')


class NetworkClientError(Exception):
    """Base exception for Network API client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize the error.

        Args:
            message: Error description.
            status_code: Optional HTTP status code.
        """
        super().__init__(message)
        self.status_code = status_code


class NetworkAuthenticationError(NetworkClientError):
    """Authentication failed with the Network API."""

    pass


class NetworkConnectionError(NetworkClientError):
    """Connection to Network API failed."""

    pass


class UniFiNetworkClient:
    """Async client for the UniFi Network API.

    This client provides async methods for interacting with the UniFi Network
    API including device management, statistics, firewall, DPI, and clients.

    Example:
        >>> config = NetworkConfig.from_env()
        >>> async with UniFiNetworkClient(config) as client:
        ...     devices = await client.list_devices()
        ...     for device in devices:
        ...         print(f"{device.name}: {device.state}")
    """

    def __init__(self, config: NetworkConfig) -> None:
        """Initialize the Network API client.

        Args:
            config: Network API configuration.
        """
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> UniFiNetworkClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Establish connection to the Network API."""
        async with self._lock:
            if self._client is not None:
                return

            self._client = httpx.AsyncClient(
                base_url=self.config.api_base_url,
                headers=self.config.get_headers(),
                verify=self.config.verify_ssl,
                timeout=httpx.Timeout(self.config.timeout),
            )

            if self.config.debug:
                log.setLevel(logging.DEBUG)

            log.debug(f"Connected to Network API at {self.config.base_url}")

    async def close(self) -> None:
        """Close the connection to the Network API."""
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
                log.debug("Disconnected from Network API")

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._client is not None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an API request.

        Args:
            method: HTTP method.
            path: API endpoint path.
            params: Query parameters.
            json: JSON body.

        Returns:
            Response JSON data.

        Raises:
            NetworkClientError: If the request fails.
        """
        if self._client is None:
            raise NetworkConnectionError("Client not connected")

        # Replace site_id placeholder
        path = path.replace('{siteId}', self.config.site_id)

        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
            )

            if response.status_code == 401:
                raise NetworkAuthenticationError(
                    "Authentication failed - check API key",
                    status_code=401,
                )

            if response.status_code == 403:
                raise NetworkAuthenticationError(
                    "Access forbidden - check API key permissions",
                    status_code=403,
                )

            if response.status_code >= 400:
                error_msg = response.text
                raise NetworkClientError(
                    f"API request failed: {error_msg}",
                    status_code=response.status_code,
                )

            return response.json()

        except httpx.ConnectError as e:
            raise NetworkConnectionError(f"Connection failed: {e}") from e
        except httpx.TimeoutException as e:
            raise NetworkConnectionError(f"Request timed out: {e}") from e

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request."""
        return await self._request('GET', path, params=params)

    async def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a POST request."""
        return await self._request('POST', path, json=json)

    async def _put(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a PUT request."""
        return await self._request('PUT', path, json=json)

    async def _delete(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a DELETE request."""
        return await self._request('DELETE', path, params=params)

    async def _paginate(
        self,
        path: str,
        limit: int = 200,
        filter_expr: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Paginate through API results.

        Args:
            path: API endpoint path.
            limit: Items per page.
            filter_expr: Optional filter expression.

        Yields:
            Individual items from paginated results.
        """
        offset = 0
        while True:
            params: dict[str, Any] = {'offset': offset, 'limit': limit}
            if filter_expr:
                params['filter'] = filter_expr

            response = await self._get(path, params)
            data = response.get('data', [])

            if not data:
                break

            for item in data:
                yield item

            if len(data) < limit:
                break

            offset += limit

    # =========================================================================
    # Device Endpoints
    # =========================================================================

    async def list_devices(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[DeviceInfo]:
        """List all adopted devices.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of device information.
        """
        devices = []
        async for item in self._paginate(
            '/sites/{siteId}/devices', limit=limit, filter_expr=filter_expr
        ):
            devices.append(DeviceInfo.model_validate(item))
        return devices

    async def get_device(self, device_id: str) -> DeviceInfo:
        """Get details for a specific device.

        Args:
            device_id: Device UUID.

        Returns:
            Device information.
        """
        response = await self._get(f'/sites/{{siteId}}/devices/{device_id}')
        return DeviceInfo.model_validate(response.get('data', response))

    async def get_device_statistics(self, device_id: str) -> DeviceStatistics:
        """Get real-time statistics for a device.

        Args:
            device_id: Device UUID.

        Returns:
            Device statistics.
        """
        response = await self._get(f'/sites/{{siteId}}/devices/{device_id}/statistics')
        data = response.get('data', response)
        data['deviceId'] = device_id
        return DeviceStatistics.model_validate(data)

    async def execute_device_action(
        self,
        device_id: str,
        action: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute an action on a device.

        Args:
            device_id: Device UUID.
            action: Action name (e.g., 'restart', 'locate').
            **kwargs: Additional action parameters.

        Returns:
            Action response.
        """
        payload = {'action': action, **kwargs}
        return await self._post(f'/sites/{{siteId}}/devices/{device_id}/actions', json=payload)

    async def execute_port_action(
        self,
        device_id: str,
        port_idx: int,
        action: str,
    ) -> dict[str, Any]:
        """Execute an action on a device port.

        Args:
            device_id: Device UUID.
            port_idx: Port index.
            action: Action name.

        Returns:
            Action response.
        """
        payload = {'action': action}
        return await self._post(
            f'/sites/{{siteId}}/devices/{device_id}/ports/{port_idx}/actions',
            json=payload,
        )

    # =========================================================================
    # Client Endpoints
    # =========================================================================

    async def list_clients(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[ClientInfo]:
        """List all connected clients.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of client information.
        """
        clients = []
        async for item in self._paginate(
            '/sites/{siteId}/clients', limit=limit, filter_expr=filter_expr
        ):
            clients.append(ClientInfo.model_validate(item))
        return clients

    async def get_client(self, client_id: str) -> ClientInfo:
        """Get details for a specific client.

        Args:
            client_id: Client UUID.

        Returns:
            Client information.
        """
        response = await self._get(f'/sites/{{siteId}}/clients/{client_id}')
        return ClientInfo.model_validate(response.get('data', response))

    async def authorize_guest(
        self,
        client_id: str,
        time_limit_minutes: int = 60,
        data_usage_limit_mbytes: int | None = None,
        rx_rate_limit_kbps: int | None = None,
        tx_rate_limit_kbps: int | None = None,
    ) -> dict[str, Any]:
        """Authorize a guest client.

        Args:
            client_id: Client UUID.
            time_limit_minutes: Access duration in minutes.
            data_usage_limit_mbytes: Optional data cap in MB.
            rx_rate_limit_kbps: Optional download rate limit.
            tx_rate_limit_kbps: Optional upload rate limit.

        Returns:
            Authorization response.
        """
        payload: dict[str, Any] = {
            'action': 'AUTHORIZE_GUEST',
            'timeLimitMinutes': time_limit_minutes,
        }
        if data_usage_limit_mbytes is not None:
            payload['dataUsageLimitMBytes'] = data_usage_limit_mbytes
        if rx_rate_limit_kbps is not None:
            payload['rxRateLimitKbps'] = rx_rate_limit_kbps
        if tx_rate_limit_kbps is not None:
            payload['txRateLimitKbps'] = tx_rate_limit_kbps

        return await self._post(f'/sites/{{siteId}}/clients/{client_id}/actions', json=payload)

    async def unauthorize_guest(self, client_id: str) -> dict[str, Any]:
        """Revoke guest client authorization.

        Args:
            client_id: Client UUID.

        Returns:
            Action response.
        """
        return await self._post(
            f'/sites/{{siteId}}/clients/{client_id}/actions',
            json={'action': 'UNAUTHORIZE_GUEST'},
        )

    # =========================================================================
    # Network Endpoints
    # =========================================================================

    async def list_networks(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[NetworkInfo]:
        """List all networks.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of network information.
        """
        networks = []
        async for item in self._paginate(
            '/sites/{siteId}/networks', limit=limit, filter_expr=filter_expr
        ):
            networks.append(NetworkInfo.model_validate(item))
        return networks

    async def get_network(self, network_id: str) -> NetworkInfo:
        """Get a specific network by ID.

        Args:
            network_id: Network UUID.

        Returns:
            Network information.
        """
        response = await self._get(f'/sites/{{siteId}}/networks/{network_id}')
        return NetworkInfo.model_validate(response.get('data', response))

    async def create_network(
        self,
        name: str,
        purpose: str = 'CORPORATE',
        vlan_id: int | None = None,
        subnet: str | None = None,
        gateway_ip: str | None = None,
        dhcp_enabled: bool = True,
        dhcp_start: str | None = None,
        dhcp_stop: str | None = None,
        internet_access_enabled: bool = True,
        ipv6_enabled: bool = False,
        domain_name: str | None = None,
    ) -> NetworkInfo:
        """Create a new network.

        Args:
            name: Network name.
            purpose: Network purpose (CORPORATE, GUEST, etc.).
            vlan_id: Optional VLAN ID.
            subnet: Network subnet (e.g., '192.168.10.0/24').
            gateway_ip: Gateway IP address.
            dhcp_enabled: Enable DHCP server.
            dhcp_start: DHCP range start IP.
            dhcp_stop: DHCP range end IP.
            internet_access_enabled: Allow internet access.
            ipv6_enabled: Enable IPv6.
            domain_name: Domain name for the network.

        Returns:
            Created network.
        """
        payload: dict[str, Any] = {
            'name': name,
            'purpose': purpose,
            'internetAccessEnabled': internet_access_enabled,
            'ipv6Enabled': ipv6_enabled,
        }

        if vlan_id is not None:
            payload['vlanId'] = vlan_id
        if subnet:
            payload['subnet'] = subnet
        if gateway_ip:
            payload['gatewayIp'] = gateway_ip
        if domain_name:
            payload['domainName'] = domain_name

        # DHCP configuration
        if dhcp_enabled:
            dhcp_config: dict[str, Any] = {'mode': 'DHCP_SERVER'}
            if dhcp_start:
                dhcp_config['start'] = dhcp_start
            if dhcp_stop:
                dhcp_config['stop'] = dhcp_stop
            payload['dhcpConfig'] = dhcp_config
        else:
            payload['dhcpConfig'] = {'mode': 'NONE'}

        response = await self._post('/sites/{siteId}/networks', json=payload)
        return NetworkInfo.model_validate(response.get('data', response))

    async def update_network(
        self,
        network_id: str,
        **updates: Any,
    ) -> NetworkInfo:
        """Update an existing network.

        Args:
            network_id: Network UUID.
            **updates: Fields to update.

        Returns:
            Updated network.
        """
        response = await self._put(
            f'/sites/{{siteId}}/networks/{network_id}',
            json=updates,
        )
        return NetworkInfo.model_validate(response.get('data', response))

    async def delete_network(self, network_id: str) -> dict[str, Any]:
        """Delete a network.

        Args:
            network_id: Network UUID.

        Returns:
            Deletion response.
        """
        return await self._delete(f'/sites/{{siteId}}/networks/{network_id}')

    # =========================================================================
    # Site Endpoints
    # =========================================================================

    async def list_sites(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[SiteInfo]:
        """List all sites.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of site information.
        """
        sites = []
        async for item in self._paginate(
            '/sites', limit=limit, filter_expr=filter_expr
        ):
            sites.append(SiteInfo.model_validate(item))
        return sites

    async def get_site(self, site_id: str) -> SiteInfo:
        """Get a specific site by ID.

        Args:
            site_id: Site UUID.

        Returns:
            Site information.
        """
        response = await self._get(f'/sites/{site_id}')
        return SiteInfo.model_validate(response.get('data', response))

    async def get_current_site(self) -> SiteInfo:
        """Get information about the current site.

        Returns:
            Current site information.
        """
        return await self.get_site(self.config.site_id)

    async def update_site(
        self,
        site_id: str,
        **updates: Any,
    ) -> SiteInfo:
        """Update a site's configuration.

        Args:
            site_id: Site UUID.
            **updates: Fields to update (name, description, timeZone, etc.).

        Returns:
            Updated site information.
        """
        response = await self._put(f'/sites/{site_id}', json=updates)
        return SiteInfo.model_validate(response.get('data', response))

    # =========================================================================
    # Firewall Endpoints
    # =========================================================================

    async def list_firewall_zones(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[FirewallZone]:
        """List all firewall zones.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of firewall zones.
        """
        zones = []
        async for item in self._paginate(
            '/sites/{siteId}/firewall/zones', limit=limit, filter_expr=filter_expr
        ):
            zones.append(FirewallZone.model_validate(item))
        return zones

    async def list_firewall_policies(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[FirewallPolicy]:
        """List all firewall policies.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of firewall policies.
        """
        policies = []
        async for item in self._paginate(
            '/sites/{siteId}/firewall/policies', limit=limit, filter_expr=filter_expr
        ):
            policies.append(FirewallPolicy.model_validate(item))
        return policies

    async def create_firewall_policy(
        self,
        name: str,
        action_type: str = 'BLOCK',
        enabled: bool = True,
        logging_enabled: bool = False,
        source_zone_id: str | None = None,
        destination_zone_id: str | None = None,
        description: str | None = None,
    ) -> FirewallPolicy:
        """Create a new firewall policy.

        Args:
            name: Policy name.
            action_type: 'ALLOW' or 'BLOCK'.
            enabled: Whether policy is enabled.
            logging_enabled: Enable syslog logging.
            source_zone_id: Source zone UUID.
            destination_zone_id: Destination zone UUID.
            description: Optional description.

        Returns:
            Created firewall policy.
        """
        payload: dict[str, Any] = {
            'name': name,
            'enabled': enabled,
            'action': {'type': action_type},
            'loggingEnabled': logging_enabled,
            'source': {},
            'destination': {},
            'ipProtocolScope': {'ipVersion': 'IPV4_IPV6'},
        }

        if source_zone_id:
            payload['source']['firewallZoneId'] = source_zone_id
        if destination_zone_id:
            payload['destination']['firewallZoneId'] = destination_zone_id
        if description:
            payload['description'] = description

        response = await self._post('/sites/{siteId}/firewall/policies', json=payload)
        return FirewallPolicy.model_validate(response.get('data', response))

    async def update_firewall_policy(
        self,
        policy_id: str,
        **updates: Any,
    ) -> FirewallPolicy:
        """Update an existing firewall policy.

        Args:
            policy_id: Policy UUID.
            **updates: Fields to update.

        Returns:
            Updated firewall policy.
        """
        response = await self._put(
            f'/sites/{{siteId}}/firewall/policies/{policy_id}',
            json=updates,
        )
        return FirewallPolicy.model_validate(response.get('data', response))

    async def enable_policy_logging(self, policy_id: str, enabled: bool = True) -> FirewallPolicy:
        """Enable or disable syslog logging for a policy.

        Args:
            policy_id: Policy UUID.
            enabled: Whether to enable logging.

        Returns:
            Updated firewall policy.
        """
        return await self.update_firewall_policy(policy_id, loggingEnabled=enabled)

    # =========================================================================
    # DPI Endpoints
    # =========================================================================

    async def list_dpi_categories(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[DPICategory]:
        """List all DPI application categories.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of DPI categories.
        """
        categories = []
        async for item in self._paginate(
            '/dpi/categories', limit=limit, filter_expr=filter_expr
        ):
            categories.append(DPICategory.model_validate(item))
        return categories

    async def list_dpi_applications(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[DPIApplication]:
        """List all DPI applications.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of DPI applications.
        """
        applications = []
        async for item in self._paginate(
            '/dpi/applications', limit=limit, filter_expr=filter_expr
        ):
            applications.append(DPIApplication.model_validate(item))
        return applications

    # =========================================================================
    # ACL Rule Endpoints
    # =========================================================================

    async def list_acl_rules(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[ACLRule]:
        """List all ACL rules on a site.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of ACL rules.
        """
        rules = []
        async for item in self._paginate(
            '/sites/{siteId}/acls', limit=limit, filter_expr=filter_expr
        ):
            rules.append(ACLRule.model_validate(item))
        return rules

    async def get_acl_rule(self, acl_rule_id: str) -> ACLRule:
        """Get a specific ACL rule.

        Args:
            acl_rule_id: ACL rule UUID.

        Returns:
            ACL rule.
        """
        response = await self._get(f'/sites/{{siteId}}/acls/{acl_rule_id}')
        return ACLRule.model_validate(response.get('data', response))

    async def create_acl_rule(
        self,
        name: str,
        rule_type: str,
        action: str = 'BLOCK',
        enabled: bool = True,
        description: str | None = None,
        source_filter: dict[str, Any] | None = None,
        destination_filter: dict[str, Any] | None = None,
        protocol_filter: list[str] | None = None,
        enforcing_device_ids: list[str] | None = None,
    ) -> ACLRule:
        """Create a new ACL rule.

        Args:
            name: Rule name.
            rule_type: Rule type.
            action: 'ALLOW' or 'BLOCK'.
            enabled: Whether rule is enabled.
            description: Optional description.
            source_filter: Source traffic filter.
            destination_filter: Destination traffic filter.
            protocol_filter: Protocol filter ('TCP', 'UDP').
            enforcing_device_ids: Switch device IDs to enforce rule.

        Returns:
            Created ACL rule.
        """
        payload: dict[str, Any] = {
            'type': rule_type,
            'name': name,
            'action': action,
            'enabled': enabled,
        }

        if description:
            payload['description'] = description
        if source_filter:
            payload['sourceFilter'] = source_filter
        if destination_filter:
            payload['destinationFilter'] = destination_filter
        if protocol_filter:
            payload['protocolFilter'] = protocol_filter
        if enforcing_device_ids:
            payload['enforcingDeviceFilter'] = {'deviceIds': enforcing_device_ids}

        response = await self._post('/sites/{siteId}/acls', json=payload)
        return ACLRule.model_validate(response.get('data', response))

    async def update_acl_rule(
        self,
        acl_rule_id: str,
        **updates: Any,
    ) -> ACLRule:
        """Update an existing ACL rule.

        Args:
            acl_rule_id: ACL rule UUID.
            **updates: Fields to update.

        Returns:
            Updated ACL rule.
        """
        response = await self._put(
            f'/sites/{{siteId}}/acls/{acl_rule_id}',
            json=updates,
        )
        return ACLRule.model_validate(response.get('data', response))

    async def delete_acl_rule(self, acl_rule_id: str) -> dict[str, Any]:
        """Delete an ACL rule.

        Args:
            acl_rule_id: ACL rule UUID.

        Returns:
            Deletion response.
        """
        return await self._delete(f'/sites/{{siteId}}/acls/{acl_rule_id}')

    # =========================================================================
    # DNS Policy Endpoints
    # =========================================================================

    async def list_dns_policies(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[DNSPolicy]:
        """List all DNS policies on a site.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of DNS policies.
        """
        policies = []
        async for item in self._paginate(
            '/sites/{siteId}/dns-policies', limit=limit, filter_expr=filter_expr
        ):
            policies.append(DNSPolicy.model_validate(item))
        return policies

    async def get_dns_policy(self, dns_policy_id: str) -> DNSPolicy:
        """Get a specific DNS policy.

        Args:
            dns_policy_id: DNS policy UUID.

        Returns:
            DNS policy.
        """
        response = await self._get(f'/sites/{{siteId}}/dns-policies/{dns_policy_id}')
        return DNSPolicy.model_validate(response.get('data', response))

    async def create_dns_policy(
        self,
        domain: str,
        policy_type: str,
        ipv4_address: str | None = None,
        ipv6_address: str | None = None,
        ttl_seconds: int = 3600,
        enabled: bool = True,
    ) -> DNSPolicy:
        """Create a new DNS policy.

        Args:
            domain: Domain name (1-127 characters).
            policy_type: DNS record type.
            ipv4_address: IPv4 address for A record.
            ipv6_address: IPv6 address for AAAA record.
            ttl_seconds: Time to live in seconds (0-604800).
            enabled: Whether policy is enabled.

        Returns:
            Created DNS policy.
        """
        payload: dict[str, Any] = {
            'type': policy_type,
            'domain': domain,
            'enabled': enabled,
            'ttlSeconds': ttl_seconds,
        }

        if ipv4_address:
            payload['ipv4Address'] = ipv4_address
        if ipv6_address:
            payload['ipv6Address'] = ipv6_address

        response = await self._post('/sites/{siteId}/dns-policies', json=payload)
        return DNSPolicy.model_validate(response.get('data', response))

    async def update_dns_policy(
        self,
        dns_policy_id: str,
        **updates: Any,
    ) -> DNSPolicy:
        """Update an existing DNS policy.

        Args:
            dns_policy_id: DNS policy UUID.
            **updates: Fields to update.

        Returns:
            Updated DNS policy.
        """
        response = await self._put(
            f'/sites/{{siteId}}/dns-policies/{dns_policy_id}',
            json=updates,
        )
        return DNSPolicy.model_validate(response.get('data', response))

    async def delete_dns_policy(self, dns_policy_id: str) -> dict[str, Any]:
        """Delete a DNS policy.

        Args:
            dns_policy_id: DNS policy UUID.

        Returns:
            Deletion response.
        """
        return await self._delete(f'/sites/{{siteId}}/dns-policies/{dns_policy_id}')

    # =========================================================================
    # Traffic Matching List Endpoints
    # =========================================================================

    async def list_traffic_matching_lists(
        self,
        filter_expr: str | None = None,
        limit: int = 200,
    ) -> list[TrafficMatchingList]:
        """List all traffic matching lists on a site.

        Args:
            filter_expr: Optional filter expression.
            limit: Maximum items to return.

        Returns:
            List of traffic matching lists.
        """
        lists = []
        async for item in self._paginate(
            '/sites/{siteId}/traffic-matching-lists', limit=limit, filter_expr=filter_expr
        ):
            lists.append(TrafficMatchingList.model_validate(item))
        return lists

    async def get_traffic_matching_list(self, list_id: str) -> TrafficMatchingList:
        """Get a specific traffic matching list.

        Args:
            list_id: Traffic matching list UUID.

        Returns:
            Traffic matching list.
        """
        response = await self._get(f'/sites/{{siteId}}/traffic-matching-lists/{list_id}')
        return TrafficMatchingList.model_validate(response.get('data', response))

    async def create_traffic_matching_list(
        self,
        name: str,
        list_type: str,
        ports: list[dict[str, Any]] | None = None,
        ip_addresses: list[dict[str, Any]] | None = None,
    ) -> TrafficMatchingList:
        """Create a new traffic matching list.

        Args:
            name: List name.
            list_type: 'PORT_LIST' or 'IP_ADDRESS_LIST'.
            ports: List of port matching configurations.
            ip_addresses: List of IP address matching configurations.

        Returns:
            Created traffic matching list.
        """
        payload: dict[str, Any] = {
            'type': list_type,
            'name': name,
        }

        if ports:
            payload['ports'] = ports
        if ip_addresses:
            payload['ipAddresses'] = ip_addresses

        response = await self._post('/sites/{siteId}/traffic-matching-lists', json=payload)
        return TrafficMatchingList.model_validate(response.get('data', response))

    async def update_traffic_matching_list(
        self,
        list_id: str,
        **updates: Any,
    ) -> TrafficMatchingList:
        """Update an existing traffic matching list.

        Args:
            list_id: Traffic matching list UUID.
            **updates: Fields to update.

        Returns:
            Updated traffic matching list.
        """
        response = await self._put(
            f'/sites/{{siteId}}/traffic-matching-lists/{list_id}',
            json=updates,
        )
        return TrafficMatchingList.model_validate(response.get('data', response))

    async def delete_traffic_matching_list(self, list_id: str) -> dict[str, Any]:
        """Delete a traffic matching list.

        Args:
            list_id: Traffic matching list UUID.

        Returns:
            Deletion response.
        """
        return await self._delete(f'/sites/{{siteId}}/traffic-matching-lists/{list_id}')


@asynccontextmanager
async def create_client(config: NetworkConfig) -> AsyncIterator[UniFiNetworkClient]:
    """Create a Network API client with context management.

    Args:
        config: Network API configuration.

    Yields:
        Connected Network API client.

    Example:
        >>> async with create_client(config) as client:
        ...     devices = await client.list_devices()
    """
    client = UniFiNetworkClient(config)
    try:
        await client.connect()
        yield client
    finally:
        await client.close()
