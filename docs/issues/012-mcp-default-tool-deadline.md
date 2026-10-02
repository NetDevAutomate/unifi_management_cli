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

Design recommendation: **approve 300 s**: above any plausible fleet read and the 100 s sampling
window, below typical host limits (the guide's Codex snippet sets `tool_timeout_sec = 300`), and
it turns a wedged controller into `[TIMEOUT]`. Before approving, measure the slowest tools
live (B14): time `network_health_check`, `security_audit`, `audit_link_speeds`,
`analyze_traffic_matrix` and `diagnose_switch_port` once each, read-only, and record the
figures here. Until then the variable works opt-in.
