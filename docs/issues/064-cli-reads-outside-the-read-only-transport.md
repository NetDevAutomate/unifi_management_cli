---
title: "CLI read commands that reach the controller outside the read-only transport"
date: 2026-10-05
status: resolved
resolved_by: 02bec3a
severity: medium
components: [src/unifi_mapper/typer_cli.py]
found_by: 0.2.0 port design (asyncio.run sites counted by AST)
---

# CLI read commands that reach the controller outside the read-only transport

## Problem

The 0.2.0 port moves `typer_cli.py`'s two async helpers, `_run_analysis` and
`_run_gateway_ssh`, behind the read-only transport: every command that runs through them
borrows one guarded controller client, so a write refuses before it leaves the host. The
rest of the CLI's async commands call `asyncio.run(...)` directly and each build their own
`UniFiClient`, outside that guard. Counted by AST after `diagnose latency-matrix` moved onto
`_run_gateway_ssh`: **47 direct sites**, pinned by `DIRECT_ASYNCIO_RUN_SITES` in
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
`DIRECT_ASYNCIO_RUN_SITES` in the same commit. Leave the write paths on their own guarded
plan, review and apply flow.

## Resolution

Resolved on 2026-10-13 (`02bec3a`). Every read path now runs through `_run_analysis`, so
the one `SharedControllerClient` that `_guarded` installs serves the command and a write is
refused before it leaves the host. The seven write paths listed above stay on their own
`asyncio.run`, and `DIRECT_ASYNCIO_RUN_SITES` in `tests/test_cli_guard.py` drops from 47 to 7.

Two counts in this issue were stale by the time of the fix: `diagnose all` was already on
`_run_analysis`, so there were 39 read sites (46 direct sites in all, under a ceiling of 47),
not 40. All 39 moved in one commit rather than one per group, so that every commit on the
branch is green; the commit body lists the groups.

Refinements of the recommended fix, from the code:

1. `stp optimize` and `stp report` compose their discovery, priority calculation and report
   into one coroutine (the latter two never touch the controller), so one login serves the
   command and the progress lines keep their order. `analyze link-errors --snapshot` writes
   its baseline inside the device read it already shared with `--record`.
2. Each command's own `load_env_from_config` call goes, because `_run_analysis` loads the
   config; a second call would log "Loaded configuration from" twice. `radio optimize` keeps
   its call, since `channel_moves_from_env()` must read the config before the controller is
   touched (a malformed rule exits 2 without a round trip), so that command logs the line
   twice, three times when applying. The write paths that follow a read (`stp optimize
   --apply`, `ports refresh --apply`, the radio applies) rely on the config the read loaded;
   a comment at each says so.
3. The commands that catch `Exception` around their read now re-raise `typer.Exit` first:
   `_run_analysis` reports a failure on stderr and raises `Exit(1)`, and `Exit` is an
   `Exception` subclass, so the old clause would have printed a second, empty "Error:" and
   masked the exit code. The same clause had been turning `stp optimize`'s cancelled
   confirmation (`Exit(0)`) into "Error:" and exit 1; it now exits 0 as written. A read
   failure in these commands prints `❌ Error: ...` on stderr instead of stdout, which keeps
   `--json` output parseable where a command has it; the text is unchanged.

Pinned in `tests/test_cli_guard.py`: for each of the 32 moved command invocations the first
controller read is replaced by a write through a fresh `UniFiClient()` and the guard's
`ReadOnlyViolation` is expected, with only the login on the shared mock transport; `radio
optimize`, which opens its client inline, is shown reading `stat/device` through that
transport. `tests/analysis/test_stp_optimizer.py` now patches
`typer_cli.load_env_from_config`, the seam `stp optimize` uses (it patched the local
`from .cli import` the command no longer has). The architecture overview and codemap no
longer say the CLI's other reads are outside the guard.
