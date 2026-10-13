---
title: "Two networks without a VLAN ID both sample as VLAN 1, so one overwrites the other in the traffic store"
date: 2026-10-06
status: resolved
resolved_by: b645b1d
severity: low
components: [analysis/vlan_interfaces, analysis/vlan_traffic, analysis/vlan_traffic_store]
found_by: 0.2.0 port review
---

# Two networks without a VLAN ID both sample as VLAN 1, so one overwrites the other in the traffic store

## Problem

`network_vlan_id` (`analysis/vlan_interfaces.py`) gives every corporate or guest network with
no `vlan` and no `vlan_enabled` the VLAN ID 1, the untagged LAN. The traffic store's raw rows
are keyed by `(ts_utc, vlan_id)`, and `insert_samples` writes them with `INSERT OR REPLACE`. If
a site has two such networks and each matches a gateway interface, one sample writes two rows
with the same key, and the second replaces the first; the reports then show one network's
traffic under the other's name, or a mix of both.

A UniFi site normally has one untagged network (the default LAN), so this needs an unusual
setup, for example a second untagged LAN on its own gateway port. No such site has been seen.

## Impact

On such a site, one untagged network's traffic is lost from every report. Nothing else is
affected. Breaks fresh clones, CI or prod: no.

## Recommended fix

In `sample_vlan_traffic`, keep the first resolved network for a VLAN ID and list any later one
under `unresolved`, so the CLI's one line counts it, with a test of two untagged networks on two
interfaces. Keying raw rows by interface as well would keep both, but changes the schema and
every rollup query; it is not worth it for a setup no site has shown.

## Resolution

Resolved on 2026-10-13 (`b645b1d`), as recommended. `sample_vlan_traffic`
(`analysis/vlan_traffic.py`) keeps the first resolved network for each VLAN ID and lists any
later one that derives the same ID under `unresolved`, with its `iface` and a `reason`
(`VLAN 1 already sampled from LAN (br0)`), so the CLI's one line counts it and nothing is
stored under another network's name. Test:
`tests/analysis/test_vlan_traffic.py::test_a_second_untagged_network_is_unresolved_not_overwritten`
(two untagged networks on two bridges; one row stored, the other unresolved).

Deliberately not changed: `network_vlan_id` still derives VLAN 1 for an untagged LAN, the raw
rows stay keyed by `(ts_utc, vlan_id)` and `resolve_vlan_interfaces` is unchanged; keying by
interface would change the schema and every rollup query for a setup no site has shown.
