---
title: "Integration API models disagree with the v10.6 reference, so some fields are lost"
date: 2026-10-03
status: open
severity: low
components: [network/models, network/acl, network/dns]
found_by: review follow-ups (checking the models against the reference)
---

# Integration API models disagree with the v10.6 reference, so some fields are lost

## Problem

Checking the models behind issues 031–033 against Ubiquiti's Network API reference for
v10.6.102 turned up more drift. None of it fails today's MCP tools, but each item either
drops data or would fail validation:

- `DeviceInfo.state` is the `DeviceState` enum (`CONNECTED`, `DISCONNECTED`, `PENDING`, …),
  but the reference sends `ONLINE`, `OFFLINE`, `PENDING_ADOPTION`, `UPDATING` and others.
  The first device would fail validation and empty `list_devices`, as in issue 033.
- `DeviceInfo.features` and `interfaces` are `list[str]`. The device list sends lower-camel
  values (`switching`, `accessPoint`, `gateway`), so `is_switch`, `is_router` and
  `is_access_point`, which test `SWITCH`, `ROUTER`/`GATEWAY` and `ACCESS_POINT`, are never
  true. The device details send both fields as objects, so `get_device` would fail.
- `ACLTrafficFilter.ports_filter` reads `portsFilter`; the reference's key is `portFilter`,
  so a rule's ports are silently dropped. `ACLRule.origin` reads a top-level `origin`; the
  reference nests it as `metadata.origin` (`USER_DEFINED`, `DERIVED`), so
  `ACLManager.get_user_rules`, `get_system_rules` and the summary's user/system split never
  match.
- DNS policy types are `A_RECORD`, `AAAA_RECORD`, `CNAME_RECORD`, `MX_RECORD`, `TXT_RECORD`,
  `SRV_RECORD` and `FORWARD_DOMAIN` in the reference, but `DNSPolicyManager` counts `A`,
  `AAAA`, … (so every policy lands in `other_records`), and `create_a_record` and
  `create_aaaa_record` send `type: A`/`AAAA`.

## Evidence

- The reference: Ubiquiti's Network API OpenAPI document for v10.6.102, downloaded from
  developer.ui.com (kept locally, not in the repo).
- Live, in the read-only live checks and the device-statistics probe recorded at `d6d013f`
  (local evidence, not in the repo): the port diagnostics' Integration API device details
  carry `state: ONLINE` and `features` and `interfaces` as objects; the device list's
  `features` for an access point is `["accessPoint"]`.

## Impact

Today, nothing visible: no MCP tool or CLI reads devices through this client, and this
console has no ACL rules and no DNS policies. Once rules exist, `get_acl_rules` returns them
without their port filters or origin, and library callers of the device, ACL and DNS
managers get wrong or failing results. It doesn't break fresh clones or CI.

## Recommended fix

Align each model with the reference, with fixture tests built from its examples: tolerant
enums for `DeviceState` (as issue 033 did for client types), the reference's `features` and
`interfaces` shapes, `portFilter`, `metadata.origin`, and the `*_RECORD` DNS types in both
the manager's counts and its create helpers. The tool output gains or renames fields, so
note it in the change.
