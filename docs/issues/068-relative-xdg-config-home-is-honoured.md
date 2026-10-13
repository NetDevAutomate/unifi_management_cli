---
title: "The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory"
date: 2026-10-05
status: resolved
resolved_by: e4d8191
severity: low
components: [cli, mcp/config, scripts/site_targets.py, scripts/unifi-mcp-launch.sh]
found_by: 0.2.0 port review follow-up (while fixing the relative `XDG_STATE_HOME`)
---

# The config searches honour a relative `XDG_CONFIG_HOME`, so they can read a file under the working directory

## Problem

The XDG Base Directory spec says every path in its variables must be absolute, and a relative
one must be ignored. The 0.2.0 port made `state_dir()` follow that rule for `XDG_STATE_HOME`.
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

## Resolution

Resolved on 2026-10-13 (`e4d8191`), as recommended: a relative `XDG_CONFIG_HOME` (any value
that is not an absolute path; `~` is not expanded, so `~/conf` counts) is treated as unset in
all four places, the way `state_dir()` already treats `XDG_STATE_HOME`:

- the CLI and the MCP server through the shared `core/utils/config_search.xdg_config_home`
  (issue 048 merged their searches into that module);
- `scripts/site_targets.py` `default_path()`, which now derives its directory from the same
  module's `config_dir()`;
- `scripts/unifi-mcp-launch.sh`, which uses `$XDG_CONFIG_HOME` only when it starts with `/`.

Tests, each with `conf`, `./conf` and `~/conf` and a stray file planted under the working
directory that must not be found: `tests/test_config_search.py` (the shared search, the CLI,
the MCP server), `tests/test_site_targets.py`, and `tests/test_mcp_launch_script.py`, which
runs the wrapper under bash with `HOME` in a temp dir and no config anywhere, so it exits 1
before sourcing anything or exec'ing `uv`, and the test reads which path it names. The
wrapper's happy path (a readable file, then exec) is not exercised by a test; running it
would start the server.
