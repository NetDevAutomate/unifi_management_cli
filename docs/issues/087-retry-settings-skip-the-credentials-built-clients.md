---
title: "`UNIFI_MAX_RETRIES` and `UNIFI_RETRY_DELAY` do not reach clients built from `Credentials`"
date: 2026-10-13
status: open
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
