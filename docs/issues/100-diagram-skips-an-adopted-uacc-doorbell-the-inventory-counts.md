---
title: "`diagram` skips an adopted `uacc` doorbell that `inventory` counts as an access point"
date: 2026-10-15
status: open, decision needed
severity: low
components: [core/device_types, analysis/device_inventory, run_methods]
found_by: 0.4.0 issue 096 live check
---

# `diagram` skips an adopted `uacc` doorbell that `inventory` counts as an access point

## Problem

`device_inventory.py:72` classes a device of type `uacc` (a UniFi Access doorbell, model prefix
`UACC`) as an access point, so `inventory` reports 11 access points on the maintainer's site.
`run_methods.py:462` draws only the devices whose type is in `NETWORK_DEVICE_TYPES`
(`core/device_types.py`: gateways, `usw`, `switch`, `uap`), so `diagram` draws 10. The two
commands disagree about what the site contains.

## Evidence

Live, read-only, 2026-10-15 (issue 096's check): 11 access points in `inventory`, 10 access
points in the diagram; the one missing is the `uacc` device. It is an adopted device with an
uplink record, wired over PoE.

## Impact

Cosmetic but visible: a device the inventory lists is absent from the topology. No analysis
reads it (it has no port table and no clients of its own).

## Decision needed

Whether `diagram` should draw a doorbell at all. Recommended: yes, as a leaf device beside the
access points, because it is an adopted, wired device with an uplink and the inventory already
counts it; add `uacc` to `NETWORK_DEVICE_TYPES` (one line plus a test) and give it its own icon
class rather than the AP one so the diagram does not call it an access point. The alternative is
to stop `inventory` counting it as an access point. Either way the two commands should agree.
0.5.0.
