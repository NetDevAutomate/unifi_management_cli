---
title: "Network Integration API and Protect MCP tools run without a read-only guard or request audit"
date: 2026-10-02
status: resolved
severity: low
components: [mcp/tools/network, mcp/tools/protect, network/client, protect/client, core/utils/readonly]
found_by: MCP uvx standards work (convergence fixer, iteration 1)
---

# Network Integration API and Protect MCP tools run without a read-only guard or request audit

## Problem

Every `controller`-family MCP tool now goes through one of the two read-only guards: the
shared async client's `ReadOnlyAsyncTransport`, or `install_read_only_guard` on the sync
`UnifiApiClient` (`inspect_switch_port` included since the issue 021 partial resolution).
The other two credential families don't:

- The six `network_api` tools (`mcp/tools/network.py`: `get_firewall_zones`,
  `get_firewall_policies`, `get_acl_rules`, `get_dns_policies`, `get_clients`,
  `get_networks`) use `network/client.py`, which builds a plain `httpx.AsyncClient`. That
  client class also has write methods (`delete_network`, `delete_acl_rule`,
  `delete_dns_policy`, `delete_traffic_matching_list`, and create/update twins).
- The five `protect` tools (`mcp/tools/protect.py`) use `uiprotect.ProtectApiClient`, which
  owns its own aiohttp session.

Their requests aren't refused if they would write, and `UNIFI_MCP_REQUEST_AUDIT` doesn't
record them. Every exposed handler is a `get_*` read today, so nothing is written.

## Impact

The "MCP is read-only" proof the request audit gives covers the controller family only; the
guide says so. A future handler change in these two families could write without a guard
noticing.

## Recommended fix

1. `network_api`: give `NetworkClient` an optional `transport=` (as `UniFiClient` gained in
   item 5) and have the MCP tools pass a `ReadOnlyAsyncTransport` with a GET-only policy for
   the Integration API paths (`/proxy/network/integrations/v1/…`; its POST endpoints are
   writes), auditing through `audit_request`. Add a test that a `delete_*` call is refused and
   that the audit file records the GETs.
2. `protect`: uiprotect doesn't take a transport. Either wrap `ProtectApiClient.request` (the
   method its calls go through) to allow only GET and audit it, or document Protect as
   outside the audit and keep the handler-level read-only contract test.
3. Update the guide's request-audit paragraph once both are covered.

## Resolution

Both families are now guarded and audited; the guards are installed by the MCP tools only,
so library callers of `UniFiNetworkClient`, the `unifi_mapper.network` managers and
`UniFiProtectClient` keep their write methods by default.

- `core/utils/readonly.py`: new pure `get_only_request_allowed(method, url)` (GET and HEAD
  only, the same path checks as `request_allowed`) and `is_login_request(method, url)` (the
  exact login test the async guard already made). `ReadOnlyAsyncTransport(inner, site=None,
  *, policy=None)` takes exactly one of `site` (the controller policy and its login
  exemption, unchanged) or `policy` (that policy only, no login exemption).
- `network_api`: `UniFiNetworkClient` takes an optional `transport=`, like `UniFiClient`.
  The six tools build their client with `_read_only_client()`: an `httpx.AsyncHTTPTransport`
  carrying `verify_ssl` (httpx ignores `verify` once a transport is given) behind
  `ReadOnlyAsyncTransport(..., policy=get_only_request_allowed)`, because every Integration API
  POST is a write. As for the controller family, an explicit transport means httpx no longer
  routes these requests through `HTTP(S)_PROXY`.
- `protect`: uiprotect 8.1.1 sends every REST call (`api_request*`, `get_bootstrap`,
  `authenticate`) through the public `BaseApiClient.request`, so
  `ReadOnlyProtectApiClient(ProtectApiClient)` overrides it with the same signature: the
  session login (`POST /api/auth/login`) is sent unaudited, GET and HEAD are audited and sent,
  anything else raises `ReadOnlyViolation` before `super().request()`, so before any login or
  I/O. `UniFiProtectClient(config, read_only=True)` builds it; all five tools pass
  `read_only=True`.
- A `ReadOnlyViolation` inside a network or protect tool is re-raised (and
  `UniFiProtectClient.connect()`/`refresh()` no longer wrap it as a connection error), so the
  runner reports `READ_ONLY_VIOLATION` as for the controller family. Every other failure
  still returns `{"error": …}` (issue 011).

Not covered, documented in the class docstring and the guide: uiprotect's websocket
subscriptions (`session.ws_connect`) and the private `_get_versions_from_api` (a direct
`session.get` nothing in uiprotect 8.1.1 calls). No MCP tool uses either. The pin
`uiprotect>=8.1.1,<9` bounds the seam.

The guide's request-audit paragraph, the Control Boundary sentence, the
`READ_ONLY_VIOLATION` row, the error-results paragraph and "Per-process state" now describe
all three families.

Tests: `tests/mcp/test_network_protect_guard.py` (32): the GET-only policy; the
transport's exactly-one-of rule and the missing login exemption for a custom policy; the
network client passing its transport; each of the six network tools sending only GETs under
`/proxy/network/integrations/v1/sites/<site>/` with matching audit lines (no key, host or
query); eight network writes (`delete_*`, `create_network`, `update_network`,
`execute_device_action`, `authorize_guest`) refused before any I/O; a write inside a network
tool and inside a protect tool reported as `READ_ONLY_VIOLATION`; the Protect guard sending
its login and a GET and auditing only the GET; four Protect writes (`reboot_nvr`, PATCH,
DELETE, a public-API PATCH) refused before any I/O; the override's signature matching
uiprotect's; `read_only=True` building the guarded class; every protect tool passing
`read_only=True`. A mutation run (guard bypassed in each place) failed 21 of them.

Found while planning this fix: the async guard judges a raw path starting with `//` as a
different path (issue 029).
