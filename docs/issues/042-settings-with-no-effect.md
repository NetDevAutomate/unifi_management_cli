---
title: "Five documented settings have no effect on `unifi-mapper`"
date: 2026-10-04
status: open, decision needed
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
