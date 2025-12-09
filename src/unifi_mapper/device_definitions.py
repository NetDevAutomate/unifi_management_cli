#!/usr/bin/env python3
"""
Device definitions for the UniFi Port Mapper.
Contains the DeviceDefinition class and device definitions registry.
"""

from typing import Dict, List, Optional


class DeviceDefinition:
    """
    Class to define device port configurations.
    This allows for easier management and expansion of device definitions.
    """

    def __init__(
        self,
        name: str,
        port_count: int,
        port_naming_scheme: str = "LAN {}",
        special_ports: Dict[int, str] = None,
        sfp_ports: List[int] = None,
    ):
        """
        Initialize a device definition.

        Args:
            name: Name of the device type
            port_count: Number of ports on the device
            port_naming_scheme: Format string for standard port names
            special_ports: Dictionary mapping port indices to special port names
            sfp_ports: List of port indices that are SFP/SFP+ ports
        """
        self.name = name
        self.port_count = port_count
        self.port_naming_scheme = port_naming_scheme
        self.special_ports = special_ports or {}
        self.sfp_ports = sfp_ports or []

    def get_port_names(self) -> Dict[int, str]:
        """
        Generate port names based on the device definition.

        Returns:
            Dictionary mapping port indices to port names
        """
        port_names = {}

        # Add special ports
        for port_idx, name in self.special_ports.items():
            port_names[port_idx] = name

        # Add standard ports
        for i in range(1, self.port_count + 1):
            if i not in port_names:
                port_names[i] = self.port_naming_scheme.format(i)

        return port_names

    def should_rename_port(self, port_idx: int) -> bool:
        """
        Check if a port should be renamed based on the device definition.

        Args:
            port_idx: Port index

        Returns:
            bool: True if the port should be renamed, False otherwise
        """
        # Don't rename special ports like WAN ports
        if port_idx in self.special_ports:
            special_name = self.special_ports[port_idx].lower()
            if "wan" in special_name:
                return False

        return True


