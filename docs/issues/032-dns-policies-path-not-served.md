---
title: "`get_dns_policies` gets a 404: the client's `/dns-policies` path isn't served"
date: 2026-10-03
status: open
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
