---
title: "The ONVIF scripts hard-coded the site's cameras, and `onvif_stream.py` a camera password that is in pushed history"
date: 2026-10-04
status: resolved
resolved_by: 2650809
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

## Resolution

Resolved on 2026-10-12 by the history rewrite. Every commit from 2025-04-25 on was rewritten
with `git filter-repo` from a reviewed replacement list (three credentials and their hashes,
the site's device, client and port names in every case and separator spelling, its MAC
addresses in every notation, its addresses in four subnets mapped to RFC 5737 documentation
addresses with the host part kept, and the removed internal document paths). The rewritten
history was verified over every object (blob, commit, tag and tree name) before and after the
push, reviewed by a four-model council in three passes, and force-pushed to `main` with a
lease on the previous tip. The superseded heads (`d045079`, `fef2344`, `3a8d731`) were purged
from GitHub by Support (ticket closed 2026-10-15; verified that day: the commits API answers
422, the commit pages 404, and a fetch by SHA is refused with `not our ref`); see
[the rewrite notice](../../CHANGELOG.md) for what a clone holding the old history must do.
The camera password of this issue is absent from every historical revision in every form
checked (clear, URL-encoded, SHA-1 as recorded in `.secrets.baseline`). The second ONVIF account's
password, which also sat in a public guide, was rotated on both cameras on 2026-10-12 (the
maintainer's report); the first account was rotated on 2026-10-03. Nothing of this issue is open.
