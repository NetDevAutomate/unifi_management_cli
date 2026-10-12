---
title: "`unifi-network-toolkit discover` and `python -m unifi_mapper.cli` still write port names by default"
date: 2026-10-02
status: resolved
resolved_by: dd2b01b
severity: medium
components: [network_cli, cli]
found_by: MCP uvx standards work
---

# `unifi-network-toolkit discover` and `python -m unifi_mapper.cli` still write port names by default

## Problem

Issue 007 made `unifi-mapper discover` and the root shortcut preview by default, writing only
with `--apply`. The two argparse twins of the same workflow were left as they were:

- `unifi-network-toolkit discover` (`network_cli.py`): writes unless `--dry-run` is passed
  (`dry_run=args.dry_run`, `network_cli.py:300`).
- `python -m unifi_mapper.cli` (`cli.py`): the same (`cli.py:235`, `:259`).

Both reach the same `run_port_mapper` / `batch_update_port_names` path, which PUTs
`port_overrides` and force-provisions the switch.

## Impact

The same command name previews in one entry point and writes production port names in the
other. An operator who learned the new `unifi-mapper` default can write by accident.

## Resolution

Resolved 2026-10-12 in `dd2b01b`: both entry points preview unless `--apply`, keep `--dry-run`
as the accepted default and exit 2 when given both; `tests/test_argparse_discover_defaults.py`
pins each case. The readiness council named the old default a blocker for a shared repository.

## Decision needed (as filed)

Give both the same default as 007: preview unless `--apply`, keep `--dry-run` accepted, and
reject `--apply` with `--dry-run` (exit 2)?

Design recommendation: **yes, the same default as 007** (plan N1). Check `scripts/` and the docs
for any caller that relies on the old default and add `--apply` there, as 007 did for
`unifi-cron.sh`, and extend `tests/test_discover_defaults.py` to both entry points.
