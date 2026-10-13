---
title: "The Integration API client's device-statistics and port-action paths aren't served"
date: 2026-10-03
status: resolved
resolved_by: b975340
severity: low
components: [network/client, network/statistics]
found_by: review follow-ups (checking the client against the reference)
---

# The Integration API client's device-statistics and port-action paths aren't served

## Problem

While moving the ACL-rule and DNS-policy paths (issues 031 and 032), two more
`UniFiNetworkClient` paths turned out to differ from Ubiquiti's Network API reference for
v10.6.102:

- `get_device_statistics` reads `/sites/{siteId}/devices/{deviceId}/statistics`; the
  reference has `/sites/{siteId}/devices/{deviceId}/statistics/latest`.
- `execute_port_action` posts to `/sites/{siteId}/devices/{deviceId}/ports/{portIdx}/actions`;
  the reference has `/sites/{siteId}/devices/{deviceId}/interfaces/ports/{portIdx}/actions`.

## Evidence

A read-only probe on Network 10.6.106 (GET only, through `ReadOnlyAsyncTransport` with the
GET-only policy and the request audit on; one access point, not the held `USW Flex XG`):
`/statistics` answered 404 and `/statistics/latest` answered 200 (4 audited GETs, 0
violations; local evidence recorded at `85551d1`, not in the repo). The port
action is a write, so it was not probed; the reference is the only evidence for it. The
port diagnostics' own Integration API reads already use `/statistics/latest`.

## Impact

Library callers only: `DeviceMetricsCollector` (`network/statistics.py`) is the only user of
`get_device_statistics`, nothing calls `execute_port_action`, and no MCP tool or CLI uses
either (the MCP `network_api` tools would refuse the POST anyway). Their calls fail with a
404. It doesn't break fresh clones or CI.

## Recommended fix

Move both to the documented paths, with `httpx.MockTransport` tests that pin them as
`tests/network/test_client_paths.py` does for 031 and 032. Consider issue 003 (the plural
`/integrations` base path) at the same time.

## Resolution

Resolved on 2026-10-13 (`b975340`), as recommended. `get_device_statistics` reads
`/sites/{siteId}/devices/{deviceId}/statistics/latest` and `execute_port_action` posts to
`/sites/{siteId}/devices/{deviceId}/interfaces/ports/{portIdx}/actions`. Both are pinned by
`tests/network/test_client_device_paths.py` with `httpx.MockTransport`, which also shows the
GET-only guard refuses the port action before it is sent (only the base-path probe of issue
003 reaches the transport).

Interaction with issue 003: none in the paths themselves. The client's paths are relative to
the resolved `/v1` base, so they are the same whichever of the two bases answers the probe;
the port action was not probed live (it is a write), so the reference remains its only
evidence.

Not changed: `DeviceStatistics` still models the keys the client was written for
(`uptimeSeconds`, `lastSeen`, `cpuMemory`, `ports`, `interfaces`), not the keys the live
`statistics/latest` carries (`uptimeSec`, `lastHeartbeatAt`, `cpuUtilizationPct`,
`memoryUtilizationPct`, as `port_diagnostics` reads them and `tests/fixtures_unifi.py`
serves them). This issue is about the path; the model drift is reported separately so the
coordinator can file it.
