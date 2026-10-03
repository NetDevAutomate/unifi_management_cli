---
title: "`get_clients` returns no clients: `access.type: DEFAULT` fails validation"
date: 2026-10-03
status: resolved
resolved_by: 1f79d47
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

## Resolution

Fixed as recommended. `ClientAccessType` gains `DEFAULT`, and `ClientAccess.type` is
`Annotated[ClientAccessType | str, Field(union_mode='left_to_right')]`: `GUEST`, `USER`,
`HOTSPOT` and `DEFAULT` validate to the enum member, and any other string is kept as sent,
so one new value can no longer empty the list. The default stays `USER`, and
`ClientInfo.is_guest` is unchanged (an unknown type is not a guest).

Tests: `tests/network/test_models.py::TestClientAccess` (`DEFAULT` is the member, an unknown
type is kept as its `str`, `GUEST` is still the member) and
`tests/mcp/test_network_tool_payloads.py::test_get_clients_returns_default_and_user_clients`
(a `MockTransport` page with one `DEFAULT` and one `USER` client, behind the tools' guard,
returns both). Three of the four failed on the old code; the `GUEST` test passes there by
design and fails on a plain `ClientAccessType | str` (checked by swapping that in).

Live (read-only: the `get_clients` tool in-process, behind its GET-only guard, request
audit on): 98 clients returned (31 wired, 67 wireless), every `access.type` the `DEFAULT`
member, and no other `ClientInfo` field rejected a live value; 11 audited GETs (the site
lookup and the six network tools), 0 violations. Evidence:
`.kiro/review-followups/iter2/network-api/f16-wip/result.json` (git-ignored).

Follow-up: `ClientInfo.type` had the same failure mode. Ubiquiti's reference documents
`TELEPORT` clients, which `ClientType` (`WIRED`, `WIRELESS`, `VPN`) would have rejected, again
emptying the list. It got the same treatment in the commit that adds this note: `TELEPORT`
joins the enum, and an unknown type is kept as its string
(`tests/network/test_models.py::TestClientConnectionType` and
`test_get_clients_keeps_teleport_and_unknown_connection_types`).
