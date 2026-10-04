---
title: "With the legacy config file, the six network_api tools return CONFIG_MISSING"
date: 2026-10-03
status: open, decision needed
severity: medium
components: [mcp/config, network/config]
found_by: review follow-ups (orchestrator F20 follow-up, variant a)
---

# With the legacy config file, the six network_api tools return CONFIG_MISSING

## Problem

The review orchestrator reports that the user's MCP clients launch `unifi-mcp` with
`UNIFI_CONFIG=~/.config/unifi_network_mapper/prod.env`. That file sets
`UNIFI_NETWORK_API_KEY` but neither `UNIFI_NETWORK_HOST` nor `UNIFI_NETWORK_SITE_ID`, and
the `network_api` family needs all three (`mcp/config.py` `CREDENTIAL_KEYS`). Launched that
way, `unifi-mcp --check` reports the family `ready: false`, `present:
[UNIFI_NETWORK_API_KEY]`, `missing: [UNIFI_NETWORK_HOST, UNIFI_NETWORK_SITE_ID]`, so every
`network_api` tool (`get_firewall_zones`, `get_firewall_policies`, `get_acl_rules`,
`get_dns_policies`, `get_clients`, `get_networks`) answers `CONFIG_MISSING`.

The key itself is valid. With the host and the site id added after the product's own
resolver had run on that file, all six tools returned data (zones 13, policies 275, ACL
rules 0, DNS policies 0, clients 98, networks 9): 11 audited GETs, 0 violations, no 401 or
403. CONFIG's `UNIFI_CONSOLE_API_TOKEN` returned the same results, so this console's
Integration API accepts either key.

There is no fallback: with `UNIFI_NETWORK_API_KEY` removed, the family wouldn't use the
console token, it would just be missing a key. No MCP client config on this machine
registers `unifi-mcp` (checked by server name, read-only), so the launch config itself is
taken from the orchestrator's report.

## Evidence

- Local evidence, not in the repo, recorded at `06d2f6a`: for the run with
  `UNIFI_NETWORK_API_KEY` and the run with the console token in its place, the resolver
  status, the `--check` output and the six tool results.

## Impact

In that deployment the six `network_api` tools can't run. Until this branch their paths and
models were also broken (issues 031–033), so they have not worked there before. Nothing is
written, and nothing breaks for fresh clones or CI.

## Decision needed

1. (User action, works today) Add the two keys to that file:
   `UNIFI_NETWORK_HOST=<console address, as in UNIFI_URL>` and
   `UNIFI_NETWORK_SITE_ID=<the id of the Integration API site whose internalReference is
   UNIFI_SITE>` (from `GET /proxy/network/integration/v1/sites`).
2. (Product change) When the family has a key but no host or site id, derive them: the host
   from `UNIFI_URL`, and the site id from one `GET /v1/sites` matched on `UNIFI_SITE`, the
   lookup `port_diagnostics.fetch_integration_ports` already makes. Optionally fall back to
   `UNIFI_CONSOLE_API_TOKEN` when no network key is set. This changes `--check` and the
   family's readiness, so it needs a decision.

Recommendation: do 1 now, because it unblocks the tools without code. Then decide on 2,
which removes the trap for every user whose file has only a key.
