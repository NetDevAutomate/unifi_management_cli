---
title: "Error hints send the model to `get_network_topology` and `vlan_info`, which don't exist"
date: 2026-10-02
status: open
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
