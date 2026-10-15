---
title: "The trunk-port rule is written three times and can disagree"
date: 2026-10-13
status: resolved
resolved_by: e5d4f23
severity: low
components: [analysis/vlan_diagnostics, analysis/foreign_bridges, analysis/vlan_coverage]
found_by: the 0.3.0 analysis lane (issue 030)
---

# The trunk-port rule is written three times and can disagree

## Problem

`vlan_diagnostics.is_trunk_profile` (line ~234, new in issue 030 and used by `mac_analyzer`),
`foreign_bridges._is_trunk` (line ~161) and `vlan_coverage._is_trunk` / `_carried_vlans` /
`_merge_profile_port` (lines ~210, 256, 371) each decide trunk-ness from `forward`,
`tagged_vlan_mgmt` and the tagged networks with slightly different rules. Separately,
`vlan_traffic_store.coverage` (line ~908) sizes its gap check with the fixed
`DEFAULT_SAMPLE_INTERVAL_SECONDS` while the 072 rate bound uses the measured grace, so
`coverage` can count a gap that `report` still rates.

## Impact

Two reports can call the same port a trunk and an access port; a coverage figure and a rate
figure can disagree about the same interval.

## Recommended fix

One `is_trunk_profile` in a shared module (`analysis/link_settings` already holds shared port-
settings helpers) used by all three, with the existing tests of each caller kept; `coverage` to
use `_measured_grace` like `report`.

## Resolution (2026-10-15)

Two fix commits: `bf46966` (the trunk rule) and `e5d4f23` (the coverage grace).

**One trunk rule.** `vlan_diagnostics.is_trunk_profile` is the rule, documented step by
step; `foreign_bridges` and `vlan_coverage` call it over the same settings `diagnose vlans`
reads (the profile with its override on top), and the `diagnose vlans` caller's extra
"tags a VLAN" test is folded into it. It keeps every answer the old function's tests pinned
and takes `vlan_coverage`'s hand-built shapes (`is_trunk` / `is_access` flags, VLAN lists,
access or client names) when a record has no `forward`. Where the old rules disagreed,
`forward: 'all'` wins over a name that says access, a `forward` decides over a bare VLAN
key, and `block_all` tags nothing even when `tagged_networkconf_ids` linger.

`vlan_coverage` also reads the VLANs a trunk carries from the settings the port runs: the
port table's own `forward` is not used (a live controller reports `forward: 'all'` on 100
port-table rows under access profiles), and a `forward: 'all'` trunk carries every VLAN, as
`diagnose vlans` says. `_merge_profile_port` is unchanged, because `uplink_transparency`
imports it.

Pinned by `tests/analysis/test_vlan_trunk_rule.py`: every shape the three rules accepted
with its one answer, and a live-shaped switch on which `diagnose vlans`, `analyze
vlan-coverage` and `analyze foreign-bridges` name the same trunks.

On the live site `diagnose vlans` is unchanged (8 VLANs, 97 ports, the same 43 trunks, 2
issues, 1 warning); `analyze vlan-coverage` now audits 39 ports instead of 13 (every trunk
that is up) with the same 3 findings; `analyze foreign-bridges` is unchanged.

**One gap bound.** `read_vlan_traffic_periods` now sizes the raw tier's gap check with the
measured grace (`_measured_grace`), so its cutoff is `max_measured_interval`, the bound
`read_vlan_traffic_report` rates a pair of samples by. Before, it used the fixed default
interval (a 360 s cutoff), so at a 5-minute cadence an 800 s interval was rated by `report`
and counted as a gap by `coverage`. The hourly and daily tiers are unchanged.

Pinned by `tests/analysis/test_vlan_traffic_coverage_grace.py`: a store at a 5-minute
cadence with one 800 s interval (rated, no gap) and one with a 1000 s interval (not rated,
one gap); `report` and `coverage` agree in both.

A user sees `vlan-traffic coverage` count only the gaps `vlan-traffic report` also refuses to
rate, and the three VLAN analyses call the same port the same thing.
