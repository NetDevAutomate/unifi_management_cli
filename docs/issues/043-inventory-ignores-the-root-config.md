---
title: "`unifi-mapper inventory` ignores the root `--config` and `UNIFI_CONFIG`"
date: 2026-10-04
status: open
severity: medium
components: [inventory_cli, typer_cli]
found_by: docs and repo hygiene review (config reference)
---

# `unifi-mapper inventory` ignores the root `--config` and `UNIFI_CONFIG`

## Problem

Every other `unifi-mapper` command reads the env file named by the root `--config`, or by
`UNIFI_CONFIG` (the root option's environment variable). The four inventory commands
(`inventory list`, `check-updates`, `firmware-skew`, `update-firmware`) come from
`inventory_cli.inventory_app` and take only their own `--config` option. Without it,
`get_api_client` falls back to `get_default_config_path()`
(`src/unifi_mapper/inventory_cli.py:95-100`); the root value never reaches them.

Checked offline with `typer.testing.CliRunner` and a fake `get_api_client`:
`unifi-mapper --config X inventory list` and `UNIFI_CONFIG=X unifi-mapper inventory list`
both called it with `None`, so the default config path was used.

## Impact

With more than one site, `unifi-mapper --config site-b.env inventory update-firmware` reads
the default config and acts on that controller. `update-firmware` asks for confirmation
unless `--force` is given, which limits the damage. Nothing breaks for fresh clones or CI.

## Recommended fix

When an inventory command's own `--config` is not given, use the root value: read it from
the parent context (`ctx.find_root().params['config']`) or keep it in `ctx.obj`, so the
order matches the other commands (`--config`, then `UNIFI_CONFIG`, then the default path).
Add a CLI test for each of the four commands. Until then, give the inventory commands
their own `--config` after the subcommand.
