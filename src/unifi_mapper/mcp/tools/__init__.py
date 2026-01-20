"""MCP tool wrappers for UniFi Management.

Provides async wrapper functions that handle client lifecycle and normalize
responses for MCP server consumption.
"""

from .network import (
    get_acl_rules,
    get_clients,
    get_dns_policies,
    get_firewall_policies,
    get_firewall_zones,
    get_networks,
)
from .protect import (
    get_cameras,
    get_doorbells,
    get_lights,
    get_nvr_info,
    get_sensors,
)

__all__ = [
    # Network tools
    "get_firewall_zones",
    "get_firewall_policies",
    "get_acl_rules",
    "get_dns_policies",
    "get_clients",
    "get_networks",
    # Protect tools
    "get_cameras",
    "get_nvr_info",
    "get_sensors",
    "get_lights",
    "get_doorbells",
]
