"""Network control plane tool wrappers for MCP server.

These wrappers handle the lifecycle of network manager classes
and provide a consistent async interface for MCP tool execution.

Every request goes through :class:`ReadOnlyAsyncTransport` with the GET-only policy
(:func:`get_only_request_allowed`; the Integration API has no read-only POST), so a write
raises :class:`ReadOnlyViolation` before any I/O, which the runner reports as
``READ_ONLY_VIOLATION``, and every GET goes to the opt-in request audit
(``UNIFI_MCP_REQUEST_AUDIT``). Each call opens its own guarded client.
"""

from __future__ import annotations

import httpx
from loguru import logger
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.readonly import (
    ReadOnlyAsyncTransport,
    ReadOnlyViolation,
    get_only_request_allowed,
)
from unifi_mapper.network.acl import ACLManager
from unifi_mapper.network.client import UniFiNetworkClient
from unifi_mapper.network.clients import ClientManager
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.dns import DNSPolicyManager
from unifi_mapper.network.firewall import FirewallManager
from unifi_mapper.network.networks import NetworkManager


def _network_config() -> NetworkConfig:
    """Load Network API configuration from environment."""
    return NetworkConfig.from_env()


def _inner_transport(config: NetworkConfig) -> httpx.AsyncBaseTransport:
    """Return the transport that does the I/O behind the guard (the test seam).

    httpx ignores ``verify`` once a transport is given, so the TLS setting goes here.

    Args:
        config: Network API configuration.

    Returns:
        An httpx transport honouring ``config.verify_ssl``.
    """
    return httpx.AsyncHTTPTransport(verify=config.verify_ssl)


def _read_only_client() -> UniFiNetworkClient:
    """Return a Network API client whose every request passes the GET-only guard.

    Returns:
        An unconnected client; use it as an async context manager.
    """
    config = _network_config()
    guard = ReadOnlyAsyncTransport(_inner_transport(config), policy=get_only_request_allowed)
    return UniFiNetworkClient(config, transport=guard)


async def get_firewall_zones(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all firewall zones and their configurations.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of firewall zone data as dictionaries, or error dict on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = FirewallManager(client)
            zones = await manager.get_zones(refresh=refresh)
            return [z.model_dump() for z in zones]
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get firewall zones: {e}')
        return [{'error': str(e)}]


async def get_firewall_policies(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all firewall policies between zones.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of firewall policy data as dictionaries, or error dict on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = FirewallManager(client)
            policies = await manager.get_policies(refresh=refresh)
            return [p.model_dump() for p in policies]
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get firewall policies: {e}')
        return [{'error': str(e)}]


async def get_acl_rules(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all ACL rules and their configurations.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of ACL rule data as dictionaries, or error dict on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = ACLManager(client)
            rules = await manager.get_all_rules(refresh=refresh)
            return [r.model_dump() for r in rules]
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get ACL rules: {e}')
        return [{'error': str(e)}]


async def get_dns_policies() -> list[dict[str, Any]]:
    """Get DNS policies and configurations.

    Returns:
        List of DNS policy data as dictionaries, or error dict on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = DNSPolicyManager(client)
            policies = await manager.get_all_policies()
            return [p.model_dump() for p in policies]
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get DNS policies: {e}')
        return [{'error': str(e)}]


async def get_clients(
    active_only: bool = True,
    limit: Annotated[
        int, Field(description='Clients per page, 1-1000 (default 200)', ge=1, le=1000)
    ] = 200,
    offset: Annotated[
        int, Field(description='Clients to skip: the next_offset of the page before', ge=0)
    ] = 0,
) -> dict[str, Any]:
    """Get connected clients with fingerprinting data, one page at a time.

    The controller's list is read in full (every Integration API page), filtered, sorted by
    client ID and then sliced, so ``total`` counts every client and a page is stable between
    calls while the set of clients is unchanged.

    Args:
        active_only: Return only currently connected clients.
        limit: Clients per page (1-1000).
        offset: Clients to skip; pass the previous page's ``next_offset``.

    Returns:
        ``total``, ``returned``, ``offset``, ``limit``, ``next_offset`` (None on the last
        page), ``truncated`` (more clients after this page) and ``clients``; or
        ``{'error': ...}`` on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = ClientManager(client)
            clients = await manager.get_all_clients()
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get clients: {e}')
        return {'error': str(e)}
    if active_only:
        clients = [c for c in clients if c.connected_at is not None]
    ordered = sorted(clients, key=lambda c: str(c.id))
    page = ordered[offset : offset + limit]
    end = offset + len(page)
    more = end < len(ordered)
    return {
        'total': len(ordered),
        'returned': len(page),
        'offset': offset,
        'limit': limit,
        'next_offset': end if more else None,
        'truncated': more,
        'clients': [c.model_dump() for c in page],
    }


async def get_networks() -> list[dict[str, Any]]:
    """Get networks/VLANs and their configurations.

    Returns:
        List of network data as dictionaries, or error dict on failure.
    """
    try:
        async with _read_only_client() as client:
            manager = NetworkManager(client)
            networks = await manager.get_all_networks()
            return [n.model_dump() for n in networks]
    except ReadOnlyViolation:
        raise
    except Exception as e:
        logger.error(f'Failed to get networks: {e}')
        return [{'error': str(e)}]
