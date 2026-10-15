---
title: "Promote the read-only live-check harness into the repo as a config-driven tool"
date: 2026-10-04
status: resolved
resolved_by: 73f03e8
severity: medium
components: [core/utils/readonly, mcp/server, typer_cli, tests]
found_by: docs and repo hygiene review
---

# Promote the read-only live-check harness into the repo as a config-driven tool

## Problem

The read-only checks against the live controller that verified the MCP rebuild and the
review follow-ups ran from a harness that was never committed. It is archived locally,
outside the repo, so no clone can repeat those checks: the next change to a controller,
Integration API or Protect path is checked offline only.

The harness found real bugs that the offline suite had passed, three times:

- `network_health_check` failed on the controller's string-valued system stats (fixed in
  `e8ce801`).
- A uvx launch from a checkout kept serving the old build after a code edit (fixed in
  `83ab0e7` with `[tool.uv] cache-keys`).
- The Integration API answered 404 for the ACL-rule and DNS-policy paths (fixed in
  `6fd892c`; issues 031 and 032).

It also hard-codes the site: the switch it inspects and the port it must never target are
constants in its source.

## Impact

Regressions that only a real controller shows (payload shapes, served paths, packaging) go
unnoticed until someone hits them. Nothing breaks for fresh clones or CI today.

## Recommended fix

Add a generic read-only live-check tool to the repo (for example `scripts/live_check.py`):

1. Run every request through the read-only guards (`install_read_only_guard`,
   `ReadOnlyAsyncTransport`, `ReadOnlyProtectApiClient`) with the request audit on
   (`configure_request_audit`, `UNIFI_MCP_REQUEST_AUDIT` for the server), and fail on any
   request outside the allowlist or any `READ_ONLY_VIOLATION`.
2. Exercise the CLI in process and the MCP server over a fresh `uvx --from <checkout>` stdio
   client, on both surfaces.
3. Take the target switch and the switches and ports to exclude from a config file. Never
   hard-code a switch or a port.
4. Never pass `--apply`, and call a `mutates: true` tool only to confirm `MUTATION_REFUSED`
   with zero requests sent.
5. Write results under the XDG state directory, never the repo, and scan every output file
   for secret values before reporting.

Why this needs a decision: it adds a script that talks to the live network (read-only), and
where it lives and how it is configured is the user's call.

## Decision (2026-10-13)

Promotion of the read-only live-check harness into the repository is deferred to 0.4.0. It is
maintainer tooling rather than a user-facing feature, the read-only guards it exercises are
unit-tested, and it is run by hand against the maintainer's controller before each release.
Decided by the 0.3.0 release council (D-039); the issue stays open.

## Resolution (2026-10-15)

Decided by the 0.4.0 planning council (pass A, D-039: the archived harness was gone, so this
is a new, time-boxed script in the finishing lane) and written as `scripts/live_check.py`,
with its pure parts pinned by `tests/test_live_check_script.py`. It meets the five criteria
above: guards and request audit on both surfaces with every audited request re-checked against
the allowlist; the CLI in process and the MCP server as a fresh `uvx --no-cache --from
<checkout>` stdio child on the direct surface; the switch, port, exclusions and VLANs from a TOML
file under XDG config (a target the exclusions cover is refused); one `mutates: true` tool
called through `execute_tool` to confirm `MUTATION_REFUSED` with no request line in its
call-log window; results under the XDG state root and a secret scan of every file written.
The run is documented in the runbook (Common Maintenance Tasks). First live run, read-only:
the CLI's four commands exit 0 with 14 audited requests all inside the allowlist; the fresh
server lists 86 tools and no probe, the four reads succeed, the refusal is logged with no
request, 85 request lines audited; three secret variables, no hits. Protect stays
`unverified` until credentials exist.
