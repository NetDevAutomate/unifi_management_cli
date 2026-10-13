---
title: "With `XDG_CONFIG_HOME` set, the CLI and the MCP server search different config files"
date: 2026-10-04
status: resolved
resolved_by: e4d8191
severity: low
components: [cli, mcp]
found_by: docs and repo hygiene review (config reference)
---

# With `XDG_CONFIG_HOME` set, the CLI and the MCP server search different config files

## Problem

Without `--config` or `UNIFI_CONFIG`, the two entry points look for the env file in
different places once `XDG_CONFIG_HOME` is set:

| Step | `unifi-mapper`, `unifi-inventory` (`cli.get_default_config_path`) | `unifi-mcp` (`mcp.config.resolve_config_path`) |
| --- | --- | --- |
| 1 | `$XDG_CONFIG_HOME/unifi_management_cli/prod.env`, or the `~/.config` one when unset | `$XDG_CONFIG_HOME/unifi_management_cli/prod.env`, then `default.env` |
| 2 | `default.env` in the same directory | `~/.config/unifi_management_cli/prod.env`, then `default.env` |
| 3 | `./.env` in the working directory | the legacy `~/.config/unifi_network_mapper/prod.env`, with a warning |

So with `XDG_CONFIG_HOME` pointing somewhere without the file, `unifi-mcp` still finds
`~/.config/unifi_management_cli/prod.env`, while `unifi-mapper` falls through to `./.env`
and, when that doesn't exist, exits 1 with `Configuration file not found`. The MCP server
never reads a `.env` in the working directory; the CLI still does as its last resort.

`unifi-network-toolkit` and `python -m unifi_mapper.verify_cli` don't search at all: their
`--config` defaults to `~/.config/unifi_management_cli/prod.env`.

The README describes each search as it is; the docstring of `get_default_config_path` was
corrected to match the code in `e144067`.

## Impact

Only users who set `XDG_CONFIG_HOME` to a directory without the file are affected; on a
default macOS or Linux setup both searches find `~/.config/unifi_management_cli/prod.env`.
For them the CLI either fails or, worse, reads a stray `./.env`.

## Decision needed

Recommendation: give the CLI the MCP server's search, minus the working-directory `.env`
(with a deprecation warning for one release first), and share one function between them.

Why this needs a decision: anyone who relies on the CLI reading `./.env` would lose that
fallback, and the order changes which file wins when both directories hold one.

## Resolution

Resolved on 2026-10-13 (`e4d8191`), as the recommendation said and as the release council
decided. One function, `core/utils/config_search.find_config`, is now the search for every
entry point: `cli.get_default_config_path` (so `unifi-mapper`, `unifi-inventory`,
`unifi-network-toolkit` without `--config`, and the scripts that import it) and the MCP
server's `mcp.config.resolve_config_path` both call it. The order is the MCP server's:
`UNIFI_CONFIG` (never falls through), `$XDG_CONFIG_HOME/unifi_management_cli/{prod,default}.env`,
`~/.config/unifi_management_cli/{prod,default}.env`, then the legacy
`~/.config/unifi_network_mapper/prod.env` with the existing warning. The CLI therefore gains
the `~/.config` and legacy steps it never had.

The working-directory `./.env` is **kept for 0.3.0 at the lowest precedence only**: the CLI
consults it when nothing else was found, and then prints a deprecation warning on stderr
before any controller connection, naming `--config ./.env` / `UNIFI_CONFIG=./.env` as the
replacement and 0.4.0 as the release that removes it. The MCP server still never reads it.
The argparse `unifi-mapper` entry now runs the search after parsing, so `--help` and
`--version` do not warn about a file they do not load. The no-config error lists every path
of the shared search plus `./.env`.

Deliberately not changed: `unifi-network-toolkit` and `verify_cli` keep a fixed `--config`
default when one is given; only the default search is shared. The `inventory` subcommands'
own `--config` (issue 043) is untouched.

Tests: `tests/test_config_search.py` (one per precedence step, the CLI/MCP parity table,
the warning-before-client ordering through `discover --dry-run` and the argparse entry),
`tests/test_first_run_surface.py` (the no-config message lists the shared paths).
