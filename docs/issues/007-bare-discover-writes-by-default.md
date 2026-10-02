---
title: "`unifi-mapper --connected-devices` writes port names by default"
date: 2026-10-02
status: resolved
resolved_by: 27bca7c
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

## Resolution

Approved (design §10.5) and applied in `typer_cli.py`:

- `discover` takes `--apply/--dry-run` and defaults to a preview: it builds the report and
  diagram, prints `DRY RUN — run with --apply to write`, and passes `dry_run=True` to
  `run_port_mapper` and to the smart mapper. Only `--apply` writes port names.
- The root shortcut fires on any of `--connected-devices`, `--verify-updates`, `--dry-run` or
  the new `--apply`, and forwards `--apply`. `--dry-run` is still accepted; `--apply` together
  with `--dry-run` exits 2 ("choose --apply or --dry-run").
- `scripts/unifi-cron.sh`: the `port-naming` task and `run-all` now pass `--apply`, so an
  installed schedule keeps writing port names, now explicitly.
- The README, the operator runbook and the use-cases guide add `--apply` wherever they
  describe writing names.

Tests: `tests/test_discover_defaults.py` (every invocation form, zero write calls on the
default path, the cron task line). The argparse twins (`unifi-network-toolkit discover`,
`python -m unifi_mapper.cli`) still write by default; that is tracked as issue 015.
