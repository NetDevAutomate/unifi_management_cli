---
title: "The trunk-port rule is written three times and can disagree"
date: 2026-10-13
status: open
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
