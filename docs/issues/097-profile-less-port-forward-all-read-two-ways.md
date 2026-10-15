---
title: "A profile-less port's own `forward: all` is honoured by one analysis and ignored by another"
date: 2026-10-15
status: open, decision needed
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
