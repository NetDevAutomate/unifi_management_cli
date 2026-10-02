---
title: "`find device`, `analyze link-quality` and `diagnose health` are stubs"
date: 2026-10-02
status: resolved
severity: low
components: [typer_cli]
found_by: port diagnostics gap analysis (F3)
---

# `find device`, `analyze link-quality` and `diagnose health` are stubs

## Problem

Three `unifi-mapper` commands print a pointer and exit 0 without doing anything:

| Command | Function in `typer_cli.py` | What it prints |
|---|---|---|
| `find device QUERY` | `find_device` | "Integration with enhanced device discovery in network_cli" |
| `analyze link-quality` | `analyze_link_quality` | A pointer to `unifi-network-toolkit analyze link-quality` |
| `diagnose health` | `diagnose_health` | A pointer to `unifi-network-toolkit diagnose network-health` |

The README Command Reference describes all three as working: "Find a device by name, IP
or MAC", "Port statistics and error rates" and "Overall network health check".

## Impact

The command looks as if it ran and found nothing, which misleads an operator. It doesn't
break fresh clones, CI or production, and nothing is written.

## Recommended fix

Wire each command to the read-only implementation that already exists:

- `find device` → `discovery/find_device.py` `find_device()`
- `analyze link-quality` → `analysis/link_quality.py` `analyze_link_quality()`
- `diagnose health` → `diagnostics/network_health.py` `network_health_check()`

Add one CLI test per command using the in-memory transport in `tests/fixtures_unifi.py`.
If they shouldn't be wired up, remove the commands and their README rows instead.

## Resolution

Applied the recommended fix in `typer_cli.py`; argument names and positions are unchanged:

- `find device QUERY [--json]` calls `discovery.find_device.find_device(identifier=QUERY)`
  and prints the matched device as a table, or its `model_dump` with `--json`.
- `analyze link-quality [--device ID] [--include-healthy] [--json]` calls
  `analysis.link_quality.analyze_link_quality(device_id=…, include_healthy=…)`. `--device`
  matches a device `_id` or MAC, as the implementation does.
- `diagnose health [--detailed] [--json]` calls
  `diagnostics.network_health.network_health_check()`; `--detailed` adds the per-device
  rows (high CPU, memory and load, uplink issues, outdated firmware) to the table.

A domain `ToolError` (for example `DEVICE_NOT_FOUND`) prints its message in red on stderr
and exits 1. Tests: `tests/test_cli_stub_commands.py` (implementations monkeypatched; the
JSON equals `model_dump`; not found exits 1 with the message).
