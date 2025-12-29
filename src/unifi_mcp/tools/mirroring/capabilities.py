"""Port mirroring capabilities detection tool."""

from typing import Any
from unifi_mcp.models import DeviceMirrorCapabilities, MirrorCapability
from unifi_mcp.utils.client import UniFiClient
from unifi_mcp.utils.errors import ErrorCodes, ToolError


# Model-based capability mappings for UniFi switches
MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    # Enterprise switches - full capabilities
    'US-48-PRO': {
        'level': MirrorCapability.ENTERPRISE,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Enterprise-48-PoE': {
        'level': MirrorCapability.ENTERPRISE,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Enterprise-24-PoE': {
        'level': MirrorCapability.ENTERPRISE,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Pro-48-PoE': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Pro-24-PoE': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Pro-Max-48-PoE': {
        'level': MirrorCapability.ENTERPRISE,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    'USW-Pro-Max-24-PoE': {
        'level': MirrorCapability.ENTERPRISE,
        'max_sessions': 4,
        'supports_vlan_mirror': True,
        'restrictions': [],
    },
    # Standard managed switches - advanced capabilities
    'US-48': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 2,
        'supports_vlan_mirror': False,
        'restrictions': ['No VLAN mirroring'],
    },
    'US-24': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 2,
        'supports_vlan_mirror': False,
        'restrictions': ['No VLAN mirroring'],
    },
    'USW-48': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 2,
        'supports_vlan_mirror': False,
        'restrictions': ['No VLAN mirroring'],
    },
    'USW-24': {
        'level': MirrorCapability.ADVANCED,
        'max_sessions': 2,
        'supports_vlan_mirror': False,
        'restrictions': ['No VLAN mirroring'],
    },
    # Lite switches - basic capabilities
    'USW-Lite-8-PoE': {
        'level': MirrorCapability.BASIC,
        'max_sessions': 1,
        'supports_vlan_mirror': False,
        'restrictions': ['Single session only', 'No VLAN mirroring'],
    },
    'USW-Lite-16-PoE': {
        'level': MirrorCapability.BASIC,
        'max_sessions': 1,
        'supports_vlan_mirror': False,
        'restrictions': ['Single session only', 'No VLAN mirroring'],
    },
    # Mini/Flex switches - limited
    'USW-Flex-Mini': {
        'level': MirrorCapability.NONE,
        'max_sessions': 0,
        'supports_vlan_mirror': False,
        'restrictions': ['Unmanaged switch - no mirroring support'],
    },
    'USW-Flex': {
        'level': MirrorCapability.BASIC,
        'max_sessions': 1,
        'supports_vlan_mirror': False,
        'restrictions': ['Single session only', 'No VLAN mirroring'],
    },
}


def _get_model_capabilities(model: str) -> dict[str, Any]:
    """Get capabilities for a specific model, with fallback defaults."""
    # Check exact match first
    if model in MODEL_CAPABILITIES:
        return MODEL_CAPABILITIES[model]

    # Check prefix matches for model variants
    for model_prefix, caps in MODEL_CAPABILITIES.items():
        if model.startswith(model_prefix):
            return caps

    # Default fallback based on model name hints
    model_upper = model.upper()
    if 'PRO' in model_upper or 'ENTERPRISE' in model_upper:
        return {
            'level': MirrorCapability.ADVANCED,
            'max_sessions': 2,
            'supports_vlan_mirror': False,
            'restrictions': ['Unknown model - capabilities estimated'],
        }
    elif 'LITE' in model_upper or 'FLEX' in model_upper:
        return {
            'level': MirrorCapability.BASIC,
            'max_sessions': 1,
            'supports_vlan_mirror': False,
            'restrictions': ['Unknown model - capabilities estimated'],
        }
    elif 'USW' in model_upper or 'US-' in model_upper:
        return {
            'level': MirrorCapability.BASIC,
            'max_sessions': 1,
            'supports_vlan_mirror': False,
            'restrictions': ['Unknown model - capabilities estimated'],
        }

    # Non-switch devices
    return {
        'level': MirrorCapability.NONE,
        'max_sessions': 0,
        'supports_vlan_mirror': False,
        'restrictions': ['Device type does not support port mirroring'],
    }


async def get_mirror_capabilities(
    device_id: str | None = None,
) -> list[DeviceMirrorCapabilities]:
    """Get port mirroring capabilities for UniFi devices.

    When to use this tool:
    - Before creating a mirror session to verify device support
    - When planning network troubleshooting that requires traffic capture
    - To inventory which switches support SPAN sessions
    - When selecting a switch for deploying a packet analyzer

    Forbidden actions:
    - Do not assume capabilities without checking - models vary significantly
    - Do not attempt mirroring on devices with NONE capability level

    Common workflow:
    1. Call get_mirror_capabilities() to see all capable switches
    2. Select appropriate device based on capability level and location
    3. Use create_mirror_session() to set up traffic capture
    4. Use list_mirror_sessions() to verify session status

    What to do next:
    - If capability_level is ENTERPRISE/ADVANCED: Proceed with mirror session creation
    - If capability_level is BASIC: Only single session available, plan accordingly
    - If capability_level is NONE: Select a different switch for monitoring

    Args:
        device_id: Optional specific device ID to check. If None, returns all switches.

    Returns:
        List of DeviceMirrorCapabilities for switches in the network

    Raises:
        ToolError: DEVICE_NOT_FOUND if device_id specified but not found
        ToolError: CONTROLLER_UNREACHABLE if cannot connect to UniFi controller
    """
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()

            results: list[DeviceMirrorCapabilities] = []

            for device in devices:
                # Filter by device_id if specified
                if device_id:
                    if device.get('_id') != device_id and device.get('mac') != device_id:
                        continue

                # Only process switch-type devices
                device_type = device.get('type', '')
                if device_type not in ('usw', 'switch') and not device_id:
                    continue

                model = device.get('model', 'Unknown')
                caps = _get_model_capabilities(model)

                # Get available ports (exclude uplink ports)
                port_table = device.get('port_table', [])
                available_ports = [
                    port.get('port_idx', 0)
                    for port in port_table
                    if not port.get('is_uplink', False) and port.get('port_idx', 0) > 0
                ]

                capability = DeviceMirrorCapabilities(
                    device_id=device.get('_id', ''),
                    device_name=device.get('name', device.get('mac', 'Unknown')),
                    model=model,
                    capability_level=caps['level'],
                    max_sessions=caps['max_sessions'],
                    supports_bidirectional=caps['level'] != MirrorCapability.NONE,
                    supports_vlan_mirror=caps['supports_vlan_mirror'],
                    available_ports=available_ports,
                    restrictions=caps['restrictions'],
                )

                results.append(capability)

                # If specific device requested and found, stop searching
                if device_id:
                    break

            # Handle device not found
            if device_id and not results:
                raise ToolError(
                    message=f'Device with ID {device_id} not found',
                    error_code=ErrorCodes.DEVICE_NOT_FOUND,
                    suggestion='Use find_device to search for the correct device ID',
                    related_tools=['find_device', 'get_network_topology'],
                )

            return results

        except ToolError:
            raise
        except Exception as e:
            if 'connection' in str(e).lower():
                raise ToolError(
                    message='Cannot connect to UniFi controller',
                    error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                    suggestion='Verify controller IP, credentials, and network connectivity',
                )
            raise ToolError(
                message=f'Error retrieving mirror capabilities: {e}',
                error_code=ErrorCodes.API_ERROR,
                suggestion='Check controller status and try again',
            )
