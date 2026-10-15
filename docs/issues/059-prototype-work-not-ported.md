---
title: "Prototype work that was not ported, and why"
date: 2026-10-05
status: open
severity: low
components: [mcp, typer_cli, analysis, diagnostics, scripts, tests]
found_by: 0.2.0 port
---

# Prototype work that was not ported, and why

## Problem

Work done between 2026-06-29 and 2026-07-27 on a second clone of this repository was never
merged here. It survives only in a local archive (not in the repo). The 0.2.0 port rebuilt
the parts that fit today's architecture as fresh commits (no archive commit or object entered
this repository). This issue is the single list of what was **not** ported, so nothing is lost
silently. Hashes below marked "archive commit" name commits in that archive, not in this
repository.

Each line gives the item, why it was not ported, and whether leaving it out breaks fresh
clones, CI or production. The open choices are in issue
[060](060-decisions-from-the-0.2.0-port.md).

This issue was filed at the start of the 0.2.0 port, before its features were rebuilt. Where a
line says the port *rebuilds* something (a CLI command, an MCP tool, a fixture), that is the
port's plan at filing time; "Rebuilt by the port" below records the commit that built each one.

## Not ported

- The `allow_mutation` flag on `execute_tool`, the manifests' `mutation: true` and
  `requires_dry_run` keys, and the `mutation: true` flag on `security_audit`: superseded by
  `mutates: true`, `MUTATION_REFUSED` and the read-only transport, which refuse writes
  outright. `security_audit` sends no write here and stays `mutates: false`. Breaks fresh
  clones, CI or prod: no.
- Archive commit `82ff6d4`, a rebased copy of an earlier port-naming fix: superseded (the
  port-name chooser is identical in both trees). Breaks fresh clones, CI or prod: no.
- `mcp_health_check` (a direct tool outside the catalog that reported `ok` when only the env
  file loaded and returned raw exception text): the need is issue 018's `server_status`;
  `unifi-mcp --check` covers the offline half. Breaks fresh clones, CI or prod: no.
- `run_port_mapping` over MCP: it writes port names; the CLI (`discover`, `ports refresh`)
  previews by default and writes only with `--apply`. Breaks fresh clones, CI or prod: no.
- `run_latency_matrix` over MCP: it pings from the gateway as root over SSH; MCP exposure is
  decision D1 in issue 060. The CLI command `diagnose latency-matrix` exists. Breaks fresh
  clones, CI or prod: no.
- The capacity-report TTL cache: it needs a new dependency (`cachetools`), keys one global
  entry, serves stale diagnostics and reads a variable outside the `UNIFI_` namespace. Breaks
  fresh clones, CI or prod: no.
- `--preserve-existing-names`: the archive threaded the flag through but never read it, and
  the port-name chooser is identical in both trees, so nothing writes more by default. Breaks
  fresh clones, CI or prod: no.
- The prototype's `core/utils/gateway_ssh.py`: it fell back to `UNIFI_PASSWORD`, interpolated
  f-strings into shell commands and disabled host-key checking a second time. The existing
  `analysis/gateway_ssh.py` gained the session and command helpers instead. Breaks fresh
  clones, CI or prod: no.
- `decode_object_timestamps`: the port folds it into `get_config_object`'s `created_utc`
  field; its `ids=` form is dropped. Breaks fresh clones, CI or prod: no.
- `rogueap` as a config kind: it is detection data, read by `analyze neighbours`. Breaks fresh
  clones, CI or prod: no.
- The gateway probes (`gateway_ping`, `gateway_traceroute`, `gateway_dns_check`,
  `gateway_http_check`, `get_active_flows`) and `diagnose_client_connectivity` over MCP: they
  open SSH to the gateway; the port rebuilds them as CLI-only commands (`gateway …`,
  `diagnose client-connectivity`), and MCP exposure is decision D1. Breaks fresh clones, CI or
  prod: no.
