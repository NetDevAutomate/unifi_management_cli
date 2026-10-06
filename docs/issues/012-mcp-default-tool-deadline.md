---
title: "MCP tool calls have no deadline by default"
date: 2026-10-02
status: open, decision needed
severity: low
components: [mcp/config, mcp/runner]
found_by: MCP uvx standards work
---

# MCP tool calls have no deadline by default

## Problem

`ToolRunner` applies a per-call deadline only when `UNIFI_MCP_TOOL_TIMEOUT` is set (5–3600 s);
unset means none (`ServerSettings.tool_timeout = None`). A wedged controller or a stuck SSH
helper therefore holds the call, and one of the four concurrency slots
(`UNIFI_MCP_MAX_CONCURRENCY`), until the client gives up. httpx's own timeouts (connect 10 s,
request 30 s on the shared client) bound single requests, not a tool that makes many.

No measurement exists of how long the slowest read-only tools take against the real
controller (design backlog B14); this work never contacted it from a FEAT step.

## Impact

A hung call surfaces as a client-side timeout with no `[TIMEOUT]` code and no server log line,
and keeps the slot busy. The sampling tools (`get_port_counter_rates`, `diagnose_switch_port`)
legitimately block for about 100 s, so any default must stay well above that.

## Decision needed

Design decision D11: default `UNIFI_MCP_TOOL_TIMEOUT` to 300 s?

Design recommendation: **approve 300 s**. It is above any plausible fleet read and the 100 s
sampling window, and it turns a wedged controller into `[TIMEOUT]`. Correction (2026-10-05): it
is not below the host limits. The guide's client snippets stop at exactly 300 s (kiro-cli
`"timeout": 300000`, Codex `tool_timeout_sec = 300`), so at 300 s the client can give up first
and `[TIMEOUT]` never arrives. Either set the server default below the client limit (for
example 270 s) or raise the client timeouts above it (for example 330 s). Before approving,
measure the slowest tools
live (B14): time `network_health_check`, `security_audit`, `audit_link_speeds`,
`analyze_traffic_matrix` and `diagnose_switch_port` once each, read-only, and record the
figures here. Until then the variable works opt-in.

## A deadline ends the call, not a worker thread (found in the July port's review)

Fourteen tools run their blocking work in `asyncio.to_thread` (counted at the July port's last
commit): `get_switch_ports`, `diff_port_profiles`, `get_client_history`, `get_device_events`,
`get_recent_events`, `get_port_counter_rates`, `diagnose_switch_port`,
`audit_port_profile_usage`, `audit_link_speeds`, `inspect_switch_port`,
`get_wan_speedtest_history`, `verify_config_backup`, `get_vlan_traffic_report` and
`list_vlan_traffic_periods`. When `UNIFI_MCP_TOOL_TIMEOUT` expires or the
client cancels, the call ends (`[TIMEOUT]`, or cancelled) and `ToolRunner` frees its
concurrency slot, but the thread cannot be cancelled and runs on to the end: for example up to 101
sequential controller reads for `get_recent_events` (one login per call, issue 021), and for
`verify_config_backup` the decrypt, the extract and the decompress (each capped at 1 GiB)
and a strict BSON walk that stops at the first failure. A client that retries after a
timeout starts another worker while the first still runs; only the default executor's
thread limit bounds them. Recommended fix: a stop flag the handler sets when its task is
cancelled, checked between the backup's stages and between event pages.

## `get_ap_retry_rates` can outlast the clients' 300 s limit (found in the July port's review)

`get_ap_retry_rates` pauses `interval_seconds` (10-240 s) between two device reads. Each read
opens its own `UniFiClient` and has no deadline of its own: only httpx's per-request timeouts
(30 s, connect 10 s) bound it. At the 240 s maximum, two reads at their 30 s request bound
alone reach 300 s, the guide's client limit (kiro-cli `"timeout": 300000`, Codex
`tool_timeout_sec = 300`), and a connect or a slower read goes past it, so the client gives up
first and `[TIMEOUT]` never arrives. The tool's docstring already says to keep the interval
short over MCP. Recommended fix, with D11: bound each read as `diagnose ap-health` does (45 s,
`SAMPLE_READ_TIMEOUT`), and cap `interval_seconds` so the interval plus both read bounds stays
under the client limit (or raise the client timeouts, as above). Breaks fresh clones, CI or
prod: no.

The port's longest composite stays CLI only: `diagnose ap-health` runs up to about 10 h, so an
MCP form waits for decision D4 in issue [060](060-decisions-from-the-july-port.md) (SDK v2
tasks, issue [008](008-mcp-sdk-v2-migration.md)), not for a deadline here.
`diagnose client-connectivity` stops at 120 s but uses SSH, so it waits for 060's D1 as well.
