---
title: "A VLAN traffic sample written more than two hours late never reaches the hourly or daily rollups"
date: 2026-10-06
status: open
severity: low
components: [analysis/vlan_traffic_store]
found_by: July port build-loop council, iteration 6 (CF-002, one reviewer)
---

# A VLAN traffic sample written more than two hours late never reaches the hourly or daily rollups

## Problem

`run_rollups` (`analysis/vlan_traffic_store.py`) rolls every complete bucket after a tier's
high-water mark and recomputes only a trailing window behind it: the newest `TRAILING_HOURS`
(2) complete hours and the newest `TRAILING_DAYS` (1) complete day. A bucket is complete once
it ended at least the grace ago (twice the sampling interval, at least 5 minutes). So a run
recomputes an hour only while it is one of the newest two complete hours: a raw sample written
into an hour that became complete two hours or more before the next run is never folded into
that hour's row, nor into the daily row built from the hourly rows.

The raw sample itself is kept, so the `now`, `1d` and `1w` reports, which read raw samples,
count it until it is pruned at 8 days; the `1m` and `1y` reports never do.

`vlan-traffic sample` stamps each sample when it reads the counters and writes it at once, so
a sample is this late only if it was written into the store some other way, or by a sampler
that stalled for over two hours between its read and its write. No such case has been seen.
Every sample written before its hour is first rolled is counted, whatever the rollup cadence.

The docs said a late sample is counted, and `run_rollups`' docstring that any cadence gives
the same result. Both now state the trailing-window guarantee, and
`tests/analysis/test_vlan_traffic_store.py` pins its boundary
(`test_a_late_sample_counts_only_inside_the_trailing_window`).

## Impact

The hourly and daily rows miss such a sample, so the `1m` and `1y` averages and peaks differ
from what the raw samples hold. Breaks fresh clones, CI or prod: no.

## Recommended fix

Make the rollups follow the data rather than the clock, in one of two ways:

1. **Dirty buckets.** `insert_samples` records, in the same transaction, each hour (and so each
   day) a row lands in, in a new `dirty_buckets` table; `run_rollups` recomputes every
   complete dirty bucket and clears it. This adds a table, which a store made by the current
   code gains on its next writable open (`CREATE TABLE IF NOT EXISTS`).
2. **Recompute what the lower tier holds in full.** Each run recomputes every complete hour
   whose raw samples are all still kept, and every complete day whose hours are all still
   kept. No schema change, but a run reads up to 8 days of raw samples.

Either way, prune on bucket boundaries only: a whole hour of raw samples and a whole day of
hourly rows, once rolled, so that no bucket is recomputed from part of its data.

Test: a sample written into an hour rolled a day earlier changes that hour's row and its
day's row on the next run, and two runs still give identical rows.
