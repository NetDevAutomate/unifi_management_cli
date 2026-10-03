---
title: "`vlan_diagnostics` and `mac_analyzer` read a raw `portconf_id` as if it were a profile name"
date: 2026-10-03
status: open, decision needed
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
