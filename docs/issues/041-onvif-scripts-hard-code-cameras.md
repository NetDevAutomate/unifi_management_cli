---
title: "The ONVIF scripts hard-coded the site's cameras, and `onvif_stream.py` a camera password that is in pushed history"
date: 2026-10-04
status: open, decision needed
severity: high
components: [scripts/onvif_stream.py, scripts/onvif_probe.py, history]
found_by: docs and repo hygiene review (privacy scan)
---

# The ONVIF scripts hard-coded the site's cameras, and `onvif_stream.py` a camera password that is in pushed history

## Status

- Fixed at HEAD by `15b0f60`. Neither script keeps a camera address, name or credential in
  the source any more. Both read `ONVIF_USERNAME`, `ONVIF_PASSWORD` and `ONVIF_CAMERAS`
  through `scripts/onvif_config.py`, and stop before they connect to any camera if one is
  unset ([AXIS guide, section 8](../guides/axis-provisioning.md#camera-list-and-credentials)).
- The password is still in the history: every revision from `5564879` up to the parent of
  `15b0f60`, the `origin/main` tip included. The user has asked for the history to be
  rewritten to remove it. That rewrite runs separately, after this review, and its
  force-push needs the user's explicit confirmation.
- The user still has to rotate the camera password: a rewrite can't recall the copies that
  were already made.

## Problem

As found, at `e38e9e7`:

- `scripts/onvif_stream.py` defined its `CAMERAS` list in the source, and each entry carried
  the cameras' ONVIF password as a literal. It was not a placeholder. It had been in the file
  since `5564879`, and it is on `origin/main`.
- `scripts/onvif_stream.py` and `scripts/onvif_probe.py` also hard-coded the cameras' real
  addresses and names.

The AXIS provisioning guide showed placeholders and told the user to edit the list before
running, but the committed lists were the live ones.

## Impact

Anyone with a copy of the repository, or of its history, has the password of that ONVIF
account. If the password is reused elsewhere the exposure is wider. The addresses and names
describe the site's camera network. Nothing breaks for fresh clones or CI.

## Decision needed

What is left, in this order:

1. User action: change that ONVIF account's password on the cameras, then put the new one
   in the file that `ONVIF_PASSWORD` comes from. Removing the value from the file at HEAD
   doesn't help with the copies in the pushed history.
2. Done in `15b0f60`: both scripts read their camera list and account from the environment,
   and the repository keeps only placeholders.
3. The history rewrite the user asked for: it purges this password and the one in
   [issue 051](051-verify-cli-help-example-held-a-password.md). Its force-push needs the
   user's explicit confirmation, and every clone has to be re-made afterwards.

Why this still needs a decision: steps 1 and 3 are actions only the user can take or
confirm.
