---
title: "The network and Protect tools each carry a copy of the redacted-failure helper"
date: 2026-10-05
status: open
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
