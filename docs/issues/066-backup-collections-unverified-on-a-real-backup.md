---
title: "`backup verify` names collections by `_type`, unverified on a real backup"
date: 2026-10-05
status: resolved
resolved_by: 68ea0ba
severity: low
components: [backup/poc_decrypt, backup/verify]
found_by: 0.2.0 port review
---

# `backup verify` names collections by `_type`, unverified on a real backup

## Problem

`verify_backup_bytes` names each document's collection by its `_type` field
(`poc_decrypt.collection_name`), as the prototype and the proof of concept it builds on did.
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

## Status (2026-10-13)

Blocked on operator input: a backup downloaded from the controller is needed to check the
collection names `backup verify` reports. No code change in 0.3.0.

## Resolution (2026-10-15)

Confirmed on a real backup, and fixed. The input was a UniFi OS console backup (`.unifi`,
2026-08-07) whose `backup/network/` directory holds the Network application's backup: the
same members a `.unf` zip holds (`db.gz`, `version`, `format`, ...). Those members, unchanged,
were zipped and encrypted with the Network key and run through `unifi-mapper backup verify`
offline; only that wrapper was rebuilt, the database is the controller's.

The hypothesis held exactly. Network 10.6.88 writes the database as a stream of 2,642 BSON
documents: 102 `{'__cmd': 'select', 'collection': <name>}` markers, each followed by that
collection's documents, which carry no `_type` (4 of the 2,540 do, with values naming no
collection). Before the fix the report was `valid: true` with every document under `other`
(2,642, the markers included), all four key sections reported missing, and no version.

The walk now follows the markers (`poc_decrypt.iter_collection_documents`, shared by the POC
and the verifier): a marker sets the collection for the documents after it, outranks a
document's own `_type` and is not counted; before the first marker, and in older backups,
the `_type` is used as before. The version comes from the zip's `version` member (capped at
64 bytes, reported only when it is a version number), else from a `setting` document's string
version; an int `version` (the `netflow` setting's protocol version) is no longer reported as
`<unrecognised>`. `KNOWN_COLLECTIONS` gained the 64 names a 10.6.88 backup uses that it
lacked. Four further names (`api_key`, `api_key_privilege`, `ssooauthtoken`,
`teleport_token`) stay out and are counted under `other`: the output redactor treats them
as secret keys, and the first run after adding them showed `--json` silently dropping their
27 documents (2,513 of 2,540 reported). A test pins that every reported name survives the
redactor.

Result on the same backup: valid, version `10.6.88`, all four key sections present, 2,540
documents in 52 collections (27 under `other`), equal to an independent census of the
stream. Against the live controller on 2026-10-15 (read-only): `networkconf` 16 in the
backup and 16 live; `device` 21 and 24 live, `wlanconf` 4 and 3 live, `apgroup` 4 and 3 live,
differences consistent with ten weeks of changes since the backup was taken. Pinned by twelve
synthetic tests in `tests/backup/test_verify.py` (both layouts, an empty collection, an
unknown or secret-looking selected name, a malformed marker, the version member's checks, the
measured name list and the CLI). The real backup is not in the repository; the copy made for
the run was deleted afterwards, and the original stays with the maintainer.
