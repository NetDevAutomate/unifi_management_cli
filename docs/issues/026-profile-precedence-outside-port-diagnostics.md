---
title: "validate_port_profiles and three other analyses resolve a port's profile without the override precedence"
date: 2026-10-03
status: open, decision needed
severity: medium
components: [analysis/port_profile_validation, analysis/foreign_bridges, analysis/uplink_transparency, analysis/vlan_coverage, analysis/link_settings]
found_by: MCP uvx standards work (semantic review finding 6 / code-review F9)
---

# validate_port_profiles and three other analyses resolve a port's profile without the override precedence

## Problem

`analysis/link_settings.effective_profile_id` is the controller's precedence: a
`port_overrides` entry's `portconf_id` wins over the `port_table` entry's, because the
override is what the controller pushes. The port-diagnostics family (`ports inspect`,
`collect_override`, `summarise_ports`, `profile_usage`, `audit_link_speeds`,
`audit_port_profile_usage`) uses it. Four older analyses don't:

- `port_profile_validation._profile_id_for_port` (MCP `validate_port_profiles`) returns the
  port table's `portconf_id` first and reads the override only when the table has none: the
  reverse precedence.
- `foreign_bridges`, `uplink_transparency` and `vlan_coverage` read only the port table's
  `portconf_id` and never `port_overrides`.

On the UGREEN fixtures (`tests/fixtures_unifi.py`, modelled on the live collection: override
= the forced 10Gbps profile, port table = Auto), `validate_port_profiles` judges port 5 on
'USW Flex XG' by the Auto profile while the switch runs the forced 10Gbps one.
`tests/analysis/test_link_settings.py::test_validate_port_profiles_uses_the_effective_profile_for_port_5`
pins the divergence as a strict xfail.

## Impact

`validate_port_profiles` (which `audit_port_profile_usage` says it complements) can report
STP-edge/BPDU-guard findings against the wrong profile for any overridden port, including
the port under the open support case. The other three can attribute a port to the wrong
profile or VLAN set. It doesn't break fresh clones, CI or production; the code predates the
MCP uvx work.

## Recommended fix

Route all four through `effective_profile_id(device, port_entry, port_idx)` and drop the
private resolvers. Remove the xfail marker, and narrow the `link_settings` module docstring
back to "every caller".

## Decision needed

The fix changes what `validate_port_profiles`, `analyze foreign-bridges`, the uplink
transparency audit and the VLAN coverage audit report for overridden ports. That is the
intended correction, but it is a visible output change, so confirm before landing it.
