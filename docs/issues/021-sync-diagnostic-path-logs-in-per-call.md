---
title: "The sync port-diagnostics MCP tools log in to the controller on every call"
date: 2026-10-02
status: resolved
resolved_by: 41665f0
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
and log out. The 0.2.0 port's `get_recent_events` (`16d7d82`) takes the same path, so it logs
in and out on every call too.

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

## Partial resolution (step 1)

Step 1's goal, guarding `inspect_switch_port`, was done in two moves. First `_inspect_sync`
called `install_read_only_guard` on a client of its own straight after login, so its requests
were refused if they would write (`READ_ONLY_VIOLATION`) and recorded by
`UNIFI_MCP_REQUEST_AUDIT`. Then (see Progress below) it moved onto
`_readonly_sync_client()`/`_mapped`, the path its siblings take, keeping its login failure
message, its `DEVICE_NOT_FOUND`/`INVALID_PORT` messages and its result (the golden).
`tests/mcp/test_inspect_port_guard.py` covers the guard, the audit sink, a refused write and
the kept error codes. Step 2 (one shared sync session) is resolved below.

## `get_recent_events` reads every page before it keeps the newest (0.2.0 port review)

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

Decided 2026-10-15 by the 0.4.0 planning council (D-021-EVENTS): the full read stays in 0.4.0;
the early stop is its own decision, filed as issue 101.

## Progress

2026-10-13 (`b37ec46`): step 1 is complete. `inspect_switch_port` runs inside
`port_diagnostics_tools._readonly_sync_client()` under `_mapped`, like its eight siblings,
so the one login-and-guard path serves every sync diagnostics tool (and the siblings' test
seam, patching `port_diagnostics_tools._readonly_sync_client`, now covers it:
`inspect_switch_port` is in the `execute_tool` read-only matrix of
`tests/mcp/test_port_diagnostic_tools.py`). Its `DEVICE_NOT_FOUND` and `INVALID_PORT`
messages, the `CONTROLLER_UNREACHABLE` text for a login that returns `False`,
`READ_ONLY_VIOLATION` and the result (`tests/data/inspect_switch_port_golden.json`, through
`tests/analysis/test_link_settings.py`) are unchanged; a login that raises is now
`CONTROLLER_UNREACHABLE` with the redacted cause rather than `TOOL_FAILED`.
`tests/mcp/test_inspect_port_guard.py` pins the seam and both login outcomes.

Still open, so the issue stays open: step 2 (one shared sync session with a per-call
`request_audit` collector in a `ContextVar`, re-login on 401, a two-concurrent-calls test)
and the `get_recent_events` early-stop decision above. Neither was in this lane's scope.

## Resolution (2026-10-15)

Step 2 is done; the 0.4.0 council (D-021) decided the design and kept the full
`get_recent_events` read (the early-stop question above stays a separate decision, to be
filed as its own issue).

What changed (`src/unifi_mapper/diagnostics/port_diagnostics_tools.py`):

- One process-wide sync `UnifiApiClient`, created lazily under a lock on the first call from
  `Credentials.from_env()` and the `UNIFI_TIMEOUT`/`UNIFI_MAX_RETRIES`/`UNIFI_RETRY_DELAY`
  settings (issue 087), logged in once, with the read-only guard installed straight after the
  login and put back after any later login. Every sync tool, `inspect_switch_port` included,
  borrows it through `_readonly_sync_client()`. A client built from other credentials or
  settings than the environment holds is retired on the next call; a build that fails leaves
  nothing behind, so the next call retries.
- Per-call `request_audit`: a `contextvars.ContextVar` holds the call's collector, set by the
  async handler before the thread hop (the context is copied into the worker) and reset with
  its token when the call ends. The guard's audit list forwards to the current call's
  collector, so `diagnose_switch_port`'s `request_audit` lists exactly that call's requests
  even with concurrent calls, and a worker abandoned by the runner's deadline writes only to
  its own.
- Re-authentication: a 401 logs in again once and replays the refused request once (the
  replay is checked and audited like any request); its answer is returned as it is, so there
  is never a loop. The guard is verified after each refresh.
- Concurrency: worker threads share the one `requests.Session` for their GET and POST reads
  (urllib3's pool is thread-safe, the cookie jar locks itself, the client's per-request header
  update writes constant values); only login and refresh take a lock.
- Shutdown: the server's lifespan calls `shutdown_shared_sync_session()`, which waits (bounded)
  for active workers, then logs out and closes; a worker still active at the bound keeps the
  session open and the last one to finish closes it.

Tests: `tests/mcp/test_shared_sync_session.py` (one login for many calls; two concurrent calls
each record only their own requests; a 401 triggers exactly one refresh and one replay, a
second 401 is returned, a concurrent call is unaffected; the guard is on the shared session and
survives a refresh and a login the client runs itself; an abandoned worker cannot append to
another call's collector or a published record; init failure resets; the drain waits, logs out,
and leaves a still-active worker alone; the lifespan calls the drain; sixteen threads over a
real `requests.Session` stay attributed). `tests/mcp/test_inspect_port_guard.py` pins
`inspect_switch_port` on the shared session; its golden
(`tests/data/inspect_switch_port_golden.json`) is unchanged.

What a user sees differently: one login when the first sync tool runs and one logout when the
server stops, instead of a pair per call, so the controller's admin log no longer fills with
MCP logins during a session; a controller that expires the session gets one quiet re-login. The
client's LLDP neighbour-name cache (MAC to adopted-device name) now lives for the server
process: a device adopted or renamed afterwards resolves by name after a restart (the guide's
per-process state section says so).
