---
title: "Network Integration API and Protect MCP tools run without a read-only guard or request audit"
date: 2026-10-02
status: open
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
