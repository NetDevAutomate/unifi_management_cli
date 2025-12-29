"""Port mirroring session management tools."""

from datetime import datetime
from typing import Any
from unifi_mcp.models import (
    MirrorCapability,
    MirrorReport,
    MirrorSession,
    MirrorSessionResult,
)
from unifi_mcp.tools.mirroring.capabilities import get_mirror_capabilities
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


async def list_mirror_sessions(device_id: str | None = None) -> list[MirrorReport]:
    """List all active port mirroring sessions.

    When to use this tool:
    - To check current SPAN session status before creating new ones
    - When troubleshooting why a packet capture isn't working
    - To audit active monitoring on the network
    - Before deleting sessions to get the session_id

    Common workflow:
    1. list_mirror_sessions() - see all active sessions
    2. If session not working: check available_session_slots > 0
    3. If need different configuration: delete_mirror_session() then create new

    What to do next:
    - If available_session_slots is 0: delete unused session first
    - If sessions empty but expected: verify device supports mirroring
    - If destination_port shows no traffic: check cable and analyzer setup

    Args:
        device_id: Optional device ID to filter by. If None, returns all devices.

    Returns:
        List of MirrorReport objects with device capabilities and active sessions

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            reports: list[MirrorReport] = []

            for device in devices:
                # Filter by device_id if specified
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                # Only process switch-type devices
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch') and not device_id:
                    continue

                # Get capabilities for this device
                caps_list = await get_mirror_capabilities(device.get('_id'))
                if not caps_list:
                    continue
                capabilities = caps_list[0]

                # Parse active mirror sessions from port_overrides
                active_sessions = _parse_mirror_sessions(device)

                # Calculate available slots
                available_slots = max(0, capabilities.max_sessions - len(active_sessions))

                report = MirrorReport(
                    device_id=device.get('_id', ''),
                    device_name=device.get('name', device.get('mac', 'Unknown')),
                    capabilities=capabilities,
                    active_sessions=active_sessions,
                    available_session_slots=available_slots,
                    report_time=datetime.now(),
                )

                reports.append(report)

                if device_id:
                    break

            if device_id and not reports:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_mirror_capabilities'],
                )

            return reports

        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                message=f'Error listing mirror sessions: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )


def _parse_mirror_sessions(device: dict[str, Any]) -> list[MirrorSession]:
    """Parse mirror session configurations from device data."""
    sessions: list[MirrorSession] = []
    port_overrides = device.get('port_overrides', [])
    port_table = device.get('port_table', [])

    # Build port name lookup
    port_names: dict[int, str] = {}
    for port in port_table:
        idx = port.get('port_idx', 0)
        name = port.get('name', '') or f'Port {idx}'
        port_names[idx] = name

    # Look for mirror configurations in port_overrides
    # UniFi stores mirror config as 'mirror_port_idx' on source ports
    mirror_destinations: dict[int, list[int]] = {}  # dest_idx -> [source_idxs]

    for override in port_overrides:
        mirror_port = override.get('mirror_port_idx')
        if mirror_port is not None and mirror_port > 0:
            source_idx = override.get('port_idx', 0)
            if mirror_port not in mirror_destinations:
                mirror_destinations[mirror_port] = []
            mirror_destinations[mirror_port].append(source_idx)

    # Create session objects from parsed data
    for dest_idx, source_idxs in mirror_destinations.items():
        for source_idx in source_idxs:
            session = MirrorSession(
                session_id=f'mirror-{device.get("_id", "")[:8]}-{source_idx}-{dest_idx}',
                device_id=device.get('_id', ''),
                device_name=device.get('name', device.get('mac', 'Unknown')),
                source_port_idx=source_idx,
                destination_port_idx=dest_idx,
                source_port_name=port_names.get(source_idx, f'Port {source_idx}'),
                destination_port_name=port_names.get(dest_idx, f'Port {dest_idx}'),
                enabled=True,
                description=f'Mirror from port {source_idx} to port {dest_idx}',
            )
            sessions.append(session)

    return sessions


async def create_mirror_session(
    device_id: str,
    source_port: int,
    destination_port: int,
    description: str | None = None,
) -> MirrorSessionResult:
    """Create a new port mirroring (SPAN) session on a switch.

    When to use this tool:
    - Setting up packet capture for network troubleshooting
    - Configuring traffic analysis with Wireshark or similar tools
    - Monitoring specific port traffic for security analysis
    - Creating tap points for network monitoring systems

    Forbidden actions:
    - Do not create sessions on devices with capability_level NONE
    - Do not use uplink ports as destination (will disrupt network)
    - Do not exceed max_sessions for the device

    Prerequisites:
    1. Call get_mirror_capabilities() to verify device supports mirroring
    2. Ensure destination_port is connected to your packet analyzer
    3. Verify available_session_slots > 0 via list_mirror_sessions()

    Common workflow:
    1. get_mirror_capabilities(device_id) - confirm support
    2. create_mirror_session() - set up the SPAN session
    3. Connect analyzer to destination port and start capture
    4. When done: delete_mirror_session() to clean up

    What to do next:
    - If success: Connect packet analyzer to destination_port
    - If error about max sessions: Delete an existing session first
    - If error about ports: Use list_mirror_sessions() to find valid port numbers

    Args:
        device_id: UniFi device ID (from find_device or get_mirror_capabilities)
        source_port: Port index to monitor (traffic will be copied from here)
        destination_port: Port index for mirrored traffic (connect analyzer here)
        description: Optional human-readable description for the session

    Returns:
        MirrorSessionResult with success status and session details

    Raises:
        ToolError: DEVICE_NOT_FOUND if device doesn't exist
        ToolError: INVALID_INPUT if ports are invalid or device doesn't support mirroring
        ToolError: RESOURCE_CONFLICT if max sessions reached
    """
    async with UniFiClient() as client:
        try:
            # Validate device and capabilities
            caps_list = await get_mirror_capabilities(device_id)
            if not caps_list:
                raise ToolError(
                    message=f'Device {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                )

            caps = caps_list[0]

            # Check capability level
            if caps.capability_level == MirrorCapability.NONE:
                return MirrorSessionResult(
                    success=False,
                    message=f'Device {caps.device_name} does not support port mirroring',
                    errors=[
                        f'Model {caps.model} has no mirroring capability',
                        *caps.restrictions,
                    ],
                )

            # Validate ports
            if source_port not in caps.available_ports:
                return MirrorSessionResult(
                    success=False,
                    message=f'Source port {source_port} is not available for mirroring',
                    errors=[
                        f'Available ports: {caps.available_ports}',
                        'Port may be an uplink or not exist',
                    ],
                )

            if destination_port not in caps.available_ports:
                return MirrorSessionResult(
                    success=False,
                    message=f'Destination port {destination_port} is not available',
                    errors=[
                        f'Available ports: {caps.available_ports}',
                        'Port may be an uplink or not exist',
                    ],
                )

            if source_port == destination_port:
                return MirrorSessionResult(
                    success=False,
                    message='Source and destination ports cannot be the same',
                    errors=['Select different ports for source and destination'],
                )

            # Check session availability
            reports = await list_mirror_sessions(device_id)
            if reports:
                report = reports[0]
                if report.available_session_slots <= 0:
                    return MirrorSessionResult(
                        success=False,
                        message=f'No available mirror session slots on {caps.device_name}',
                        errors=[
                            f'Max sessions: {caps.max_sessions}',
                            f'Active sessions: {len(report.active_sessions)}',
                        ],
                        warnings=['Delete an existing session to create a new one'],
                    )

                # Check if this exact session already exists
                for existing in report.active_sessions:
                    if (
                        existing.source_port_idx == source_port
                        and existing.destination_port_idx == destination_port
                    ):
                        return MirrorSessionResult(
                            success=True,
                            message='Mirror session already exists',
                            session=existing,
                            warnings=['Session was already configured'],
                        )

            # Create the mirror session via port override
            device = await client.get_device(device_id)
            if not device:
                raise ToolError(
                    message=f'Device {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                )

            # Get current port overrides
            port_overrides = list(device.get('port_overrides', []))

            # Find or create override for source port
            source_override = None
            for override in port_overrides:
                if override.get('port_idx') == source_port:
                    source_override = override
                    break

            if source_override:
                # Update existing override
                source_override['mirror_port_idx'] = destination_port
            else:
                # Create new override
                port_overrides.append(
                    {
                        'port_idx': source_port,
                        'mirror_port_idx': destination_port,
                    }
                )

            # Apply the configuration
            await client.update_device_port(device_id, port_overrides)

            # Create session object for response
            session = MirrorSession(
                session_id=f'mirror-{device_id[:8]}-{source_port}-{destination_port}',
                device_id=device_id,
                device_name=caps.device_name,
                source_port_idx=source_port,
                destination_port_idx=destination_port,
                source_port_name=f'Port {source_port}',
                destination_port_name=f'Port {destination_port}',
                enabled=True,
                description=description or f'Mirror from port {source_port} to {destination_port}',
            )

            return MirrorSessionResult(
                success=True,
                message=f'Mirror session created on {caps.device_name}',
                session=session,
                warnings=[
                    f'Connect packet analyzer to port {destination_port}',
                    'Session active - traffic is now being mirrored',
                ],
            )

        except ToolError:
            raise
        except Exception as e:
            return MirrorSessionResult(
                success=False,
                message=f'Failed to create mirror session: {e}',
                errors=[str(e)],
            )


async def delete_mirror_session(
    device_id: str,
    source_port: int,
) -> MirrorSessionResult:
    """Delete a port mirroring (SPAN) session from a switch.

    When to use this tool:
    - After completing packet capture/analysis
    - When reconfiguring mirror sessions
    - To free up session slots for new configurations
    - During cleanup of test/troubleshooting configurations

    Common workflow:
    1. list_mirror_sessions(device_id) - find session to delete
    2. delete_mirror_session() - remove the configuration
    3. Optionally create_mirror_session() with new configuration

    What to do next:
    - If success: Session is removed, port returns to normal operation
    - If error: Verify session exists via list_mirror_sessions()

    Args:
        device_id: UniFi device ID containing the session
        source_port: Source port index of the session to delete

    Returns:
        MirrorSessionResult with success status

    Raises:
        ToolError: DEVICE_NOT_FOUND if device doesn't exist
        ToolError: RESOURCE_NOT_FOUND if session doesn't exist
    """
    async with UniFiClient() as client:
        try:
            # Get device
            device = await client.get_device(device_id)
            if not device:
                raise ToolError(
                    message=f'Device {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                )

            device_name = device.get('name', device.get('mac', 'Unknown'))

            # Get current port overrides
            port_overrides = list(device.get('port_overrides', []))

            # Find and remove the mirror configuration
            session_found = False
            updated_overrides = []

            for override in port_overrides:
                if override.get('port_idx') == source_port:
                    if override.get('mirror_port_idx'):
                        session_found = True
                        # Remove mirror_port_idx but keep other overrides
                        override_copy = dict(override)
                        del override_copy['mirror_port_idx']
                        if len(override_copy) > 1:  # More than just port_idx
                            updated_overrides.append(override_copy)
                        # else: drop the override entirely if only port_idx remains
                    else:
                        updated_overrides.append(override)
                else:
                    updated_overrides.append(override)

            if not session_found:
                return MirrorSessionResult(
                    success=False,
                    message=f'No mirror session found on port {source_port}',
                    errors=[f'Port {source_port} does not have an active mirror session'],
                    warnings=['Use list_mirror_sessions() to see active sessions'],
                )

            # Apply the updated configuration
            await client.update_device_port(device_id, updated_overrides)

            return MirrorSessionResult(
                success=True,
                message=f'Mirror session deleted from {device_name} port {source_port}',
                warnings=['Port has returned to normal operation'],
            )

        except ToolError:
            raise
        except Exception as e:
            return MirrorSessionResult(
                success=False,
                message=f'Failed to delete mirror session: {e}',
                errors=[str(e)],
            )
