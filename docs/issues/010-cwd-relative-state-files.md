---
title: "Radio snapshots and several baselines are written relative to the working directory"
date: 2026-10-02
status: resolved
resolved_by: edae795
severity: medium
components: [analysis/radio_config, analysis/config_drift, analysis/roaming_analysis, analysis/neighbour_trend, analysis/rf_strategy, typer_cli]
found_by: MCP uvx standards work
---

# Radio snapshots and several baselines are written relative to the working directory

## Problem

Issues 002 and 004 moved the link-error baseline, the port-counter baseline and the new
counter history under `$XDG_STATE_HOME/unifi_mapper/`. Other state files still default to a
`reports/` directory under the current working directory:

| File | Written by | Default |
| --- | --- | --- |
| Radio snapshot | `snapshot_radio_config_mcp` (MCP tool `snapshot_radio_config`, `writes_local: true`), `radio snapshot`/`radio optimize`/`radio restore` | `reports/radio-snapshot.json` (`analysis/radio_config.py:368`) |
| Config-drift baseline | `analyze config-drift` | `reports/config-baseline.json` (`analysis/config_drift.py:14`) |
| Roaming history | `analyze roaming`, `rf_strategy` | `reports/client-roaming-history.json` (`analysis/roaming_analysis.py:15`, `rf_strategy.py:957`) |
| Neighbour baseline | `analyze neighbours` | `reports/neighbour-baseline.json` (`analysis/neighbour_trend.py:24`) |

## Impact

Under uvx the MCP server's working directory is whatever the client chose, often `/` (read-only
on macOS) or the user's home. `snapshot_radio_config` over MCP then fails, or writes a snapshot
nobody can find; the restore command needs its path. For the CLI, a cron job and an interactive
run started in different directories compare against different baselines. It doesn't break
fresh clones or CI.

## Decision needed

Design decision D3: in MCP mode, should `snapshot_radio_config` write
`$XDG_STATE_HOME/unifi_management_cli/reports/radio-snapshot-<timestamp>.json` and return the
**absolute path** plus the exact `unifi-mapper radio restore --snapshot <abs path>` command
(the CLI keeps its relative default)? And should `execute_tool` refuse `writes_local` tools
outright?

Design recommendation: **approve the move, reject the refusal** (refusing would remove a
working capability). Use the existing state root `$XDG_STATE_HOME/unifi_mapper/` (plan P11)
rather than a second one. Then move the config-drift, roaming and neighbour defaults the same
way issue 002/004 moved the link-error baseline: explicit path wins, then the XDG file, then a
legacy `./reports/` file reported as legacy. That also unblocks exposing them over MCP
(issue 018, B6 and B9).

## Resolution

Resolved on 2026-10-13 (`edae795`), the way the recommendation and the release council
decided: **the move is approved, the refusal is rejected** (`writes_local` tools keep working
over MCP). One state root, the existing `state_dir()` of `analysis/port_counter_baseline.py`
(`$XDG_STATE_HOME/unifi_mapper/`, `~/.local/state/unifi_mapper/` when unset; a relative
`XDG_STATE_HOME` is ignored), now holds every default in the table above:

| File | Default |
| --- | --- |
| Radio snapshot | `radio_config.default_radio_snapshot_path()` -> `radio-snapshot.json`; the pre-apply snapshots `radio-pre-optimization.json` and `radio-pre-autochannel.json` beside it |
| Config-drift baseline | `config_drift.default_config_baseline_path()` -> `config-baseline.json` |
| Roaming history | `roaming_analysis.default_roaming_history_path()` -> `client-roaming-history.json`; `rf_strategy.generate_plan` and the `rf_simulator` entry points share it |
| Neighbour baseline | `neighbour_trend.default_neighbour_baseline_path()` -> `neighbour-baseline.json` |

Each default is read at call time (the functions take `None`, not a frozen string default),
so a changed `XDG_STATE_HOME` takes effect without re-import. An explicit path given by option
or argument is unchanged. The Typer options (`radio snapshot --output`, `radio optimize
--snapshot`, `radio restore --snapshot`, `analyze roaming --history`, `analyze config-drift
--baseline`, `analyze neighbours --baseline`) default to `None` and name the XDG default in
`--help`. Over MCP, `snapshot_radio_config` returns `file`, the absolute path it wrote, and
`restore_command`, exactly `unifi-mapper radio restore --snapshot <path>` with the path
through `shlex.quote`, so a path with a space round-trips; the restore previews by default.
The MCP snapshot is not timestamped: it is the same file `radio restore` reads by default, so
the CLI and the tool share one restore point. The `DEFAULT_CONFIG_PATH`,
`DEFAULT_ROAMING_PATH` and `DEFAULT_BASELINE_PATH` string constants are gone (nothing outside
the package imported them).

Deliberately not changed: files written by earlier releases under `./reports/` are **not**
moved and **not** read as a legacy fallback (unlike the link-error baseline of issues 002/004):
pass the old path explicitly once (`analyze config-drift --baseline
./reports/config-baseline.json`) or move the file into the state directory. The legacy
`port_history.DEFAULT_LINK_ERROR_BASELINE` constant the issue lists is unused and names a
file issue 004 already moved; it is left as is. The MCP compare tools (issue 078) still
require an absolute path argument and never write.

Tests: `tests/analysis/test_state_file_defaults.py` (each default under a monkeypatched
`XDG_STATE_HOME`, a relative `XDG_STATE_HOME` ignored, explicit paths honoured, no
`'reports/` literal left in the five modules, the snapshot tool's absolute path and
space-safe restore command, the pre-optimisation snapshot location). Docs:
`docs/reference/cli.md` (new "Radio snapshots and the other baselines" table with the
migration note), README known limitations, `MCP_STANDARDS_REVIEW.md` A17 and D3.
