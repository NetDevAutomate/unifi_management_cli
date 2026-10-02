---
title: "Radio snapshots and several baselines are written relative to the working directory"
date: 2026-10-02
status: open, decision needed
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
