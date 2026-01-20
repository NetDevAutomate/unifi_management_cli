"""Network control plane tool wrappers for MCP server.

These wrappers handle the lifecycle of network manager classes
and provide a consistent async interface for MCP tool execution.
"""

from __future__ import annotations

from loguru import logger
from typing import Any
from unifi_mapper.core.utils import UniFiClient
from unifi_mapper.network.acl import ACLManager
from unifi_mapper.network.clients import ClientManager
from unifi_mapper.network.dns import DNSPolicyManager
from unifi_mapper.network.firewall import FirewallManager
from unifi_mapper.network.networks import NetworkManager


async def get_firewall_zones(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all firewall zones and their configurations.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of firewall zone data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = FirewallManager(client)
            zones = await manager.get_zones(refresh=refresh)
            return [z.model_dump() for z in zones]
    except Exception as e:
        logger.error(f"Failed to get firewall zones: {e}")
        return [{"error": str(e)}]


async def get_firewall_policies(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all firewall policies between zones.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of firewall policy data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = FirewallManager(client)
            policies = await manager.get_policies(refresh=refresh)
            return [p.model_dump() for p in policies]
    except Exception as e:
        logger.error(f"Failed to get firewall policies: {e}")
        return [{"error": str(e)}]


async def get_acl_rules(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all ACL rules and their configurations.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of ACL rule data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = ACLManager(client)
            rules = await manager.get_rules(refresh=refresh)
            return [r.model_dump() for r in rules]
    except Exception as e:
        logger.error(f"Failed to get ACL rules: {e}")
        return [{"error": str(e)}]


async def get_dns_policies() -> list[dict[str, Any]]:
    """Get DNS policies and configurations.

    Returns:
        List of DNS policy data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = DNSPolicyManager(client)
            policies = await manager.get_policies()
            return [p.model_dump() for p in policies]
    except Exception as e:
        logger.error(f"Failed to get DNS policies: {e}")
        return [{"error": str(e)}]


async def get_clients(active_only: bool = True) -> list[dict[str, Any]]:
    """Get connected clients with fingerprinting data.

    Args:
        active_only: Return only currently connected clients.

    Returns:
        List of client data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = ClientManager(client)
            clients = await manager.get_clients(active_only=active_only)
            return [c.model_dump() for c in clients]
    except Exception as e:
        logger.error(f"Failed to get clients: {e}")
        return [{"error": str(e)}]


async def get_networks() -> list[dict[str, Any]]:
    """Get networks/VLANs and their configurations.

    Returns:
        List of network data as dictionaries, or error dict on failure.
    """
    try:
        async with UniFiClient() as client:
            manager = NetworkManager(client)
            networks = await manager.get_networks()
            return [n.model_dump() for n in networks]
    except Exception as e:
        logger.error(f"Failed to get networks: {e}")
        return [{"error": str(e)}]
