---
title: "Should the MCP server list every tool (the direct surface) by default?"
date: 2026-10-02
status: open, decision needed
severity: low
components: [mcp/server]
found_by: MCP uvx standards work
---

# Should the MCP server list every tool (the direct surface) by default?

## Problem

`unifi-mcp` has two tool surfaces (`--surface`, `UNIFI_MCP_TOOL_SURFACE`):

- `discovery` (the default, `DEFAULT_SURFACE` in `mcp/server.py`): `tools/list` returns four
  meta-tools; the model searches, reads one schema with `get_tool_info`, then calls
  `execute_tool`.
- `direct`: also lists the 62 non-mutating, non-pipeline catalog tools, each with its own
  input and output schema, title and annotations.

Measured at commit `b249104` over an in-memory session: discovery 4 tools, 6,376 characters of
`tools/list`; direct 66 tools, 184,713 characters (roughly 46k tokens).

Verify step, commit `ca6869b`, over a real `uvx --python 3.12 --refresh --from` subprocess
(the built wheel and the checkout give identical figures). Tokens are estimated as
characters / 4:

| Surface | Tools | `tools/list` response on the wire (one JSON-RPC line) | Estimated tokens |
| --- | --- | --- | --- |
| discovery | 4 | 6,136 characters | ~1.5k |
| direct | 66 | 172,117 characters | ~43k |

The legacy `uv --directory <checkout> run unifi-mcp` launch serves the same 6,136-character
discovery listing.

The original brief asked for direct by default. It wasn't made the default because changing
what `tools/list` returns is a behaviour change for existing clients (design decision D2, plan
decision P2).

## Impact

- Hosts that defer MCP tool schemas (kiro-cli, Claude Code tool search) handle the direct
  surface well: they keep the schemas out of context and the model calls tools by name, with
  per-tool annotations and output schemas. The guide's kiro-cli and Claude Code snippets
  already set `UNIFI_MCP_TOOL_SURFACE=direct`.
- Hosts that load every schema up front (Codex, some desktop clients) would pay about 172k
  characters (~43k tokens) per session on direct, and may not defer it at all if it sits under their
  deferral thresholds.

## Decision needed

Keep `discovery` as the default, or flip `DEFAULT_SURFACE` to `direct`?

Design recommendation: **keep `discovery` for now** and opt in per client (done in the guide's
snippets). The verify step's measurement is recorded above; revisit once the hosts in use are
confirmed to defer schemas; a flip is one constant plus the `test_protocol_contract.py`
expectations, and `--surface discovery` keeps the old listing available.
