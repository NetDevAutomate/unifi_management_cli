---
title: "`unifi-mapper --connected-devices` writes port names by default"
date: 2026-10-02
status: open, decision needed
severity: medium
components: [typer_cli, run_methods, port_mapper]
found_by: port diagnostics gap analysis (F2)
---

# `unifi-mapper --connected-devices` writes port names by default

## Problem

The root callback turns a bare `unifi-mapper --connected-devices` (or `--verify-updates`)
into `discover`. That runs `run_port_mapper(dry_run=False)`. When a port label differs
from LLDP or client data, `batch_update_port_names` PUTs `port_overrides` and sends
`force-provision` to the switch. Only `--dry-run` makes the command read-only.

Until commit `9648851` (`docs(readme): stop calling --connected-devices read-only`), the
README called the command "(read-only)".

## Impact

An operator can write to production while expecting only a report. The README is now
accurate. The default behaviour hasn't changed.

## Decision needed

Should `discover`, and the bare-flag shortcut, default to a dry run and require an
explicit `--apply`, as `ports refresh` already does? That would change behaviour for
anyone who relies on today's default, so it hasn't been made without a decision.
