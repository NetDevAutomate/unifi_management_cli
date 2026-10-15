---
title: "A UXG gateway is classified as an access point in every diagram format"
date: 2026-10-13
status: open
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
