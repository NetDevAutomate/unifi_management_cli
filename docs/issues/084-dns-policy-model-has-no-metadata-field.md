---
title: "`DNSPolicy` has no `metadata` field although the API sends `metadata.origin`"
date: 2026-10-13
status: open
severity: low
components: [network/models, network/dns]
found_by: the 0.3.0 Integration API lane (issue 036)
---

# `DNSPolicy` has no `metadata` field although the API sends `metadata.origin`

## Problem

The `DNS_POLICY` fixture in `tests/mcp/test_network_tool_payloads.py` (line ~116) shows
`metadata.origin` on a DNS policy; `DNSPolicy` in `network/models.py` declares no `metadata`,
so pydantic drops it.

## Impact

The user/system split that issue 036 gave ACL rules through `ACLRuleMetadata` is unavailable
for DNS policies; `get_dns_policies` cannot tell a user-defined policy from a derived one.
Ignored, not rejected: low.

## Recommended fix

Add `metadata: ACLRuleMetadata | None = None` (or a DNS-specific twin) and surface `origin` as
a property, with a fixture test; reuse the 036 pattern.
