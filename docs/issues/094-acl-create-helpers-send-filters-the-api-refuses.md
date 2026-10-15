---
title: "ACL create helpers send filters without a `type` and with empty lists the API refuses"
date: 2026-10-15
status: resolved
resolved_by: e31c00d
severity: medium
components: [network/acl, network/models]
found_by: 0.4.0 lane 2a (issue 083 fix)
---

# ACL create helpers send filters without a `type` and with empty lists the API refuses

## Problem

Issue 083 fixed the rule-level `type` default (`IPV4`). The same reference (Ubiquiti's published
OpenAPI for Network v10.6.102) also constrains the per-side filters, and
`src/unifi_mapper/network/acl.py` `create_block_rule` (line 240) and `create_allow_rule`
(line 306) break it in three ways:

- Each source and destination filter must carry its own `type` discriminator
  (`IP_ADDRESSES_OR_SUBNETS`, `PORTS`, `NETWORKS`; `MAC_ADDRESSES` for a MAC rule). The helpers
  send none (lines 272-283, 338-346).
- The list fields have `minItems: 1`. The helpers send every list, empty or not
  (`'ipAddressesOrSubnets': source_ips or []`, `'portFilter': source_ports or []`).
- `create_block_rule(source_macs=...)` puts `macAddresses` into an `IPV4` rule (line 276). A
  MAC rule is type `MAC` with a `networkIdFilter`, and `macAddresses` belongs to a
  `MAC_ADDRESSES` filter.

`ACLTrafficFilter` (`network/models.py:726`) already has an optional `type` and
`mac_addresses`, so the read side tolerates both shapes; only the write side is wrong.

## Evidence

The reference's schema, quoted in issue 083's Resolution. Not exercised live (ACL writes are
off-limits to agents; the helpers are CLI-only writers with `--apply`).

## Impact

A user who creates a rule with any IP or port filter is likely to have it refused by the API;
a rule created with `source_macs` is wrong in kind. No caller in `src/` uses the helpers today
(they are library surface for the ACL CLI commands' future `--apply` paths), so nothing shipped
breaks. Breaks fresh clones, CI or prod: no.

## Recommended fix

Emit `{'type': 'IP_ADDRESSES_OR_SUBNETS', 'ipAddressesOrSubnets': ips, 'portFilter': ports}`
when IPs are given and `{'type': 'PORTS', 'portFilter': ports}` when only ports are; omit empty
lists; refuse `source_macs` on an `IPV4` rule, or add a separate MAC-rule helper that requires a
network id. Update `test_create_helpers_send_the_reference_port_key` and add one test per
filter shape over the mock transport. Decision needed: whether to remove `source_macs` from the
IPv4 helpers (Breaking for library callers) or add the MAC helper.

## Decision needed

Remove `source_macs` from the IPv4 helpers, or add a `create_mac_rule` helper beside them.

## Decision and resolution (2026-10-15)

Decided by the 0.4.0 validation council (pass B, D-094, 4 of 5 seats, MODIFY): repair the IPv4
helpers in 0.4.0 and defer a MAC-rule writer to 0.5.0 rather than add writer surface during the
finishing lane. One `_typed_filter()` builds both sides for both helpers in the reference's
tagged-union shape (`IP_ADDRESSES_OR_SUBNETS` with `ipAddressesOrSubnets` and an optional
`portFilter`; `PORTS` with `portFilter` only); an empty list is never sent, and nothing given
means no filter object. `create_block_rule(source_macs=...)` raises `ValueError` before any
request. Pinned by five cases in `tests/network/test_acl_create_type.py` over the real client
and a recording transport. Not exercised live (ACL writes are off-limits to agents). Breaking
for library callers who passed `source_macs`; no shipped caller does.
