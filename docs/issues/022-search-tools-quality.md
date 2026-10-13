---
title: "`search_tools` misses multi-word queries, tags and differently-cased categories"
date: 2026-10-02
status: resolved
resolved_by: 0c98496
severity: low
components: [mcp/registry, mcp/server]
found_by: MCP uvx standards work
---

# `search_tools` misses multi-word queries, tags and differently-cased categories

## Problem

`ToolRegistry.search` (`mcp/registry.py`) keeps a tool only if the whole query string is a
substring of `"<name> <description>"`, lower-cased. Measured against the 76 registered tools at
commit `ab32faa`:

| Call | Results | Why |
| --- | ---: | --- |
| `search_tools(query="port vlan")` | 0 | The words aren't adjacent anywhere |
| `search_tools(query="list devices")` | 0 | Same |
| `search_tools(query="link speed")` | 0 | `audit_link_speeds` matches only as `link_speed` |
| `search_tools(query="inventory")` | 0 | Tags aren't searched (`tags=["inventory"]` finds 4) |
| `search_tools(category="Analysis")` | 0 | Category match is case-sensitive (`"analysis"` finds 46) |

Results are sorted by `(category, name)`, not by relevance, and summary results don't mark the
three mutating tools, so a model can pick one and only learn from `MUTATION_REFUSED` (sibling
review §3.5).

## Impact

On the default discovery surface `search_tools` is how the model finds tools. Natural queries
return nothing, so the model guesses names or falls back to `list_categories`, costing turns.

## Recommended fix

Keep the signature and the summary/full shapes; change only matching and order:

- Tokenise the query (split on whitespace, `_` and `-`), and match a tool when every token
  appears in its name (with `_` read as a space), description or tags.
- Match `category` case-insensitively.
- Rank by where tokens hit (name > tags > description) and priority (P0 first), then
  `(category, name)` for ties, so results stay deterministic.
- Add `mutates: true` to summary results for the mutating tools.

Add table-driven tests for the five calls above, and keep the existing
`tests/mcp/test_registry.py` expectations.

## Resolution

Resolved on 2026-10-13 (`0c98496`), as recommended. `ToolRegistry.search` splits the query
on whitespace, `_` and `-`; every word must appear in the name (`_` read as a space), the
description or a tag, case-insensitively; `category` matches case-insensitively; with a
query the results are ranked by where the words hit (name, then tags, then description),
then priority (`P0` first), then `(category, name)`; a mutating tool's summary carries
`mutates: true`. The signature and both result shapes are otherwise unchanged.

One refinement of the recommendation: ranking applies only when a `query` is given. With
no query there are no hits to rank by, and ordering the whole catalogue by priority would
have broken the `(category, name)` order that `tests/mcp/test_registry_keys.py` and the
`unifi://catalog` readers rely on; the recommendation's "then `(category, name)` for ties"
is kept as the tie-break with a query.

The same five calls, on the shipped 96 tools at this commit: `"port vlan"` 8 results,
`"list devices"` 5 (`get_device_inventory` first), `"link speed"` 3 (`audit_link_speeds`
first), `"inventory"` 6, `category="Analysis"` 57 (equal to `"analysis"`).
`tests/mcp/test_search_quality.py` pins them, the ranking on a fixture whose answer is
known, the token splitting and the summary shape; `test_registry.py` and
`test_registry_keys.py` pass unchanged. The `search_tools` docstring (the description the
MCP client sees) and the guide's meta-tools bullet describe the matching.
