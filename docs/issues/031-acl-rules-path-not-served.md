---
title: "`get_acl_rules` gets a 404: the client's `/acls` path isn't served by Network 10.6"
date: 2026-10-03
status: open
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
