---
title: "`DeviceFeature` uses `SWITCH`/`ROUTER` names the Integration API does not send"
date: 2026-10-13
status: open
severity: low
components: [network/models]
found_by: the 0.3.0 Integration API lane (issue 036)
---

# `DeviceFeature` uses `SWITCH`/`ROUTER` names the Integration API does not send

## Problem

`network/models.py` `DeviceFeature` enumerates `SWITCH`, `ROUTER`, `ACCESS_POINT`; the
reference's feature names are `switching`, `gateway`, `accessPoint`, which issue 036 taught
`DeviceInfo.feature_names` and the `is_*` properties to use. The enum is still referenced in
four places outside the model.

## Impact

A caller comparing `DeviceInfo.features` to a `DeviceFeature` member never matches a live
device; the four remaining references are dead comparisons waiting to mislead.

## Recommended fix

Re-key the enum to the reference's names (`SWITCHING = 'switching'`, ...) and route the four
references through `feature_names`; or delete the enum if the four sites can use the string
names directly. Pin with a test over the 036 fixtures.
