---
title: "A UXG gateway is classified as an access point in every diagram format"
date: 2026-10-13
status: resolved
resolved_by: 262eea1
severity: medium
components: [enhanced_network_topology]
found_by: the 0.3.0 CLI lane (issue 044)
---

# A UXG gateway is classified as an access point in every diagram format

## Problem

`enhanced_network_topology.py` `_determine_device_type` (line ~877) matches model names against
pattern lists; `'xg'` is in the access-point list (line ~928) and the router list has no `uxg`
entry, so a UXG model matches the AP pattern first.

## Impact

On a UXG site the gateway is coloured, grouped and placed as an AP in the PNG, SVG, HTML, DOT
and Mermaid diagrams, and in any topology summary that counts device types.

## Recommended fix

Add `uxg` (and `uxg-` prefixes) to the router patterns and check routers before access points;
pin with a fixture that has a UXG and a U6 model.

## Resolution (2026-10-15)

`_determine_device_type` now has `uxg` in its gateway patterns, still checked before the
switch and access-point patterns, and the switch patterns gain `usf` (the USW Flex model
codes, `USF5P` and `USFXG`) and `us6xg` (US-XG-6POE). The loose AP pattern `xg` stays, for
the UAP-XG, but no gateway or switch reaches it. The same `xg` pattern had also drawn the
USW Flex XG (`USFXG`) as an access point; on the maintainer's site all three Flex XGs were.

The HTML page classifies with `is_router`, `is_switch` and `is_unifi_device`, not
`_determine_device_type`: `uxg` joins the router and UniFi words (a UXG was left off the
page), and `usf` the switch and UniFi words (a Flex XG whose name lacks "USW" was left off).
The `diagram` command also dropped stat/device type `uxg` before drawing; it now keeps it,
reads its LLDP and counts it as a router.

Pinned by `tests/test_enhanced_network_topology_device_type.py` (UXG model codes, the live
site's gateway, switch and AP models, a UXG and a U6 in the DOT layers and the Mermaid data,
the HTML classifiers) and
`tests/cli/test_diagram_command.py::test_diagram_draws_a_uxg_gateway_as_the_gateway`.

A user on a UXG site sees the gateway in the gateway layer and colour in every format, and
the HTML page shows it; a Flex XG is drawn as a switch. `discover` still keeps only types
`ugw`, `usg`, `udm`, `usw` and `uap` when it builds its topology, so a UXG is absent from the
diagram `discover` draws until that filter learns `uxg` too.
