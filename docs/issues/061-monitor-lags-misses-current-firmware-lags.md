---
title: "`monitor_lags` misses LAGs on current switch firmware"
date: 2026-10-05
status: open
severity: medium
components: [src/unifi_mapper/analysis/lag_monitoring.py]
found_by: 0.2.0 port (an untracked prototype test, kept in a local archive, not in the repo)
---

# `monitor_lags` misses LAGs on current switch firmware

## Problem

`monitor_lags` finds link aggregation groups only in a device's `port_aggregates` list
(`_extract_lag_groups` in `analysis/lag_monitoring.py`). A read-only capture taken in
September 2026 on current switch firmware showed `port_aggregates` empty while a LAG was up.
On that firmware the LAG is described by:

- `link_aggregation_groups`: `{lag_idx, aggregate_members: [port, …], type: 'lag'}`;
- `port_overrides`: the master port carries `op_mode: 'aggregate'`, `aggregate_members` and
  `lag_idx`;
- `port_table`: the master port carries `lacp_state`, a list of
  `{member_port, active, speed}`, which is the authoritative member state, and
  `partner_system_id`; each subordinate member is `masked: true` with `aggregated_by: <master
  port>` and a cosmetic `up: false, speed: 0` while it forwards traffic.

So `monitor_lags` reports no LAG where one exists, and a naive reading of the subordinate
port would call a healthy member down. `find_lag_candidates` can likewise propose a LAG over
ports that already form one (`_existing_lag_ports` also reads only `port_aggregates`).

An untracked test written against that capture (never committed; it held a real device name
and MAC) specifies the fix. Its cases, anonymised:

1. A LAG declared in `link_aggregation_groups` is found: one LAG, two expected members,
   members are the two declared ports.
2. A masked subordinate takes its state from the master's `lacp_state`, not from its own
   `up`/`speed`: it is active at the `lacp_state` speed; the LAG has two active members, the
   sum of both speeds as active bandwidth, and status `HEALTHY`.
3. A healthy LAG makes the report healthy: one healthy, none degraded or critical.
4. An inactive `lacp_state` entry degrades the LAG: one active member, status `DEGRADED`, the
   report not healthy.
5. `partner_system_id` from the master port is surfaced on the LAG group.
6. A LAG declared only in `port_overrides` (no `link_aggregation_groups`) is still found.
7. Legacy `port_aggregates` (`{member_ports: [...]}`) still works.
8. No LAG gives an empty report with a recommendation.
9. An unknown `device_id` raises `ToolError`.
10. `find_lag_candidates_from_data` excludes ports already in a modern LAG, even when both
    look like healthy parallel LLDP links to the same peer.
11. The core is pure: it does not mutate its input.

## Recommendation

Add a pure `monitor_lags_from_data(devices, device_id=None)` that reads
`link_aggregation_groups`, `port_overrides` with `op_mode: 'aggregate'` and the master port's
`lacp_state`, still reads legacy `port_aggregates`, and treats a `masked` subordinate with
`up: false, speed: 0` as not down; make `monitor_lags` a thin wrapper over it, and teach
`_existing_lag_ports` the same sources. Write the 11 cases above first, with documentation
values only. Confirm the field shapes with one read-only live capture (device level, scanned
by key path) before building, because the capture that showed them is not in the repo.

Breaks fresh clones, CI or prod: no (the tool under-reports; it writes nothing).
