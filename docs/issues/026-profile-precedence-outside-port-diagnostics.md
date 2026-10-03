---
title: "validate_port_profiles and three other analyses resolve a port's profile without the override precedence"
date: 2026-10-03
status: resolved
resolved_by: 865d417
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

## Resolution

Approved as a bug fix: the design has one precedence rule, and these four analyses were the
callers that hadn't adopted it.

- `port_profile_validation` picks the profile with `effective_profile_id(device, port,
  port_idx)` (ports with no profile id are still skipped); `_profile_id_for_port` is gone.
- `foreign_bridges._locate_bridge`, `uplink_transparency.audit_uplink_transparency_from_data`
  and `vlan_coverage.audit_vlan_coverage_from_data` look the profile up by
  `effective_profile_id` instead of the port table's `portconf_id`. Field-level merging
  (`_merge_profile_port`) is unchanged.
- The alternate keys the old resolvers also read (`port_conf_id` on either side, and
  `profile_id` on the port) are dropped with them: the precedence rule reads only
  `portconf_id`, which is what the controller sends.
- The `link_settings` module docstring says every caller that picks a port's profile uses
  the helper again, and names the two modules that still read an id for another purpose
  (issue 030).

Tests: one override-precedence case per analysis (`test_port_profile_validation.py`,
`test_foreign_bridges.py`, `test_uplink_transparency.py` ×2, `test_vlan_coverage.py`); in
`test_link_settings.py` the strict xfail is now a plain test on the UGREEN fixture (port 5 is
judged by the 10Gbps override, not the Auto port table), the docstring test checks every
caller is named, and `test_only_link_settings_resolves_a_portconf_id` AST-scans
`src/unifi_mapper` and fails if any module other than `link_settings`, `port_diagnostics`
(`collect_override` reports both raw ids) and the two issue-030 modules reads a
`portconf_id` itself. All eight failed on the old code.

Live evidence (read-only, guarded, 25 audited GETs per run, no violations): the four
analyses were replayed on one snapshot with the old and the new code, and run live before and
after. The snapshot had 81 ports with an override `portconf_id`, 0 of them differing from the
port table's (port 5 on `USW Flex XG` included), and no port used the dropped keys; replay
verdict PASS with no changed finding or aggregate, and no live change either. The fix
therefore changes nothing on today's network; it matters while an override's profile hasn't
been applied, as in the fixtures. Evidence: `.kiro/review-followups/issue-026/diff.md`
(git-ignored).
