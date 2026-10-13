---
title: "The MCP deadline cannot stop a synchronous handler or a worker thread it started"
date: 2026-10-13
status: open
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
