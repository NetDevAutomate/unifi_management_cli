---
title: "The gateway ping step is written twice, in gateway ping and in AP-health's client pings"
date: 2026-10-06
status: open
severity: low
components: [connectivity/gateway_probe, analysis/ap_health]
found_by: 0.2.0 port review
---

# The gateway ping step is written twice, in gateway ping and in AP-health's client pings

## Problem

`gateway_probe.gateway_ping` (`unifi-mapper gateway ping`) and `ap_health._ping_clients`
(`diagnose ap-health --ping-clients`) each build the same command and handle it the same way:

- the argv `['ping', '-c', count, '-i', interval, '-W', '2', address]`;
- the bound `count × interval + 12` seconds for `run_gateway_command`;
- exit statuses 0 and 1 accepted as a result (`check_exit_status`), anything else an error;
- `parse_ping_output` on the output.

Only the session differs: `gateway_ping` opens its own, while `_ping_clients` pings every
client over the one session the capture holds. `diagnose latency-matrix` builds a third ping
argv, with a per-reply timeout and no interval, on purpose; it is not a copy.

This is the same kind of duplication as [issue 067](067-mcp-tool-failure-helper-duplicated.md).

## Impact

None today: the two copies agree. A change to one (the bound, an option, the statuses that
count as a result) can miss the other. Breaks fresh clones, CI or prod: no.

## Recommended fix

One helper in `connectivity/gateway_probe.py` that pings an address over an open connection,
for example `ping_over(conn, address, count, interval) -> PingStats`: it checks the address and
the bounds, builds the argv, runs it under the bound, checks the exit status and parses the
output. `gateway_ping` calls it inside its own session, and `_ping_clients` inside its
per-client `try`. Test that both callers' argv and bound come from it, and keep the existing
FakeSSH cases of both commands passing unchanged.
