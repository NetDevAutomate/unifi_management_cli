---
title: "`get_clients` returns no clients: `access.type: DEFAULT` fails validation"
date: 2026-10-03
status: open
severity: medium
components: [network/models]
found_by: review follow-ups live checks at 7ef13c2 (L3)
---

# `get_clients` returns no clients: `access.type: DEFAULT` fails validation

## Problem

`ClientAccess.type` in `network/models.py` is the `ClientAccessType` enum, which knows
`GUEST`, `USER` and `HOTSPOT`. Network 10.6.106 sends `DEFAULT` for every client that isn't
a guest; Ubiquiti's API reference calls it a placeholder that later releases may refine.
`UniFiNetworkClient.list_clients` validates each record as a `ClientInfo`, so the first
`DEFAULT` client raises a `ValidationError`, and the `get_clients` MCP tool returns no
clients at all, only `[{"error": "1 validation error for ClientInfo …"}]` (as `ok: true`,
issue 011).

## Evidence

- Under `.kiro/review-followups/live-checks/run-7ef13c2/mcp/` (git-ignored):
  `mcp-discovery-network_api-get_clients.json` and `mcp-direct-network_api-get_clients.json`:
  `access.type: Input should be 'GUEST', 'USER' or 'HOTSPOT' [input_value='DEFAULT']`.
- `.kiro/review-followups/live-findings.md` (L3).

## Impact

One value the model doesn't know empties the whole list, so the tool is useless on this
controller, and the next value Ubiquiti adds would do the same. Read-only. It doesn't break
fresh clones or CI.

## Recommended fix

Add `DEFAULT` to `ClientAccessType` and type the field as
`Annotated[ClientAccessType | str, Field(union_mode='left_to_right')]`: a known value stays
the enum member and an unknown one is kept as sent. A plain `ClientAccessType | str` would
not do: pydantic's default smart union matches every string input to `str`, so known values
would come back as plain strings. That settles L3's open question (keep an unknown value,
or map it to `UNKNOWN`) in favour of keeping it.
