---
title: "The ONVIF scripts hard-code the site's cameras, and `onvif_stream.py` a camera password"
date: 2026-10-04
status: open, decision needed
severity: high
components: [scripts/onvif_stream.py, scripts/onvif_probe.py]
found_by: docs and repo hygiene review (privacy scan)
---

# The ONVIF scripts hard-code the site's cameras, and `onvif_stream.py` a camera password

## Problem

- `scripts/onvif_stream.py` defines its `CAMERAS` list in the source, and each entry carries
  the cameras' ONVIF password as a literal. It is not a placeholder. It has been in the file
  since `5564879` and is on `origin/main`.
- `scripts/onvif_stream.py` and `scripts/onvif_probe.py` also hard-code the cameras' real
  addresses and names.

The AXIS provisioning guide shows placeholders and tells the user to edit the list before
running, but the committed lists are the live ones.

## Impact

Anyone with a copy of the repository, or of its history, has the password of that ONVIF
account. If the password is reused elsewhere the exposure is wider. The addresses and names
describe the site's camera network. Nothing breaks for fresh clones or CI.

## Decision needed

Recommendation, in this order:

1. User action: change that ONVIF account's password on the cameras now. It is in the
   pushed history, so removing it from the file alone doesn't help.
2. Make both scripts read their camera list from a file outside the repo (the AXIS
   provisioning config `~/.config/axiscam/config.yaml`, which `scripts/axis_provision.py`
   already reads, has a name and an address per device and the ONVIF users) or from the
   environment, and keep only placeholders in the repo.
3. Decide whether to rewrite the history. That is the user's call: the repository is
   already pushed, and a rewrite needs a force-push.

Why this needs a decision: step 2 changes how both scripts are run, and steps 1 and 3 are
actions only the user can take.
