---
title: "Decisions from the July port"
date: 2026-10-05
status: open, decision needed
severity: medium
components: [mcp, typer_cli, analysis/gateway_ssh, core/utils/readonly, analysis/wlan_config]
found_by: July port (feat/july-port)
---

# Decisions from the July port

## Problem

The July work (2026-06-29 to 2026-07-27, kept in a local archive, not in the repo) included
features that the July port did not build, because building them changes what the system
does: an SSH probe triggered from an MCP call, a controller command, or a controller write.
Each needs a user decision. What was not ported and why is listed in issue
[059](059-july-work-not-ported.md).

This issue was filed at the start of the July port. It describes as existing only what has
landed; a command or tool the port builds later is marked "planned in item N" (the port's
plan, kept outside the repo), and the port's last update records the commit for each.

## Decision needed

- **D1: expose the class B probes over MCP?** These are `diagnose latency-matrix` (it exists),
  the gateway probes (`gateway ping`, `traceroute`, `dns`, `http`, `flows`; they exist, CLI
  only), `diagnose client-connectivity` and AP-health sampling with client pings (`diagnose
  ap-health --ping-clients`; they exist, CLI only), and an on-demand `vlan-traffic sample`
  (it exists, CLI only; the MCP tools read stored results only). Recommendation: **not by
  default, and not before issue [038](038-ssh-host-key-verification-disabled.md) is
  fixed**: an MCP-triggered probe would send the gateway's root SSH password to a host whose
  key is not verified. If wanted after 038, add an `active_probe: true` manifest key that
  keeps a tool off both surfaces unless `UNIFI_MCP_ALLOW_ACTIVE_PROBES=1`, annotate it
  `openWorldHint: true` and `readOnlyHint: false`, require `UNIFI_MCP_TOOL_TIMEOUT`, and give
  the catalog its own rule for `active_probe` tools (the `mutates` naming rule in
  `tests/mcp/test_execute.py` leaves `trigger_*` out for this reason).
- **D2: an on-demand WAN speedtest?** It is a controller command (`POST cmd/devmgr`) and
  saturates the WAN for 10 to 30 s. Recommendation: **not now**. If wanted: CLI only
  (`diagnose wan --speedtest`, with a confirmation), a body-aware guard policy admitting
  exactly `{cmd: speedtest}` and `{cmd: speedtest-status}` on `cmd/devmgr`, and a test pinning
  both bodies; never MCP. The controller's scheduled result needs no command: reading it is
  `get_wan_health` and `diagnose wan` (landed in `82e9b4d`).
- **D3: read the controller's backup list?** The only known call is
  `POST cmd/backup {cmd: list-backups}`. Recommendation: **not now**. If wanted: D2's
  body-aware policy admitting exactly that body on `cmd/backup` (no other `cmd/backup` body,
  so no backup is ever started or deleted), pinned by a test of the admitted and a refused
  body, CLI only (`backup list`), never MCP. A GET, if one is found and verified read-only on
  a live controller, replaces the POST. It is the safer first user of the body-aware policy,
  because the command reads.
- **D4: long-running MCP jobs** (the July job registry, AP-health sampling over MCP)?
  Recommendation: wait for SDK v2 tasks (issue [008](008-mcp-sdk-v2-migration.md)) rather
  than an in-process registry outside the tool runner, which escaped its concurrency cap,
  timeout and cancellation (issue [012](012-mcp-default-tool-deadline.md)).

Controller writes from the July work. Each follows issue
[019](019-write-capable-cli-ideas.md)'s rules if built: CLI only, dry run by default,
explicit `--apply`, re-read to verify, never over MCP.

- **W6** `wlan set-option`, built on `wlan_config.update_wlan_settings` (minimal patch,
  verify, plan, review, apply). The July version was a GET-modify-PUT of the whole WLAN
  object, the pattern `analysis/wlan_config.py` documents as having flipped `wlan_bands` and
  WPA3 and dropped clients.
- **W7** `wlan ap-group` (the v2 `apgroups` PUT), with a snapshot under XDG state first.
- **W8** `radio spectrum-scan`: a `cmd/devmgr` POST that takes the AP's radio off-channel
  during the scan, so it disrupts clients.
- **W9** the AP-health PoE power-cycle phase. It depends on issue 019 W2, must cycle only a
  port the operator names in the command, and the operator's standing port holds (kept
  outside the repo) always apply.
- **W10** an unattended weekly `radio auto-channel --apply`: a production write from cron,
  and issue [025](025-launchd-plists-are-invalid-xml.md)'s plists are invalid.

## Impact

Until decided, these stay unbuilt. Nothing that exists today depends on them. Breaks fresh
clones, CI or prod: no.
