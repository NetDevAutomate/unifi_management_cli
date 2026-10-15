---
title: "ACL create helpers send filters without a `type` and with empty lists the API refuses"
date: 2026-10-15
status: open, decision needed
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
