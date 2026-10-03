---
title: "`get_dns_policies` gets a 404: the client's `/dns-policies` path isn't served"
date: 2026-10-03
status: resolved
resolved_by: fb4ff9e
severity: medium
components: [network/client]
found_by: review follow-ups live checks at 7ef13c2 (L2)
---

# `get_dns_policies` gets a 404: the client's `/dns-policies` path isn't served

## Problem

`UniFiNetworkClient` builds every DNS-policy request on `/sites/{siteId}/dns-policies`:
`list_dns_policies`, `get_dns_policy`, `create_dns_policy`, `update_dns_policy` and
`delete_dns_policy` in `network/client.py`. Network 10.6.106 has no such endpoint. On the
first live run of the `get_dns_policies` MCP tool, the read-only guard let one audited
`GET /proxy/network/integrations/v1/sites/<site>/dns-policies` through, and the controller
answered `404 "No endpoint GET /integration/v1/sites/<site>/dns-policies."`. The tool
returned that as `ok: true` with an `{"error": …}` payload (issue 011), on both MCP
surfaces.

## Evidence

- Under `.kiro/review-followups/live-checks/run-7ef13c2/mcp/` (git-ignored):
  `mcp-discovery-network_api-get_dns_policies.json` and
  `mcp-direct-network_api-get_dns_policies.json` hold the 404 payload and the audited GET.
- `.kiro/review-followups/live-findings.md` (L2).
- Ubiquiti's Network API reference for v10.6.102 lists the resource as
  `/v1/sites/{siteId}/dns/policies` (`GET` and `POST`), with `GET`, `PUT` and `DELETE` on
  `/v1/sites/{siteId}/dns/policies/{dnsPolicyId}`.

## Impact

The tool never returns DNS policies from this controller, and the write methods would fail
the same way for a library caller. Read-only; no data is at risk. It doesn't break fresh
clones or CI.

## Recommended fix

As for issue 031: confirm the served path with one guarded GET, move all five call sites to
`/sites/{siteId}/dns/policies` together, and pin them with `httpx.MockTransport` tests.

## Resolution

Fixed as recommended, together with issue 031. On Network 10.6.106 the guarded probe's GET
on `/dns-policies` answered 404 again and `/dns/policies` answered 200 (an empty page: this
console has no DNS policies). All five call sites now use `/sites/{siteId}/dns/policies`.

Tests: `tests/network/test_client_paths.py` pins the list and get paths, and shows
`create_dns_policy`, `update_dns_policy` and `delete_dns_policy` build the same path while
the GET-only guard refuses each of them before any I/O;
`tests/mcp/test_network_tool_payloads.py::test_acl_and_dns_tools_read_the_served_paths`
returns a reference-shaped policy through the tool. All of them failed on the old path.

Live after the fix: `get_dns_policies` returned `[]` with no error; 11 audited GETs for the
site lookup and the six tools, 0 violations. Evidence (git-ignored):
`.kiro/review-followups/iter2/f17/probe.json` and
`.kiro/review-followups/iter2/network-api/f17-wip/result.json`.
