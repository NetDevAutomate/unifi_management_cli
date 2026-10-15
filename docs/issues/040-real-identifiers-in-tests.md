---
title: "Test fixtures carried MAC addresses and addresses from the live network"
date: 2026-10-04
status: resolved
resolved_by: 2650809
severity: low
components: [tests, history]
found_by: docs and repo hygiene review (privacy scan)
---

# Test fixtures carried MAC addresses and addresses from the live network

## Status

- Fixed at HEAD. The repository is public, so this review replaced the identifiers:
  - `95dde93`: every address in a subnet the local captures show is now in an RFC 5737
    documentation range, with the same host part, in 19 test files.
  - `c9bdf3e`: the MAC addresses, a serial number and a device ID are synthetic values in
    11 test files. Each MAC is locally administered, and MACs that shared a vendor prefix
    still share one.
  - `246245b`: `tests/test_docs_consistency.py` fails when a tracked test or script holds a
    MAC address, serial number, device or site ID, or an address in a subnet or IPv6 prefix
    that the local captures (`reports/*.json`) hold. It skips on a fresh clone, and it reports
    the file, line and kind only.
- The history still holds the old values. The eight files below were on `origin/main`
  before `259af9b`; `9fce34a` (not pushed) added a live address; and the removed lines of
  `95dde93` and `c9bdf3e` hold the values they replaced. The earlier doc and docstring
  scrubs removed MACs and addresses that were already public, too:
  - `bd6c531` (the docs): 41 lines that held a captured MAC or an address in a captured
    subnet, all 41 on `origin/main`: `README.md` 7, `docs/guides/axis-provisioning.md` 15,
    `docs/guides/use-cases-and-howto.md` 14, `docs/operations/troubleshooting-and-runbook.md`
    1 and `docs/solutions/analysis/port-label-drift.md` 4;
  - `eeb34b9` (the `src/` docstrings): 4 such lines, all 4 on `origin/main`:
    `src/unifi_mapper/analysis/port_naming.py` 3 and
    `src/unifi_mapper/analysis/uplink_transparency.py` 1.

  Only a history rewrite removes them.
  The rewrite the user asked for, to purge two passwords
  ([issue 041](041-onvif-scripts-hard-code-cameras.md),
  [issue 051](051-verify-cli-help-example-held-a-password.md)), runs separately, after this
  review, and its force-push needs the user's explicit confirmation.

## Problem

As found, at `27e0c0b`: a privacy scan compared the identifiers in tracked files with local
captures of the live network. The docs were cleaned in `bd6c531`, but eight test files still
used MAC addresses of real devices on that network, and three of them also addresses in its
subnets (marked):

- `tests/analysis/test_foreign_bridges.py` (addresses too)
- `tests/analysis/test_link_error_tracking_unadopted.py`
- `tests/analysis/test_port_naming_plan.py`
- `tests/analysis/test_uplink_transparency.py`
- `tests/test_new_analysis_tools.py` (addresses too)
- `tests/test_port_inspect.py` (addresses too)
- `tests/test_port_naming.py`
- `tests/utility/test_overrides.py`

All eight predate `259af9b`, so they are on `origin/main`. The wider scan behind the fix also
counted generic examples in the site's subnets, a serial number and a device ID, in 26 test
files in all.

Separately, `9fce34a` (not pushed) added an address from the live network to
`tests/mcp/test_execute_call_shapes.py`. `f9c06a6` replaced it with a documentation address,
but the original stays in `9fce34a`'s history.

## Impact

The values identify devices on one private network; they are not credentials. Nothing
breaks for fresh clones, CI or users.

## Decision needed

What is left: the history copies of these identifiers, that is the pushed history of the
eight test files, `9fce34a`, the removed lines of `95dde93` and `c9bdf3e`, and the removed
lines of `bd6c531` and `eeb34b9` (the 45 doc and docstring lines above, public since before
this review). The user has approved removing the network details in the unpushed commits in
the same rewrite as the passwords. Only the identifiers in the pushed history are still to
decide. The maintainer sets the exact commit list. A rewrite changes every later commit
hash, including the `resolved_by` hashes the issue files record, and every clone has to be
re-made afterwards.

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
The identifiers of this issue (test-fixture MACs, serial, device ID and addresses) are gone
from every historical revision; the positive control detected each of them in the pre-rewrite
mirror and none in the rewritten history.
