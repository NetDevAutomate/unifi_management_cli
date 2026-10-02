---
title: "The MCP guide and server docstrings miss the observability category and new counts"
date: 2026-10-02
status: open
severity: low
components: [mcp/server, docs/mcp-server/MCP_SERVER_GUIDE.md]
found_by: port diagnostics review (R3)
---

# The MCP guide and server docstrings miss the observability category and new counts

## Problem

The port diagnostics work added six MCP tools and a new `observability` category. The
registry now has 70 tools: analysis 40, connectivity 4, diagnostics 8, discovery 5,
network 6, observability 2 and protect 5. Two files were deliberately left untouched,
because they belong to an earlier change committed separately:

- `src/unifi_mapper/mcp/server.py`
  - The `search_tools` docstring lists the categories as "analysis, diagnostics,
    discovery, connectivity, network, protect".
  - The `list_categories` docstring has no `observability` entry.
  - An MCP client that reads these docstrings doesn't learn that the category exists.
- `docs/mcp-server/MCP_SERVER_GUIDE.md`
  - It says "Exposes 50+".
  - It lists analysis (30), diagnostics (4) and discovery (4).
  - It has no observability row.

The same guide has two more stale statements:

- It gives `uvx install .` as the install command. The command is `uv tool install .`.
- It says "MCP exposes Python validation and mutation tools". That contradicts
  `execute_tool`, which refuses controller writers with `MUTATION_REFUSED`.

## Impact

MCP clients and readers get the wrong tool inventory. It doesn't break fresh clones, CI
or production.

## Fix

- `server.py`, `search_tools`: add `observability` to the `category` list.
- `server.py`, `list_categories`: add
  `- observability: Event, alarm and system-log history; port counter rates`.
- Guide:
  - "Exposes 50+" → "Exposes 70".
  - analysis (30) → (40).
  - diagnostics (4) → (8): "Health, performance, security, connectivity, single-port
    inspection, port evidence bundle, all-ports view, profile diff".
  - discovery (4) → (5): add "client history".
  - Add "**observability** (2 tools): Event, alarm and system-log history; port counter
    rates".
  - `uvx install .` → `uv tool install .`.
  - Reword the "mutation tools" sentence.

`tests/mcp/test_port_diagnostic_tools.py::test_registry_totals` pins the registry counts.
