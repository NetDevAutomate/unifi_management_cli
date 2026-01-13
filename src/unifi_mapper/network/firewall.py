"""Firewall management with syslog logging support.

This module provides tools for managing firewall zones and policies
with integrated logging for security auditing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unifi_mapper.network.models import (
    FirewallActionType,
    FirewallPolicy,
    FirewallZone,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class PolicyHitStats:
    """Statistics for firewall policy hits.

    Note: These stats would typically be populated from syslog data.
    The UniFi API enables logging but doesn't provide hit counters directly.
    """

    policy_id: str
    policy_name: str
    hit_count: int = 0
    last_hit: datetime | None = None
    blocked_count: int = 0
    allowed_count: int = 0
    bytes_matched: int = 0


@dataclass
class ZoneTrafficStats:
    """Traffic statistics for firewall zone pairs."""

    source_zone_id: str
    source_zone_name: str
    destination_zone_id: str
    destination_zone_name: str
    policy_count: int = 0
    enabled_policies: int = 0
    logging_enabled_count: int = 0
    policies: list[FirewallPolicy] = field(default_factory=list)


class FirewallManager:
    """Manage firewall zones and policies.

    This class provides high-level operations for firewall management
    including zone configuration, policy creation, and logging control.

    Example:
        >>> manager = FirewallManager(client)
        >>> zones = await manager.get_zones()
        >>> await manager.enable_logging_for_all_policies()
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the firewall manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._zones_cache: dict[str, FirewallZone] = {}
        self._policies_cache: dict[str, FirewallPolicy] = {}

    async def refresh_cache(self) -> None:
        """Refresh the zones and policies cache."""
        zones = await self._client.list_firewall_zones()
        self._zones_cache = {z.id: z for z in zones}

        policies = await self._client.list_firewall_policies()
        self._policies_cache = {p.id: p for p in policies}

        log.debug(f"Cached {len(self._zones_cache)} zones, {len(self._policies_cache)} policies")

    async def get_zones(self, refresh: bool = False) -> list[FirewallZone]:
        """Get all firewall zones.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of firewall zones.
        """
        if refresh or not self._zones_cache:
            await self.refresh_cache()
        return list(self._zones_cache.values())

    async def get_policies(self, refresh: bool = False) -> list[FirewallPolicy]:
        """Get all firewall policies.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of firewall policies.
        """
        if refresh or not self._policies_cache:
            await self.refresh_cache()
        return list(self._policies_cache.values())

    async def get_zone_by_name(self, name: str) -> FirewallZone | None:
        """Get a zone by name.

        Args:
            name: Zone name.

        Returns:
            Firewall zone or None.
        """
        zones = await self.get_zones()
        for zone in zones:
            if zone.name.lower() == name.lower():
                return zone
        return None

    async def get_policies_for_zone_pair(
        self,
        source_zone_id: str,
        destination_zone_id: str,
    ) -> list[FirewallPolicy]:
        """Get policies for a specific source/destination zone pair.

        Args:
            source_zone_id: Source zone UUID.
            destination_zone_id: Destination zone UUID.

        Returns:
            List of matching policies.
        """
        policies = await self.get_policies()
        matching = []
        for policy in policies:
            source_match = (
                policy.source and
                policy.source.firewall_zone_id == source_zone_id
            )
            dest_match = (
                policy.destination and
                policy.destination.firewall_zone_id == destination_zone_id
            )
            if source_match and dest_match:
                matching.append(policy)
        return matching

    async def get_zone_traffic_stats(self) -> list[ZoneTrafficStats]:
        """Get traffic statistics for all zone pairs.

        Returns:
            List of zone traffic statistics.
        """
        zones = await self.get_zones()
        policies = await self.get_policies()

        # Build zone name lookup
        zone_names = {z.id: z.name for z in zones}

        # Group policies by zone pair
        zone_pairs: dict[tuple[str, str], ZoneTrafficStats] = {}

        for policy in policies:
            source_id = policy.source.firewall_zone_id if policy.source else ''
            dest_id = policy.destination.firewall_zone_id if policy.destination else ''

            if not source_id or not dest_id:
                continue

            key = (source_id, dest_id)
            if key not in zone_pairs:
                zone_pairs[key] = ZoneTrafficStats(
                    source_zone_id=source_id,
                    source_zone_name=zone_names.get(source_id, 'Unknown'),
                    destination_zone_id=dest_id,
                    destination_zone_name=zone_names.get(dest_id, 'Unknown'),
                )

            stats = zone_pairs[key]
            stats.policy_count += 1
            stats.policies.append(policy)
            if policy.enabled:
                stats.enabled_policies += 1
            if policy.logging_enabled:
                stats.logging_enabled_count += 1

        return list(zone_pairs.values())

    async def enable_logging_for_policy(self, policy_id: str) -> FirewallPolicy:
        """Enable syslog logging for a policy.

        Args:
            policy_id: Policy UUID.

        Returns:
            Updated policy.
        """
        policy = await self._client.enable_policy_logging(policy_id, enabled=True)
        self._policies_cache[policy_id] = policy
        log.info(f"Enabled logging for policy {policy.name}")
        return policy

    async def disable_logging_for_policy(self, policy_id: str) -> FirewallPolicy:
        """Disable syslog logging for a policy.

        Args:
            policy_id: Policy UUID.

        Returns:
            Updated policy.
        """
        policy = await self._client.enable_policy_logging(policy_id, enabled=False)
        self._policies_cache[policy_id] = policy
        log.info(f"Disabled logging for policy {policy.name}")
        return policy

    async def enable_logging_for_all_policies(
        self,
        block_only: bool = False,
    ) -> list[FirewallPolicy]:
        """Enable logging for all policies.

        Args:
            block_only: Only enable for BLOCK policies.

        Returns:
            List of updated policies.
        """
        policies = await self.get_policies(refresh=True)
        updated = []

        for policy in policies:
            # Skip if already enabled
            if policy.logging_enabled:
                continue

            # Skip if not a block policy and block_only is True
            if block_only and policy.action.type != FirewallActionType.BLOCK:
                continue

            # Skip system policies that may not be modifiable
            if policy.origin == 'SYSTEM':
                continue

            try:
                updated_policy = await self.enable_logging_for_policy(policy.id)
                updated.append(updated_policy)
            except Exception as e:
                log.warning(f"Failed to enable logging for {policy.name}: {e}")

        log.info(f"Enabled logging for {len(updated)} policies")
        return updated

    async def get_policies_without_logging(self) -> list[FirewallPolicy]:
        """Get all policies that don't have logging enabled.

        Returns:
            List of policies without logging.
        """
        policies = await self.get_policies()
        return [p for p in policies if not p.logging_enabled]

    async def create_block_policy(
        self,
        name: str,
        source_zone_name: str,
        destination_zone_name: str,
        logging_enabled: bool = True,
        description: str | None = None,
    ) -> FirewallPolicy:
        """Create a new block policy between zones.

        Args:
            name: Policy name.
            source_zone_name: Source zone name.
            destination_zone_name: Destination zone name.
            logging_enabled: Enable syslog logging.
            description: Optional description.

        Returns:
            Created firewall policy.

        Raises:
            ValueError: If zones not found.
        """
        source_zone = await self.get_zone_by_name(source_zone_name)
        if not source_zone:
            raise ValueError(f"Source zone not found: {source_zone_name}")

        dest_zone = await self.get_zone_by_name(destination_zone_name)
        if not dest_zone:
            raise ValueError(f"Destination zone not found: {destination_zone_name}")

        policy = await self._client.create_firewall_policy(
            name=name,
            action_type='BLOCK',
            enabled=True,
            logging_enabled=logging_enabled,
            source_zone_id=source_zone.id,
            destination_zone_id=dest_zone.id,
            description=description,
        )

        self._policies_cache[policy.id] = policy
        log.info(f"Created block policy: {name}")
        return policy

    async def create_allow_policy(
        self,
        name: str,
        source_zone_name: str,
        destination_zone_name: str,
        logging_enabled: bool = False,
        description: str | None = None,
    ) -> FirewallPolicy:
        """Create a new allow policy between zones.

        Args:
            name: Policy name.
            source_zone_name: Source zone name.
            destination_zone_name: Destination zone name.
            logging_enabled: Enable syslog logging.
            description: Optional description.

        Returns:
            Created firewall policy.

        Raises:
            ValueError: If zones not found.
        """
        source_zone = await self.get_zone_by_name(source_zone_name)
        if not source_zone:
            raise ValueError(f"Source zone not found: {source_zone_name}")

        dest_zone = await self.get_zone_by_name(destination_zone_name)
        if not dest_zone:
            raise ValueError(f"Destination zone not found: {destination_zone_name}")

        policy = await self._client.create_firewall_policy(
            name=name,
            action_type='ALLOW',
            enabled=True,
            logging_enabled=logging_enabled,
            source_zone_id=source_zone.id,
            destination_zone_id=dest_zone.id,
            description=description,
        )

        self._policies_cache[policy.id] = policy
        log.info(f"Created allow policy: {name}")
        return policy

    async def get_security_audit_report(self) -> dict:
        """Generate a security audit report.

        Returns:
            Dictionary containing audit information.
        """
        zones = await self.get_zones(refresh=True)
        policies = await self.get_policies(refresh=True)

        # Count policies by type
        block_policies = [p for p in policies if p.action.type == FirewallActionType.BLOCK]
        allow_policies = [p for p in policies if p.action.type == FirewallActionType.ALLOW]

        # Count logging status
        policies_with_logging = [p for p in policies if p.logging_enabled]
        block_policies_with_logging = [p for p in block_policies if p.logging_enabled]

        # Find disabled policies
        disabled_policies = [p for p in policies if not p.enabled]

        # Find user-defined vs system policies
        user_policies = [p for p in policies if p.origin != 'SYSTEM']
        system_policies = [p for p in policies if p.origin == 'SYSTEM']

        return {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'summary': {
                'total_zones': len(zones),
                'total_policies': len(policies),
                'block_policies': len(block_policies),
                'allow_policies': len(allow_policies),
                'policies_with_logging': len(policies_with_logging),
                'block_policies_without_logging': len(block_policies) - len(block_policies_with_logging),
                'disabled_policies': len(disabled_policies),
                'user_defined_policies': len(user_policies),
                'system_policies': len(system_policies),
            },
            'recommendations': self._generate_recommendations(
                policies, block_policies_with_logging, disabled_policies
            ),
            'zones': [
                {
                    'id': z.id,
                    'name': z.name,
                    'network_count': len(z.network_ids),
                    'configurable': z.configurable,
                }
                for z in zones
            ],
            'policies_without_logging': [
                {'id': p.id, 'name': p.name, 'action': p.action.type.value}
                for p in policies if not p.logging_enabled
            ],
        }

    def _generate_recommendations(
        self,
        all_policies: list[FirewallPolicy],
        block_with_logging: list[FirewallPolicy],
        disabled_policies: list[FirewallPolicy],
    ) -> list[str]:
        """Generate security recommendations."""
        recommendations = []

        # Check block policies without logging
        block_without_logging = [
            p for p in all_policies
            if p.action.type == FirewallActionType.BLOCK and not p.logging_enabled
        ]
        if block_without_logging:
            recommendations.append(
                f"Enable logging for {len(block_without_logging)} BLOCK policies "
                "to improve security visibility"
            )

        # Check for disabled policies
        if disabled_policies:
            recommendations.append(
                f"Review {len(disabled_policies)} disabled policies - "
                "consider removing if no longer needed"
            )

        # Check logging coverage
        total_policies = len(all_policies)
        logging_coverage = len([p for p in all_policies if p.logging_enabled])
        if total_policies > 0:
            coverage_percent = (logging_coverage / total_policies) * 100
            if coverage_percent < 50:
                recommendations.append(
                    f"Logging coverage is only {coverage_percent:.0f}% - "
                    "consider enabling for more policies"
                )

        return recommendations
