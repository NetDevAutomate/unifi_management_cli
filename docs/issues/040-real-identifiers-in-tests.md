---
title: "Test fixtures carry MAC addresses and addresses from the live network"
date: 2026-10-04
status: open, decision needed
severity: low
components: [tests]
found_by: docs and repo hygiene review (privacy scan)
---

# Test fixtures carry MAC addresses and addresses from the live network

## Problem

A privacy scan compared the identifiers in tracked files with local captures of the live
network. The docs were cleaned in `e6a6aae`, but eight test files still use MAC addresses of
real devices on that network, and three of them also addresses in its subnets (marked):

- `tests/analysis/test_foreign_bridges.py` (addresses too)
- `tests/analysis/test_link_error_tracking_unadopted.py`
- `tests/analysis/test_port_naming_plan.py`
- `tests/analysis/test_uplink_transparency.py`
- `tests/test_new_analysis_tools.py` (addresses too)
- `tests/test_port_inspect.py` (addresses too)
- `tests/test_port_naming.py`
- `tests/utility/test_overrides.py`

All eight predate `d045079`, so they are already on `origin/main`.

Separately, `062a0e5` (not pushed) added an address from the live network to
`tests/mcp/test_execute_call_shapes.py`. `b062b17` replaced it with a documentation address,
but the original stays in `062a0e5`'s history.

## Impact

The values identify devices on one private network; they are not credentials. Nothing
breaks for fresh clones, CI or users.

## Decision needed

Recommendation:

1. Replace the MACs with locally administered `02:00:00:…` values and the addresses with
   RFC 5737 documentation addresses, as `tests/fixtures_unifi.py` already does. Check each
   test first: an assertion that depends on a vendor OUI (an OUI lookup, a vendor name)
   needs that OUI kept and only the device bytes changed.
2. Before the unpushed commits are pushed, decide whether to rewrite `062a0e5`. It is the
   user's call: the rewrite changes every later commit hash, including the `resolved_by`
   hashes the issue files record.
