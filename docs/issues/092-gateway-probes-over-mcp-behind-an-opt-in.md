---
title: "Expose the gateway SSH probes over MCP behind an explicit opt-in (0.4.0 design)"
date: 2026-10-15
status: open, decision needed
severity: medium
components: [mcp/manifests, mcp/registry, mcp/catalog, mcp/runner, mcp/parity, connectivity/gateway_probe, analysis/latency_matrix]
found_by: issue 060 decision D1, revisited for 0.4.0 after issue 038 landed
---

# Expose the gateway SSH probes over MCP behind an explicit opt-in (0.4.0 design)

Nothing in this record is built. It is the design the 0.4.0 work implements, written so the
work has a finish line before it starts.

## Problem

Eight `unifi-mapper` commands run a command on the gateway over SSH and have no MCP tool:
`gateway ping`, `gateway traceroute`, `gateway dns`, `gateway http`, `gateway flows`,
`diagnose latency-matrix`, `diagnose bandwidth` and `diagnose client-connectivity`. The parity
gate (`src/unifi_mapper/mcp/parity.py`, category `active probe`) exempts them, citing issue 060
decision D1: not before host-key verification (issue 038), and then only behind an explicit
opt-in, because an agent-triggered root SSH session to the gateway is a different trust class
from a controller read. Issue 038 is fixed in 0.3.0: the gateway's host key is verified by
default, and a missing or changed key is refused before the password is sent. D1's precondition
is met; its opt-in design is not written, so the probes stay CLI-only and an agent diagnosing
"why can't X reach Y" cannot ask the gateway the one question that answers it.

The handlers already have the shape a manifest entry needs: `gateway_ping(target, count,
interval)`, `gateway_traceroute(target, max_hops)`, `gateway_dns_check(hostname, server)`,
`gateway_http_check(url, vlan, interface, timeout_seconds)` and `get_active_flows(ip, state,
limit)` in `connectivity/gateway_probe.py`; `run_latency_matrix(ping_count, timeout,
include_clients)` in `analysis/latency_matrix.py`; `diagnose_client_connectivity(client,
probe_url)` in `diagnostics/client_connectivity.py`. Each is async, validates its inputs with
the `require_*` bounds in `analysis/gateway_ssh.py`, and returns a dict or a Pydantic model.
What is missing is the gate, not the tools.

## Design

