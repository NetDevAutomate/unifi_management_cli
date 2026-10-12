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

- Fixed at HEAD by `01abf2c`. Neither script keeps a camera address, name or credential in
  the source any more. Both read `ONVIF_USERNAME`, `ONVIF_PASSWORD` and `ONVIF_CAMERAS`
  through `scripts/onvif_config.py`, and stop before they connect to any camera if one is
  unset ([AXIS guide, section 8](../guides/axis-provisioning.md#camera-list-and-credentials)).
- The password is still in the history: every revision from `3957561` up to the parent of
  `01abf2c`, the `origin/main` tip included. The user has asked for the history to be
  rewritten to remove it. That rewrite runs separately, after this review, and its
  force-push needs the user's explicit confirmation.
- The user reports that the camera password has been changed everywhere it was used. The old
  value stays in the history until the planned history rewrite purges it.

## Problem

As found, at `0f76fd6`:

- `scripts/onvif_stream.py` defined its `CAMERAS` list in the source, and each entry carried
  the cameras' ONVIF password as a literal. It was not a placeholder. It had been in the file
  since `3957561`, and it is on `origin/main`.
- `scripts/onvif_stream.py` and `scripts/onvif_probe.py` also hard-coded the cameras' real
  addresses and names.

The AXIS provisioning guide showed placeholders and told the user to edit the list before
running, but the committed lists were the live ones.

## Impact

Anyone with a copy of the repository, or of its history, had the password of that ONVIF
account. Where the password was reused, the exposure was wider. The user has since changed
it everywhere it was used. The addresses and names
describe the site's camera network. Nothing breaks for fresh clones or CI.

## Decision needed

What is left, in this order:

1. Done by the user: the ONVIF account's password has been changed on the cameras and
   everywhere else it was used (the user's report; not checked here). The new value belongs
   in the file that `ONVIF_PASSWORD` comes from.
2. Done in `01abf2c`: both scripts read their camera list and account from the environment,
   and the repository keeps only placeholders.
3. The history rewrite the user asked for: it purges this password and the one in
   [issue 051](051-verify-cli-help-example-held-a-password.md). Its force-push needs the
   user's explicit confirmation, and every clone has to be re-made afterwards.

Why this still needs a decision: the rewrite's force-push in step 3 needs the user's
explicit confirmation.
