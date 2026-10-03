---
title: "`get_acl_rules` gets a 404: the client's `/acls` path isn't served by Network 10.6"
date: 2026-10-03
status: resolved
severity: medium
components: [network/client]
found_by: review follow-ups live checks at 7ef13c2 (L1)
---

# `get_acl_rules` gets a 404: the client's `/acls` path isn't served by Network 10.6

## Problem

`UniFiNetworkClient` builds every ACL-rule request on `/sites/{siteId}/acls`:
`list_acl_rules`, `get_acl_rule`, `create_acl_rule`, `update_acl_rule` and
`delete_acl_rule` in `network/client.py`. Network 10.6.106 has no such endpoint. On the
first live run of the `get_acl_rules` MCP tool, the read-only guard let one audited
`GET /proxy/network/integrations/v1/sites/<site>/acls` through, and the controller answered
`404 "No endpoint GET /integration/v1/sites/<site>/acls."`. The tool returned that as
`ok: true` with an `{"error": …}` payload (issue 011), on the discovery and the direct MCP
surface alike.

## Evidence

- Under `.kiro/review-followups/live-checks/run-7ef13c2/mcp/` (git-ignored):
  `mcp-discovery-network_api-get_acl_rules.json` and `mcp-direct-network_api-get_acl_rules.json`
  hold the 404 payload and the one audited GET.
- `.kiro/review-followups/live-findings.md` (L1).
- Ubiquiti's Network API reference for v10.6.102 lists the resource as
  `/v1/sites/{siteId}/acl-rules` (`GET` and `POST`), with `GET`, `PUT` and `DELETE` on
  `/v1/sites/{siteId}/acl-rules/{aclRuleId}`.

## Impact

The tool never returns ACL rules from this controller. The write methods, which no MCP tool
calls and the tools' guard refuses, would fail the same way for a library caller. Read-only;
no data is at risk. It doesn't break fresh clones or CI.

## Recommended fix

Confirm the served path with one guarded GET, then move all five call sites to
`/sites/{siteId}/acl-rules` together. Add `httpx.MockTransport` tests that pin the list and
get paths, and one that shows the write methods build the same path while the GET-only
guard still refuses them before any I/O.

## Resolution

Fixed as recommended, together with issue 032. The guarded probe (read-only: GET only,
through `ReadOnlyAsyncTransport(policy=get_only_request_allowed)` with the request audit on,
using CONFIG's API key) sent one GET per candidate on Network 10.6.106: `/acls` answered 404
again and `/acl-rules` answered 200 (an empty page: this console has no ACL rules). All five
call sites now use `/sites/{siteId}/acl-rules`.

Tests: `tests/network/test_client_paths.py` pins the list and get paths, and shows
`create_acl_rule`, `update_acl_rule` and `delete_acl_rule` build the same path while the
GET-only guard refuses each of them before any I/O, naming that path;
`tests/mcp/test_network_tool_payloads.py::test_acl_and_dns_tools_read_the_served_paths`
returns a reference-shaped rule through the tool. All of them failed on the old path.

Live after the fix (the six network tools in-process, behind their guard): `get_acl_rules`
returned `[]` with no error, and all six tools succeeded; 11 audited GETs, 0 violations.
Evidence (git-ignored): `.kiro/review-followups/iter2/f17/probe.json` and
`.kiro/review-followups/iter2/network-api/f17-wip/result.json`.