- The probes' hostname fallback: the prototype passed a `gateway ping` or `traceroute` target that
  matched no device or client to the gateway as a DNS hostname. The port probes only an
  address or a name the controller knows (design section 4.8) and refuses anything else as
  `DEVICE_NOT_FOUND`, so a mistyped name never reaches the gateway's resolver; `gateway dns
  NAME` resolves a hostname, and the probes take its address. Breaks fresh clones, CI or prod:
  no.
- `run_spectrum_scan`, `power_cycle_poe_port`, `set_wlan_option`, `set_wlan_ap_group` and
  `run_wan_speedtest`: controller writes or commands; never over MCP, filed as W8, issue
  019 W2, W6, W7 and D2 in issue 060. Breaks fresh clones, CI or prod: no.
- The job registry and its four tools (`list_jobs`, `get_job_status`, `get_job_result`,
  `cancel_job`): tasks ran outside the tool runner, so they escaped the concurrency cap, the
  tool timeout and cancellation (issue 012), and died with the stdio process. Decision D4.
  Breaks fresh clones, CI or prod: no.
- `run_ap_health_test` over MCP (decision D4; the port rebuilds the sampling as the CLI-only
  `diagnose ap-health`) and its PoE power-cycle phase (W9). Breaks fresh clones, CI or prod: no.
- `trigger_vlan_traffic_sample`: opens SSH from an MCP call (decision D1); the port's CLI
  command `vlan-traffic sample` covers it. Breaks fresh clones, CI or prod: no.
- `get_backup_status`: its only known call is a `cmd/backup` POST, a controller command the
  read-only guard refuses (decision D3). Breaks fresh clones, CI or prod: no.
- The secret-key scan's untested network purposes (`vpn-client`, `site-vpn`): no capture held
  such a network; confirm on a site that has one with a single read-only capture, scanned by
  key path. Breaks fresh clones, CI or prod: no.
- `system-log/all`, `system-log/critical` and `system-log/triggers`: the read-only allowlist
  is not widened; the port's `get_recent_events` uses the four allowlisted system-log
  classes. Breaks
  fresh clones, CI or prod: no.
- The dump script's `stat/event`, `stat/alarm`, `stat/dhcp`, v2 `events` and `mdns` paths:
  they returned 404 in the prototype capture. Breaks fresh clones, CI or prod: no.
- `UNIFI_VLAN_TRAFFIC_DB`: replaced by `--db` on each of the port's `vlan-traffic`
  commands. Breaks fresh
  clones, CI or prod: no.
- The hard-coded SSID default and the `reports/` output defaults of the AP-health and dump
  scripts: site-specific, and `reports/` captures carry secrets. Breaks fresh clones, CI or
  prod: no.
- `network-audit.sh --apply-stp`: `stp apply --plan` already exists. Breaks fresh clones, CI
  or prod: no.
- `scripts/ap_health_test.py` and `scripts/vlan_traffic_sample.py`: thin wrappers, replaced by
  the port's `diagnose ap-health` and `vlan-traffic sample`. Breaks fresh clones, CI or prod: no.
- The 17-switch topology capture: the port carries it anonymised as
  `tests/fixtures/fleet_17_switch_anonymised.json`, used by the 17-switch STP audit test; the
  real capture stays out. Breaks fresh clones, CI or prod: no.
- The prototype's MCP tests `test_mutation_enforcement.py`, `test_jobs.py`, `test_health_check.py`,
  `test_server.py`, `test_manifests.py`, `test_wire_only_tools.py` and
  `tests/network/test_wlan_mutations.py`: superseded by today's catalog, runner and parity
  tests, or their feature was not ported. Breaks fresh clones, CI or prod: no.
- The `.worktrees/` line in `.gitignore`: worktrees live under a git-ignored agent directory.
  Breaks fresh clones, CI or prod: no.
- `AGENTS.md`, the changelog, working notes, images, PDFs, tool caches and
  `.gitattributes`: no project content. Open items from the working notes are in issue
  [062](062-open-items-from-the-archived-plans.md). Breaks fresh clones, CI or prod: no.
- `reports/` captures: raw controller JSON with credentials included; never carried into the
  repo. Breaks fresh clones, CI or prod: no.
- 13 personal scripts kept in a git-ignored personal folder beside the archived prototype branch
  (a crash monitor, 11 one-off investigation scripts and an upgrade-ordering script):
  personal, git-ignored, kept outside the repo. Breaks fresh clones, CI or prod: no.

## Rebuilt by the port

The lines above that name a rebuilt command, tool or fixture, with the commit that built it:

- The gateway probes as CLI-only `gateway ping`, `traceroute`, `dns`, `http` and `flows`, with
  no hostname fallback: `ed9a076`.
- `diagnose client-connectivity` and `diagnose ap-health` (no PoE phase, no SSID or `reports/`
  default), which replace `scripts/ap_health_test.py`: `1e10f19`.
- `vlan-traffic sample`, `rollup`, `report` and `coverage`, with `--db` instead of
  `UNIFI_VLAN_TRAFFIC_DB`, which replace `scripts/vlan_traffic_sample.py`: `65c7a6e`.
- `get_config_object`'s `created_utc` field: `90e6616`.
- `get_recent_events` over the four allowlisted system-log classes: `16d7d82`.
- The read-only controller dump and network audit scripts, without the 404 paths or a
  `reports/` default: `144bad5`.
- The anonymised 17-switch fleet fixture and its STP audit test: `befd632`.

## Recommendation

Keep this list as the record. Revisit an item only through issue 060's decisions or a new
issue.

## Decision (2026-10-13)

Record only. Nothing listed here was ported in 0.3.0; the 0.3.0 release council treated this
issue as the record of what the prototype had and the port chose not to carry, to be consulted
when a 0.4.0 feature is planned.
