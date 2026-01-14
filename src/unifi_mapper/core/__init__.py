"""Core components migrated from unifi_mcp - models, client, and utilities.

This module provides convenient re-exports of commonly used components.
For the full list of available models, import directly from unifi_mapper.core.models.
"""

# Re-export commonly used models
from unifi_mapper.core.models import (
    CapacityReport,
    Device,
    FirewallRule,
    IPConflict,
    IPConflictReport,
    LAGHealthReport,
    LinkQualityReport,
    MACAnalysisReport,
    MACTableEntry,
    MirrorSession,
    NetworkPath,
    PathHop,
    Port,
    QoSValidationReport,
    StormDetectionReport,
    VLAN,
    VLANDiagnosticReport,
)

# Re-export utilities
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.logging import configure_logging, get_logger
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.auth import get_credentials

__all__ = [
    # Models
    'CapacityReport',
    'Device',
    'FirewallRule',
    'IPConflict',
    'IPConflictReport',
    'LAGHealthReport',
    'LinkQualityReport',
    'MACAnalysisReport',
    'MACTableEntry',
    'MirrorSession',
    'NetworkPath',
    'PathHop',
    'Port',
    'QoSValidationReport',
    'StormDetectionReport',
    'VLAN',
    'VLANDiagnosticReport',
    # Utils
    'ErrorCodes',
    'ToolError',
    'UniFiClient',
    'configure_logging',
    'get_credentials',
    'get_logger',
]
