---
title: "`create_block_rule` / `create_allow_rule` default `rule_type='USER'`, a value the ACL API rejects"
date: 2026-10-13
status: resolved
resolved_by: c884fb3
severity: low
components: [network/acl]
found_by: the 0.3.0 Integration API lane (issue 036)
---

# `create_block_rule` / `create_allow_rule` default `rule_type='USER'`, a value the ACL API rejects

## Problem

`network/acl.py` lines 243 and 308 default `rule_type` to `'USER'`. The ACL `type` values
present in the in-repo fixtures are `IPV4`; `USER` is the value of `metadata.origin`, a
different field.

## Impact

A caller that accepts the default builds a rule the controller refuses, with a 400 that names a
field the caller did not set. These helpers are CLI-only (ACL writes are not exposed over MCP),
so no automated path is affected today.

## Recommended fix

Default `rule_type` to `IPV4` or make it a required argument; add a MockTransport test that the
request body carries the type the fixtures show.

## Resolution (2026-10-15)

`create_block_rule` and `create_allow_rule` now default `rule_type` to `IPV4`. Ubiquiti's
published OpenAPI for Network v10.6.102 makes an ACL rule's `type` a discriminator with exactly
two values, `IPV4` and `MAC`; `USER` belongs to `metadata.origin`. An explicit `rule_type` is
still sent as given.

Pinned by `tests/network/test_acl_create_type.py`, which drives the real `UniFiNetworkClient`
over a mock transport and reads the body each helper POSTs.

What a user sees: a rule created with the default type is no longer refused for its type.
Not exercised against the live controller (no writes). The same reference also requires a
`type` on each source and destination filter (`IP_ADDRESSES_OR_SUBNETS`, `PORTS`, `NETWORKS`;
`MAC_ADDRESSES` for a MAC rule) and at least one item in each list; the helpers send neither,
so a rule with an IP or port filter is still likely to be refused. That is a separate defect,
reported for its own record.
