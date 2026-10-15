---
title: "`DNSPolicy` has no `metadata` field although the API sends `metadata.origin`"
date: 2026-10-13
status: resolved
resolved_by: f8cccb0
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

## Resolution (2026-10-15)

`DNSPolicy` now declares `metadata: ACLRuleMetadata | None`, the same `{origin}` object an ACL
rule carries, and an `origin` property that reads through to it (`USER_DEFINED`, `DERIVED`, an
unknown value as sent, or `''` when the policy has no metadata). The field is optional, so a
policy without it still parses.

Pinned by `test_acl_and_dns_tools_keep_the_records_origin` in
`tests/mcp/test_network_tool_payloads.py` (the MCP payload keeps `metadata.origin` for ACL rules
and DNS policies alike) and `TestDNSPolicyOrigin` in `tests/network/test_models_reference.py`.

What a user sees: each record `get_dns_policies` returns carries `metadata.origin`, so a
user-defined policy can be told from a derived one. The key is new; nothing was removed. No
CLI command reads DNS policies, so the shape rests on the reference-shaped fixture, not on a
live read.
