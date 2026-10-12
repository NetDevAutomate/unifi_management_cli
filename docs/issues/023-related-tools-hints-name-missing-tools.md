---
title: "Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist"
date: 2026-10-02
status: resolved
resolved_by: a3efa2f
severity: low
components: [analysis, connectivity, discovery, diagnostics/network_health, core/utils/auth]
found_by: MCP uvx standards work
---

# Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist

## Problem

`ToolError.related_tools` and the "When to use this tool" docstrings point the model at tools
that aren't registered:

- `get_network_topology` is named in 14 modules: `analysis/firmware_advisor.py`,
  `lag_monitoring.py`, `link_quality.py`, `mac_analyzer.py`, `qos_validation.py`,
  `storm_detection.py`, `stp_optimizer.py`, `connectivity/traceroute.py`,
  `core/utils/auth.py`, `diagnostics/network_health.py`, `discovery/client_trace.py`,
  `find_device.py`, `find_ip.py` and `find_mac.py`.
- `vlan_info` is named in `discovery/find_ip.py` (`related_tools`, `:93` and `:113`, and its
  docstring) and in the docstrings of `connectivity/path_analysis.py`, `firewall_check.py` and
  `traceroute.py`.

`execute_tool` returns `related_tools` verbatim in error envelopes, and the docstrings become
tool descriptions on the direct surface (sibling review §3.3).

## Impact

After an error the model tries a suggested tool and gets `TOOL_NOT_FOUND`, wasting a turn and
eroding trust in the hints.

## Recommended fix

1. Add a contract test: every name in any `related_tools=[...]` literal under
   `src/unifi_mapper` (an AST scan) must be registered in `ToolRegistry()`.
2. Make it pass by replacing the hints with real tools: `vlan_info` → `get_networks` /
   `diagnose_vlans`; `get_network_topology` → `find_device` / `discover_stp_topology` /
   `get_switch_ports` as fits each module, or implement `get_network_topology` (issue 018)
   and keep the name.
3. Fix the docstrings the same way.

## Resolution

Every `ToolError` hint now names a registered, read-only tool (paths under
`src/unifi_mapper/`):

| Site | `related_tools` now |
| --- | --- |
| `analysis/firmware_advisor.py`, `lag_monitoring.py`, `link_quality.py`, `qos_validation.py`, `storm_detection.py`, `stp_optimizer.py` (device not found) | `['find_device']` |
| `analysis/mac_analyzer.py` (device not found) | `['find_device', 'find_mac']` |
| `connectivity/traceroute.py`, both "gateway not found" errors | `['find_device', 'network_health_check']` |
| `discovery/client_trace.py` (client not found) | `['find_device', 'find_mac', 'get_client_history']` |
| `discovery/find_device.py` (not found) | `['find_mac', 'find_ip', 'get_client_history']` |
| `discovery/find_ip.py`, IP in a known VLAN but no device | `['get_client_history', 'diagnose_vlans']` |
| `discovery/find_ip.py`, IP in no known VLAN | `['diagnose_vlans', 'check_dhcp_pool_utilization', 'traceroute']` |
| `discovery/find_mac.py` (not found) | `['find_device', 'get_client_history']` |

`stp_optimizer` doesn't hint at `discover_stp_topology`: that tool is the one raising the
error. Two hints were dropped rather than re-pointed, because no tool can help when every
tool needs the thing that is missing: `core/utils/auth.py` (no credentials from any source)
and `diagnostics/network_health.py` (controller unreachable).

Docstrings: `vlan_info()` → `diagnose_vlans()` in `connectivity/firewall_check.py` (two
lines), `discovery/find_ip.py`, `discovery/client_trace.py` and `discovery/find_mac.py`;
→ `check_inter_vlan_routing()` in `connectivity/path_analysis.py` and
`connectivity/traceroute.py`. In `find_ip`'s docstring the DHCP line now names
`check_dhcp_pool_utilization()` and the IP-conflict line `detect_ip_conflicts()` (it named
`get_network_topology()`).

Test: `tests/mcp/test_related_tools.py` AST-scans every `ToolError(...)` call under
`src/unifi_mapper`: `related_tools` must be a literal list of names, every name must be
registered in `ToolRegistry(strict=True)` and not `mutates`, and every `name()` in a
`suggestion` (including a suggestion held in a variable) must be registered too. It failed
with 18 unregistered hints before the fix.

Docstrings and `path_analysis` recommendation strings name other tools that don't exist
(`link_quality()`, `system_load()`, `get_port_map()`, …); that is issue 028.
