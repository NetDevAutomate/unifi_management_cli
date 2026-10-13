---
title: "A VLAN traffic interval can span a sampler outage, so one fresh sample reports days of traffic as current"
date: 2026-10-06
status: resolved
resolved_by: 5bc743e
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

## Resolution

Resolved on 2026-10-13 (`5bc743e`), the decision taken as the recommendation leaned: an
interval across an outage is a gap, not a measurement. `compute_rates`
(`analysis/vlan_traffic_store.py`) takes an optional `max_interval`; a pair of samples further
apart gives no rate. `max_measured_interval(grace)` is `GAP_THRESHOLD_SECONDS` plus the sampling
grace, and every pairing passes it: the first sample of a raw window and the consecutive
samples inside it (`_raw_rates`, which measures the grace from the newest raw stamps as
`run_rollups` does) and the boundary carry in `_roll_hours` (the run's own grace). The later
sample still counts in `samples` and not as a valid interval, so `valid_sample_pct` drops; the
raw-tier caveat says so, as do the docs.

One reading of the recommendation chosen over the other: the bound adds the *grace* (twice
the measured interval, at least 5 minutes: 600 s at a one-minute cadence) rather than the bare
interval (360 s). A sampler that misses a few minutes still gives an honest average over them
(the counters are cumulative), so the looser bound loses less; an outage of hours or days is a
gap under either. `vlan-traffic coverage` keeps its own, tighter, gap count
(`expected spacing + GAP_THRESHOLD_SECONDS`), unchanged.

Tests in `tests/analysis/test_vlan_traffic_store.py`:
`test_an_interval_longer_than_the_bound_has_no_rate`,
`test_the_raw_reader_treats_an_outage_as_a_gap_before_and_inside_a_window` (a six-hour outage
inside a `1w` window and a three-day one before a `now` window, a normal cadence beside them)
and `test_the_hourly_carry_across_an_outage_is_a_gap` (the hour rolled after a three-day
outage holds 59 intervals, not 60, and its peak is the cadence's rate). Deliberately not
changed: `compute_rates` without a bound behaves as before (the prototype's signature is
kept), and reporting each interval's length was not added.
