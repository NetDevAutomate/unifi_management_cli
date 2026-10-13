---
title: "Migrate the MCP server to the SDK v2 `MCPServer` API"
date: 2026-10-02
status: open
severity: low
components: [mcp/server, mcp/catalog, mcp/runner, pyproject.toml]
found_by: MCP uvx standards work
---

# Migrate the MCP server to the SDK v2 `MCPServer` API

## Problem

The server runs on the FastMCP bundled with the v1 SDK, pinned to `mcp>=1.30,<1.31` (1.30.0 is
locked; the latest SDK on PyPI is 2.x). Three pieces depend on FastMCP internals that aren't
public API, which is why the pin is one minor wide:

- `UnifiFastMCP.call_tool` (`mcp/server.py`) overrides FastMCP's dispatch so direct catalog
  tools run through `ToolRunner` instead of `Tool.run`.
- `_build_fastmcp()` writes `server._mcp_server.version`, because FastMCP has no version
  argument; without it `serverInfo.version` reports the SDK's version.
- `ToolRunner._validate` uses `Tool.fn_metadata` (`arg_model`, `pre_parse_json`,
  `convert_result`) to validate arguments and build structured results.

SDK v2 replaces FastMCP with `MCPServer`: it supports the newest protocol revision, sanitises
errors and runs sync tools on a thread, and has public hooks for most of the above (design
backlog B1).

## Impact

Each SDK minor upgrade needs `uv lock --upgrade-package mcp` plus
`uv run pytest --run-slow tests/mcp/test_packaging.py` and may break on an internals change.
Clients that negotiate only the newest protocol revision may lose features. Nothing breaks
today.

## Recommended fix

Do it as one change once the current behaviour is locked by tests (it now is:
`tests/mcp/test_protocol_contract.py`, `test_error_semantics.py`, `test_manifest_parity.py`,
`test_execute_call_shapes.py`):

1. Bump to `mcp>=2.2,<3` and follow the SDK's v2 migration guide.
2. Replace the `call_tool` override and the `_mcp_server.version` write with `MCPServer`'s
   public equivalents; keep `ToolRunner` as the single call path.
3. Keep the envelope, `isError`, annotations, resources and prompts identical (the contract
   tests above must pass unchanged), then widen the pin rule in `pyproject.toml`.

## Decision (2026-10-13)

No migration to the MCP SDK v2 `MCPServer` API in 0.3.0. The behaviour is locked by the
protocol-contract tests, so the migration can land as one change in a later release once the
v2 task support (issue 060 D4) is wanted. Decided by the 0.3.0 release council (D-008); the
issue stays open.