**Manifest.** A new boolean key `active_probe` on a tool entry (default `false`), parsed into
`ToolMetadata.active_probe` beside `mutates`. The registry's key check (`tests/mcp/
test_registry_keys.py`) learns the key; an entry with both `active_probe` and `mutates` is a
load error.

**Gate.** One environment variable, `UNIFI_MCP_ALLOW_ACTIVE_PROBES`, read by the server at
start the way `UNIFI_MCP_TOOL_SURFACE` is, accepting exactly `1`; any other value is a config
error at start, named. When unset:

- active-probe tools appear in neither surface's tool list, nor in `search_tools`,
  `get_tool_info` or `list_categories` counts;
- `execute_tool` on one refuses with a tool error whose code is `ACTIVE_PROBES_DISABLED` and whose
  message names the variable and the command the tool would run;
- the catalog's startup log says how many probes are held back.

When set, the tools are listed with annotations `readOnlyHint: false` (a probe sends traffic),
`openWorldHint: true`, `idempotentHint: false`, and a description that begins `Runs <command>
on the gateway over SSH:`, so a client that shows annotations shows the trust class. They run
through the ordinary runner: the per-call deadline (`UNIFI_MCP_TOOL_TIMEOUT`, default 270 s)
bounds them, the call audit records them, and `mask_secrets` covers `UNIFI_SSH_PASSWORD` in
results and errors as it covers every `UNIFI_*` value today.

**Errors.** A host-key refusal (issue 038) reaches the client as a tool error that names
`user@host` and the one `ssh` command that records the key, exactly as the CLI prints it; a
missing `UNIFI_SSH_PASSWORD` is `CONFIG_MISSING`, as for the CLI.

**Parity.** The tier-1 commands below leave `CLI_ONLY_COMMANDS` and become `cli:` mappings on
their tool entries, so the gate pins them in both directions. The commands that stay off MCP
keep an `active probe` reason that says why in one line (below). The `trigger_*` note in
`tests/mcp/test_execute.py` points here.

**Catalog rule.** An `active_probe` tool must have `writes_local: false`, must not start with a
writer prefix, and its handler module must be one of the three probe modules; a test loads the
real manifests and asserts it, so a future tool cannot acquire the flag by accident.

## Tiers

**Tier 1, in 0.4.0:** `gateway_ping`, `gateway_traceroute`, `gateway_dns_check`,
`run_latency_matrix`. Network diagnostics with bounded, validated inputs (an address, a
hostname, hop and count limits); results hold round trips, hops and addresses, no payload data.
This is what an agent needs for a reachability question.

**Tier 2, decision needed:** `gateway_http_check` makes the gateway fetch a URL the agent
chose; `require_http_url` bounds its shape but not its destination, and the response head
comes back in the result. `get_active_flows` returns the site's live connection table
(addresses, ports, states; `limit` 1-5000, default 200), which is the whole site's activity
handed to a model. `diagnose_client_connectivity` composes probes including a captive-portal
fetch. All three are read-only in effect and already bounded; the question is whether their
output belongs in an agent's context at all, which is the operator's call, not the code's.
Recommendation: hold them for a second decision after tier 1 has run live for a while, behind
the same flag if adopted.

**Excluded:** `diagnose bandwidth` needs an iperf3 server on the target and saturates a link
for `duration` seconds, not something to trigger unattended; `diagnose ap-health` is
long-running (issue 060 D4, waits on issue 008).

## Definition of done

1. Registry: `active_probe` parsed, defaulted, rejected beside `mutates`; key test updated.
2. Gate off: four listing surfaces hide the tools and `execute_tool` refuses with
   `ACTIVE_PROBES_DISABLED`; one test per surface, over the real manifests.
3. Gate on: the four tier-1 tools list with the annotations above; `execute_tool` runs each
   through the runner over the fake gateway (the asyncssh server in
   `tests/analysis/test_gateway_ssh_handshake.py`)
   and the result matches the handler's; a planted `UNIFI_SSH_PASSWORD` appears in no result
   or error text.
4. Host-key refusal over MCP: the 038 connection-level test, driven through `execute_tool`, yields
   the named error.
5. Parity gate green with the four commands mapped and the four remaining reasons rewritten.
6. Docs: `docs/mcp-server/MCP_SERVER_GUIDE.md` gains "Active probes (opt-in)"; `.env.example`
   gains the variable; the CHANGELOG entry is under Added, not Breaking (off by default).
7. Live: with the flag on, `gateway_ping` through the MCP runner against the real gateway
   reports loss and round trips within the CLI's own run of the same probe.

## Impact

Until built, an agent cannot run a reachability probe from the gateway's vantage point; the
operator runs the CLI by hand and pastes the result. Breaks fresh clones, CI or prod: no.

## Decision needed

Whether tier 2 (`gateway_http_check`, `get_active_flows`, `diagnose_client_connectivity`) joins
tier 1 behind the same flag in 0.4.0, or waits for a later decision as recommended. Tier 1 is
built behind the flag (see Progress); tier 2 is still pending this decision.

## Progress (2026-10-15)

Points 1 to 6 of the definition of done are built and pinned by tests; point 7 (live) could
not be observed, so the record stays open.

What changed:

- **Registry.** `active_probe` (bool, default `false`) is a manifest key, parsed into
  `ToolMetadata.active_probe`; an entry with both `active_probe` and `mutates` is a load error
  (`tests/mcp/test_registry_keys.py`). A `ToolRegistry` holds active probes back unless built
  with `active_probes=True`: they are loaded and checked, but no lookup, search, category or
  count sees them, so the default catalog is unchanged and nothing can run a held probe.
  `held_active_probes()` names them.
- **Manifests.** `gateway_ping`, `gateway_traceroute`, `gateway_dns_check`
  (`connectivity.yaml`) and `run_latency_matrix` (`analysis.yaml`) carry `active_probe: true`,
  `cli:` mappings and descriptions that begin `Runs <command> on the gateway over SSH:`.
- **Gate.** `UNIFI_MCP_ALLOW_ACTIVE_PROBES`, read once at start: exactly `1` lists the four;
  unset or empty holds them; any other present value (`0`, `true`, `yes`, `TRUE`, a
  whitespace-padded `" 1 "`) stops `unifi-mcp` (and `--check`) with exit 2, naming the
  variable and the value, never a silent off and never a truthy parse. The error text says this
  deliberately differs from `UNIFI_MCP_TOOL_SURFACE`'s warn-and-fall-back because the setting
  permits agent-triggered SSH to the gateway; the flag is a process-wide permission that lets
  any caller of that server choose probe destinations within the validators' bounds. Off,
  neither surface lists them, `search_tools`, `get_tool_info`,
  `list_categories` and `unifi://catalog` do not show them, and `execute_tool` (or a
  direct-surface call by name) returns `ACTIVE_PROBES_DISABLED` naming the variable, the
  program and the `unifi-mapper` command, before any argument, credential or gateway is
  touched; the call log records the refusal. The lifespan logs the held count at INFO, or a
  WARNING naming the listed probes. `--check` reports `active_probes` (`enabled`, `held`).
