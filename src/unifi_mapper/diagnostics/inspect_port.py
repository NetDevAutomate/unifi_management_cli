"""Deep single-port inspection tool for MCP consumers.

Wraps the synchronous :mod:`unifi_mapper.port_inspect` implementation so the
same logic backs both the CLI (``unifi-mapper ports inspect``) and the MCP
server. The sync work is offloaded to a worker thread so it never blocks the
event loop.
"""

from __future__ import annotations

import asyncio
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


def _inspect_sync(switch: str, port: int) -> dict[str, Any]:
    """Run the blocking inspection and return a JSON-serialisable result."""
    from unifi_mapper.api_client import UnifiApiClient
    from unifi_mapper.port_inspect import inspect_port, resolve_switch

    creds = Credentials.from_env()
    scheme = 'https' if creds.port != 80 else 'http'
    base_url = f'{scheme}://{creds.host}:{creds.port}'

    client = UnifiApiClient(
        base_url=base_url,
        site=creds.site,
        verify_ssl=creds.verify_ssl,
        username=creds.username,
        password=creds.password,
        api_token=creds.api_token,
    )

    if not client.login():
        raise ToolError(
            message=f'Could not authenticate to the UniFi controller at {creds.host}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=(
                'Check UNIFI_URL and UNIFI_CONSOLE_API_TOKEN (or '
                'UNIFI_USERNAME/UNIFI_PASSWORD). The account must be local to the '
                'controller, not a UniFi Cloud account.'
            ),
        )

    try:
        try:
            target = resolve_switch(client, creds.site, switch)
        except LookupError as e:
            raise ToolError(
                message=str(e),
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion=(
                    'Pass a more specific switch name, or use its IP or MAC address. '
                    'Use find_device to list candidates.'
                ),
                related_tools=['find_device', 'find_mac'],
            )

        try:
            result = inspect_port(client, creds.site, target, port)
        except LookupError as e:
            raise ToolError(
                message=str(e),
                error_code=ErrorCodes.INVALID_PORT,
                suggestion='Use a port index that exists on this switch.',
                related_tools=['find_device'],
            )

        return result.to_dict()
    finally:
        client.logout()


async def inspect_switch_port(
    switch: Annotated[
        str,
        Field(description='Switch name, model, IP or MAC (e.g. "Office Desk Flex 5")'),
    ],
    port: Annotated[int, Field(description='Port index on the switch, 1-based')],
) -> dict[str, Any]:
    """Inspect one switch port in depth, including what is plugged into it.

    When to use this tool:
    - A host links up but misbehaves at L3, for example never obtains DHCP
    - Identifying exactly what is connected to a port, UniFi gear or not
    - Confirming which VLAN a port places untagged traffic into
    - Checking whether a client holds a real DHCP lease or a static address
    - Investigating a port that looks down but appears to still pass traffic

    How this differs from the other port tools:
    - analyze_link_quality scores error counters across every port
    - find_mac locates which port a MAC sits on
    - This tool answers "tell me everything about this one port"

    What it reports:
    - Link state: up, speed, duplex, media, autoneg, STP state, flap count
    - Effective port profile and which VLANs the port actually forwards
    - The native network with its subnet, gateway and DHCP pool
    - The connected device, with a fingerprint-guessed model and confidence
      score for third-party hosts, or the adopted-device record for UniFi gear
    - Addressing verdict: leased, static, or no address at all
    - LLDP neighbour, resolved against the adopted-device registry so switches
      and access points are named even when they send no system_name
    - The switch's remembered last_connection, error counters and PoE state
    - A freshness warning when cached controller state disagrees with reality

    Interpreting the addressing verdict:
    - "leased": a DHCP lease expiry exists, so DHCP is working on this port
    - "static": an address with no lease, configured on the host itself
    - "no_address": the client is present but unaddressed. Check that the
      native VLAN reaches the gateway on every hop of the uplink path, and
      that the switch has been provisioned since the VLAN was created
    - "no_client": nothing is reporting on the port

    Common workflow:
    1. inspect_switch_port() to establish the port's VLAN and addressing state
    2. If addressing is "no_address", check_uplink_transparency() to verify
       every hop carries that VLAN
    3. vlan_coverage() to confirm trunk membership end to end
    4. analyze_link_quality() if the fault looks physical rather than logical

    Args:
        switch: Switch name, model, IP or MAC. Partial names work when they
            resolve to exactly one switch.
        port: Port index on that switch, 1-based.

    Returns:
        Dictionary containing switch, port_idx, link, profile, network,
        connected_device, addressing, lldp, last_connection, counters, poe
        and freshness sections.

    Raises:
        ToolError: DEVICE_NOT_FOUND if the switch cannot be resolved uniquely.
        ToolError: INVALID_PARAMETER if the port does not exist on the switch.
        ToolError: CONTROLLER_UNREACHABLE if authentication fails.
    """
    return await asyncio.to_thread(_inspect_sync, switch, port)
