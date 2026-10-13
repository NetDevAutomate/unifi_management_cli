---
title: "`vlan_diagnostics` and `mac_analyzer` read a raw `portconf_id` as if it were a profile name"
date: 2026-10-03
status: resolved
resolved_by: b3732d8
severity: low
components: [analysis/mac_analyzer, analysis/vlan_diagnostics]
found_by: review follow-ups (issue 026)
---

# `vlan_diagnostics` and `mac_analyzer` read a raw `portconf_id` as if it were a profile name

## Problem

Issue 026 routed every analysis that picks a port's profile through
`link_settings.effective_profile_id`. Two modules still read a `portconf_id` themselves,
not to pick a profile but as if the id were the profile's name:

- `analysis/vlan_diagnostics.py` (MCP `diagnose_vlans`) builds its port list from
  `port_overrides` only, so ports without an override are never audited, and stores the
  override's raw `portconf_id` (or `'Default'`) as `profile_name`. Trunk detection then
  tests `'trunk' in profile_name.lower() or 'all' in profile_name.lower()`; a `portconf_id`
  is a 24-character hex id, which can contain neither, so a port is a trunk only through
  its tagged VLANs. The port-consistency check groups ports by that id and reports ids,
  not profile names.
- `analysis/mac_analyzer.py::_is_trunk_port` makes the same substring test on the port
  table's `portconf_id`, so it never matches either.

`tests/analysis/test_link_settings.py::test_only_link_settings_resolves_a_portconf_id`
allowlists both modules by name, citing this issue.

## Impact

`diagnose_vlans` can miss trunk ports, so its trunk-coverage check sees fewer trunks than
exist and its consistency findings name ids a reader has to look up. `mac_analyzer`'s trunk
flag depends only on tagged VLANs. Nothing writes; it doesn't break clones, CI or
production.

## Recommended fix

Resolve each port's profile with `effective_profile_id(device, port_entry, port_idx)`, look
it up in `rest/portconf` and judge trunk-ness from the profile's `forward` (and
`tagged_vlan_mgmt`, as `foreign_bridges._is_trunk` does) and its `name`; audit every switch
port, not only overridden ones; report the profile name. Then remove both modules from
`READS_A_PROFILE_ID` in `tests/analysis/test_link_settings.py`.

## Decision needed

The fix changes `diagnose_vlans` output (more ports audited, names instead of ids, trunk
findings that were missed) and the MAC analysis' trunk flag, so confirm before landing it.

## Resolution

Resolved on 2026-10-13 (`b3732d8`), as recommended; the decision taken is to land the output
change. `diagnose_vlans` (`analysis/vlan_diagnostics.py`) reads `rest/portconf` as a third
read and delegates to the pure `diagnose_vlans_from_data(networks, devices, port_profiles)`.
`mac_analyzer.analyze_mac_table` reads `rest/portconf` too and `_is_trunk_port` resolves the
profile the same way. Both modules are out of `READS_A_PROFILE_ID` in
`tests/analysis/test_link_settings.py`.

What changed in the output, exactly:

1. **Every switch port is audited**, not only ports with an override. `port_configs` grows
   to one row per `port_table` entry. Live, same site, same hour: 75 rows became 97.
2. **`profile_name` is the profile's name** (`rest/portconf` `name`), resolved through
   `link_settings.effective_profile_id` (the override's id wins, else the port table's). A port
   whose id matches no profile keeps the raw id visible; a port with no id is `Default`. Live:
   15 distinct raw ids (UUIDs on this controller, not 24-hex) became 14 profile names plus
   `Default`. The `Port Profile Consistency` check's `inconsistent_profiles` lists names too.
3. **Trunk-ness** is `is_trunk_profile` on the profile merged with the override: `forward:
   'all'` unless `tagged_vlan_mgmt: 'block_all'` (the `foreign_bridges._is_trunk` rule),
   `forward: 'customize'` with at least one tagged network, or `trunk` in the name; a port
   with tagged VLANs is a trunk as before. Live: 0 trunks became 42.
4. **`native_vlan` and `tagged_vlans` follow the resolved settings**, the override's own
   fields (`native_networkconf_id`, `tagged_networkconf_ids`, `excluded_networkconf_ids`,
   `voice_networkconf_id`, `forward`, `tagged_vlan_mgmt`) on top of the profile's. On `auto`
   a trunk tags every configured VLAN minus the excluded networks; on `custom` the listed
   networks; the voice VLAN is added; the native VLAN is never listed as tagged. Before, a
   port's `tagged_vlans` could hold only its voice VLAN.
5. **`Trunk VLAN Coverage`** therefore judges real trunks. Live: `WARNING: No trunk ports
   detected` became `PASS: All VLANs covered on 42 trunk ports`. The other three checks gave
   the same verdicts before and after.
6. **`analyze_mac_table`**'s `is_trunk` per port comes from the resolved profile, so a trunk
   that learns many MACs is no longer an `exceeds_threshold` access port. Not observable live
   on this site: the controller's `stat/device` records carry no `mac_table`, so the analysis
   sees no MACs before or after (reported separately).

Tests: `tests/analysis/test_vlan_diagnostics.py` (every port audited, names not ids, the
override wins, trunk-ness from `forward`/`tagged_vlan_mgmt`, native and tagged VLANs from the
resolved settings and from an override, the consistency check naming a profile, a
forward-all trunk covering every VLAN, an unknown id kept visible, the read set through the
fake controller) and `tests/analysis/test_mac_analyzer_trunks.py` (a trunk by profile is not an
overloaded access port; `rest/portconf` is read; only GETs).

Deliberately not changed: the four checks' rules and wording, `VLANInfo` parsing, and the
`PortVLANConfig` model. `is_trunk_profile` lives in `vlan_diagnostics` and is imported by
`mac_analyzer`; `foreign_bridges._is_trunk` and `vlan_coverage` keep their own copies of the
rule for now (a consolidation is noted for the coordinator).
