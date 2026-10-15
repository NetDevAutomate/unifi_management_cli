---
title: "The MCP deadline cannot stop a synchronous handler or a worker thread it started"
date: 2026-10-13
status: resolved
resolved_by: f4ccc0c
severity: low
components: [mcp/runner]
found_by: issue 012 work and the 0.3.0 release council's validation pass
---

# The MCP deadline cannot stop a synchronous handler or a worker thread it started

## Problem

`ToolRunner._execute` (`src/unifi_mapper/mcp/runner.py`) wraps a call in `anyio.fail_after`
inside the concurrency semaphore. Three things follow, all pinned or recorded since issue 012:

- The deadline starts once the call holds its slot; time spent waiting for a slot is not
  counted.
- A synchronous handler runs inline on the event loop (`_call`), so `fail_after` cannot
  interrupt it, and it blocks every other request while it runs; the STP pipeline tools are
  synchronous. `tests/mcp/test_error_semantics.py::test_a_sync_handler_is_not_interrupted_by_the_deadline`
  documents this.
- The tools that use `asyncio.to_thread` get `[TIMEOUT]`, but the worker thread keeps running
  until it finishes, holding its controller session.

## Impact

Low on a home or small-business controller: the slowest read-only tool measured live takes
2.3 s against the 270 s default (issue 012's timings). A wedged controller can still hold one
of the four slots for a sync handler's full duration, and a timed-out threaded read keeps
working after the client has been told it failed.

## Recommended fix

Run synchronous handlers in a worker thread (`anyio.to_thread.run_sync`) so the event loop stays
free and the deadline applies to the wait; give threaded handlers a cooperative stop flag they
check between controller pages; start the deadline before acquiring the slot, or report the
slot wait separately. Each with a test in `tests/mcp/test_error_semantics.py` that replaces the
current characterisation test.

## Resolution (2026-10-15)

The 0.4.0 council (D-090) took the first and third parts of the recommended fix and dropped the
cooperative stop flag: a timeout ends the caller's wait, not the controller activity.

What changed, in `ToolRunner._execute` (`src/unifi_mapper/mcp/runner.py`):

- The deadline starts before the slot. `anyio.fail_after` now wraps the concurrency
  semaphore, so `UNIFI_MCP_TOOL_TIMEOUT` is measured from the client's call. A call still
  queued when it fires is `[TIMEOUT]` and its handler is never invoked.
- A synchronous handler runs via `anyio.to_thread.run_sync(partial(fn, **kwargs),
  abandon_on_cancel=True)`. The event loop stays free (a quick async call completes while a
  sync handler blocks) and the deadline applies to the await: at the deadline the caller gets
  `[TIMEOUT]`; the abandoned worker runs to its end on its own and its result is dropped.
- No cooperative stop flag. An abandoned worker finishes its current request, each bounded by
  the client's `UNIFI_TIMEOUT` and retry settings (a guard test checks every sync
  `UnifiApiClient` is built with a `timeout`). The unfinished work this can pile up is bounded
  by one process worker budget (`core/utils/workers.py`, `max_concurrency` permits, never
  anyio's default pool, which the stdio transport reads stdin through), not by the number of
  timeouts. Both blocking hops draw on it: the runner's sync-handler hop and the async
  port-diagnostics wrappers' `_run`. A permit is held until the worker thread exits, so an
  abandoned worker keeps its permit and the next call cannot start a thread in its place
  (the 0.4.0 validation council caught that an anyio `CapacityLimiter` releases on the
  caller's cancellation, before the thread ends, and that `_run` hopped outside any budget).
- The call log (`mcp/call_audit.py`) writes `slot_wait_ms` on every call that reached the
  execution step, including one the deadline ended while it was still queued.

Tests, replacing `test_a_sync_handler_is_not_interrupted_by_the_deadline` in
`tests/mcp/test_error_semantics.py`: `test_the_event_loop_stays_free_while_a_sync_handler_runs`,
`test_a_call_queued_for_a_slot_times_out_without_invoking_the_handler`,
`test_a_timeout_during_a_sync_handler_returns_at_the_deadline`,
`test_abandoned_sync_handlers_are_bounded_by_the_thread_limiter`,
`test_the_calling_context_reaches_a_sync_handler_in_its_thread`; in
`tests/mcp/test_call_audit.py`: `test_the_slot_wait_is_in_the_call_line`,
`test_a_call_that_never_got_its_slot_records_the_wait`; in
`tests/mcp/test_port_diagnostic_tools.py`: `test_every_sync_client_is_built_with_a_bounded_timeout`,
`test_get_recent_events_request_ceiling_is_the_documented_101`.

What a user sees differently: a call that queues behind busy slots can now come back
`[TIMEOUT]` instead of waiting without end; a synchronous tool no longer stalls every other
call while it runs, and one that overruns the deadline returns `[TIMEOUT]` at the deadline
rather than a late success; each call line in the MCP call log carries `slot_wait_ms`. The
guide's deadline section describes the semantics.
