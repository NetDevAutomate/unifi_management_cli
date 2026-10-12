---
title: "`inventory update-firmware` writes after a confirmation prompt, not a preview"
date: 2026-10-12
status: resolved
resolved_by: 40b8653
severity: medium
components: [inventory_cli, README, SECURITY]
found_by: readiness review, validation council (openai.gpt-6-astra, lens 3)
---

# `inventory update-firmware` writes after a confirmation prompt, not a preview

## Problem

Every other command that writes to the controller previews by default and writes only with
`--apply` or `--no-dry-run` (issues 007, 015; `stp apply`, `stp optimize`, `radio optimize`,
`radio restore`, `ports refresh`, `discover`). `inventory update-firmware` is the one
exception: it has `--dry-run` (opt-in preview) and otherwise starts the upgrades after a
`y/N` prompt, which `--force` skips (`src/unifi_mapper/inventory_cli.py`, the
`update_firmware` command). The README's safety model says so plainly ("the firmware command
asks for confirmation instead"), but the rule the rest of the tool follows is that the
*default* is the preview.

## Impact

An operator who learned the tool's rule can run `unifi-mapper inventory update-firmware
--filter all` expecting a preview and get a prompt that, answered `y`, upgrades every matching
device. A firmware upgrade reboots devices. Breaks fresh clones, CI or prod: no (interactive
prompt; `--force` is explicit).

## Resolution

Resolved 2026-10-12: `update-firmware` previews by default; `--apply` triggers the upgrades after
the confirmation that `--force` skips; `--force` alone previews and says so; `--dry-run` with
`--apply` exits 2 before any controller call. README, `docs/reference/cli.md`, the `--help` text
and the `check-updates` hints describe the new default; `tests/test_inventory_firmware_defaults.py`
covers each case at the module seams.

## Decision needed (as filed)

Make `update-firmware` preview by default and write only with `--apply` (keeping `--force` to
skip the confirmation that `--apply` would still ask for), as the other writers do? That is a
behaviour change for anyone scripting it today with `--force`, which would then need
`--apply --force`.

Recommendation: yes, the same default as the rest; update the README safety model and
`docs/reference/cli.md` in the same change, and extend `tests/test_argparse_discover_defaults.py`'s
pattern to it.
