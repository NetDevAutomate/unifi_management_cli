---
title: "There is no on-disk history of port error counters"
date: 2026-10-02
status: open
severity: low
components: [analysis/link_error_tracking, scripts/unifi-cron.sh]
found_by: port diagnostics gap analysis (F6)
---

# There is no on-disk history of port error counters

## Problem

Nothing on disk can say how a port's error counters changed over time:

- `analyze link-errors --snapshot` overwrites a single file,
  `reports/link-error-baseline.json`.
- `scripts/unifi-cron.sh` schedules that snapshot every 300 s. Even when the schedule is
  installed, only the latest snapshot survives, and every run replaces the baseline that
  `analyze link-errors` compares against.
- In this checkout `reports/link-error-baseline.json` was last written on 2026-05-03, so
  the schedule isn't running here.
- The XDG port-counter store has no producer (issue 002).

`ports counters` and `get_port_counter_rates` work around this by sampling live, an
inform interval apart.

## Impact

A question such as "when did CRC errors start on this port?" has no data to answer it.
It doesn't break fresh clones, CI or production.

## Recommended fix

If long-term trends matter:

- Append timestamped snapshots, for example as JSON Lines, under the XDG state directory
  instead of overwriting one file.
- Keep the comparison baseline separate from the rolling snapshots.
- Cap retention.

Moving snapshot and baseline paths off the working-directory-relative `reports/` is also
needed for the MCP server to run as an installed uv tool.
