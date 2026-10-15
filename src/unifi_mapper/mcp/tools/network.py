"""Network control plane tool wrappers for MCP server.

These wrappers handle the lifecycle of network manager classes
and provide a consistent async interface for MCP tool execution.

Every request goes through :class:`ReadOnlyAsyncTransport` with the GET-only policy
(:func:`get_only_request_allowed`; the Integration API has no read-only POST), so a write
raises :class:`ReadOnlyViolation` before any I/O, which the runner reports as
``READ_ONLY_VIOLATION``, and every GET goes to the opt-in request audit
(``UNIFI_MCP_REQUEST_AUDIT``). Each call opens its own guarded client.

A failure is an error result, never a success value (issue 011): a client error the wrapper
can name is a :class:`ToolError` with its domain code (``CONTROLLER_UNREACHABLE``,
``AUTHENTICATION_FAILED``, ``API_ERROR``); anything else propagates to the runner, which
reports it as ``TOOL_FAILED``.
"""

from __future__ import annotations

import httpx
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.readonly import (
    ReadOnlyAsyncTransport,
    get_only_request_allowed,
)
from unifi_mapper.mcp.failure_text import tool_failure
from unifi_mapper.network.acl import ACLManager
from unifi_mapper.network.client import (
    NetworkAuthenticationError,
    NetworkClientError,
    NetworkConnectionError,
    NetworkSiteResolutionError,
    UniFiNetworkClient,
)
from unifi_mapper.network.clients import ClientManager
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.dns import DNSPolicyManager
from unifi_mapper.network.firewall import FirewallManager
from unifi_mapper.network.networks import NetworkManager


CONNECTION_SUGGESTION = 'Check UNIFI_NETWORK_HOST and that the controller is reachable.'
AUTHENTICATION_SUGGESTION = 'Check UNIFI_NETWORK_API_KEY and its permissions.'
API_SUGGESTION = 'Check the controller status and try again.'
SITE_SUGGESTION = (
    'Set UNIFI_NETWORK_SITE_ID to the id of the site whose internalReference is UNIFI_SITE '
    '(from GET /proxy/network/integration/v1/sites), or set UNIFI_SITE to one of the names found.'
)


def _tool_error(action: str, error: NetworkClientError) -> ToolError:
    """Map a Network API client failure to a ``ToolError`` with its domain code.

    Args:
        action: What the tool was doing, for the log line.
        error: The client's typed exception.

    Returns:
        The error to raise; its message is the client's text, redacted.
    """
    if isinstance(error, NetworkAuthenticationError):
        code, suggestion = ErrorCodes.AUTHENTICATION_FAILED, AUTHENTICATION_SUGGESTION
    elif isinstance(error, NetworkSiteResolutionError):
        code, suggestion = ErrorCodes.CONFIG_INVALID, SITE_SUGGESTION
    elif isinstance(error, NetworkConnectionError):
        code, suggestion = ErrorCodes.CONTROLLER_UNREACHABLE, CONNECTION_SUGGESTION
    else:
        code, suggestion = ErrorCodes.API_ERROR, API_SUGGESTION
    return ToolError(message=tool_failure(action, error), error_code=code, suggestion=suggestion)


def _network_config() -> NetworkConfig:
    """Load Network API configuration from environment.

    The runner's family gate has already checked readiness, so a ``ValueError`` here (a key
    that vanished between the two reads) is reported as ``CONFIG_MISSING`` with the loader's
    own wording, never the token.

    Raises:
        ToolError: ``CONFIG_MISSING`` when the family cannot be resolved.
    """
    try:
        return NetworkConfig.from_env()
    except ValueError as e:
        raise ToolError(
            message=f'network_api family not configured: {e}',
            error_code=ErrorCodes.CONFIG_MISSING,
            suggestion=(
                'set UNIFI_NETWORK_API_KEY (UNIFI_NETWORK_HOST and UNIFI_NETWORK_SITE_ID are '
                'derived from UNIFI_URL and UNIFI_SITE when unset)'
            ),
        ) from e


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
        List of firewall zone data as dictionaries.
    """
    try:
        async with _read_only_client() as client:
            manager = FirewallManager(client)
            zones = await manager.get_zones(refresh=refresh)
            return [z.model_dump() for z in zones]
    except NetworkClientError as e:
        raise _tool_error('get firewall zones', e) from e


async def get_firewall_policies(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all firewall policies between zones.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of firewall policy data as dictionaries.
    """
    try:
        async with _read_only_client() as client:
            manager = FirewallManager(client)
            policies = await manager.get_policies(refresh=refresh)
            return [p.model_dump() for p in policies]
    except NetworkClientError as e:
        raise _tool_error('get firewall policies', e) from e


async def get_acl_rules(refresh: bool = False) -> list[dict[str, Any]]:
    """Get all ACL rules and their configurations.

    Args:
        refresh: Force cache refresh.

    Returns:
        List of ACL rule data as dictionaries.
    """
    try:
        async with _read_only_client() as client:
            manager = ACLManager(client)
            rules = await manager.get_all_rules(refresh=refresh)
            return [r.model_dump() for r in rules]
    except NetworkClientError as e:
        raise _tool_error('get ACL rules', e) from e


async def get_dns_policies() -> list[dict[str, Any]]:
    """Get DNS policies and configurations.

    Returns:
        List of DNS policy data as dictionaries.
    """
    try:
        async with _read_only_client() as client:
            manager = DNSPolicyManager(client)
            policies = await manager.get_all_policies()
            return [p.model_dump() for p in policies]
    except NetworkClientError as e:
        raise _tool_error('get DNS policies', e) from e


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

    The controller's list is read in full (every Integration API page), filtered by
    ``active_only``, sorted by client ID (ascending, as text) and then sliced, so ``total``
    counts every client that passed the filter (only connected clients while ``active_only``
    is true) and a page is stable between calls while that set is unchanged.

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
    except NetworkClientError as e:
        raise _tool_error('get clients', e) from e
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
        List of network data as dictionaries.
    """
    try:
        async with _read_only_client() as client:
            manager = NetworkManager(client)
            networks = await manager.get_all_networks()
            return [n.model_dump() for n in networks]
    except NetworkClientError as e:
        raise _tool_error('get networks', e) from e
