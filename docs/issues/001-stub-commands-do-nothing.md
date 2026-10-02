---
title: "`find device`, `analyze link-quality` and `diagnose health` are stubs"
date: 2026-10-02
status: open
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
