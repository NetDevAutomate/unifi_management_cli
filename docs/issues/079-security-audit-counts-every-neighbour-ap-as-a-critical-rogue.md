---
title: "security_audit counts every neighbouring AP as a critical rogue"
date: 2026-10-13
status: open, decision needed
severity: medium
components: [diagnostics/security_audit, typer_cli]
found_by: running the new `diagnose security` command against a live controller
---

# `security_audit` counts every neighbouring AP as a critical rogue

## Problem

`security_audit` (now also `unifi-mapper diagnose security`) feeds every entry of the
controller's passive neighbour list (`stat/rogueap`) through `_analyze_rogue_ap`, which gives
each one `risk_level='critical'` and the flag `Strong signal - rogue AP is very close` or
`Medium signal - rogue AP in vicinity`. On a home site in a built-up area the live run on
2026-10-13 reported 748 "devices", 619 of them unauthorised and critical: the 619 are the
neighbours' own Wi-Fi networks. The immediate actions then open with
"CRITICAL: 619 rogue access points detected - locate and eliminate", which is wrong and buries
the real findings (2 high, 48 medium, 195 MAC anomalies).

Until this commit the tool never got that far: it read `rest/rogueap`, which the controller
answers with `400 api.err.InvalidObject`, so every call failed with `API_ERROR`
(fixed in the same change that added the CLI command; `tests/diagnostics/test_security_audit_reads.py`).

## Impact

The report's headline numbers are noise on any site with neighbours, so the one place that
lists unauthorised devices and MAC anomalies cannot be trusted at a glance. The CLI caps the
risk table at 40 rows and points at `--json`, which hides the problem rather than fixing it.

## Recommended fix

A neighbouring AP is a *rogue* only when it threatens this site, which the passive data can
show in three ways, in order of certainty:

1. **SSID impersonation**: its `essid` matches one of this site's WLANs (`rest/wlanconf`)
   while its `bssid` is not one of this site's AP radios (`stat/device` `vap_table`
   `bssid`s). Critical.
2. **Our own hardware, unadopted**: `is_ubnt` true and the BSSID is not an adopted AP; a
   UniFi AP on the premises that the controller does not manage. High.
3. **Wired on our LAN**: the controller marks some entries `is_wired`/`on_wire` (a neighbour
   seen through the switch fabric). High.

Everything else is a neighbour: counted in a `neighbour_aps` total with the three strongest
listed for interference context, never in `critical_risks`, `unauthorized_devices` or the
immediate actions. The existing `scan_neighbour_aps` / `analyze neighbours` already gives the
interference view, so the audit should not duplicate it.

## Decision needed

Whether a neighbour broadcasting an open network with a very strong signal (above about
-50 dBm, i.e. inside the building) should still be flagged as medium, as a possible
unauthorised AP on the premises, or left to `analyze neighbours`.
