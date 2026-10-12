---
title: "The MCP-name guard counts any name assigned in `src/` as known, local variables included"
date: 2026-10-04
status: open
severity: low
components: [tests/test_docs_consistency.py]
found_by: docs and repo hygiene review (code review, iteration 5)
---

# The MCP-name guard counts any name assigned in `src/` as known, local variables included

## Problem

`tests/test_docs_consistency.py` fails when a current doc names a tool-shaped identifier (a
backticked snake_case name with one of the `TOOLISH` verb prefixes, such as `check_` or
`get_`) that isn't a known name. `_known_names()` builds the known set from the registry's
tools, the meta-tools, the prompts and the credential families, from every `def` and `class`
name and module stem under `src/`, and from the parameter keys in the MCP manifests.

It also adds every name that matches `^\s*name\s*[:=]` in a tracked `src/` file. That pattern
matches more than module-level names: local variables, class attributes, parameters written
on their own line and keyword arguments on their own line all count. So a doc that names a
removed or misspelt tool still passes when the name happens to be assigned somewhere in
`src/`, and the negative self-test can't show it, because its made-up name is absent from
`src/`.

At `02043ea`, across the 155 tracked `.py` files under `src/`:

- 76 tool-shaped names, from 56 files, are known only through that pattern;
- by binding (a name can have several): 52 are local variables, 27 class attributes, 26
  keyword arguments, 21 parameters and 3 module-level names;
- narrowing the pattern to module-level `Assign` and `AnnAssign` targets would drop 73 of
  them, and it would report 0 new problems in any doc, current or historical.

Issues [052](052-class-names-outside-the-docs-guard.md) (class names),
[053](053-mcp-counts-in-prose-match-any-registry-count.md) (counts) and
[055](055-env-guard-counts-a-mention-as-a-read.md) (env-var reads) don't cover it.

## Impact

Docs only, and nothing is wrong today: every tool-shaped name in the docs resolves without
the 76. The guard would miss a stale tool name that matches one of them. The exact checks
(the tool index per category, and the counts from `ToolRegistry()`) don't depend on it.

## Recommendation

1. Add a negative self-test first: a synthetic `src/` file in which a tool-shaped name
   exists only as a local variable, and a doc that names it, which must be reported. It
   fails until step 2 lands.
2. Harvest the names with `ast`, as `env_vars_read` already parses source: module-level
   `Assign` and `AnnAssign` targets, plus whichever other bindings a doc may name.
3. Re-run the guard, and fix or file any doc it then reports. At `02043ea` the narrowest
   set reports none, so no doc needs triage today.

The design step is the binding list in step 2. Class attributes (model and result fields)
and function parameters are names a doc can legitimately describe; local variables and
keyword-argument lines are not.
