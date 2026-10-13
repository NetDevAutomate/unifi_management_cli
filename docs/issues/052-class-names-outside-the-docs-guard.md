---
title: "Class names in the docs are outside the docs-drift guard"
date: 2026-10-04
status: resolved
resolved_by: 9b5af8b
severity: low
components: [tests/test_docs_consistency.py, docs]
found_by: docs and repo hygiene review
---

# Class names in the docs are outside the docs-drift guard

## Problem

`tests/test_docs_consistency.py` checks commands, MCP tool names and counts, links, local
paths, environment variables and identifiers, but not class or member names. Its
`mcp_name_problems` reads only backticked snake_case names that start with a tool-like verb,
so a class that is renamed or removed stays in the prose and in the Mermaid class views, and
nothing fails.

The drift is real. The docs review fixed six stale class names by hand (`StatisticsManager`,
`DPIManager`, `StatisticsCollector`, `TrafficMatchingManager`, `ProtectRepository` and a
`FastMCPServer` class view), each found by a local scan the repository doesn't keep.

At `78241ce` the current docs (all but `docs/issues/` and `docs/solutions/`) hold:

- 93 distinct backticked names with at least two capitalised parts (such as `UniFiClient`),
  260 uses. 83 are classes defined under `src/`. The other 10 are built-ins or third-party
  types: `BaseModel` and `SecretStr` (pydantic), `CallToolResult` and `ToolAnnotations`
  (mcp), `ProtectApiClient` and `UnsubscribeFunc` (uiprotect), `GetStreamUri` (an ONVIF
  operation), and `ImportError`, `PermissionError` and `ValueError`.
- 10 Mermaid `classDiagram` blocks naming 38 classes. All but `Exception` are defined under
  `src/`.

## Impact

Docs only: nothing breaks for users, CI or fresh clones. A stale class name sends a reader,
or an agent, looking for code that isn't there.

## Recommendation

Add a detector with the same shape as the others, a pure `(path, text)` function with a
negative self-test on a synthetic snippet:

1. Collect the `class` names under `src/`, as `_known_names()` already does.
2. Report each backticked name with two or more capitalised parts in a current doc, and each
   `class Name` line in a Mermaid `classDiagram` block, that is neither one of them nor in an
   explicit allowlist of built-in and third-party types. Seed the allowlist with the 11 names
   above, and add a name only after checking it is a real type of that library.
3. Later, optionally: check `Class.member` references against the class's AST.

Design the allowlist first (where it lives and what may join it), then build the detector.

## Resolution

Resolved on 2026-10-13 (`9b5af8b`). `class_name_problems` in `tests/test_docs_consistency.py`
reports a backticked CamelCase name (two or more capitals and a lower-case letter, alone,
called or with a member) in a current doc, and each class a Mermaid `classDiagram` declares
with `class Name` or relates with one of the class-diagram arrows, when it is neither a class
under `src/`, nor a module-level CamelCase type alias there, nor one of
`KNOWN_EXTERNAL_TYPES`.

The allowlist lives beside the detector. It holds the eleven built-in and third-party names
the current docs use, each checked against its library before joining: `Exception`,
`ImportError`, `PermissionError` and `ValueError` (Python), `BaseModel` and `SecretStr`
(pydantic), `CallToolResult` and `ToolAnnotations` (`mcp.types`), `ProtectApiClient`
(uiprotect), `GetStreamUri` and `XAddr` (ONVIF: the Media operation and the service-address
element). A name defined under `src/` never joins it, so a renamed or removed class fails.
Two corrections to the counts above: `UnsubscribeFunc` is not a uiprotect type but a type
alias in `protect/events.py` (`Callable[[], None]`), which is why module-level CamelCase
aliases count as known; and the docs now hold 132 distinct such names (324 uses) and name
`XAddr`, which the list above lacked. Relation ends are checked as well as `class` lines,
since a renamed class is as stale in `A <|-- B` as in `class B`.

The names come from `src_bindings`, an AST reading of each tracked source into functions,
classes, module-level names, class attributes and parameters, shared with issue
[056](056-mcp-name-guard-knows-every-assigned-name.md). The self-test reports a made-up class
in prose and in a diagram and accepts real, aliased and external ones; without the allowlist
the detector reports exactly the eleven external names in the current docs and nothing else,
so no doc needed a fix. `Class.member` references are still not checked against the class's
AST (the optional third step).
