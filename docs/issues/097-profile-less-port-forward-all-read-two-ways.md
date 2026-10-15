---
title: "A profile-less port's own `forward: all` is honoured by one analysis and ignored by another"
date: 2026-10-15
status: resolved
resolved_by: 3b65ea8
severity: low
components: [analysis/vlan_coverage, analysis/uplink_transparency, analysis/vlan_diagnostics]
found_by: 0.4.0 lane 2b (issue 089 live check)
---

# A profile-less port's own `forward: all` is honoured by one analysis and ignored by another

## Problem

Issue 089 made the trunk rule one function, but the port table's own `forward` field is still
read two ways. `uplink_transparency` reads a port through `vlan_coverage._merge_profile_port`
(`uplink_transparency.py:27`), which keeps the port-table row's `forward`. `vlan-coverage`'s
`_running_port` (`vlan_coverage.py:389-403`) merges the same row and then deliberately drops
`forward` (`merged.pop('forward', None)`, line 403) so that only the profile's and the
override's settings decide. For a port with no profile whose port-table row says
`forward: all`, the two analyses therefore disagree: one treats it as a trunk carrying every
VLAN, the other as carrying none.

## Evidence

Live, read-only, 2026-10-15: the three standing `vlan-coverage` findings on the maintainer's
site are profile-less uplinks whose port-table row says `forward: all`, each reported as
missing all 8 VLANs. `diagnose vlans` does not flag them. The lane rated them likely false
positives.

## Impact

Low: a handful of findings on uplinks that are in fact forwarding everything, and two reports
that cannot both be right about the same port. Nothing is written. Breaks fresh clones, CI or
prod: no.

## Recommended fix

Decide whether the port-table row's `forward` is authoritative for a profile-less port (the
controller writes it from the running config, so the recommendation is yes). If yes: stop
popping `forward` in `_running_port` for profile-less ports, so `vlan-coverage` agrees with
`uplink_transparency`, and add a test with a profile-less `forward: all` row asserting both
analyses call it a trunk carrying every VLAN; the three live findings should then clear. If no:
make `uplink_transparency` drop it too, so the disagreement goes the other way, and document
why the running `forward` is not trusted.

Related, from the same check: a `forward: customize` / `tagged_vlan_mgmt: auto` profile with no
tagged ids is a trunk only by its name under both the old and the new rule; one live profile has
this shape. Record the intended reading in the same decision.

## Decision and resolution (2026-10-15)

Decided by the 0.4.0 validation council (pass B, D-097, 4 of 5 seats, MODIFY: honour the row
in both the trunk test and the carried-VLAN calculation, retaining profile and override
precedence) and verified in source by the agent; the maintainer can revert before the release
merges.

`vlan_diagnostics.running_vlan_settings(row, profile, override)` is the one place the running
VLAN settings are decided: the profile, then the override; the port table row's own VLAN
fields only when no profile applies. `diagnose vlans`, `vlan-coverage` (`_is_trunk` and
`_running_port`, so the carried VLANs too) and `foreign-bridges` all read it, so issue 089's
one-rule invariant holds; `foreign-bridges` names a profile-less running trunk `port table`.
Under a profile the row's copy of `forward` is still ignored, because a live controller reports
`forward: 'all'` on rows under access profiles.

Pinned by `tests/analysis/test_vlan_profile_less_forward.py` (the function's precedence; a
profile-less `forward: all` row is a trunk carrying every VLAN for all three analyses while the
access-profile and override cases are not; a profile-less `forward: all` uplink is not reported
missing every VLAN) and the shared fixture in `tests/analysis/test_vlan_trunk_rule.py`, whose
profile-less port is now a trunk for every analysis.

What a user sees: on the maintainer's site, read-only, `diagnose vlans` names 64 trunks where it
named 43, and `analyze vlan-coverage` audits 47 ports where it audited 39 and reports 1 finding
where it reported 3; the three that cleared were the profile-less uplinks this issue describes.
The `customize`/`auto` profile with no tagged ids stays a trunk only by its name under both the
old and new rule; the name is not taken as proof of forwarding.
