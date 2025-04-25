#!/usr/bin/env python3
"""
UniFi Mapper package.
Contains modules for mapping UniFi network topology.
"""

__version__ = "1.0.0"
__author__ = "UniFi Port Mapper Team"
__license__ = "MIT"

# Import core classes for easier access
try:
    from .models import DeviceInfo, PortInfo
    from .port_mapper import UnifiPortMapper
    from .topology import NetworkTopology
    from .device_definitions import DeviceDefinition, DEVICE_DEFINITIONS, get_device_definition
except ImportError:
    # Handle import errors gracefully
    pass