# Device definitions registry
DEVICE_DEFINITIONS = {
    # UniFi Dream Machine Pro
    "udm-pro": DeviceDefinition(
        name="UniFi Dream Machine Pro",
        port_count=10,
        special_ports={
            1: "WAN",
            2: "LAN 1",
            3: "LAN 2",
            4: "LAN 3",
            5: "LAN 4",
            6: "LAN 5",
            7: "LAN 6",
            8: "LAN 7",
            9: "LAN 8",
            10: "SFP+ WAN",
        },
        sfp_ports=[10],
    ),
    # UniFi Dream Machine SE
    "udm-se": DeviceDefinition(
        name="UniFi Dream Machine SE",
        port_count=10,
        special_ports={
            1: "WAN 1",
            2: "WAN 2",
            3: "LAN 1",
            4: "LAN 2",
            5: "LAN 3",
            6: "LAN 4",
            7: "LAN 5",
            8: "LAN 6",
            9: "SFP+ WAN",
            10: "SFP+ LAN",
        },
        sfp_ports=[9, 10],
    ),
    # UniFi Dream Machine Pro Max
    "udm-pro-max": DeviceDefinition(
        name="UniFi Dream Machine Pro Max",
        port_count=12,
        special_ports={
            1: "WAN 1",
            2: "WAN 2",
            3: "LAN 1",
            4: "LAN 2",
            5: "LAN 3",
            6: "LAN 4",
            7: "LAN 5",
            8: "LAN 6",
            9: "LAN 7",
            10: "LAN 8",
            11: "SFP+ WAN",
            12: "SFP+ LAN",
        },
        sfp_ports=[11, 12],
    ),
    # UniFi Switch Pro 24
    "usw-pro-24": DeviceDefinition(
        name="UniFi Switch Pro 24",
        port_count=28,
        port_naming_scheme="Port {}",
        special_ports={25: "SFP+ 1", 26: "SFP+ 2", 27: "SFP+ 3", 28: "SFP+ 4"},
        sfp_ports=[25, 26, 27, 28],
    ),
    # UniFi Switch Pro 48
    "usw-pro-48": DeviceDefinition(
        name="UniFi Switch Pro 48",
        port_count=52,
        port_naming_scheme="Port {}",
        special_ports={49: "SFP+ 1", 50: "SFP+ 2", 51: "SFP+ 3", 52: "SFP+ 4"},
        sfp_ports=[49, 50, 51, 52],
    ),
    # UniFi Switch 24
    "usw-24": DeviceDefinition(
        name="UniFi Switch 24",
        port_count=26,
        port_naming_scheme="Port {}",
        special_ports={25: "SFP 1", 26: "SFP 2"},
        sfp_ports=[25, 26],
    ),
    # UniFi Switch 16
    "usw-16": DeviceDefinition(
        name="UniFi Switch 16",
        port_count=18,
        port_naming_scheme="Port {}",
        special_ports={17: "SFP 1", 18: "SFP 2"},
        sfp_ports=[17, 18],
    ),
    # UniFi Switch 8
    "usw-8": DeviceDefinition(
        name="UniFi Switch 8", port_count=8, port_naming_scheme="Port {}"
    ),
    # UniFi Switch Aggregation
    "usw-aggregation": DeviceDefinition(
        name="UniFi Switch Aggregation",
        port_count=8,
        port_naming_scheme="SFP+ {}",
        sfp_ports=[1, 2, 3, 4, 5, 6, 7, 8],
    ),
    # Generic switch with 8 ports
    "switch-8": DeviceDefinition(
        name="8-Port Switch", port_count=8, port_naming_scheme="Port {}"
    ),
    # Generic switch with 16 ports
    "switch-16": DeviceDefinition(
        name="16-Port Switch", port_count=16, port_naming_scheme="Port {}"
    ),
    # Generic switch with 24 ports
    "switch-24": DeviceDefinition(
        name="24-Port Switch", port_count=24, port_naming_scheme="Port {}"
    ),
    # Generic switch with 48 ports
    "switch-48": DeviceDefinition(
        name="48-Port Switch", port_count=48, port_naming_scheme="Port {}"
    ),
    # Access Point
    "ap": DeviceDefinition(name="Access Point", port_count=1, special_ports={1: "LAN"}),
    # Server
    "server": DeviceDefinition(
        name="Server", port_count=2, special_ports={1: "eth0", 2: "eth1"}
    ),
    # Router
    "router": DeviceDefinition(
        name="Router", port_count=2, special_ports={1: "WAN", 2: "LAN"}
    ),
    # Default
    "default": DeviceDefinition(
        name="Unknown Device", port_count=1, special_ports={1: "Port 1"}
    ),
    # UniFi Switch 8 PoE (150W)
    "us-8-150": DeviceDefinition(
        name="UniFi Switch 8 PoE (150W)", port_count=8, port_naming_scheme="Port {}"
    ),
    # UniFi Switch 8 PoE (60W)
    "us-8-60": DeviceDefinition(
        name="UniFi Switch 8 PoE (60W)", port_count=8, port_naming_scheme="Port {}"
    ),
    # UniFi Switch Lite 16 PoE
    "usw-lite-16-poe": DeviceDefinition(
        name="UniFi Switch Lite 16 PoE", port_count=16, port_naming_scheme="Port {}"
    ),
    # UniFi Switch Lite 8 PoE
    "usw-lite-8-poe": DeviceDefinition(
        name="UniFi Switch Lite 8 PoE", port_count=8, port_naming_scheme="Port {}"
    ),
    # UniFi Switch Flex Mini
    "usw-flex-mini": DeviceDefinition(
        name="UniFi Switch Flex Mini", port_count=5, port_naming_scheme="Port {}"
    ),
    # UniFi Switch Enterprise 24 PoE
    "usw-enterprise-24": DeviceDefinition(
        name="UniFi Switch Enterprise 24 PoE",
        port_count=24,
        port_naming_scheme="Port {}",
        special_ports={25: "SFP28 1", 26: "SFP28 2"},
        sfp_ports=[25, 26],
    ),
    # UniFi AP 6 Mesh Pro
    "u6-mesh-pro": DeviceDefinition(
        name="UniFi AP 6 Mesh Pro", port_count=1, port_naming_scheme="Main Port"
    ),
    # UniFi AP 6 In-Wall
    "u6-iw": DeviceDefinition(
        name="UniFi AP 6 In-Wall",
        port_count=4,
        special_ports={1: "Main Port", 2: "LAN 1", 3: "LAN 2", 4: "LAN 3"},
    ),
    # UniFi AP 6 Long-Range v2
    "u6-lr": DeviceDefinition(
        name="UniFi AP 6 Long-Range v2", port_count=1, port_naming_scheme="Main Port"
    ),
    # UniFi Access Connector PoE
    "access-connector": DeviceDefinition(
        name="UniFi Access Connector PoE",
        port_count=2,
        special_ports={1: "LAN", 2: "AP"},
    ),
    # UniFi AP AC Lite
    "uap-ac-lite": DeviceDefinition(
        name="UniFi AP AC Lite", port_count=1, port_naming_scheme="Main Port"
    ),
    # UniFi AP AC Pro
    "uap-ac-pro": DeviceDefinition(
        name="UniFi AP AC Pro",
        port_count=2,
        special_ports={1: "Main Port", 2: "Secondary Port"},
    ),
}

