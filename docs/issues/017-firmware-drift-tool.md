---
title: "Add a firmware drift tool (`get_firmware_drift`) and `inventory firmware-skew --json`"
date: 2026-10-02
status: open
severity: low
components: [inventory_cli, analysis, mcp/manifests/analysis.yaml]
found_by: MCP uvx standards work
---

# Add a firmware drift tool (`get_firmware_drift`) and `inventory firmware-skew --json`

## Problem

`unifi-mapper inventory firmware-skew` finds devices of the same model on different firmware,
but only prints a Rich table, and the logic lives in `inventory_cli.py` behind
`fetch_and_categorize_devices`, which uses the sync client, prints to the console and raises
`typer.Exit(1)` on failure (`inventory_cli.py:135`). MCP has `get_firmware_report`, but nothing
that answers "which devices are behind the fleet's newest firmware for their model?". This was
the design's tool T4 (priority P2), deferred by plan decision P4.

## Impact

Firmware drift, a frequent cause of inconsistent switch behaviour, can't be checked from an
assistant or scripted from JSON.

## Recommended fix

The design's spec (MCP_STANDARDS_REVIEW.md §3 T4):

- Move the pure `find_firmware_skew`, and the categorisation part of
  `fetch_and_categorize_devices` as
  `categorize_devices(devices: list[dict]) -> dict[str, list[dict]]`, into
  `analysis/firmware_drift.py`. `inventory_cli` re-exports `find_firmware_skew` so the existing
  test import keeps working; `fetch_and_categorize_devices` keeps its signature and calls
  `categorize_devices`.
- MCP: `get_firmware_drift(device_type: Literal['all', 'switch', 'ap', 'firewall'] = 'all')
  -> FirmwareDriftReport`, the same vocabulary as `inventory firmware-skew --filter`. Per
  model: versions → device names, `fleet_newest`, `devices_behind`, the controller's
  `upgradable`/`upgrade_to_firmware`, offline devices flagged.
- Data source: the MCP wrapper fetches `stat/device` through the async `UniFiClient` and calls
  the pure `categorize_devices` and `find_firmware_skew`. It must **never** call
  `fetch_and_categorize_devices` (Rich output and `typer.Exit` inside an MCP call).
- CLI: no new command. `inventory firmware-skew` gains `--json` (the `FirmwareDriftReport`
  dump) and opt-in `--show-upgradable` (adds the upgrade columns). The default table and
  `--stp-window` are unchanged.
- Manifest entry in `analysis.yaml` (`credentials: controller`, explicit title), bump
  `test_registry_totals`, offline tests for the pure core and the JSON parity.
