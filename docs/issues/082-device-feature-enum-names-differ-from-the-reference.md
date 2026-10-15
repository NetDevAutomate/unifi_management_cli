---
title: "`DeviceFeature` uses `SWITCH`/`ROUTER` names the Integration API does not send"
date: 2026-10-13
status: resolved
resolved_by: 7ab0e60
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

## Resolution (2026-10-15)

`DeviceFeature` is re-keyed to the reference's feature names: `SWITCHING = 'switching'`,
`ACCESS_POINT = 'accessPoint'`, `GATEWAY = 'gateway'`, the three values the v10.6.102 OpenAPI
lists for a device's `features`. `SWITCH` and `ROUTER` remain as enum aliases of `SWITCHING`
and `GATEWAY`, so code that names them keeps working and now matches a live device.
`PROTECT` and `TALK` are removed, because the API sends no such feature.

The "four references" are the definition, the package's import, its `__all__` entry and the
mention in issue 036's record. No comparison against the enum exists in the code, so none
needed rerouting through `feature_names`.

Pinned by `TestDeviceFeatureEnum` in `tests/network/test_models_reference.py`: the members are
the reference names, a member matches a live device in either `features` shape, and the old
names resolve to the new members.

What a user sees: `DeviceFeature.SWITCHING in device.feature_names` (or `DeviceFeature.SWITCH`)
is true for a live switch. A caller that compared against the old string values (`'SWITCH'`)
or used `PROTECT` / `TALK` must change; those never matched a live device.