# Model alias mapping for consistency
MODEL_ALIAS_MAP = {
    # Dream Machines
    "udmpro": "udm-pro",
    "UDMPRO": "udm-pro",
    "udmse": "udm-se",
    "UDMSE": "udm-se",
    "udm-pro-max": "udm-pro-max",
    "udmpromax": "udm-pro-max",
    "UDMPROMAX": "udm-pro-max",
    # Pro Switches
    "uswpro24": "usw-pro-24",
    "USWPRO24": "usw-pro-24",
    "uswpro48": "usw-pro-48",
    "USWPRO48": "usw-pro-48",
    # Standard Switches
    "usw24": "usw-24",
    "USW24": "usw-24",
    "usw48": "usw-48",
    "USW48": "usw-48",
    "us8p150": "us-8-150",
    "US8P150": "us-8-150",
    "us8p60": "us-8-60",
    "US8P60": "us-8-60",
    "usm8p210": "us-8-150",  # Similar to US-8-150W
    "USM8P210": "us-8-150",  # Similar to US-8-150W
    # Enterprise Switches
    "uswed35": "usw-enterprise-24",
    "USWED35": "usw-enterprise-24",
    "uswed37": "usw-aggregation",
    "USWED37": "usw-aggregation",
    # Lite Switches
    "usl16lpb": "usw-lite-16-poe",
    "USL16LPB": "usw-lite-16-poe",
    "usl8lp": "usw-lite-8-poe",
    "USL8LP": "usw-lite-8-poe",
    "usmini": "usw-flex-mini",
    "USMINI": "usw-flex-mini",
    # Access Points
    "uap-ac-lite": "uap-ac-lite",
    "UAP-AC-LITE": "uap-ac-lite",
    "uap-ac-pro": "uap-ac-pro",
    "UAP-AC-PRO": "uap-ac-pro",
    "uap6mp": "u6-mesh-pro",
    "UAP6MP": "u6-mesh-pro",
    "u6iw": "u6-iw",
    "U6IW": "u6-iw",
    "ualr6v2": "u6-lr",
    "UALR6v2": "u6-lr",
    "UALR6V2": "u6-lr",
    # Other Devices
    "uaccmpoeaf": "access-connector",
    "UACCMPOEAF": "access-connector",
}


def get_device_definitions() -> Dict[str, DeviceDefinition]:
    """
    Get the device definitions registry.

    Returns:
        Dict[str, DeviceDefinition]: Dictionary mapping device model keys to DeviceDefinition objects
    """
    return DEVICE_DEFINITIONS


def get_device_definition(model: str) -> Optional[DeviceDefinition]:
    """
    Get a device definition by model.

    Args:
        model: Device model or key

    Returns:
        Optional[DeviceDefinition]: DeviceDefinition for the model, or None if not found
    """
    if not model:
        return None

    # Convert to lowercase for case-insensitive matching
    model_lower = model.lower()

    # Check direct match
    if model_lower in DEVICE_DEFINITIONS:
        return DEVICE_DEFINITIONS[model_lower]

    # Check alias map
    if model_lower in MODEL_ALIAS_MAP:
        alias = MODEL_ALIAS_MAP[model_lower]
        if alias in DEVICE_DEFINITIONS:
            return DEVICE_DEFINITIONS[alias]

    # Handle special case for UDMPROMAX which should map to udm-pro-max
    if "udm" in model_lower and "pro" in model_lower and "max" in model_lower:
        return DEVICE_DEFINITIONS.get("udm-pro-max")

    # Try to find a match based on model fragments
    if (
        model_lower.startswith("usw")
        or model_lower.startswith("us-")
        or model_lower.startswith("usl")
    ):
        # It's a switch
        if "lite" in model_lower or "l" in model_lower:
            if "16" in model_lower:
                return DEVICE_DEFINITIONS.get("usw-lite-16-poe")
            elif "8" in model_lower:
                return DEVICE_DEFINITIONS.get("usw-lite-8-poe")
        elif "mini" in model_lower or "flex" in model_lower:
            return DEVICE_DEFINITIONS.get("usw-flex-mini")
        elif "8" in model_lower and "poe" in model_lower:
            if "150" in model_lower or "210" in model_lower:
                return DEVICE_DEFINITIONS.get("us-8-150")
            else:
                return DEVICE_DEFINITIONS.get("us-8-60")
        elif "agg" in model_lower or "ed37" in model_lower:
            return DEVICE_DEFINITIONS.get("usw-aggregation")
        elif "enterprise" in model_lower or "ed35" in model_lower:
            return DEVICE_DEFINITIONS.get("usw-enterprise-24")
    elif (
        model_lower.startswith("uap")
        or model_lower.startswith("u6")
        or "ap" in model_lower
    ):
        # It's an access point
        if "mesh" in model_lower or "mp" in model_lower:
            return DEVICE_DEFINITIONS.get("u6-mesh-pro")
        elif "iw" in model_lower or "wall" in model_lower:
            return DEVICE_DEFINITIONS.get("u6-iw")
        elif "lr" in model_lower or "long" in model_lower:
            return DEVICE_DEFINITIONS.get("u6-lr")
        elif "lite" in model_lower:
            return DEVICE_DEFINITIONS.get("uap-ac-lite")
        elif "pro" in model_lower and "mesh" not in model_lower:
            return DEVICE_DEFINITIONS.get("uap-ac-pro")
        else:
            # Generic AP definition
            return DEVICE_DEFINITIONS.get("uap-ac-lite")  # Default to single-port AP
    elif "acc" in model_lower or "connector" in model_lower:
        return DEVICE_DEFINITIONS.get("access-connector")

    # Try to match partial model string as last resort
    for key in DEVICE_DEFINITIONS:
        if key in model_lower or model_lower in key:
            return DEVICE_DEFINITIONS[key]

    # No match found
    return DEVICE_DEFINITIONS["default"]