- **On.** The four list with `readOnlyHint: false`, `idempotentHint: false`,
  `openWorldHint: true`, `destructiveHint: false`, and run through the ordinary `ToolRunner`.
- **Parity.** The four commands left `CLI_ONLY`; `gateway http`, `gateway flows` and
  `diagnose client-connectivity` cite tier 2, `diagnose bandwidth` its exclusion. The parity
  report walks the held probes too.
- **Docs.** `docs/mcp-server/MCP_SERVER_GUIDE.md` "Active probes (opt-in)", the environment and
  error tables, the manifest-key table; `.env.example` lists the variable with a warning.

Tests (`tests/mcp/test_active_probes.py`, over the real manifests): each listing surface hides
the probes and `execute_tool` refuses each with the named error (point 2); with the flag on,
each runs through `execute_tool` against a real asyncssh server (`tests/fake_gateway.py`, the
server the issue 038 handshake test uses, now shared) and returns what its handler returns, and
a planted `UNIFI_SSH_PASSWORD` value that reaches the handler's result or error never reaches
the MCP result or error (point 3); a missing or changed host key reaches the client as
`CONTROLLER_UNREACHABLE` naming `root@<gateway>` and the `ssh` command, with no password offered
(point 4); the parity gate is green (point 5); a catalog-rule test requires every probe to be
in a probe module, write nothing local, carry no writer name and keep the description shape.
From the council's review of the implementation: a refusal with the gate off makes zero
`asyncssh.connect` calls and zero controller requests (spies at 0); `mutates: true` stays
refused with the gate on; the `require_*` checks run through `execute_tool` before any SSH
connect (a shell metacharacter and a leading-option target, a count, interval, hop count and
timeout over their bounds, a controller-reported address with a metacharacter); the planted
password reaches none of the result, the error text, any loguru line or the call-audit record,
a forced `TOOL_FAILED` included; and a probe over the fake gateway finishes in under 10 s with
the runner's deadline at its default 270 s.

What a user sees: nothing, until the operator sets `UNIFI_MCP_ALLOW_ACTIVE_PROBES=1` in the MCP
client's `env` block; then an agent can ask the gateway to ping, trace or resolve, and a host
that shows annotations marks those calls as not read-only.

What remains:

- **Point 7, live state: `credentials unavailable`.** (The four states a live attempt is
  recorded as: `live comparison succeeded`; `host-key refusal (expected 038 behaviour; live
  comparison not run)`; `credentials unavailable`; `deferred`.) On 2026-10-15 `gateway_ping`
  through the real server objects with the flag on (the controller's own address, `count` 3)
  and `unifi-mapper gateway ping <same> --count 3` both stopped with the same `CONFIG_MISSING`
  ("UNIFI_SSH_PASSWORD is not set") before connecting: the gateway's host key is recorded, but
  the config file in use has no `UNIFI_SSH_PASSWORD`. Nothing was verified live. With the
  password set, run each once more and compare loss and round trips; a host-key refusal on
  that run is the 038 behaviour, not a verification.
- `tests/mcp/test_manifest_parity.py::test_rule6_strict_registry_loads_every_manifest` asserts
  `len(ToolRegistry(strict=True)) == ` the raw entry count; with the probes held that is 96
  against 100. The identity it means is `len(registry) + len(registry.held_active_probes())`,
  which holds.
