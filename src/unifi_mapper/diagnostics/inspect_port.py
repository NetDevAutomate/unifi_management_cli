"""Deep single-port inspection tool for MCP consumers.

Wraps the synchronous :mod:`unifi_mapper.port_inspect` implementation so the
same logic backs both the CLI (``unifi-mapper ports inspect``) and the MCP
server. The sync work is offloaded to a worker thread so it never blocks the
event loop.

The controller session is the one every sync port-diagnostics tool uses (issue 021):
:func:`port_diagnostics_tools._readonly_sync_client` logs in once per call, installs the
read-only guard (which refuses a write before it is sent and records each request in the
opt-in ``UNIFI_MCP_REQUEST_AUDIT`` file) and logs out; :func:`port_diagnostics_tools._mapped`
turns a refused write into ``READ_ONLY_VIOLATION``. Both are looked up on the module at
call time, as the sibling tools do, so one test seam (patching
``port_diagnostics_tools._readonly_sync_client``) covers every sync tool.
"""

from __future__ import annotations

import asyncio
from pydantic import Field
from typing import Annotated, Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics import port_diagnostics_tools as _sync_tools


def _inspect_sync(switch: str, port: int) -> dict[str, Any]:
    """Run the blocking inspection behind the read-only guard; return a JSON-serialisable result.

    ``resolve_switch`` and ``inspect_port`` raise ``LookupError`` (not the
    ``diagnostic_reads`` exceptions ``_mapped`` knows), so this maps them to the tool's own
    ``DEVICE_NOT_FOUND`` and ``INVALID_PORT``; the login failure and a refused write are
    mapped by the shared helpers.
    """
    from unifi_mapper.port_inspect import inspect_port, resolve_switch

    with _sync_tools._readonly_sync_client() as (client, site):
        try:
            target = resolve_switch(client, site, switch)
        except LookupError as e:
            raise ToolError(
                message=str(e),
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
                suggestion=(
                    'Pass a more specific switch name, or use its IP or MAC address. '
                    'Use find_device to list candidates.'
                ),
                related_tools=['find_device', 'find_mac'],
            ) from e

        try:
            result = inspect_port(client, site, target, port)
        except LookupError as e:
            raise ToolError(
                message=str(e),
                error_code=ErrorCodes.INVALID_PORT,
                suggestion='Use a port index that exists on this switch.',
                related_tools=['find_device'],
            ) from e

        return result.to_dict()


async def inspect_switch_port(
    switch: Annotated[
        str,
        Field(description='Switch name, model, IP or MAC (e.g. "Rack Switch 24")'),
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
    2. If addressing is "no_address", audit_uplink_transparency() to verify
       every hop carries that VLAN
    3. audit_vlan_coverage() to confirm trunk membership end to end
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
        ToolError: INVALID_PORT if the port does not exist on the switch.
        ToolError: CONTROLLER_UNREACHABLE if the login fails or raises.
        ToolError: READ_ONLY_VIOLATION if the inspection attempted a controller
            write (a bug; the read-only guard refuses it before it is sent).
    """
    return await asyncio.to_thread(_sync_tools._mapped, _inspect_sync, switch, port)
