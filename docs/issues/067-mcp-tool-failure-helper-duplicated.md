---
title: "The network and Protect tools each carry a copy of the redacted-failure helper"
date: 2026-10-05
status: resolved
resolved_by: 681497f
severity: low
components: [mcp/tools/network, mcp/tools/protect, mcp/runner]
found_by: 0.2.0 port review
---

# The network and Protect tools each carry a copy of the redacted-failure helper

## Problem

`_failure(action, error)` and `FAILURE_TEXT_LIMIT = 2000` appear word for word in
`src/unifi_mapper/mcp/tools/network.py` and `src/unifi_mapper/mcp/tools/protect.py`. Each
logs a tool's failure and returns its error text, both through `redact_text`. The limit's
comment points at the runner's own cap, `ERROR_TEXT_LIMIT = 2000` in `mcp/runner.py`, which
is a third copy of the number.

Two copies of a redaction helper can drift: a fix to one (a tighter limit, a log field)
would leave the other tools behind.

## Impact

None today: both copies and the runner's cap agree. Breaks fresh clones, CI or prod: no.

## Recommended fix

In a `refactor` commit, keep one helper and one constant in a leaf module that imports
nothing from `mcp/tools/` (so the runner can import it without loading the tool wrappers,
whose package `__init__` imports the Protect client), for example
`src/unifi_mapper/mcp/failure_text.py` holding `ERROR_TEXT_LIMIT` and `tool_failure()`. Make
`runner.py`, `network.py` and `protect.py` import them. The existing tests in
`tests/mcp/test_network_tool_payloads.py` and `tests/mcp/test_network_protect_guard.py` pin
the redacted text and log lines, so they prove the move.

## Resolution

Resolved on 2026-10-13 (`681497f`), as recommended. `src/unifi_mapper/mcp/failure_text.py`
holds `ERROR_TEXT_LIMIT = 2000` and `tool_failure(action, error)`; `mcp/runner.py`,
`mcp/tools/network.py` and `mcp/tools/protect.py` import them, and the two `_failure` copies
and both `FAILURE_TEXT_LIMIT`s are gone. The module imports only loguru and
`core.utils.redact`, so the runner loads it without the tool wrappers;
`tests/mcp/test_failure_text.py` pins that (an AST check that the module has no import from
`mcp.tools` and no relative import), that the three importers share the one object, and the
helper's log line, redaction and cap.

Since issue 011 (`9c57b2e`) the helper's text is the message of the `ToolError` the
wrappers raise rather than a returned `error` value, which is why the pinning tests named
here are `test_network_protect_guard.py` and `test_network_protect_errors.py`
(`test_network_tool_payloads.py` now asserts on the raised error, not on text).
