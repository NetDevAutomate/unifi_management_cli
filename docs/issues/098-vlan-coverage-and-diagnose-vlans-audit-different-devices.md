---
title: "`vlan-coverage` audits any device with a port table while `diagnose vlans` reads switches only"
date: 2026-10-15
status: open
severity: low
components: [analysis/vlan_coverage, analysis/vlan_diagnostics]
found_by: 0.4.0 issue 097 live check
---

# `vlan-coverage` audits any device with a port table while `diagnose vlans` reads switches only

## Problem

Issues 089 and 097 made the three VLAN analyses apply one rule to a port's settings. They still
disagree about WHICH devices to read. `vlan_coverage._is_switch_like` (`vlan_coverage.py:140`)
accepts `usw`, `switch`, `udm`, `udmpro` and any device with a `port_table`, so an access point
with switch ports (a U6 In-Wall) is audited. `diagnose_vlans_from_data`
(`vlan_diagnostics.py:155`) reads `usw` and `switch` only. A finding on an AP's port therefore
appears in `vlan-coverage` and can never be cross-checked in `diagnose vlans`.

## Evidence

Live, read-only, 2026-10-15, after the 097 fix: `analyze vlan-coverage` reports one finding, an
in-wall AP's `PoE In + Data` port missing every required VLAN; `diagnose vlans --json` lists no
port for that device (0 of its ports in `port_configs`). Whether the AP's uplink port actually
carries tagged VLANs is not knowable from its row the way a switch port's is (AP port tables
do not carry the switch profile fields), so the finding may be a false positive of a new class.

## Impact

Low: one finding on the maintainer's site; a user with several in-wall or mesh APs with switch
ports sees coverage findings they cannot verify with `diagnose vlans`. Nothing is written.
Breaks fresh clones, CI or prod: no.

## Recommended fix

Decide the device scope once and share it (a `vlan_devices()` selector beside
`running_vlan_settings`), then either audit APs with switch ports in both analyses, reading
their VLAN state from the fields an AP row actually carries (needs a read-only capture of one
AP's `port_table` row), or exclude them from `vlan-coverage` with a one-line note in the report
saying how many AP ports were skipped. The capture decides which; until then the finding
stays, labelled by device type in the report so a reader can tell it apart.
