---
title: "No default audit log of MCP calls, and no cap on result size"
date: 2026-10-02
status: resolved
resolved_by: e2fbac2
severity: low
components: [mcp/runner, mcp/server, core/utils/readonly]
found_by: MCP uvx standards work
---

# No default audit log of MCP calls, and no cap on result size

## Problem

1. **Audit log (design D5).** The server keeps no record of which tools an assistant ran.
   The opt-in `UNIFI_MCP_REQUEST_AUDIT=<file>` (plan P9) records the controller requests the
   read-only guards let through (method and path, one JSON line each), but not the MCP calls
   themselves (tool, argument keys, duration, outcome).
2. **Result size (design D4).** `execute_tool` returns results of any size. A fleet-wide
   analysis can produce a very large result.

## Impact

Without a call log, reconstructing what an assistant did during an incident relies on the
host's transcript; the MCP spec recommends servers keep an audit trail. Very large results
cost context and some hosts persist or truncate them unpredictably. Neither breaks anything
today.

## Decision needed

- D5: write a default-on JSONL log at `$XDG_STATE_HOME/unifi_mapper/mcp-audit.jsonl` with one
  line per call (time, tool, argument **keys** only, duration, outcome code), size-capped like
  the counter history? Design recommendation: **approve** (it is a new file on disk, hence a
  decision). Reuse the request-audit writer's locking, never log argument values, and make
  `UNIFI_MCP_REQUEST_AUDIT` a per-request detail on the same file.
- D4: a global result cap on `execute_tool` (for example 200k characters, then
  `truncated: true`)? Design recommendation: **not now**: hosts already persist oversized
  results, and the new tools paginate (`limit`/`offset`). Revisit if a tool is seen to exceed
  it. D4 moved to issue [063](063-execute-tool-result-cap.md) (2026-10-05), so this issue can
  close when D5 lands.

## Resolution

D5 is implemented as recommended, in the 0.2.0 port: `mcp/call_audit.py` writes one JSON line
per catalog tool call, on by default, to `$XDG_STATE_HOME/unifi_mapper/mcp-audit.jsonl`
(resolved at each write, never relative to the working directory). A line holds the time,
the registered tool's name (an unregistered name is `<unregistered>` with its length), the
surface, the argument keys that are the tool's own parameter names (any other key only
counted), the duration and the outcome (`ok`, the error code, or `CANCELLED`); argument
values, results and messages are never written. `UNIFI_MCP_CALL_AUDIT` turns it off or moves
it to an absolute path, and `UNIFI_MCP_REQUEST_AUDIT=on` adds the read-only guards' request
lines to the same file (a path still writes the separate file; the `off` family and `default`
write nothing). The file is capped at 16 MiB through the shared capped JSON-lines writer
(`core/utils/jsonl.py`: a lock file, torn-line repair, compaction to 80%), `0o600`. The runner
writes in a worker thread inside a shielded cancel scope, and a failed write warns once and
turns the log off for the process, so no tool result changes. `unifi-mcp --check` reports the
path as `call_audit`.

D4 moved to issue [063](063-execute-tool-result-cap.md) before this closed. Tests:
`tests/mcp/test_call_audit.py`.
