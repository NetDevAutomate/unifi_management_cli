---
title: "The port counter baseline store has no producer"
date: 2026-10-02
status: resolved
resolved_by: 5885ece
severity: low
components: [analysis/port_counter_baseline, port_history]
found_by: port diagnostics gap analysis (F4)
---

# The port counter baseline store has no producer

## Problem

`analysis/port_counter_baseline.py` can snapshot per-port error counters from an STP
topology (`snapshots_from_switches`), persist them with `PortCounterBaselineStore.save`
to `$XDG_STATE_HOME/unifi_mapper/port-counters.json`, and diff against them
(`diff_since_last`). Nothing calls `save()` or `snapshots_from_switches()`. No command,
MCP tool or analysis module produces the store.

The only reader is `port_history.read_counter_baselines`, behind `ports counters`,
`ports diagnose`, `get_port_counter_rates` and `diagnose_switch_port`. It reads the store
when the file exists and never writes it. As a result `port_counter_baseline.found` is
false everywhere, unless something outside this repo wrote the file.

The codemap (§20.4) described `stp_optimizer.py` as the store's producer and consumer.
That was corrected when this issue was filed.

## Impact

Dead code, and a section of the counter report that is always empty. It doesn't break
fresh clones, CI or production.

## Decision needed

Choose one:

1. **Wire it in.** `stp validate-10g` already reads per-port error counters for its
   readiness findings. Have it report `diff_since_last`, and save a snapshot only behind
   an explicit flag, so a plain run stays read-only.
2. **Delete it.** Remove the module, its exports in `analysis/__init__.py`, its tests and
   the `port_counter_baseline` part of `port_history.CounterBaselines`.

Option 1 overlaps issue 004 (no counter history).

## Resolution

Option 1, wired in through `analyze link-errors` rather than `stp validate-10g` (approved
with issue 004, design §10.5):

- `analysis/port_counter_baseline.py` gains `state_dir()` (the existing
  `$XDG_STATE_HOME/unifi_mapper` root; `default_baseline_path()` is unchanged) and pure
  `snapshots_from_devices(devices)` (switch-type devices with an `_id`; CRC from the same
  source as the port diagnostics).
- `analyze link-errors --snapshot` is the producer: `snapshot_link_errors` writes the
  link-error baseline and `PortCounterBaselineStore().save(snapshots_from_devices(...))`
  from one device read. Nothing else writes the store; plain runs stay read-only.
- `port_history.read_counter_baselines` still only reads it, so `port_counter_baseline` in
  `ports counters`, `ports diagnose`, `get_port_counter_rates` and `diagnose_switch_port`
  is now populated once a baseline has been set.
- Upgrade note: a cron/launchd schedule installed before this change still runs
  `analyze link-errors --snapshot` every 5 minutes, which now also overwrites this store, so
  comparisons would be against a baseline at most 5 minutes old. Run
  `./scripts/unifi-cron.sh update` after upgrading (see issue 004).

Tests: `tests/test_cli_link_errors.py` (`--snapshot` writes both baselines and no history).
