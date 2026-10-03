---
title: "Root `--connected-devices`, `--verify-updates` and `--dry-run` are silently dropped before a subcommand"
date: 2026-10-03
status: open, decision needed
severity: medium
components: [typer_cli]
found_by: review follow-ups (code-review F11)
---

# Root `--connected-devices`, `--verify-updates` and `--dry-run` are silently dropped before a subcommand

## Problem

The root callback (`typer_cli.main`) turns its discover shortcuts into a `discover` run only
when `ctx.invoked_subcommand is None`. Typer parses each command level on its own, so a root
flag given before a subcommand is parsed, accepted and then ignored:

- `unifi-mapper --connected-devices discover` previews without connected devices (exit 0).
- `unifi-mapper --verify-updates discover` skips the smart mapper (exit 0).
- `unifi-mapper --dry-run <subcommand> …` never reaches the subcommand, so these four forms
  write although `--dry-run` was typed:
  - `unifi-mapper --dry-run discover --apply`
  - `unifi-mapper --dry-run ports refresh --apply`
  - `unifi-mapper --dry-run stp optimize --apply`
  - `unifi-mapper --dry-run stp apply --plan P --no-dry-run`

Checked offline with the `tests/test_discover_defaults.py` fakes: `--connected-devices
discover` and `--verify-updates discover` exit 0 with one preview and no smart-mapper call;
`--dry-run discover --apply` exits 0 with one write. The `ports refresh` and `stp` forms
follow from the code: each reads only its own flags.

Root `--apply` before a subcommand no longer has this problem: since code-review F11 it
exits 2 with `--apply must follow the subcommand and its arguments (e.g. unifi-mapper
discover --apply)` (`test_root_apply_before_a_subcommand_is_rejected`; code-review F26 made
the hint generic, so it also fits `ports refresh` and `stp`).

## Impact

Silent flag loss. The `--connected-devices` and `--verify-updates` forms produce a weaker
report than asked for. The four `--dry-run … --apply` / `--no-dry-run` forms write to the
controller although the operator typed `--dry-run`; the `stp` ones still ask for
confirmation unless `--force` is given, `discover --apply` and `ports refresh --apply` don't.

## Decision needed

Two fixes, each changing behaviour:

1. **Reject** any root discover shortcut given before a subcommand (exit 2, as root
   `--apply` does now). Explicit and decoupled, but `unifi-mapper --connected-devices
   discover` and `unifi-mapper --dry-run discover`, which exit 0 today, would start to fail.
2. **Forward** the root flags to the subcommand (for example through `state`). Keeps those
   invocations working, but couples the callback to every command that has its own
   `--dry-run`/`--apply`, and a root `--dry-run` would then have to win over a subcommand
   `--apply`.

Recommendation: forward into `discover` only, the one subcommand the shortcuts belong to
(store the three flags in `state`; `discover` adds `--connected-devices`/`--verify-updates`
and exits 2 when a root `--dry-run` meets its `--apply`), and exit 2 when any of the three
precedes another subcommand, which never reads them. That keeps `--dry-run discover` and
`--connected-devices discover` working and closes all four write forms; the cost is that
meaningless forms such as `unifi-mapper --dry-run ports list X` (exit 0 today) start to
fail. Extend `tests/test_discover_defaults.py` with every form above.
