---
title: "Test fixtures carried MAC addresses and addresses from the live network"
date: 2026-10-04
status: open, decision needed
severity: low
components: [tests, history]
found_by: docs and repo hygiene review (privacy scan)
---

# Test fixtures carried MAC addresses and addresses from the live network

## Status

- Fixed at HEAD. The repository is public, so this review replaced the identifiers:
  - `29879cf`: every address in a subnet the local captures show is now in an RFC 5737
    documentation range, with the same host part, in 19 test files.
  - `a78d403`: the MAC addresses, a serial number and a device ID are synthetic values in
    11 test files. Each MAC is locally administered, and MACs that shared a vendor prefix
    still share one.
  - `4845976`: `tests/test_docs_consistency.py` fails when a tracked test or script holds a
    MAC address, serial number, device or site ID, or an address in a subnet or IPv6 prefix
    that the local captures (`reports/*.json`) hold. It skips on a fresh clone, and it reports
    the file, line and kind only.
- The history still holds the old values. The eight files below were on `origin/main`
  before `d045079`; `062a0e5` (not pushed) added a live address; and the removed lines of
  `29879cf` and `a78d403` hold the values they replaced. The earlier doc and docstring
  scrubs removed MACs and addresses that were already public, too:
  - `e6a6aae` (the docs): 41 lines that held a captured MAC or an address in a captured
    subnet, all 41 on `origin/main`: `README.md` 7, `docs/guides/axis-provisioning.md` 15,
    `docs/guides/use-cases-and-howto.md` 14, `docs/operations/troubleshooting-and-runbook.md`
    1 and `docs/solutions/analysis/port-label-drift.md` 4;
  - `3afa3bc` (the `src/` docstrings): 4 such lines, all 4 on `origin/main`:
    `src/unifi_mapper/analysis/port_naming.py` 3 and
    `src/unifi_mapper/analysis/uplink_transparency.py` 1.

  Only a history rewrite removes them.
  The rewrite the user asked for, to purge two passwords
  ([issue 041](041-onvif-scripts-hard-code-cameras.md),
  [issue 051](051-verify-cli-help-example-held-a-password.md)), runs separately, after this
  review, and its force-push needs the user's explicit confirmation.

## Problem

As found, at `80c11fe`: a privacy scan compared the identifiers in tracked files with local
captures of the live network. The docs were cleaned in `e6a6aae`, but eight test files still
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

All eight predate `d045079`, so they are on `origin/main`. The wider scan behind the fix also
counted generic examples in the site's subnets, a serial number and a device ID, in 26 test
files in all.

Separately, `062a0e5` (not pushed) added an address from the live network to
`tests/mcp/test_execute_call_shapes.py`. `b062b17` replaced it with a documentation address,
but the original stays in `062a0e5`'s history.

## Impact

The values identify devices on one private network; they are not credentials. Nothing
breaks for fresh clones, CI or users.

## Decision needed

What is left: whether the history rewrite also covers these identifiers, that is the pushed
history of the eight test files, `062a0e5`, the removed lines of `29879cf` and `a78d403`,
and the removed lines of `e6a6aae` and `3afa3bc` (the 45 doc and docstring lines above,
public since before this review). It is the user's call: a rewrite changes every later
commit hash, including the `resolved_by` hashes the issue files record, and every clone has
to be re-made afterwards.
