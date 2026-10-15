---
title: "Five documented settings have no effect on `unifi-mapper`"
date: 2026-10-04
status: resolved
resolved_by: 38594dd
severity: low
components: [config, cli, typer_cli, api_client]
found_by: docs and repo hygiene review (config reference)
---

# Five documented settings have no effect on `unifi-mapper`

## Problem

`.env.example` documented five settings that the main CLI never applies:

- `UNIFI_DEFAULT_FORMAT`, `UNIFI_OUTPUT_DIR` and `UNIFI_DIAGRAM_DIR`. `UnifiConfig.from_env`
  reads them (`src/unifi_mapper/config.py:109-111`), but only the legacy
  `python -m unifi_mapper.cli` uses them (`src/unifi_mapper/cli.py:188-201`).
  `unifi-mapper discover` always defaults to `--format png`,
  `./reports/port_mapping_report.md` and `./diagrams/network_diagram.<format>`
  (`src/unifi_mapper/typer_cli.py`, `discover`). The file said the format setting applied
  whenever `--format` was not given.
- `UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY`. `UnifiConfig` reads and clamps them
  (`config.py:106-107`), but no caller passes them to `UnifiApiClient`, which keeps its
  defaults of 3 attempts and a 1.0 s back-off (`src/unifi_mapper/api_client.py:132-133`).

`.env.example` now lists all five under "Settings with limited or no effect".

## Impact

A user who sets any of them sees no change and no warning. The defaults the docs gave match
the built-in ones, so nothing behaves differently from a default configuration.

## Decision needed

Recommendation: make them work. Apply the three output settings in `discover` when the
matching option is not given, and pass the two retry settings to `UnifiApiClient` wherever
`UnifiConfig` builds a client. The alternative is to drop them from `UnifiConfig` and the
docs.

Why this needs a decision: wiring them in changes what `discover` writes, and how often
requests retry, for anyone whose config file already sets them.

## Resolution

Resolved on 2026-10-13 (`38594dd`), the recommended way: the five settings work.

- `UNIFI_DEFAULT_FORMAT`, `UNIFI_OUTPUT_DIR` and `UNIFI_DIAGRAM_DIR` are `discover`'s
  defaults when `--format`, `--output` or `--diagram` is not given. `--format` now defaults
  to none rather than `png`, so a typed `--format png` and no `--format` can be told apart
  (the help shows `[default: UNIFI_DEFAULT_FORMAT, or png]`); the root shortcuts pass no
  format either. A `~` in the two directories is expanded, as `.env.example`'s
  `~/Documents/...` examples need.
- `UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` reach `UnifiApiClient` from every place a
  `UnifiConfig` builds a client: `discover` and `diagram` (through `UnifiPortMapper`, which
  gains the two parameters and hands them on), `_readonly_client` (the read-only
  diagnostics), `verify_cli`, the legacy `python -m unifi_mapper.cli` and
  `unifi-network-toolkit`'s mapper and two enhanced clients. The clients clamp the values
  to the same 1-10 and 0.1-10.0 ranges `UnifiConfig` does.

The user-visible change is for anyone whose config file already set them: `discover` now
writes where and in the format the file says, and requests retry as the file says.
`.env.example` documents the five again (they were dropped as no-effect in `c47698d`); the
runbook's settings table, the guide and the architecture docs describe the new behaviour.
Deliberately not changed: `inventory_cli`, `diagnostics/inspect_port` and
`port_diagnostics_tools` build their clients from `Credentials`, not `UnifiConfig`, and keep
the defaults; the MCP server's async client has its own retry settings. Tests:
`tests/test_config_settings_apply.py`, one per setting at `discover`'s seam, plus the mapper
and `_readonly_client` hand-offs.
