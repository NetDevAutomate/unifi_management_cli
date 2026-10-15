---
title: "The output redactor drops entries of any map keyed by a name that looks like a secret"
date: 2026-10-15
status: open, decision needed
severity: low
components: [core/utils/redact, typer_cli._emit_json, mcp results]
found_by: issue 066 fix (a real backup's report lost 27 documents)
---

# The output redactor drops entries of any map keyed by a name that looks like a secret

## Problem

`strip_secrets` removes every mapping key that `is_secret_key` matches: any key that starts
with `x_`, or contains `password`, `secret`, `token`, `authkey`, `psk`, `pre-shared`,
`passphrase`, `api_key` or `private_key` (case-insensitive), or ends in `community`,
`syslog_key` or `lcm_tracker_seed`. It also drops the `value` of a `{key|name: <secret-looking>,
value: ...}` pair. That rule is right for API objects, where the keys are schema field names.
It is wrong for a report whose mapping keys are data: names the operator or the controller
chose.

`--json` output goes through `strip_secrets` (`typer_cli._emit_json`), so an entry keyed by such
a name vanishes with no warning. Found while fixing issue 066: `backup verify` keyed its counts
by collection name, and `api_key`, `api_key_privilege`, `ssooauthtoken` and `teleport_token`
were stripped, so the JSON reported 2,513 of a real backup's 2,540 documents. 066 worked around
it for that one output, by counting those names as `other`.

A probe on 2026-10-15 shows ordinary names it would strip: `Office-Token-Ring`, `tokens`,
`secret garden`, `password_hint`, `privatekey`, `x_passphrase`. So would an SSID or network
named, for example, `IoT-PSK` or `Guest-Token`.

## Impact

Two outputs lose data; nothing else does (audit below). It is not a leak: data is removed,
never exposed. On the site this was found on, no current name matches the rule, so nothing is
lost there today. Breaks fresh clones, CI or prod: no.

## Audit (2026-10-15)

Every mapping-typed field on the package's 222 Pydantic models (54 fields, found by
introspection) and every name-keyed mapping a handler builds (found by search) was classified
by what its keys are and whether its output passes a redactor: the CLI's `_emit_json` runs
`strip_secrets` (keys removed); the MCP runner runs `mask_secrets` (values replaced by
`***redacted***`). Each affected case was then driven through the real path, over the fake
controller, with one secret-looking name beside an ordinary one.

**Affected: operator-chosen keys, and a redactor on the path.**

1. `firewall_check` -> `vlan_matrix.connectivity_matrix` (network name -> network name ->
   verdict). `diagnose firewall Office IoT-PSK --json` prints a matrix with only the `Office`
   row and only the `Office` cell in it: the `IoT-PSK` row and every `IoT-PSK` cell are gone.
   Over MCP, every value in the `IoT-PSK` row and the `IoT-PSK` cell of every other row reads
   `***redacted***`; the agent sees no verdict for the network it asked about.
2. `get_firmware_drift` -> `FirmwareDriftReport.upgradable` (device name -> the firmware the
   controller offers). Over MCP a device named `Guest-Token-AP` shows `***redacted***` where
   `Hall-AP` shows `6.6.77`. The CLI's `inventory firmware-skew --json` prints the same model
   through `inventory_cli`'s own JSON path, which has no redactor, so the CLI is unaffected.

**Operator-chosen keys, but no redactor on the path (unaffected today, fragile):**
`STPPreflightReport.required_priorities` (switch name -> priority) is written only by
`stp preflight --output`, through `model_dump_json`, and has no MCP tool; `inventory
firmware-skew --json` as above. If either path ever gains `_emit_json` or a tool, it needs the
fix below.

**Keys are controller or schema vocabulary (unaffected):** `DeviceInventoryReport.counts`,
`firmware_summary` and `model_summary` (device type, firmware version, model code);
`FirmwareDriftModel.versions` (version -> a list of device names: list items are untouched by
both rules); the `backup verify` collection names (worked around in 066); the `sources`,
`deltas` and `rates_per_minute` maps keyed by field names; the parity and MCP family maps keyed
by tool and family names.

**Keys are ids or MACs (unaffected):** `STPSnapshot.switches` and `ports` (device id; proved:
a switch named `Core-Token-Ring` survives as a value); `IntegrationPorts.devices` (MAC); every
internal `*_by_mac` and `*_by_id` map. Of the three candidates named above: `clients_by_network`
is keyed by `network_id` and never leaves `_analyze_dhcp_pools`; `by_ap` is keyed by `ap_mac`
and becomes a list of records with `ap_name`; `required_priorities` is in the fragile group.

**The pair rule has no accidental victims.** No Pydantic model or dataclass in the package has
both a `name` or `key` field and a `value` field (checked by introspection), so no report record
loses its value that way; `DNSRecordInfo` has `domain` and `value`, which the rule does not
match. The rule bites only controller objects passed through raw, which is where it belongs.

**Live site, 2026-10-15:** 16 network names, 3 SSIDs, 15 port-profile names and 12 switch
names; none matches `is_secret_key`.

## Recommended fix

The audit narrows the general reshape to the two affected outputs; the rest of the package
keys nothing a user names, or sends it through no redactor.

1. `connectivity_matrix` becomes a list of `{'source': ..., 'destination': ..., 'verdict': ...}`
   records and `upgradable` a list of `{'device': ..., 'offered': ...}` records. Neither field
   name is `key`, `name` or `value`, so neither redactor rule can touch them. This is Breaking
   for `--json` and MCP consumers of those two outputs and belongs in a minor release with a
   CHANGELOG entry.
2. The audit's six probe cases become regression tests, inverted: each secret-looking name and
   its value must survive both the CLI and the MCP path.
3. A note on `STPPreflightReport` and `FirmwareDriftReport` that their name-keyed maps must not
   be printed through `_emit_json` or an MCP tool without the same reshape.

The decision needed: accept the Breaking shape change for the two outputs in 0.4.0
(recommended: silent loss of a firewall verdict for the network the user asked about is worse
than a one-time shape change, and 0.3.0's consumers are a day old), or document the limitation
and leave both as they are.
