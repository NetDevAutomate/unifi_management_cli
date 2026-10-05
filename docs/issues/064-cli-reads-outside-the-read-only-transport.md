---
title: "CLI read commands that reach the controller outside the read-only transport"
date: 2026-10-05
status: open
severity: medium
components: [src/unifi_mapper/typer_cli.py]
found_by: July port design (asyncio.run sites counted by AST)
---

# CLI read commands that reach the controller outside the read-only transport

## Problem

The July port moves `typer_cli.py`'s two async helpers, `_run_analysis` and
`_run_gateway_ssh`, behind the read-only transport: every command that runs through them
borrows one guarded controller client, so a write refuses before it leaves the host. The
rest of the CLI's async commands call `asyncio.run(...)` directly and each build their own
`UniFiClient`, outside that guard. Counted by AST after `diagnose latency-matrix` moved onto
`_run_gateway_ssh`: **47 direct sites**, pinned by `I6_DIRECT_SITES` in
`tests/test_cli_guard.py`.

Read paths (40 sites), by command:

| Command | Sites |
| --- | --- |
| `analyze port-profiles`, `lag-candidates`, `mtu`, `radio`, `sfp`, `vlan-coverage`, `uplink-transparency`, `power-budget`, `traffic-matrix` | 1 each (9) |
| `analyze link-errors` | 3 |
| `analyze roaming` | 2 |
| `analyze config-drift` | 2 |
| `analyze neighbours` | 3 |
| `diagnose all`, `diagnose inter-vlan` | 1 each (2) |
| `stp analyze`, `snapshot`, `diff`, `preflight`, `guard`, `drift`, `validate-10g` | 1 each (7) |
| `stp optimize` (topology and priorities) | 2 |
| `stp report` | 3 |
| `ports refresh` (the preview) | 1 |
| `radio snapshot`, `radio report` | 1 each (2) |
| `radio optimize` (the read and the snapshot before applying) | 2 |
| `radio auto-channel` (the channel read and the snapshot before applying) | 2 |

Write paths (7 sites), **out of scope** because they must write: `stp optimize --apply`,
`stp apply`, `stp rollback`, `ports refresh --apply`, `radio optimize` when applying,
`radio restore`, `radio auto-channel` when applying.

## Impact

No read command is known to send a write. Outside the guard, a write introduced into one of
these paths would reach the controller; behind it, the write would be refused before it left
the host. Breaks fresh clones, CI or prod: no.

## Recommendation

Move each read path onto `_run_analysis`, one commit per command group, test first, and lower
`I6_DIRECT_SITES` in the same commit. Leave the write paths on their own guarded plan, review
and apply flow.
