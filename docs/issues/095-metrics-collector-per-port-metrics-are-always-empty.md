---
title: "`DeviceMetricsCollector` per-port metrics are always empty: `statistics/latest` sends no ports"
date: 2026-10-15
status: open, decision needed
severity: low
components: [network/statistics, network/models]
found_by: 0.4.0 lane 2a (issue 081 fix, live capture)
---

# `DeviceMetricsCollector` per-port metrics are always empty: `statistics/latest` sends no ports

## Problem

`src/unifi_mapper/network/statistics.py` aggregates per-port figures from the Integration API's
`/devices/{id}/statistics/latest` answer: `DeviceMetrics.port_metrics` (line 88),
`get_top_ports_by_throughput` (line 102) and `get_error_ports` (line 111), fed by
`DeviceMetricsCollector._port_metrics` (line 149). The live answer, captured read-only on
2026-10-15 for issue 081, carries `uptimeSec`, heartbeat times, CPU and memory percentages,
`uplink` rates and `interfaces` (radios); it sends no `ports` array and no
`temperatureCelsius`. The reference's example for the endpoint sends neither either. So for a
live device the three port views are always empty and `temperature_celsius` is always `None`,
while the model keeps both fields and the collector's API offers them.

## Evidence

Issue 081's Resolution and `tests/network/test_device_statistics_shape.py` (the captured
live switch answer and the reference example, both without `ports`).

## Impact

Low: no CLI command or MCP tool surfaces the collector's port views (checked: no caller outside
`network/statistics.py` reads `port_metrics`, `get_top_ports_by_throughput` or
`get_error_ports`). A library caller gets empty results with no indication that the source
never has the data. Per-port counters are available from the classic API path the
port-diagnostics tools already use. Breaks fresh clones, CI or prod: no.

## Recommended fix

Decision needed: (a) remove the port aggregation and `temperature_celsius` from the Integration
API collector and model, documenting that per-port counters come from the classic
`stat/device` path; or (b) keep the fields and source them from the classic path inside the
collector. (a) is the smaller change and matches what the endpoint sends; it is Breaking for
library callers of `DeviceMetrics`.
