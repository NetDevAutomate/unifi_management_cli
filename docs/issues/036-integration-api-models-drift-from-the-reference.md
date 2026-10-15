---
title: "Integration API models disagree with the v10.6 reference, so some fields are lost"
date: 2026-10-03
status: resolved
resolved_by: befe82a
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
- Live, in the read-only live checks and the device-statistics probe recorded at `85551d1`
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

## Resolution

Resolved on 2026-10-13 (`befe82a`), item by item as recommended. The reference text itself
is not in the repo, so each change is pinned to what this issue quotes from it and to the
in-repo fixtures that were built from it (`tests/mcp/test_network_tool_payloads.py`'s
`ACL_RULE` and `DNS_POLICY`, `tests/fixtures_unifi.integration_routes`' device detail).

- `DeviceState` gains `ONLINE`, `OFFLINE`, `PENDING_ADOPTION` and `UPDATING`, and
  `DeviceInfo.state` is `Annotated[DeviceState | str, Field(union_mode='left_to_right')]`
  as issue 033 did for client types: a known state is the member, an unknown one is kept as
  sent, so one new state cannot empty `list_devices`. The older members (`CONNECTED`,
  `DISCONNECTED`, `PENDING`, `ADOPTING`, `PROVISIONING`, `UPGRADING`, `UNKNOWN`) are kept
  for callers that compare against them; whether any release sends them is unverified.
- `DeviceInfo.features` is `list[str] | dict[str, Any]` and `interfaces` is
  `list[str] | DeviceInterfaces`, so the list's names and the detail's objects both
  validate. `feature_names` gives the names from either shape, and `is_switch`,
  `is_router` and `is_access_point` test the reference's `switching`, `gateway` and
  `accessPoint` (the old `SWITCH`/`ROUTER`/`GATEWAY`/`ACCESS_POINT` checks are gone).
  `DeviceInterfaces.ports` is a list of `DevicePortInterface` with the five fields the port
  diagnostics read live (`idx`, `state`, `connector`, `maxSpeedMbps`, `speedMbps`); both
  models keep any other key in `model_extra` rather than drop it.
- `ACLTrafficFilter.port_filter` reads and writes `portFilter`; `ACLManager`'s create
  helpers send that key.
- `ACLRule.metadata` (`ACLRuleMetadata.origin`, tolerant over the new `ACLRuleOrigin`:
  `USER_DEFINED`, `DERIVED`) replaces the top-level `origin` field; `ACLRule.origin` is now
  a property through it, and `get_user_rules`, `get_system_rules` and the summary's split
  compare against `USER_DEFINED` and `DERIVED`.
- `DNSRecordType` is `A_RECORD`, `AAAA_RECORD`, `CNAME_RECORD`, `MX_RECORD`, `TXT_RECORD`,
  `SRV_RECORD`, `FORWARD_DOMAIN`; `DNSPolicyManager.get_summary` counts those names and
  `create_a_record`/`create_aaaa_record` send them. `FORWARD_DOMAIN` has no counter of its
  own and lands in `other_records` (the summary's shape is unchanged).

Tool output: `get_acl_rules` records now carry `metadata: {origin: ...}` and
`sourceFilter`/`destinationFilter` carry `portFilter`; the always-empty top-level `origin`
and the never-filled `portsFilter` are gone.

Not verified, left as is: the shape *inside* the detail's `features` object (the issue says
only that it is an object; the model keeps it as a `dict` and treats a key with a null value
as a feature the device lacks, which is the safer reading either way); whether `interfaces`
carries keys beyond `ports` (kept via `model_extra` if so); the detail's full port fields
beyond the five the diagnostics read; and `DNSPolicy.metadata`, which the `DNS_POLICY`
fixture shows but this issue does not list. `DeviceFeature` (`SWITCH`, `ROUTER`, ...) is
unused in `src` and untouched.

Tests: `tests/network/test_models_reference.py` (23 fixture tests from the quoted
examples); `tests/network/test_models.py`, `test_acl.py` and `test_dns.py` moved from the
old spellings to the reference's.
