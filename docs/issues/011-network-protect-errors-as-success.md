---
title: "Network and Protect MCP tools return failures as successful results"
date: 2026-10-02
status: open, decision needed
severity: medium
components: [mcp/tools/network, mcp/tools/protect]
found_by: MCP uvx standards work
---

# Network and Protect MCP tools return failures as successful results

## Problem

The 11 handlers in `mcp/tools/network.py` (6) and `mcp/tools/protect.py` (5) catch every
exception and return `{'error': str(e)}` or `[{'error': str(e)}]`. `ToolRunner` sees a normal
return value, so `execute_tool` answers `{"ok": true, "result": {"error": "..."}}` with
`isError: false` (the error text is masked like any result). Every other tool raises, and its
failure arrives as `[TOOL_FAILED]` or a domain code with `isError: true`.

## Impact

A model or host that trusts `ok`/`isError` treats a failed Network or Protect read as an
empty or odd success, and may draw conclusions from it. The MCP spec says a tool error should
be reported as an error result, not a success value.

## Decision needed

Design decision D10: convert these handlers to raise (a `ToolError` with a domain code where
one fits, else let the exception reach the runner as `TOOL_FAILED`)?

Design recommendation: **approve**. Callers that today get `ok: true` with an error dict (or a
list containing one) would get `ok: false` and `isError: true`. Add a case per handler to
`tests/mcp/test_error_semantics.py` and keep the CLI paths that call these wrappers printing
the same message.
