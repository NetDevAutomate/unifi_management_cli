"""DNS Policy management.

This module provides tools for managing DNS policies including
domain resolution, DNS record management, and local DNS configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unifi_mapper.network.models import DNSPolicy


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class DNSPolicySummary:
    """Summary of DNS policies on a site."""

    total_policies: int = 0
    enabled_policies: int = 0
    disabled_policies: int = 0
    a_records: int = 0
    aaaa_records: int = 0
    cname_records: int = 0
    mx_records: int = 0
    txt_records: int = 0
    srv_records: int = 0
    other_records: int = 0
    domains: list[str] = field(default_factory=list)


@dataclass
class DNSRecordInfo:
    """Information about a DNS record."""

    policy_id: str
    domain: str
    record_type: str
    enabled: bool
    ttl_seconds: int
    value: str  # IP address, target domain, etc.


class DNSPolicyManager:
    """Manage network DNS policies.

    This class provides tools for managing and analyzing DNS policies
    including domain resolution and local DNS configuration.

    Example:
        >>> manager = DNSPolicyManager(client)
        >>> policies = await manager.get_all_policies()
        >>> await manager.create_a_record('local.example.com', '192.168.1.100')
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the DNS policy manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._policies_cache: dict[str, DNSPolicy] = {}

    async def refresh_cache(self) -> None:
        """Refresh the DNS policies cache."""
        policies = await self._client.list_dns_policies()
        self._policies_cache = {p.id: p for p in policies}
        log.debug(f"Cached {len(self._policies_cache)} DNS policies")

    async def get_all_policies(self, refresh: bool = False) -> list[DNSPolicy]:
        """Get all DNS policies.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of DNS policies.
        """
        if refresh or not self._policies_cache:
            await self.refresh_cache()
        return list(self._policies_cache.values())

    async def get_policy_by_id(self, policy_id: str) -> DNSPolicy | None:
        """Get a DNS policy by ID.

        Args:
            policy_id: Policy UUID.

        Returns:
            DNS policy or None.
        """
        policies = await self.get_all_policies()
        for policy in policies:
            if policy.id == policy_id:
                return policy
        return None

    async def get_policy_by_domain(self, domain: str) -> DNSPolicy | None:
        """Get a DNS policy by domain.

        Args:
            domain: Domain name (case-insensitive).

        Returns:
            DNS policy or None.
        """
        policies = await self.get_all_policies()
        for policy in policies:
            if policy.domain.lower() == domain.lower():
                return policy
        return None

    async def get_enabled_policies(self) -> list[DNSPolicy]:
        """Get all enabled DNS policies.

        Returns:
            List of enabled policies.
        """
        policies = await self.get_all_policies()
        return [p for p in policies if p.enabled]

    async def get_disabled_policies(self) -> list[DNSPolicy]:
        """Get all disabled DNS policies.

        Returns:
            List of disabled policies.
        """
        policies = await self.get_all_policies()
        return [p for p in policies if not p.enabled]

    async def get_policies_by_type(self, record_type: str) -> list[DNSPolicy]:
        """Get DNS policies by record type.

        Args:
            record_type: Record type (A, AAAA, CNAME, MX, TXT, SRV).

        Returns:
            List of matching policies.
        """
        policies = await self.get_all_policies()
        return [p for p in policies if p.type.upper() == record_type.upper()]

    async def search_policies(self, query: str) -> list[DNSPolicy]:
        """Search DNS policies by domain.

        Args:
            query: Search query (partial match, case-insensitive).

        Returns:
            List of matching policies.
        """
        policies = await self.get_all_policies()
        query_lower = query.lower()
        return [p for p in policies if query_lower in p.domain.lower()]

    async def create_a_record(
        self,
        domain: str,
        ipv4_address: str,
        ttl_seconds: int = 3600,
        enabled: bool = True,
    ) -> DNSPolicy:
        """Create an A record DNS policy.

        Args:
            domain: Domain name.
            ipv4_address: IPv4 address.
            ttl_seconds: TTL in seconds.
            enabled: Whether policy is enabled.

        Returns:
            Created DNS policy.
        """
        policy = await self._client.create_dns_policy(
            domain=domain,
            policy_type='A',
            ipv4_address=ipv4_address,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )
        self._policies_cache[policy.id] = policy
        return policy

    async def create_aaaa_record(
        self,
        domain: str,
        ipv6_address: str,
        ttl_seconds: int = 3600,
        enabled: bool = True,
    ) -> DNSPolicy:
        """Create an AAAA record DNS policy.

        Args:
            domain: Domain name.
            ipv6_address: IPv6 address.
            ttl_seconds: TTL in seconds.
            enabled: Whether policy is enabled.

        Returns:
            Created DNS policy.
        """
        policy = await self._client.create_dns_policy(
            domain=domain,
            policy_type='AAAA',
            ipv6_address=ipv6_address,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )
        self._policies_cache[policy.id] = policy
        return policy

    async def update_policy(
        self,
        policy_id: str,
        **updates,
    ) -> DNSPolicy:
        """Update a DNS policy.

        Args:
            policy_id: Policy UUID.
            **updates: Fields to update.

        Returns:
            Updated policy.
        """
        policy = await self._client.update_dns_policy(policy_id, **updates)
        self._policies_cache[policy.id] = policy
        return policy

    async def enable_policy(self, policy_id: str) -> DNSPolicy:
        """Enable a DNS policy.

        Args:
            policy_id: Policy UUID.

        Returns:
            Updated policy.
        """
        return await self.update_policy(policy_id, enabled=True)

    async def disable_policy(self, policy_id: str) -> DNSPolicy:
        """Disable a DNS policy.

        Args:
            policy_id: Policy UUID.

        Returns:
            Updated policy.
        """
        return await self.update_policy(policy_id, enabled=False)

    async def update_ttl(self, policy_id: str, ttl_seconds: int) -> DNSPolicy:
        """Update the TTL of a DNS policy.

        Args:
            policy_id: Policy UUID.
            ttl_seconds: New TTL in seconds.

        Returns:
            Updated policy.
        """
        return await self.update_policy(policy_id, ttlSeconds=ttl_seconds)

    async def delete_policy(self, policy_id: str) -> bool:
        """Delete a DNS policy.

        Args:
            policy_id: Policy UUID.

        Returns:
            True if successful.
        """
        await self._client.delete_dns_policy(policy_id)
        if policy_id in self._policies_cache:
            del self._policies_cache[policy_id]
        return True

    def get_record_info(self, policy: DNSPolicy) -> DNSRecordInfo:
        """Get detailed information about a DNS record.

        Args:
            policy: DNS policy.

        Returns:
            DNS record information.
        """
        # Determine the value based on record type
        value = ''
        if policy.ipv4_address:
            value = policy.ipv4_address
        elif policy.ipv6_address:
            value = policy.ipv6_address
        elif policy.target_domain:
            value = policy.target_domain
        elif policy.mail_server_domain:
            value = policy.mail_server_domain
        elif policy.text:
            value = policy.text
        elif policy.ip_address:
            value = policy.ip_address

        return DNSRecordInfo(
            policy_id=policy.id,
            domain=policy.domain,
            record_type=policy.type,
            enabled=policy.enabled,
            ttl_seconds=policy.ttl_seconds,
            value=value,
        )

    async def get_summary(self) -> DNSPolicySummary:
        """Get a summary of all DNS policies.

        Returns:
            DNS policy summary.
        """
        policies = await self.get_all_policies()

        summary = DNSPolicySummary(
            total_policies=len(policies),
            domains=[p.domain for p in policies],
        )

        for policy in policies:
            if policy.enabled:
                summary.enabled_policies += 1
            else:
                summary.disabled_policies += 1

            record_type = policy.type.upper()
            if record_type == 'A':
                summary.a_records += 1
            elif record_type == 'AAAA':
                summary.aaaa_records += 1
            elif record_type == 'CNAME':
                summary.cname_records += 1
            elif record_type == 'MX':
                summary.mx_records += 1
            elif record_type == 'TXT':
                summary.txt_records += 1
            elif record_type == 'SRV':
                summary.srv_records += 1
            else:
                summary.other_records += 1

        return summary

    async def export_policies(self) -> list[dict]:
        """Export all DNS policies as dictionaries.

        Returns:
            List of policy dictionaries.
        """
        policies = await self.get_all_policies()
        return [
            {
                'domain': p.domain,
                'type': p.type,
                'enabled': p.enabled,
                'ttl_seconds': p.ttl_seconds,
                'ipv4_address': p.ipv4_address,
                'ipv6_address': p.ipv6_address,
                'target_domain': p.target_domain,
            }
            for p in policies
        ]

    async def get_domains_list(self) -> list[str]:
        """Get list of all configured domains.

        Returns:
            List of domain names.
        """
        policies = await self.get_all_policies()
        return sorted(set(p.domain for p in policies))
