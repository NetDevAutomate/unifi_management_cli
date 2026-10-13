---
title: "Tool docstrings and `path_analysis` recommendations name tools that don't exist"
date: 2026-10-03
status: resolved
resolved_by: d9ce545
severity: low
components: [connectivity, diagnostics, discovery, analysis/storm_detection]
found_by: review follow-ups (issue 023)
---

# Tool docstrings and `path_analysis` recommendations name tools that don't exist

## Problem

Issue 023 fixed the `ToolError` hints and the docstring lines that named `vlan_info()` and
`get_network_topology()`. An AST scan of every module, class and function docstring under
`src/unifi_mapper` still finds 25 `name()` references that are neither a registered tool
nor a function or class defined in the package (`stdio_server()`, an MCP SDK function, is
excluded), in 11 modules:

| Module | Line: reference |
| --- | --- |
| `analysis/storm_detection.py` | 57: `discover_lldp_topology()` |
| `connectivity/firewall_check.py` | 27: `best_practice_check()`; 32: `config_validator()` |
| `connectivity/path_analysis.py` | 24: `link_quality()`; 25: `system_load()`; 28: `link_quality()`, `system_load()`; 30: `get_port_map()`; 31: `best_practice_check()` |
| `connectivity/traceroute.py` | 40: `link_quality()`, `system_load()`; 41: `get_port_map()`; 46: `link_quality()` |
| `diagnostics/connectivity_analysis.py` | 95: `port_map()`; 96: `network_topology()` |
| `diagnostics/inspect_port.py` | 132: `check_uplink_transparency()`; 134: `vlan_coverage()` |
| `diagnostics/performance_analysis.py` | 86: `port_map()` |
| `diagnostics/security_audit.py` | 87: `network_topology()` |
| `discovery/client_trace.py` | 25: `link_quality()`; 27: `system_load()` |
| `discovery/find_device.py` | 26: `get_port_map()` |
| `discovery/find_mac.py` | 23: `port_config()`; 25: `get_device_tree()`; 28: `port_config()` |

The same scan over every other string constant finds seven more, and these do reach the
model: `connectivity/path_analysis.py::_generate_recommendations` returns them in every
`path_analysis` result's recommendations (lines 302, 323, 330 and 337: `system_load()` ×3,
`link_quality()` ×3, `get_device_tree()`). The default recommendation, returned whenever
nothing else fires, is one of them.

Also found while fixing 023: three `CONTROLLER_UNREACHABLE` hints name registered tools
that need the same unreachable controller, so they can't help:
`diagnostics/connectivity_analysis.py:142`, `diagnostics/performance_analysis.py:123` and
`diagnostics/security_audit.py:125` (`['network_health_check', 'find_device']`). Issue 023
dropped the equivalent hint in `diagnostics/network_health.py` for that reason.

## Impact

The docstrings reach the model only if a manifest `description` is removed (FastMCP uses
`description or fn.__doc__`; every manifest entry has a description today), but a reader
following one gets `TOOL_NOT_FOUND`. The `path_analysis` recommendations reach the model on
every call and send it to tools that don't exist, as 023's hints did. The unreachable-
controller hints cost the model a call that fails the same way.

## Recommended fix

1. Map the names: `link_quality` → `analyze_link_quality`, `system_load` →
   `performance_analysis`, `get_port_map` / `port_map` → `get_switch_ports`,
   `network_topology` / `discover_lldp_topology` / `get_device_tree` →
   `discover_stp_topology`, `port_config` → `inspect_switch_port`, `best_practice_check` /
   `config_validator` → `security_audit`, `check_uplink_transparency` →
   `audit_uplink_transparency`, `vlan_coverage` → `audit_vlan_coverage` (all registered).
2. Drop the three unreachable-controller `related_tools`, as 023 did.
3. Extend `tests/mcp/test_related_tools.py` with the docstring scan and the
   every-string-constant scan above (excluding names defined in the package and
   `stdio_server`), so a new phantom name fails the suite.

## Resolution

Resolved on 2026-10-13 (`d9ce545`), as recommended. The scan was re-run against the
source first and found exactly the 25 docstring references in 11 modules and the 7
recommendation strings listed above (`security_audit.py`'s hint had moved to line 169 since
issue 079). All 32 were replaced through the name map in step 1; the three
`CONTROLLER_UNREACHABLE` hints naming `network_health_check` and `find_device` were dropped
(step 2). No test pinned the old strings.

Step 3 went into a new file rather than `tests/mcp/test_related_tools.py`:
`tests/mcp/test_docstring_tool_names.py` scans every module, class and function docstring
and, separately, every other string constant under `src/unifi_mapper` for `name()` mentions,
and fails on one that is neither a registered tool nor a name the package defines. Two
names from outside the package are allowed by a short list: `stdio_server()` (the MCP SDK,
as the issue says) and `as_uri()` (`Path.as_uri()`, named in
`analysis/vlan_traffic_store.py`'s module docstring; the issue's scan predates that
module). It also checks that no mentioned tool mutates and that no `CONTROLLER_UNREACHABLE`
hint names a `controller`-family tool, so the step 2 class of hint cannot return.
`test_related_tools.py` keeps the `related_tools` lists and `suggestion` texts (issue 023).
