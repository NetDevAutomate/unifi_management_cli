---
title: "No cap on `execute_tool` result size"
date: 2026-10-05
status: resolved
resolved_by: 54b89b2
severity: low
components: [mcp/runner, mcp/server]
found_by: MCP uvx standards work (moved from issue 013, decision D4)
---

# No cap on `execute_tool` result size

## Problem

`execute_tool` returns results of any size. A fleet-wide analysis can produce a very large
result. Moved here from issue [013](013-mcp-audit-log-and-result-cap.md) (its design
decision D4) so that 013 can close when its call log lands.

## Impact

Very large results cost context and some hosts persist or truncate them unpredictably. It
breaks nothing today. Breaks fresh clones, CI or prod: no.

## Decision needed

- D4: a global result cap on `execute_tool` (for example 200k characters, then
  `truncated: true`)? Design recommendation: **not now**: hosts already persist oversized
  results, and the new tools paginate (`limit`/`offset`). Revisit if a tool is seen to exceed
  it.

## Decision (2026-10-13)

No global cap on `execute_tool` result size in 0.3.0: hosts already persist oversized results
and the tools that can grow paginate (`limit`/`offset`). Revisit if a tool is seen to exceed a
host's limit in practice. Decided by the 0.3.0 release council (D-063); resolved as a recorded
decision, no code change.
