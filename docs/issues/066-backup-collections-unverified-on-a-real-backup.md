---
title: "`backup verify` names collections by `_type`, unverified on a real backup"
date: 2026-10-05
status: open
severity: low
components: [backup/poc_decrypt, backup/verify]
found_by: July port review
---

# `backup verify` names collections by `_type`, unverified on a real backup

## Problem

`verify_backup_bytes` names each document's collection by its `_type` field
(`poc_decrypt.collection_name`), as the July work and the proof of concept it builds on did.
Every backup in the test suite is synthetic (`tests/backup/synthetic_unf.py`) and tags its
documents the same way, so no test shows that a backup downloaded from a controller is laid
out like that. The port's live check uses a synthetic backup too, by design (no real backup
is read).

If a real backup instead switches collection with a marker document (for example one naming
the collection for the documents after it), its documents carry no `_type`: all of them are
counted under `other` and every entry of `key_sections_present` is false.

## Impact

A good backup could be reported with its key sections missing, a false warning. It cannot
make a corrupt or truncated backup pass: the walk is strict whatever the layout. Breaks
fresh clones, CI or prod: no.

## Recommended fix

Run `unifi-mapper backup verify` on a backup downloaded from the controller (offline, it
contacts nothing) and compare its collection counts with the controller's own. If they are
all `other`, teach the walk the real layout (a marker document sets the collection for the
documents after it and is not counted itself), with a synthetic test of that layout.
