---
title: "The output redactor drops entries of any map keyed by a name that looks like a secret"
date: 2026-10-15
status: resolved
resolved_by: cafbb13
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

## Decision (2026-10-15)

Andy, verbatim: "Yes, reshape the two outputs in 0.4.0".

What that binds: the recommended fix above is the fix, in 0.4.0, as lane 3 of the release
plan. `connectivity_matrix` becomes a list of `{source, destination, verdict}` records and
`upgradable` a list of `{device, offered}` records; the six audit probe cases become
regression tests, inverted; the two fragile maps get their note. The change is recorded under
Breaking in the CHANGELOG, because `--json` and MCP consumers of `diagnose firewall` /
`firewall_check` and `get_firmware_drift` see a new shape. The issue stays open until that
lands and is resolved with the fix hash. The alternative (document the limitation) is closed.

## Resolution (2026-10-15)

Both outputs are reshaped, as decided; the redactor's behaviour is unchanged. Two commits:
`089db7f` (the firewall matrix) and `cafbb13` (the firmware drift report).

1. `firewall_check` -> `vlan_matrix.connectivity_matrix` is a list of
   `{'source': ..., 'destination': ..., 'verdict': ...}` records, one per ordered pair of
   networks, in the order the controller lists them. It was a map keyed by source network
   name of maps keyed by destination name. Affects the MCP tool `firewall_check` and
   `diagnose firewall --json`; the Mermaid firewall-matrix renderer reads the records.
2. `FirmwareDriftReport.upgradable` is a list of `{'device': ..., 'offered': ...}` records
   (`FirmwareUpgradeOffer`), one per kept device the controller offers an upgrade, in
   inventory order (by type, then name). It was a map of device name -> offered firmware.
   Affects the MCP tool `get_firmware_drift` and `inventory firmware-skew --json` (the CLI
   path has no redactor and lost nothing, but prints the same model). The per-device boolean
   `upgradable` on inventory rows is unchanged.

No record has a `key`, `name` or `value` field, so neither the key rule nor the pair rule can
reach a name. `FirmwareDriftModel.versions` stays a map, with a comment that its keys are
firmware versions (controller vocabulary), and `core/utils/redact.py` gains a module note: a
report must not key a mapping by a name the operator or the controller chose.

The audit's six probe cases are regression tests in `tests/test_issue_091_regressions.py`,
inverted and over the fake controller: `inventory firmware-skew --json`; `get_firmware_drift`
through the real MCP runner on both surfaces (`Guest-Token-AP` keeps `6.6.77`, where it read
`***redacted***` before); `diagnose firewall Office IoT-PSK --json` (the `IoT-PSK` row and
cells are present, where the CLI printed only `Office` before); `firewall_check` through the
runner on both surfaces (no verdict reads `***redacted***`); the STP snapshot (keyed by device
id, already safe, kept as a guard); and the pair rule, now asserted against both record shapes
(both redactors leave them untouched) while a controller `{name: <secret>, value: ...}` pair
still loses its value. `tests/utility/test_render_mermaid_firewall.py` pins the renderer on
the records.

What a user sees differently: `--json` and MCP consumers of `diagnose firewall` /
`firewall_check` and `get_firmware_drift` / `inventory firmware-skew` get lists of records in
place of the two maps, and a network or device whose name looks like a secret keeps its
verdict or its offered version. On the live site, read-only: `diagnose firewall 1 1 --json`
returns 256 records for 16 networks (16 x 16, nothing dropped); `inventory firmware-skew
--json` analyses 24 devices and returns an empty `upgradable` list (no upgrade offered today).

Still fragile, outside this fix: `STPPreflightReport.required_priorities` (switch name ->
priority) is keyed by operator-chosen names and passes no redactor today (`stp preflight
--output` writes `model_dump_json`; there is no MCP tool). It needs the same reshape before
either path gains `_emit_json` or a tool.
