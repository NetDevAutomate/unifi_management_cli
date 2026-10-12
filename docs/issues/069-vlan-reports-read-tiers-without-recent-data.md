---
title: "VLAN traffic reports read rollup tiers that held no recent data, so `1w` was always empty"
date: 2026-10-06
status: resolved
resolved_by: dec3450
severity: medium
components: [analysis/vlan_traffic_store, typer_cli, mcp/manifests/analysis.yaml]
found_by: July port review (iteration 5, semantic review and council)
---

# VLAN traffic reports read rollup tiers that held no recent data, so `1w` was always empty

## Problem

The VLAN traffic store was ported from the July work (a local archive, not in the repo) with
July's tier timing, and that timing was broken:

- `vlan-traffic rollup` rolled an hour of raw samples into an hourly row only once the hour
  was more than 8 days old, and a day of hourly rows into a daily row only once the day was
  about 61 days old.
- The `1w` report read the hourly tier, which never held an hour newer than 8 days, so it
  was always empty. `1m`, also hourly, covered only days 8 to 30. `1y`, daily, left out the
  newest 61 days or so.

Measured on 70 days of synthetic samples, 5 minutes apart, rolled and reported at a fixed
time: `1w` returned no VLAN; `1m` read 527 hourly rows, the newest 8.05 days old; `1y` read
10 daily rows, the newest 61.6 days old. No test caught it, because the tests inserted rollup
rows directly instead of rolling samples.

## Impact

The documented `vlan-traffic report 1w` and `get_vlan_traffic_report('1w')` never returned a
VLAN, and a burst this week or this month never showed in the monthly or yearly peak. It
wrote nothing wrong and leaked nothing. Breaks fresh clones, CI or prod: no.

## Resolution

Signed off as a user-visible change by the port's orchestrator (its decision record is kept
outside the repo):

- `now`, `1d` and `1w` read raw samples, which are kept 8 days; `1m` reads hourly rows and
  `1y` daily rows. Each report's methodology caption names its tier.
- `rollup` rolls every complete hour and day. A bucket is complete once it ended twice the
  sampling interval ago (the median gap between the newest samples), and at least 5 minutes.
- Each row is recomputed in full from the tier below and written with `INSERT OR REPLACE`,
  and every run also recomputes the newest 2 complete hours and the newest complete day, so
  two runs give identical rows and a sample written late is counted by a run less than 2
  hours after its hour is complete; a later one never reaches the rollups
  ([issue 071](071-late-vlan-samples-never-reach-the-rollups.md)).
- Raw samples are pruned after 8 days and hourly rows after 60, and never before their hour
  or day has been rolled.
- A store the July code made upgrades in place on its first run: no schema change, every hour
  after its high-water mark is rolled from raw (none is skipped), and the recent days are
  backfilled.

Tests, at a fixed time: sample, rollup and report across every tier boundary for `1d`, `1w`,
`1m` and `1y`, asserting the newest bucket each includes; the grace for two sampling
intervals; a late sample; two identical runs; pruning, and a row that stays because its
hour is not complete; and an upgrade of a store as the July code left it.
