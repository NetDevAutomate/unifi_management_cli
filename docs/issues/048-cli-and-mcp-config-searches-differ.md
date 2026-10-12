---
title: "With `XDG_CONFIG_HOME` set, the CLI and the MCP server search different config files"
date: 2026-10-04
status: open, decision needed
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
corrected to match the code in `838d902`.

## Impact

Only users who set `XDG_CONFIG_HOME` to a directory without the file are affected; on a
default macOS or Linux setup both searches find `~/.config/unifi_management_cli/prod.env`.
For them the CLI either fails or, worse, reads a stray `./.env`.

## Decision needed

Recommendation: give the CLI the MCP server's search, minus the working-directory `.env`
(with a deprecation warning for one release first), and share one function between them.

Why this needs a decision: anyone who relies on the CLI reading `./.env` would lose that
fallback, and the order changes which file wins when both directories hold one.
