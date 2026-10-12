---
title: "There is no on-disk history of port error counters"
date: 2026-10-02
status: resolved
resolved_by: 5885ece
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

## Resolution

Applied the recommended fix (approved, design §10.5):

- New `analysis/counter_history.py`: `analyze link-errors --record` appends one JSON line
  per switch per run to `$XDG_STATE_HOME/unifi_mapper/port-counter-history.jsonl` (schema
  version, time, device id/MAC/name, uptime, `last_seen`, and every port's state, error,
  drop, CRC, link-down and byte counters). The append holds an `fcntl.flock` on a sibling
  `.lock`; compaction (temp file + `os.replace`) runs only once the oldest line is a day past
  `--retention-days` (default 14, 1-365; it then drops every line older than the window) or
  the file passes the 64 MiB cap (it then trims to 80% of the cap), so a full file is not
  rewritten on every run (code-review F6). Each `--record` prints the days the file holds.
- The comparison baseline stays separate: only `--snapshot` sets it. The link-error
  baseline default moved off the working directory to
  `$XDG_STATE_HOME/unifi_mapper/link-error-baseline.json`; a legacy
  `./reports/link-error-baseline.json` is still read when the XDG file is absent, and is
  reported as legacy.
- `scripts/unifi-cron.sh`: the `link-error-snapshot` task (name kept, so `uninstall` still
  finds installed jobs) and `run-all` now run `analyze link-errors --record` instead of
  overwriting the baseline every 5 minutes. A schedule installed before this change keeps
  running `--snapshot` (resetting both baselines every 5 minutes, recording no history)
  until it is reinstalled: run `./scripts/unifi-cron.sh update` after upgrading; `status`
  flags the stale entry.
- Readers: `ports counters`, `ports diagnose`, `get_port_counter_rates` and
  `diagnose_switch_port` report `baselines.history` (`first_increase` per counter, deltas,
  resets, the newest 48 points). They never write; `ports counters --history PATH` reads
  another file.

Tests: `tests/analysis/test_counter_history.py`, `tests/test_cli_link_errors.py`, and
additions to `tests/test_port_history.py` and `tests/test_ports_cli.py`.
