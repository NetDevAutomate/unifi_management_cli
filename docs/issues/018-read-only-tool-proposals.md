---
title: "Read-only tool proposals for the CLI and MCP"
date: 2026-10-02
status: open
severity: low
components: [analysis, diagnostics, discovery, mcp/manifests, mcp/server, typer_cli]
found_by: MCP uvx standards work
---

# Read-only tool proposals for the CLI and MCP

## Problem

The MCP uvx standards work added six read-only tools (`audit_link_speeds`,
`audit_port_profile_usage`, `check_poe_budget`, `check_uplink_redundancy`,
`analyze_client_density`, `check_dhcp_pool_utilization`) plus T3/T4 as issues 016/017. The
design's backlog (§8) and the sibling MCP review (§6) list more read-only tools that would
help day-to-day troubleshooting but were out of scope. They are collected here so none is
lost; each should become its own change, built the house way: a pure `*_from_data` core
returning a pydantic model, a thin wrapper that only fetches, a CLI command rendering it, and a
manifest entry (the parity tests enforce the rest).

## Impact

Without them an assistant has no single call for the first questions of most investigations
(what devices exist, is the server configured, what is the topology, is the WAN up), and some
CLI analyses can't be reached over MCP at all.

## Recommended fix

From the design backlog:

| ID | Proposal | Depends on |
| --- | --- | --- |
| B5 | Composite read-only STP tools (`stp_audit()` and friends, mirroring `stp analyze/guard/drift/preflight/path-costs/diff`) that fetch the topology themselves, so the 11 pipeline-object tools needn't be chained by hand; then update the `plan_stp_change` prompt | Most useful on the direct surface (issue 009) |
| B6 | `diff_config_baseline(baseline_path)`: config snapshot + diff over MCP | A CWD-independent baseline location (issue 010) |
| B7 | STP topology-change (TCN) tracking over time | Persisted samples, like the counter history |
| B8 | MAC flapping / loop-indicator history across samples (`analyze_mac_table` covers one sample) | Same as B7 |
| B9 | Expose `analyze roaming` and the RF neighbour summaries (`analyze_roaming`, `scan_neighbours`, `detect_neighbour_trend`) | Their history files must leave `./reports/` first (issue 010) |
| B10 | Resource template `unifi://switch/{switch}/ports` (the `get_switch_ports` view as a resource) | After issue 009 |

From the sibling review §6 (items not yet built):

| Proposal | Why | Basis |
| --- | --- | --- |
| `list_devices(type?, fields?)` / `unifi-mapper inventory list --json` | Almost every investigation starts with "which switches and APs exist, with model, IP, firmware, state, uptime and uplink"; `find_device` answers one device at a time | `UniFiClient.get_devices`, `inventory_cli.py` |
| `server_status` / `unifi-mapper doctor` | Which config file was used, which families are ready, controller reachability and version, manifest load errors, package and SDK versions: tells "misconfigured" from "controller down". `unifi-mcp --check` and `unifi://config/status` cover the offline half | New, cheap |
| `get_network_topology(format=json\|mermaid)` / `topology` | `UniFiClient.get_network_topology()` already exists and 14 modules' error hints already name this tool (issue 023) | `core/utils/client.py`, `utility/render_mermaid.py` |
| `get_device_detail(device, fields=[...])` | A redacted raw `stat/device` record as an incident escape hatch; the redaction boundary it needed (`mask_secrets`) has landed | `stat/device` |
| `get_wan_status` | WAN and gateway health, ISP latency, failover state: a frequent first question in an outage | Controller health and stat endpoints |

Also from §6: expose `analyse_port_names` as a plan-only (read-only) tool. `run_latency_matrix`
and `run_bandwidth_test` generate traffic on the production network; expose them only with an
explicit opt-in and an `active_probe` marker, never by default.

## Progress (0.2.0 port)

- `get_wan_status` was built as `get_wan_health` (MCP) and `diagnose wan` (CLI), with the
  recorded speedtest history beside it, in `4e41505`.
- B5's priority slice was built as `audit_stp_priorities` and `stp audit-priorities` in
  `1860ab5`, and the `plan_stp_change` prompt now runs it before and after a change; the other
  composite STP tools are still open.
- `server_status` (`unifi-mapper doctor`) is still open, as are the rest of the tables above.

## Decision (2026-10-13)

Not in 0.3.0. The proposals stay the 0.4.0 backlog, triaged in the table above; none was built
in this release by the 0.3.0 release council's decision (D-016/018/062). Any that is built must
land on both surfaces or carry a parity-gate exemption with a reason.
