---
title: "`get_lldp_info` returns no LLDP neighbours on a current controller, so diagrams draw no LLDP links"
date: 2026-10-15
status: resolved
resolved_by: 50a7877
severity: medium
components: [api_client, run_methods, enhanced_network_topology]
found_by: 0.4.0 lane 2b (issue 085 live check)
---

# `get_lldp_info` returns no LLDP neighbours on a current controller, so diagrams draw no LLDP links

## Problem

`UnifiApiClient.get_lldp_info` (`src/unifi_mapper/api_client.py:1140`) reads a device's
`lldp_table` by calling `get_device_details(site_id, device_id)` (line 833), which requests
`stat/device/{device_id}` and `rest/device/{device_id}` with the device's `_id`. On the live
controller (Network 10.6.x) that call returned no `lldp_table` for any of the 13 switches, while
the site-wide `stat/device` answer, already fetched by every caller, carried 43 `lldp_table`
rows across those switches. `run_methods.get_devices_and_lldp_data` (line 375) therefore hands
the smart mapper an empty LLDP map, and the topology falls back to uplink fields alone: no
LLDP-derived link appears in any diagram.

The likely mechanism, to confirm with a read-only capture: current controllers key the
per-device `stat/device/<x>` path by MAC address, not `_id`, so a lookup by `_id` answers with an
empty list. `get_lldp_info` already builds a MAC-to-device cache (lines 1166-1169), which
suggests the mismatch was noticed before.

## Evidence

Live, read-only, 2026-10-15: `get_lldp_info` returned 0 ports for 13 of 13 switches;
`stat/device` carried 43 `lldp_table` rows. Not pinned by a test yet: the fake controller's
`stat/device/{id}` route has not been checked for which key it honours.

## Impact

Medium: every diagram and the smart port mapper lose the LLDP view of the topology on a
current controller, silently (the log reports the device count, not the empty LLDP map).
Breaks fresh clones, CI or prod: no.

## Recommended fix

Read `lldp_table` from the already-fetched site-wide `stat/device` record (one request, no
per-device round trip, and no dependence on which key the per-device path accepts); keep
`get_device_details` for callers that need a single fresh record, requesting by MAC when the
caller has one. Pin with a fake-controller test whose `stat/device` records carry `lldp_table`
and whose per-device route answers nothing for an `_id`, asserting the LLDP map is populated.
Capture one live `stat/device/<mac>` and `<_id>` answer pair first (read-only) and record the
shapes in the fix commit.

## Related

The `UACCMPOEAF` doorbell (type `uacc`) is outside `diagram`'s device-type filter, so inventory
lists 11 access points and the diagram draws 10. `device_inventory.py:72` already classes
`uacc` as an access point; whether `diagram` should draw it is a small follow-on decision for the
same fix.

## Resolution (2026-10-15)

Decided by the 0.4.0 validation council (pass B, D-096, unanimous) and verified live by the
agent. The mechanism was not quite the one guessed above: a current controller's device `_id`
is a 36-character hyphenated UUID, and `_validate_device_id` strips every non-hex character
before the request, so the per-device path was asked for a mangled id. The controller answered
400 (`stat/device/<id>`) and 404 (`rest/device/<id>`), `get_device_details` fabricated a
"minimal" record with no `lldp_table`, and every switch reported no LLDP ports.

The MAC-to-name cache already fetches the site-wide `stat/device` records; it now keeps each
record by `_id`, by the sanitised id and by MAC, and `get_lldp_info` reads `lldp_table` from
that record first, falling back to the per-device fetch only when the site-wide record lacks
the table. No per-device request is made in the common case.

Pinned by `tests/test_api_client_lldp_source.py`: the site-wide record serves the rows when
the per-device path answers a record without them; the per-device path is still the fallback
when the site-wide record has no table; a hyphenated UUID id finds its record while the
per-device routes answer 400 and 404.

What a user sees: on the maintainer's site, read-only, 12 switches, 40 LLDP rows, 40 LLDP
ports found where 0 were, with 0 per-device requests; diagrams and the smart port mapper get
their LLDP links back. The `UACC` doorbell note stays a follow-on (issue 085's filter work).
