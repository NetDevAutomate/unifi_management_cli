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

Three tools run their blocking work in `asyncio.to_thread`: `get_device_events`,
`get_recent_events` and `verify_config_backup`. When `UNIFI_MCP_TOOL_TIMEOUT` expires or the
client cancels, the call ends (`[TIMEOUT]`, or cancelled) and `ToolRunner` frees its
concurrency slot, but the thread cannot be cancelled and runs on to the end: up to 101
sequential controller reads for `get_recent_events` (one login per call, issue 021), and for
`verify_config_backup` the decrypt, the extract and the decompress (each capped at 1 GiB)
and a strict BSON walk that stops at the first failure. A client that retries after a
timeout starts another worker while the first still runs; only the default executor's
thread limit bounds them. Recommended fix: a stop flag the handler sets when its task is
cancelled, checked between the backup's stages and between event pages.
