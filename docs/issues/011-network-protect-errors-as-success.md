---
title: "Network and Protect MCP tools return failures as successful results"
date: 2026-10-02
status: resolved
resolved_by: 9c57b2e
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

## Resolution

Resolved on 2026-10-13 (`9c57b2e`), as recommended (D10 approved). The eleven handlers in
`mcp/tools/network.py` and `mcp/tools/protect.py` no longer catch every exception. Each
catches only its client's typed error and raises a `ToolError` with the matching domain
code: `NetworkConnectionError` and Protect's `ConnectionError` are `CONTROLLER_UNREACHABLE`,
`NetworkAuthenticationError` and Protect's `AuthenticationError` (the client wraps a 401/403
and a failed login) are `AUTHENTICATION_FAILED`, any other `NetworkClientError` /
`ProtectClientError` is `API_ERROR`, and `get_nvr_info` on a controller that reports no NVR
is `NO_DATA` (it returned `{'error': 'NVR not available'}` as a success). Anything else
(an httpx protocol error, a pydantic validation error) propagates and the runner reports
it as `TOOL_FAILED` with its masked ERROR log line, like every other tool. The handlers'
own ERROR line and redaction are kept: the `ToolError`'s message is the redacted text.

Two of the issue's statements were checked against the source and corrected here:

- "keep the CLI paths that call these wrappers printing the same message": no CLI path
  imports `unifi_mapper.mcp.tools` (grep over `src/`), so there is nothing to keep. The
  wrappers are MCP-only.
- The cases went into a new file, `tests/mcp/test_network_protect_errors.py` (28 tests:
  every code for all eleven tools through `ToolRunner`, plus the raised message's
  redaction), rather than into `test_error_semantics.py`, whose fakes declare
  `credentials: none` and never reach the network or Protect clients.

Deliberately unchanged: the per-call client (issue 021 is the shared-session question), the
`FAILURE_TEXT_LIMIT` copies (issue 067), and `ReadOnlyViolation`, which still reaches the
runner as `READ_ONLY_VIOLATION` (now simply because nothing catches it).
