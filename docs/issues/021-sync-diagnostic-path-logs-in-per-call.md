---
title: "The sync port-diagnostics MCP tools log in to the controller on every call"
date: 2026-10-02
status: open, decision needed
severity: medium
components: [diagnostics/port_diagnostics_tools, diagnostics/inspect_port, api_client, core/utils/readonly]
found_by: MCP uvx standards work
---

# The sync port-diagnostics MCP tools log in to the controller on every call

## Problem

Plan decision P3 gave the MCP server one shared, read-only-guarded async client
(`SharedControllerClient`), so the async tools log in once per server process. The sync
diagnostics path was deliberately left per call: `diagnose_switch_port`, `get_switch_ports`,
`diff_port_profiles`, `get_client_history`, `get_device_events`, `get_port_counter_rates`,
`audit_link_speeds` and `audit_port_profile_usage` each build a new `UnifiApiClient` through
`port_diagnostics_tools._readonly_sync_client()`, log in, install the read-only guard, run,
and log out.

They stay per call because each call's `request_audit` (the list of controller requests that
call made, which ends up in the evidence bundle) must cover exactly that call. A shared
session would mix requests from concurrent calls into one record.

**Related gap found while documenting this.** `inspect_switch_port`
(`diagnostics/inspect_port.py`, `_inspect_sync`) builds its own `UnifiApiClient` from
`Credentials.from_env()` and never calls `install_read_only_guard`, so it is the one MCP
catalog tool whose controller requests are neither guarded nor recorded by
`UNIFI_MCP_REQUEST_AUDIT`. Its code only reads (`resolve_switch`, `inspect_port`), so nothing
is written today; the gap is that a future change could write without the guard noticing.

## Impact

One extra login and logout per sync tool call: a little latency, and extra entries in the
controller's admin log during a long assistant session. The unguarded `inspect_switch_port`
weakens the "MCP is read-only" proof the request audit is meant to give. Neither breaks
anything today.

## Recommended fix

1. Route `inspect_switch_port` through `_readonly_sync_client()` and `_mapped`, as its sibling
   tools do, keeping its error codes (`CONTROLLER_UNREACHABLE`, `DEVICE_NOT_FOUND`,
   `INVALID_PORT`) and result shape (the `tests/data/inspect_switch_port_golden.json` golden
   must stay equal), and add it to the read-only guard tests.
2. Share the sync session only once per-call attribution survives it: give each call its own
   `request_audit` collector scoped by a `contextvars.ContextVar` (set in `_mapped` before
   `asyncio.to_thread`, which copies the context), keep the read-only guard installed on the
   shared session, and re-login on a 401. Add a test that two concurrent calls each record
   only their own requests. Until then, keep the per-call login.

## Partial resolution

Step 1's goal, guarding `inspect_switch_port`, is done: `_inspect_sync` now calls
`install_read_only_guard` straight after login, so its requests are refused if they would
write (`READ_ONLY_VIOLATION`) and are recorded by `UNIFI_MCP_REQUEST_AUDIT`. It keeps its own
client rather than `_readonly_sync_client()`/`_mapped`, so its login failure message, its
`DEVICE_NOT_FOUND`/`INVALID_PORT` messages and its result (the golden) are unchanged.
`tests/mcp/test_inspect_port_guard.py` covers the guard, the audit sink, a refused write and
the kept error codes. Step 2 (one shared sync session) is still open, so this issue stays
open.

## `get_recent_events` reads every page before it keeps the newest (July port review)

`collect_recent_events` pages each source to its page cap (`stat/event` 20 pages of 1000,
`list/alarm` once, the four system-log classes 20 pages of 100 each) and only then sorts and
keeps the newest `max_events`. With no filter, a one-year window on a busy site is up to 101
sequential requests behind one login per call. `stat/event` is requested newest first
(`_sort: -time`), so with no `category`, `severity` or `contains` filter it could stop once it
holds `max_events` records. Not done, because it changes what the result reports:
`matched_total` would count only the records read, not every match in the window, and the
source's `truncated` would turn true. Decision needed: accept that change, or keep the full
read. The system log's page order has to be checked, read-only, before it could stop early
too.
