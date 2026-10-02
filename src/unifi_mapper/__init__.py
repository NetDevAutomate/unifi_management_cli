"""UniFi management CLI and MCP server.

The connectivity helpers below are exported lazily (PEP 562): ``from unifi_mapper import
traceroute`` still works, but a bare ``import unifi_mapper`` (for example from
``unifi-mcp --version``) doesn't import the connectivity package.
"""

import importlib
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from unifi_mapper.connectivity.firewall_check import firewall_check
    from unifi_mapper.connectivity.inter_vlan import check_inter_vlan_routing
    from unifi_mapper.connectivity.path_analysis import path_analysis
    from unifi_mapper.connectivity.traceroute import traceroute

_LAZY_EXPORTS = {
    'check_inter_vlan_routing': 'unifi_mapper.connectivity.inter_vlan',
    'firewall_check': 'unifi_mapper.connectivity.firewall_check',
    'path_analysis': 'unifi_mapper.connectivity.path_analysis',
    'traceroute': 'unifi_mapper.connectivity.traceroute',
}

__all__ = [
    'check_inter_vlan_routing',
    'firewall_check',
    'path_analysis',
    'traceroute',
]


def __getattr__(name: str) -> Any:
    """Import a connectivity export on first access (PEP 562)."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value
