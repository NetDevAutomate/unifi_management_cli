---
title: "`UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` do not reach clients built from `Credentials`"
date: 2026-10-13
status: resolved
resolved_by: 47e6dd5
severity: low
components: [inventory_cli, diagnostics/port_diagnostics_tools, diagnostics/inspect_port]
found_by: the 0.3.0 CLI lane (issue 042)
---

# `UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` do not reach clients built from `Credentials`

## Problem

Issue 042 passed the two retry settings to `UnifiApiClient` wherever `UnifiConfig` builds a
client. `inventory_cli.py` line ~101 and `diagnostics/port_diagnostics_tools.py` line ~41 build
the client from `Credentials` instead and do not read the two variables.

## Impact

The inventory commands and the sync port-diagnostics tools keep the client's built-in retry
defaults whatever the config file says, unlike every other command.

## Recommended fix

Read the two variables in `Credentials.from_env` (or pass them through where `Credentials`
builds a client) and extend the 042 test to these sites.

## Resolution (2026-10-15)

`UNIFI_TIMEOUT` was skipped at both sites as well as the two retry settings. The inventory
commands now build their client from `UnifiConfig.from_env`, the same construction as every
other command, so all three settings arrive with the same clamping; a configuration that
`UnifiConfig` rejects (no credentials, a URL with no scheme) ends with a one-line error.
The MCP port-diagnostics sync client keeps `Credentials` for the identity (it still accepts
`UNIFI_HOST`) and now passes the three settings under the same names and defaults, which the
API client clamps to the same ranges. A value that is not a number is a `CONFIG_INVALID` tool
error. `inspect_switch_port` builds its client through that same context manager, so it needed
no change.

Pinned by `tests/diagnostics/test_client_settings.py`, which builds a real client through the
config path, the inventory path and the MCP path from one configuration and asserts the same
`(timeout, max_retries, retry_delay)` for configured, out-of-range and unset settings.

What a user sees: `inventory` commands and the MCP port tools wait, retry and back off as the
configuration says, like every other command.
