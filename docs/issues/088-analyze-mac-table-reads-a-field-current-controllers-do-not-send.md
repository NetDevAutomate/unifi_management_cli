---
title: "`analyze mac-table` reads `device['mac_table']`, which current controllers do not send, so it reports nothing"
date: 2026-10-13
status: resolved
resolved_by: 2694f2f
severity: medium
components: [analysis/mac_analyzer]
found_by: the 0.3.0 analysis lane, live run during issue 030
---

# `analyze mac-table` reads `device['mac_table']`, which current controllers do not send, so it reports nothing

## Problem

`analysis/mac_analyzer.py` line ~122 reads `device.get('mac_table', [])` from `stat/device`. On
the maintainer's controller no device record carries `mac_table`, before or after issue 030, so
the tool reports 0 ports with MAC addresses live while its fixture tests pass.

## Impact

`analyze mac-table` and `analyze_mac_table` are empty on current controllers: a user gets a
clean-looking report with no data and no warning.

## Recommended fix

Derive per-port MACs from `stat/sta` (`sw_mac` and `sw_port` per client) when `mac_table` is
absent, and say in the report which source was used; a live capture should pin the shape.
Record the controller version the field disappeared in if a capture shows it.

## Resolution (2026-10-15)

A read-only capture of the maintainer's controller (UniFi Network 11.0.83) confirmed the
record: no `stat/device` record carries `mac_table`; each switch port has only
`mac_table_count`. Every wired `stat/sta` client carries `sw_mac` and `sw_port` (31 of 31),
with `sw_depth` beside them; `vlan` is present on 58 of 107 clients. One wired client, keys
only: `{is_wired: bool, last_connection_network_id: str, last_seen: int, last_uplink_mac:
str, mac: str, network_id: str, sw_depth: int, sw_mac: str, sw_port: int, uptime: int}`.
No earlier capture exists, so the version the field disappeared in is not known.

`analyze_mac_table` now takes a switch's entries from the wired clients learned on it
(`sw_mac`, `sw_port`, and `vlan` where the client has one) when the switch record has no
`mac_table`; a switch that sends `mac_table` is still read from it, since that is the
switch's own table. When any switch was read from the client list, the report's first
recommendation says which source it used, verbatim: `MAC entries for N switch(es) come from
the client list (stat/sta sw_mac and sw_port): the controller sends no mac_table for them,
so a MAC that is not a listed wired client is not counted, and a MAC moving between ports
(flapping) cannot be seen`. The report's fields are unchanged.

Pinned by `tests/analysis/test_mac_analyzer_client_source.py`, over a fixture in the live
record shape with documentation MACs: wired clients fill their ports and an access port
with seven clients is flagged, `--device` by MAC reads only that switch's clients, a
wireless client and a client on another switch are not counted, and a switch that sends
`mac_table` is read from it.

On the live site `analyze mac-table` went from 0 entries to 28 entries on 27 ports across
13 switches and gateways, with the source line first in its recommendations.
