---
title: "`DeviceStatistics` reads keys the live `statistics/latest` endpoint does not send"
date: 2026-10-13
status: resolved
resolved_by: a434b7a
severity: medium
components: [network/models, network/statistics]
found_by: the 0.3.0 Integration API lane, after fixing issue 035
---

# `DeviceStatistics` reads keys the live `statistics/latest` endpoint does not send

## Problem

`network/models.py` `DeviceStatistics` (line ~200) declares `uptimeSeconds`, `lastSeen`,
`cpuMemory` and `ports`. The live `GET .../devices/{id}/statistics/latest` answer, as
`port_diagnostics.py` lines 1665-1668 and the `tests/fixtures_unifi.py` capture show, carries
`uptimeSec`, `lastHeartbeatAt`, `cpuUtilizationPct` and `memoryUtilizationPct`. None of the
model's aliases match.

## Impact

Since issue 035 moved the client onto the documented path, `DeviceMetricsCollector` reaches the
endpoint and parses a valid answer into zeros and `None`s. A consumer sees a device with 0 s
uptime and no CPU figure rather than an error.

## Recommended fix

Alias the four keys the endpoint sends (keep the old names as fallbacks only if a capture shows
them), drop or verify the rest against the v10.6 reference, and pin the model with a fixture
test built from the capture in `tests/fixtures_unifi.py`.

## Resolution (2026-10-15)

The defect was larger than recorded: a live answer did not parse into zeros, it failed
validation, because the model declared `interfaces` a list and the endpoint sends an object
(`{}` for a switch). `DeviceStatistics` now aliases the keys the endpoint sends: `uptimeSec`,
`lastHeartbeatAt`, `nextHeartbeatAt`, `cpuUtilizationPct`, `memoryUtilizationPct`,
`loadAverage1Min` / `5Min` / `15Min`, `uplink` (`txRateBps`, `rxRateBps`) and `interfaces`
(`radios`: `frequencyGHz`, `txRetriesPct`). A figure the device did not send is `None`, not 0,
and an unknown key is kept in `model_extra`. No capture showed the old keys, so they are not
kept as fallbacks. `DeviceMetricsCollector` reads the flat percentages. `port_diagnostics.py`
reads the raw answer, not the model, and is unchanged.

The model's Python attributes changed for library callers: `last_seen` is now
`last_heartbeat_at`, and `cpu_memory` is replaced by `cpu_utilization_pct` and
`memory_utilization_pct`. No CLI or MCP output serialises this model.

Pinned by `tests/network/test_device_statistics_shape.py`: a live switch answer captured
read-only on 2026-10-15, the reference's example for the endpoint, the shared fixture
(`fake_statistics_latest` in `tests/fixtures_unifi.py`, now in the live shape), the client over
a mock transport and the metrics collector.

What a user sees: `get_device_statistics` returns the device's uptime, CPU and memory instead
of raising; the metrics collector reports them instead of logging a collection failure.
`ports` and `temperature_celsius` remain on the model but the endpoint sends neither, so
per-port metrics from the collector stay empty for a live device.
