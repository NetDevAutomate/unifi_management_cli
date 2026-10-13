---
title: "A VLAN traffic sample written two hours or more late, into an hour already rolled, never reaches the hourly or daily rollups"
date: 2026-10-06
status: resolved
resolved_by: 1146b22
severity: low
components: [analysis/vlan_traffic_store]
found_by: 0.2.0 port review
---

# A VLAN traffic sample written two hours or more late, into an hour already rolled, never reaches the hourly or daily rollups

## Problem

`run_rollups` (`analysis/vlan_traffic_store.py`) rolls every complete bucket after a tier's
high-water mark and recomputes only a trailing window behind it: the newest `TRAILING_HOURS`
(2) complete hours and the newest `TRAILING_DAYS` (1) complete day. A bucket is complete once
it ended at least the grace ago (twice the sampling interval, at least 5 minutes). So a run
recomputes an hour only while it is one of the newest two complete hours.

The omission is narrow: it needs an hour that a run has already rolled and that has left the
trailing window. A raw sample written into such an hour is folded into its row only by a run
less than two hours after the hour became complete; once a run comes two hours or more after
that (the boundary `tests/analysis/test_vlan_traffic_store.py` pins, at exactly
`TRAILING_HOURS` hours not counted), the sample never reaches that hour's row, nor the daily
row built from the hourly rows.

The raw sample itself is kept, so the `now`, `1d` and `1w` reports, which read raw samples,
count it until it is pruned at 8 days; the `1m` and `1y` reports never do.

`vlan-traffic sample` stamps each sample when it reads the counters and writes it at once, so
a sample is this late only if it was written into the store some other way, or by a sampler
that stalled for two hours or more between its read and its write. No such case has been
seen. Every sample written before its hour is first rolled is counted, whatever the rollup
cadence.

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

## Resolution

Resolved on 2026-10-13 (`1146b22`) with **option 1, dirty buckets**. `insert_samples`
(`analysis/vlan_traffic_store.py`) records, in the same transaction as the rows, each hour a
row lands in (`dirty_buckets (tier, bucket)`, `INSERT OR IGNORE`); `run_rollups` recomputes
every complete dirty hour that its high-water-mark range does not already cover, marks the day
of each dirty, recomputes every complete dirty day the same way, and clears what it rolled. A
dirty bucket that is not complete yet stays until it is. The table is created with
`CREATE TABLE IF NOT EXISTS`, so a store made by the current code gains it on its next writable
open, as the issue foresaw.

Why option 1 and not option 2 (recompute everything the lower tier holds): option 2 is not
clearly smaller in code. It needs the same boundary pruning, it must know where the fully kept
hours begin (the carry sample each VLAN keeps sits in a pruned hour, so `MIN(ts_utc)` cannot
say), which means recording the prune boundary anyway, and it makes every run read up to 8 days
of raw samples and 60 days of hourly rows to rewrite rows that have not changed. Dirty buckets
cost one small table and recompute only what a write touched.

Pruning now follows the issue's "either way" clause: raw samples are cut on an hour boundary
and hourly rows on a day boundary (`_raw_cutoff`, `_hourly_cutoff`), so a bucket is kept whole or
not at all. A dirty hour that lies before the raw cutoff is dropped, not recomputed: its
samples are past retention and about to be pruned, and rewriting the row from the carry sample
alone would replace a correct row with a one-interval one
(`test_a_late_sample_into_a_pruned_hour_is_dropped_not_rolled_from_part_of_its_data`).

Deliberately kept: the trailing window (`TRAILING_HOURS`, `TRAILING_DAYS`). It is now the only
net for a row written straight into `raw_samples` by something other than `insert_samples`
(no dirty mark), which `test_a_late_sample_counts_only_inside_the_trailing_window` continues
to pin; the sampler's own writes are always counted. Tests:
`test_insert_samples_records_each_hour_it_writes_into_as_dirty`,
`test_a_sample_written_a_day_late_reaches_the_hourly_and_daily_rows` (a sample into an hour
rolled a day earlier changes that hour's row and its day's row on the next run, and two runs
give identical rows) and `test_pruning_keeps_whole_buckets_only`, all in
`tests/analysis/test_vlan_traffic_store.py`. The `vlan-traffic rollup` help text,
`docs/reference/cli.md` and `docs/guides/use-cases-and-howto.md` describe the new guarantee.
