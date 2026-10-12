---
title: "The Network Integration API client uses an undocumented base path"
date: 2026-10-02
status: open
severity: low
components: [network/config, network/client]
found_by: port diagnostics gap analysis
---

# The Network Integration API client uses an undocumented base path

## Problem

`network/config.py` (`NetworkConfig.api_base_url`) builds
`https://{host}/proxy/network/integrations/v1`, and `tests/network/test_config.py` pins
it. Ubiquiti's published Integration API spec gives the server as
`https://{consoleIP}/proxy/network/integration` (singular), with paths under `/v1`.

## Evidence

On 2026-10-02 a read-only check against the console (UniFi Network 10.6.106) sent
`GET /v1/info` on both bases. Both returned HTTP 200 with the same `applicationVersion`.
The result is in `linkdown-snapshot-20261002-1733/18-integration-api-base-path-check.json`
in the UGREEN ticket attachments. The port diagnostics' own Integration API reads try the
documented base first, and they recorded `base_path_used: /proxy/network/integration`.

## Impact

Nothing breaks today, because the plural path answers on 10.6.106. The risk is that the
plural is an undocumented alias. If a future Network release drops it, every
`network.yaml` MCP tool fails at once. It doesn't break fresh clones or CI.

## Recommended fix

Either switch `api_base_url` to the documented `/proxy/network/integration/v1` and update
its test, or try the documented base first and fall back to the plural on a 404, as
`port_diagnostics` already does.
