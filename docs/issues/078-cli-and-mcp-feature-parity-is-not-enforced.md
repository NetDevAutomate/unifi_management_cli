---
title: "The CLI and the MCP server do not have feature parity, and nothing checks that they do"
date: 2026-10-12
status: open, decision needed
severity: medium
components: [typer_cli, inventory_cli, mcp/manifests, tests/mcp]
found_by: maintainer's question after the 0.2.0 readiness work
---

# The CLI and the MCP server do not have feature parity, and nothing checks that they do

## Problem

The maintainer's requirement is that the two surfaces offer the same features. They do not,
in either direction, and no test or document states the intended mapping, so the gap grows
with every command or tool added on one side only.

Counted on 2026-10-12 from the source (the `typer` command tree and the seven MCP manifests;
mapping by the handler each side calls, checked by hand where the handlers differ):

- 80 CLI commands in 17 groups; 87 MCP tools in 7 manifests.
- 57 CLI commands have an MCP tool for the same feature.
- 5 CLI commands are CLI-only by nature: `install-completions`, `version`, `verify`,
  `diagram` (renders files), `discover` (writes the port-mapping report).
- The write-capable commands are CLI-only by the documented
  [control boundary](../mcp-server/MCP_SERVER_GUIDE.md#mcp-control-boundary): `stp apply`,
  `stp optimize --apply`, `stp rollback`, `radio optimize --apply`, `radio restore --apply`,
  `inventory update-firmware`, `ports refresh`, `discover --apply`, and the collectors
  `vlan-traffic sample` and `vlan-traffic rollup`. The MCP server declares
  `apply_stp_changes`, `apply_radio_optimization` and `restore_radio_config` but refuses them.
  That boundary is deliberate and stays.
- **15 read-only CLI commands have no MCP tool**: `analyze config-drift`,
  `analyze link-errors`, `analyze neighbours`, `analyze roaming`, `capabilities`,
  `diagnose all` (the composite), `diagnose ap-health`, `diagnose bandwidth`,
  `diagnose client-connectivity`, `diagnose latency-matrix`, `gateway ping`, `gateway dns`,
  `gateway http`, `gateway flows`, `gateway traceroute` (the MCP `traceroute` traces between
  endpoints; the CLI runs the probe on the gateway over SSH), `inventory list`,
  `inventory firmware-skew`. Several run active probes or write local snapshots; all are
  read-only against the controller.
- **30 MCP tools have no CLI command**: `detect_ip_conflicts`, `detect_storms`,
  `diagnose_vlans`, `get_capacity_report` (the CLI reaches it only inside `diagnose all`),
  `monitor_lags`, `detect_foreign_bridges`, `summarise_freshness`, `check_device_freshness`,
  `validate_qos`, `analyze_mac_table`, `audit_stp_path_costs`, `firewall_check`,
  `path_analysis`, `connectivity_analysis`, `performance_analysis`, `security_audit`,
  `find_ip`, `find_mac`, `client_trace` (`find device` accepts a MAC or IP, so the first two
  are partly covered), `get_firewall_zones`, `get_firewall_policies`, `get_acl_rules`,
  `get_dns_policies`, `get_clients`, `get_networks`, `get_cameras`, `get_nvr_info`,
  `get_sensors`, `get_lights`, `get_doorbells`.

`tests/mcp/test_manifest_parity.py` is not this check: it verifies that each manifest entry
matches its handler's signature, not that the CLI offers the same feature.
[Issue 018](018-read-only-tool-proposals.md) proposes new read-only tools for both surfaces
and [issue 009](009-mcp-default-tool-surface.md) decides the default MCP surface; neither
states the parity rule.

## Impact

A user who learns a feature on one surface cannot assume it on the other. The documentation
has to describe two different feature sets, and the gap is invisible until someone counts.

## Recommended fix

1. Make the mapping explicit and enforced before closing any gap: add an optional `cli:`
   field to each manifest entry naming the CLI command (`cli: analyze poe-budget`) and an
   exemption list with a reason per entry (`cli_only: writer`, `cli_only: by nature`,
   `mcp_only: raw read for agents`). A new `tests/test_surface_parity.py` walks the typer
   tree and the manifests and fails when a read-only CLI command has no `cli:` reference and
   no exemption, or an MCP tool has neither. The test ships with the 45 gaps above listed as
   known exemptions, so it passes today and every new command or tool must declare its
   counterpart or its reason.
2. Close the gaps in the order they matter to a user, each one removing its exemption:
   first the 15 read-only CLI commands (new manifest entries; the handlers already exist),
   then CLI commands for the MCP-only reads that a human would want at a terminal
   (`network` and `protect` listings, `detect_ip_conflicts`, `security_audit`, ...).

## Decision needed

- Whether parity is a rule (the test fails on an undeclared gap) or a report (the test
  prints the gap). The maintainer's statement of 2026-10-12 is that it matters, which argues
  for the rule.
- Whether the MCP-only raw reads (`get_firewall_policies`, `get_cameras`, ...) need CLI
  commands or are exempt as agent-facing reads of controller objects the UI already shows.
