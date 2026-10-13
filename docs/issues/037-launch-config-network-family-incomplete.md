---
title: "With the legacy config file, the six network_api tools return CONFIG_MISSING"
date: 2026-10-03
status: resolved
resolved_by: 05c9416
severity: medium
components: [mcp/config, network/config]
found_by: review follow-ups
---

# With the legacy config file, the six network_api tools return CONFIG_MISSING

## Problem

The maintainer's MCP clients launch `unifi-mcp` with
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
console token, it would just be missing a key. Correction (2026-10-05): two MCP clients on this
machine do register `unifi-mcp` (kiro-cli and Codex, both as server `unifi` with
`UNIFI_CONFIG` pointing at the XDG `prod.env`). That file sets the console token,
`UNIFI_URL` and `UNIFI_SITE` but no `UNIFI_NETWORK_*` key (key names checked, read-only).
So deriving the host and site id alone wouldn't unblock the six tools; they also need the
console-token fallback, or the keys added to that file.

## Evidence

- Local evidence, not in the repo, recorded at `a0f95e0`: for the run with
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

## Resolution

Resolved on 2026-10-13 (`05c9416`) with option 2, as the release council decided; option 1
(adding the two keys to the file) still works and always wins. `NetworkConfig.from_env`
(`network/config.py`) derives whatever `UNIFI_NETWORK_*` key is unset from the controller
family, and `resolve_network_env` is the same rule set without I/O:

1. **Host**: with `UNIFI_NETWORK_HOST` unset, the scheme, host and port come from `UNIFI_URL`
   (or `UNIFI_HOST`/`UNIFI_PORT`), normalised to an `Origin` (lower-cased host, the scheme's
   default port when none is given). `NetworkConfig` gained a `scheme` field so an `http://`
   console keeps its scheme; `base_url` follows it.
2. **Site id**: with `UNIFI_NETWORK_SITE_ID` unset the config carries `site_name`
   (`UNIFI_SITE`, `default` when unset, the controller family's own default) and
   `UniFiNetworkClient.site_id()` resolves it at the first request that needs `{siteId}`:
   one `GET /v1/sites` (all pages) matched on `internalReference == site_name`, exactly as
   `port_diagnostics.fetch_integration_ports` matches. The result is cached for the process
   per `(base_url, site name)`, so every tool call and every client the server opens shares
   one lookup. Zero or several matches raise `NetworkSiteResolutionError`, which the MCP
   wrapper reports as `[CONFIG_INVALID]` naming the names found (or the ids of the duplicates)
   and how to pin the id. `fetch_integration_ports` itself was not reused: it is a synchronous
   `UnifiApiClient` + `Collection` routine for the legacy transport, not callable from the
   async httpx client; the matching rule is the same.
3. **Key**: with `UNIFI_NETWORK_API_KEY` unset, `UNIFI_CONSOLE_API_TOKEN` stands in **only**
   when the network origin equals the controller's origin (`network_origin(env) ==
   controller_origin(env)`); a different host or port is reported as the key missing, with
   the token's name but never its value. The client sets `follow_redirects=False` and treats
   any 3xx as an error naming the target host, so the key never leaves the origin it was
   given for. `api_key_source` records `network` or `console`.
4. **Offline readiness**: `mcp.config.family_status('network_api', ...)` now uses
   `resolve_network_env`, so `--check`, the status resource and the runner's family gate
   agree; the `FamilyStatus` carries a new `derived` list (`host: derived from UNIFI_URL`,
   `site id: resolved at first call`, `key: console token (same origin)`) and the report
   never contacts the controller. `source` still names where the family's **own** keys came
   from, so a controller-only file shows `source: none, ready: true, derived: [...]`.

Behaviour the tests pin (`tests/network/test_config_derivation.py`,
`tests/mcp/test_network_site_resolution.py`): the sites lookup with one, zero and two
matches through the tools' own read-only guard (`httpx.MockTransport`); the lookup happens
once per process; an explicit site id skips it; a different `UNIFI_NETWORK_HOST` gets no
console token and sends nothing; a 302 to another origin is not followed; `--check` on a
controller-only file is offline and reports the three derived notes.

Two existing tests changed deliberately: `test_credential_keys_match_config_loaders` now
treats `UNIFI_NETWORK_SITE_ID` as deferred (removing it yields `site_name='default'`, not an
error), and `test_lab_export_with_prod_discovered_file_is_not_applied` now expects the family
ready by derivation from the exported lab controller (the foreign prod file's key is still
not applied). `CREDENTIAL_KEYS['network_api']` is unchanged: it documents the family's own
keys.

Not changed: the Protect family; `UNIFI_NETWORK_VERIFY_SSL` still defaults to `false`
independently of `UNIFI_VERIFY_SSL`; the live evidence at `a0f95e0` is not re-run here (the
tests are offline). Docs: `docs/mcp-server/MCP_SERVER_GUIDE.md`, `.env.example`, the README
known-limitations bullet.
