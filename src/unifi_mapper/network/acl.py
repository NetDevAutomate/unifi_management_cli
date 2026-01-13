"""ACL (Access Control List) rule management.

This module provides tools for managing network ACL rules including
traffic filtering, device enforcement, and security policy management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unifi_mapper.network.models import (
    ACLActionType,
    ACLProtocol,
    ACLRule,
    ACLTrafficFilter,
)


if TYPE_CHECKING:
    from unifi_mapper.network.client import UniFiNetworkClient


log = logging.getLogger(__name__)


@dataclass
class ACLRuleStats:
    """Statistics for an ACL rule."""

    rule_id: str
    rule_name: str
    action: ACLActionType
    enabled: bool = True
    has_source_filter: bool = False
    has_destination_filter: bool = False
    protocols: list[ACLProtocol] = field(default_factory=list)
    enforcing_device_count: int = 0


@dataclass
class ACLSummary:
    """Summary of ACL rules on a site."""

    total_rules: int = 0
    enabled_rules: int = 0
    disabled_rules: int = 0
    block_rules: int = 0
    allow_rules: int = 0
    user_rules: int = 0
    system_rules: int = 0
    rules_with_source_filter: int = 0
    rules_with_destination_filter: int = 0
    rules_by_protocol: dict[str, int] = field(default_factory=dict)


class ACLManager:
    """Manage network ACL rules.

    This class provides tools for managing and analyzing ACL rules
    including traffic filtering and security policy enforcement.

    Example:
        >>> manager = ACLManager(client)
        >>> rules = await manager.get_all_rules()
        >>> summary = await manager.get_acl_summary()
    """

    def __init__(self, client: UniFiNetworkClient) -> None:
        """Initialize the ACL manager.

        Args:
            client: Network API client.
        """
        self._client = client
        self._rules_cache: dict[str, ACLRule] = {}

    async def refresh_cache(self) -> None:
        """Refresh the ACL rules cache."""
        rules = await self._client.list_acl_rules()
        self._rules_cache = {r.id: r for r in rules}
        log.debug(f"Cached {len(self._rules_cache)} ACL rules")

    async def get_all_rules(self, refresh: bool = False) -> list[ACLRule]:
        """Get all ACL rules.

        Args:
            refresh: Force cache refresh.

        Returns:
            List of ACL rules.
        """
        if refresh or not self._rules_cache:
            await self.refresh_cache()
        return list(self._rules_cache.values())

    async def get_rule_by_id(self, rule_id: str) -> ACLRule | None:
        """Get an ACL rule by ID.

        Args:
            rule_id: Rule UUID.

        Returns:
            ACL rule or None.
        """
        rules = await self.get_all_rules()
        for rule in rules:
            if rule.id == rule_id:
                return rule
        return None

    async def get_rule_by_name(self, name: str) -> ACLRule | None:
        """Get an ACL rule by name.

        Args:
            name: Rule name (case-insensitive).

        Returns:
            ACL rule or None.
        """
        rules = await self.get_all_rules()
        for rule in rules:
            if rule.name.lower() == name.lower():
                return rule
        return None

    async def get_enabled_rules(self) -> list[ACLRule]:
        """Get all enabled ACL rules.

        Returns:
            List of enabled rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if r.enabled]

    async def get_disabled_rules(self) -> list[ACLRule]:
        """Get all disabled ACL rules.

        Returns:
            List of disabled rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if not r.enabled]

    async def get_block_rules(self) -> list[ACLRule]:
        """Get all BLOCK action rules.

        Returns:
            List of block rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if r.action == ACLActionType.BLOCK]

    async def get_allow_rules(self) -> list[ACLRule]:
        """Get all ALLOW action rules.

        Returns:
            List of allow rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if r.action == ACLActionType.ALLOW]

    async def get_user_rules(self) -> list[ACLRule]:
        """Get all user-defined ACL rules.

        Returns:
            List of user rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if r.origin == 'USER']

    async def get_system_rules(self) -> list[ACLRule]:
        """Get all system ACL rules.

        Returns:
            List of system rules.
        """
        rules = await self.get_all_rules()
        return [r for r in rules if r.origin == 'SYSTEM']

    async def get_rules_by_protocol(self, protocol: ACLProtocol) -> list[ACLRule]:
        """Get ACL rules filtered by protocol.

        Args:
            protocol: Protocol to filter by.

        Returns:
            List of matching rules.
        """
        rules = await self.get_all_rules()
        return [
            r for r in rules
            if r.protocol_filter and protocol in r.protocol_filter
        ]

    async def get_rules_for_network(self, network_id: str) -> list[ACLRule]:
        """Get ACL rules associated with a network.

        Args:
            network_id: Network UUID.

        Returns:
            List of rules for the network.
        """
        rules = await self.get_all_rules()
        matching = []
        for rule in rules:
            # Check network_id field
            if rule.network_id == network_id:
                matching.append(rule)
                continue
            # Check source filter
            if rule.source_filter and network_id in rule.source_filter.network_ids:
                matching.append(rule)
                continue
            # Check destination filter
            if rule.destination_filter and network_id in rule.destination_filter.network_ids:
                matching.append(rule)
        return matching

    async def get_rules_for_device(self, device_id: str) -> list[ACLRule]:
        """Get ACL rules enforced on a specific device.

        Args:
            device_id: Device UUID.

        Returns:
            List of rules enforced on the device.
        """
        rules = await self.get_all_rules()
        matching = []
        for rule in rules:
            if not rule.enforcing_device_filter:
                # Rule applies to all devices
                matching.append(rule)
            elif rule.enforcing_device_filter.device_ids is None:
                # Rule applies to all devices
                matching.append(rule)
            elif device_id in rule.enforcing_device_filter.device_ids:
                matching.append(rule)
        return matching

    async def create_block_rule(
        self,
        name: str,
        rule_type: str = 'USER',
        source_ips: list[str] | None = None,
        source_ports: list[int] | None = None,
        source_macs: list[str] | None = None,
        destination_ips: list[str] | None = None,
        destination_ports: list[int] | None = None,
        protocols: list[ACLProtocol] | None = None,
        enforcing_device_ids: list[str] | None = None,
        description: str | None = None,
    ) -> ACLRule:
        """Create a new BLOCK ACL rule.

        Args:
            name: Rule name.
            rule_type: Rule type.
            source_ips: Source IP addresses/subnets.
            source_ports: Source ports.
            source_macs: Source MAC addresses.
            destination_ips: Destination IP addresses/subnets.
            destination_ports: Destination ports.
            protocols: Protocol filter (TCP/UDP).
            enforcing_device_ids: Device IDs to enforce rule on.
            description: Optional description.

        Returns:
            Created ACL rule.
        """
        source_filter = None
        if source_ips or source_ports or source_macs:
            source_filter = {
                'ipAddressesOrSubnets': source_ips or [],
                'portsFilter': source_ports or [],
                'macAddresses': source_macs or [],
            }

        destination_filter = None
        if destination_ips or destination_ports:
            destination_filter = {
                'ipAddressesOrSubnets': destination_ips or [],
                'portsFilter': destination_ports or [],
            }

        protocol_filter = None
        if protocols:
            protocol_filter = [p.value for p in protocols]

        rule = await self._client.create_acl_rule(
            name=name,
            rule_type=rule_type,
            action='BLOCK',
            enabled=True,
            description=description,
            source_filter=source_filter,
            destination_filter=destination_filter,
            protocol_filter=protocol_filter,
            enforcing_device_ids=enforcing_device_ids,
        )

        # Update cache
        self._rules_cache[rule.id] = rule
        return rule

    async def create_allow_rule(
        self,
        name: str,
        rule_type: str = 'USER',
        source_ips: list[str] | None = None,
        source_ports: list[int] | None = None,
        destination_ips: list[str] | None = None,
        destination_ports: list[int] | None = None,
        protocols: list[ACLProtocol] | None = None,
        enforcing_device_ids: list[str] | None = None,
        description: str | None = None,
    ) -> ACLRule:
        """Create a new ALLOW ACL rule.

        Args:
            name: Rule name.
            rule_type: Rule type.
            source_ips: Source IP addresses/subnets.
            source_ports: Source ports.
            destination_ips: Destination IP addresses/subnets.
            destination_ports: Destination ports.
            protocols: Protocol filter (TCP/UDP).
            enforcing_device_ids: Device IDs to enforce rule on.
            description: Optional description.

        Returns:
            Created ACL rule.
        """
        source_filter = None
        if source_ips or source_ports:
            source_filter = {
                'ipAddressesOrSubnets': source_ips or [],
                'portsFilter': source_ports or [],
            }

        destination_filter = None
        if destination_ips or destination_ports:
            destination_filter = {
                'ipAddressesOrSubnets': destination_ips or [],
                'portsFilter': destination_ports or [],
            }

        protocol_filter = None
        if protocols:
            protocol_filter = [p.value for p in protocols]

        rule = await self._client.create_acl_rule(
            name=name,
            rule_type=rule_type,
            action='ALLOW',
            enabled=True,
            description=description,
            source_filter=source_filter,
            destination_filter=destination_filter,
            protocol_filter=protocol_filter,
            enforcing_device_ids=enforcing_device_ids,
        )

        # Update cache
        self._rules_cache[rule.id] = rule
        return rule

    async def enable_rule(self, rule_id: str) -> ACLRule:
        """Enable an ACL rule.

        Args:
            rule_id: Rule UUID.

        Returns:
            Updated rule.
        """
        rule = await self._client.update_acl_rule(rule_id, enabled=True)
        self._rules_cache[rule.id] = rule
        return rule

    async def disable_rule(self, rule_id: str) -> ACLRule:
        """Disable an ACL rule.

        Args:
            rule_id: Rule UUID.

        Returns:
            Updated rule.
        """
        rule = await self._client.update_acl_rule(rule_id, enabled=False)
        self._rules_cache[rule.id] = rule
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        """Delete an ACL rule.

        Args:
            rule_id: Rule UUID.

        Returns:
            True if successful.
        """
        await self._client.delete_acl_rule(rule_id)
        if rule_id in self._rules_cache:
            del self._rules_cache[rule_id]
        return True

    def analyze_rule(self, rule: ACLRule) -> ACLRuleStats:
        """Analyze an ACL rule.

        Args:
            rule: ACL rule to analyze.

        Returns:
            Rule statistics.
        """
        has_source = bool(rule.source_filter and (
            rule.source_filter.ip_addresses_or_subnets or
            rule.source_filter.ports_filter or
            rule.source_filter.mac_addresses or
            rule.source_filter.network_ids
        ))

        has_dest = bool(rule.destination_filter and (
            rule.destination_filter.ip_addresses_or_subnets or
            rule.destination_filter.ports_filter or
            rule.destination_filter.network_ids
        ))

        enforcing_count = 0
        if rule.enforcing_device_filter and rule.enforcing_device_filter.device_ids:
            enforcing_count = len(rule.enforcing_device_filter.device_ids)

        return ACLRuleStats(
            rule_id=rule.id,
            rule_name=rule.name,
            action=rule.action,
            enabled=rule.enabled,
            has_source_filter=has_source,
            has_destination_filter=has_dest,
            protocols=list(rule.protocol_filter) if rule.protocol_filter else [],
            enforcing_device_count=enforcing_count,
        )

    async def get_acl_summary(self) -> ACLSummary:
        """Get a summary of all ACL rules.

        Returns:
            ACL summary statistics.
        """
        rules = await self.get_all_rules()

        summary = ACLSummary(
            total_rules=len(rules),
        )

        for rule in rules:
            if rule.enabled:
                summary.enabled_rules += 1
            else:
                summary.disabled_rules += 1

            if rule.action == ACLActionType.BLOCK:
                summary.block_rules += 1
            else:
                summary.allow_rules += 1

            if rule.origin == 'USER':
                summary.user_rules += 1
            elif rule.origin == 'SYSTEM':
                summary.system_rules += 1

            if rule.source_filter and (
                rule.source_filter.ip_addresses_or_subnets or
                rule.source_filter.ports_filter or
                rule.source_filter.mac_addresses
            ):
                summary.rules_with_source_filter += 1

            if rule.destination_filter and (
                rule.destination_filter.ip_addresses_or_subnets or
                rule.destination_filter.ports_filter
            ):
                summary.rules_with_destination_filter += 1

            if rule.protocol_filter:
                for protocol in rule.protocol_filter:
                    key = protocol.value
                    summary.rules_by_protocol[key] = (
                        summary.rules_by_protocol.get(key, 0) + 1
                    )

        return summary

    async def get_security_report(self) -> dict:
        """Generate a security report for ACL rules.

        Returns:
            Security report dictionary.
        """
        rules = await self.get_all_rules()
        summary = await self.get_acl_summary()

        # Analyze rules for potential issues
        issues = []
        recommendations = []

        # Check for disabled rules
        disabled = [r for r in rules if not r.enabled]
        if disabled:
            issues.append({
                'severity': 'INFO',
                'message': f'{len(disabled)} ACL rules are disabled',
                'rule_ids': [r.id for r in disabled],
            })

        # Check for rules without filters
        overly_broad = []
        for rule in rules:
            has_filter = bool(
                rule.source_filter or
                rule.destination_filter or
                rule.protocol_filter
            )
            if not has_filter and rule.action == ACLActionType.BLOCK:
                overly_broad.append(rule)

        if overly_broad:
            issues.append({
                'severity': 'WARNING',
                'message': f'{len(overly_broad)} BLOCK rules have no specific filters',
                'rule_ids': [r.id for r in overly_broad],
            })
            recommendations.append(
                'Consider adding source/destination filters to broad BLOCK rules'
            )

        # Check for rules enforced on all devices
        global_rules = [
            r for r in rules
            if not r.enforcing_device_filter or
            not r.enforcing_device_filter.device_ids
        ]
        if len(global_rules) > 5:
            recommendations.append(
                f'{len(global_rules)} rules are enforced on all devices. '
                'Consider targeting specific switches for better performance.'
            )

        return {
            'summary': {
                'total_rules': summary.total_rules,
                'enabled_rules': summary.enabled_rules,
                'block_rules': summary.block_rules,
                'allow_rules': summary.allow_rules,
                'user_rules': summary.user_rules,
                'system_rules': summary.system_rules,
            },
            'issues': issues,
            'recommendations': recommendations,
            'rules_by_protocol': summary.rules_by_protocol,
        }
