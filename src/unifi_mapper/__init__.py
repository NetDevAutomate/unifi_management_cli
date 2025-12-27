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
    from .device_definitions import (
        DEVICE_DEFINITIONS,
        DeviceDefinition,
        get_device_definition,
    )
    from .models import DeviceInfo, PortInfo
    from .port_mapper import UnifiPortMapper
    from .topology import NetworkTopology
except ImportError:
    # Handle import errors gracefully
    pass

# Import validation and auto-fix modules
try:
    from .config_validation import (
        Category,
        ConfigValidator,
        Severity,
        ValidationFinding,
        ValidationResult,
    )
    from .config_autofix import (
        AutoFixResult,
        ConfigAutoFix,
        FixResult,
        FixStatus,
    )
except ImportError:
    # Handle import errors gracefully
    pass
