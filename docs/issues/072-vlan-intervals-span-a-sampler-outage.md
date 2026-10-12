---
title: "A VLAN traffic interval can span a sampler outage, so one fresh sample reports days of traffic as current"
date: 2026-10-06
status: open, decision needed
severity: low
components: [analysis/vlan_traffic_store]
found_by: 0.2.0 port review
---

# A VLAN traffic interval can span a sampler outage, so one fresh sample reports days of traffic as current

## Problem

A rate is the difference between two samples (`compute_rates` in
`analysis/vlan_traffic_store.py`), and nothing bounds how far apart the two may be:

- `_raw_rates`, which the `now`, `1d` and `1w` reports read, pairs each VLAN's first sample in
  the window with its newest sample before the window, however old (the pairing an earlier
  review asked for), and pairs the samples inside the window one after another;
- `_roll_hours` carries each VLAN's newest earlier sample into the first hour it rolls, as the
  prototype's code did.

So after the sampler stops for three days, one sample taken now makes `report now` show the
three-day average as the current rate, with `samples: 1` and `valid_sample_pct: 100.0` (named
`coverage_pct` before a review renamed it). In `1d` and
`1w` that one long interval weighs as much in the mean of rates as any one-minute interval, and
the hourly row of the hour the sampler came back in holds the whole gap. `coverage` lists the
gap, but only to someone who runs it.

## Impact

Rates and valid-sample shares across a sampler outage are misleading: an average over days is
shown as one current interval with every sample valid. Nothing is lost or written wrongly. Breaks fresh clones,
CI or prod: no.

## Recommended fix

Treat a pair of samples further apart than `GAP_THRESHOLD_SECONDS` plus the sampling interval
(the median gap `sampling_grace` already measures) as a gap, not a measurement, in every
pairing: the first sample of a raw window, consecutive samples inside it, and the boundary
carry in `_roll_hours`. The later sample then counts in `samples` but not as a valid interval,
so `valid_sample_pct` drops, as a window's first sample did before CF-003. Test both readers with a
gap of several days before a window and inside one, and a normal cadence beside it.

The decision needed: this changes what the reports show for any store with an outage in it
(a lower `valid_sample_pct`, and no rate for the interval across the gap). Reporting each interval's length
instead keeps today's numbers, but leaves the reader to spot the long one.
