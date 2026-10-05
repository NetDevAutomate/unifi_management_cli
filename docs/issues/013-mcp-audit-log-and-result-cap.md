---
title: "No default audit log of MCP calls, and no cap on result size"
date: 2026-10-02
status: open, decision needed
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
