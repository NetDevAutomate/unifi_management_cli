---
title: "The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory"
date: 2026-10-05
status: open, decision needed
severity: low
components: [cli, mcp/config, scripts/site_targets.py, scripts/unifi-mcp-launch.sh]
found_by: July port review follow-up (iteration 6, while fixing the relative `XDG_STATE_HOME`)
---

# The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory

## Problem

The XDG Base Directory spec says every path in its variables must be absolute, and a relative
one must be ignored. The July port made `state_dir()` follow that rule for `XDG_STATE_HOME`.
The four config searches still use any non-empty `XDG_CONFIG_HOME`:

- `get_default_config_path()` in `src/unifi_mapper/cli.py` (the CLI's search);
- `resolve_config_path()` in `src/unifi_mapper/mcp/config.py` (the MCP server's search);
- `default_path()` in `scripts/site_targets.py`;
- `ENV_FILE` in `scripts/unifi-mcp-launch.sh`.

With `XDG_CONFIG_HOME=conf`, each of them reads `conf/unifi_management_cli/...` under the
directory the command is run from. The MCP server's `--config` help says a `.env` in the
working directory is never read, but this path is just as relative.

## Impact

A config file under the directory a command runs from (a cloned repository, a download
folder) could be loaded as the controller config, the MCP server's included. That needs a
relative `XDG_CONFIG_HOME`, which the spec calls invalid, so it is rare. Breaks fresh clones,
CI or prod: no.

## Decision needed

Recommendation: ignore a relative `XDG_CONFIG_HOME` in all four places, as `state_dir()`
now does for `XDG_STATE_HOME`, with one test per search (`'conf'`, `'./conf'`, `'~/conf'`).
It is a decision because it changes which config file is found when the variable is
relative: the search then goes to `~/.config` instead.
