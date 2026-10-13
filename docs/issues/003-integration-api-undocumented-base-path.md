---
title: "The Network Integration API client uses an undocumented base path"
date: 2026-10-02
status: resolved
resolved_by: 2533cf6
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

## Resolution

Resolved on 2026-10-13 (`2533cf6`), the second way: `UniFiNetworkClient` tries the documented
base first and falls back to the plural on a 404, as `port_diagnostics` does. On its first
request the client sends `GET {base}/v1/info` for each of `INTEGRATION_BASES` (new, in
`network/config.py`: `/proxy/network/integration`, then `/proxy/network/integrations`); a 404
moves to the next base, the first base that answers is used for every later request, and
`client.base_path_used` says which one. Both 404 raises `NetworkClientError` (status 404)
naming both bases; a 401/403 on the probe raises the usual `NetworkAuthenticationError`. The
probe runs once per connection under the client's lock, so concurrent first requests (the
statistics collector gathers them) share it. `NetworkConfig.api_base_url` is now the
documented base.

Cost, deliberately accepted: one extra `GET /v1/info` per connection. The MCP `network` tools
open one client per call, so each tool call sends one more read. The GET-only guard lets it
through (it is a GET), and it appears in the request audit like any other read.

Tests: `tests/network/test_client_base_path.py` (a console serving the documented base is
probed once and used; one serving only the plural is used after one 404; neither fails with
404 before any resource request; a 401 probe is the authentication error; the probe passes
the read-only guard). `tests/network/test_client_paths.py`, `tests/network/test_config.py`
and the two `tests/mcp` files that pinned the plural path and exact call lists
(`test_network_tool_payloads.py`, `test_network_protect_guard.py`) now expect the documented
base and the one probe request; "refused before any I/O" there became "the write itself
never reaches the transport", which is what the guard promises.

Not changed: `port_diagnostics.INTEGRATION_BASES` still has its own copy of the two bases
(it does not import from `network/config.py`); `tests/fixtures_unifi.integration_routes`
still defaults to the plural base for the diagnostics' own tests; the `readonly.py` docstring
still names the plural path.
