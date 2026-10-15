---
title: "`DeviceStatistics` reads keys the live `statistics/latest` endpoint does not send"
date: 2026-10-13
status: open
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
