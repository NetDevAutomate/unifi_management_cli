---
title: "A tool count in prose only has to match one of the registry's counts"
date: 2026-10-04
status: open
severity: low
components: [tests/test_docs_consistency.py, docs]
found_by: docs and repo hygiene review
---

# A tool count in prose only has to match one of the registry's counts

## Problem

`tests/test_docs_consistency.py` checks most MCP numbers in the docs exactly against
`ToolRegistry()`: the category table rows, the tool index headings, the direct-surface sums,
the "Of the N" split sentence and the `--check` output. Any other count of tools in an MCP
line, such as "registers 76 tools", is checked by `mcp_count_problems` against
`McpFacts.valid`, the set of every count a claim may equal: the total, each category, each
surface, the meta-tools, the mutating and pipeline tools, and a few more. The module
docstring says so.

So a stale total passes whenever it happens to equal another registry count. If the
registry grew by one tool, a sentence still saying "66 tools" (today's direct listing) or
"46 tools" (today's analysis category) would pass.

At `150e446` the current docs (all but `docs/issues/` and `docs/solutions/`) hold 72 such
free-text counts in 8 files: 21 equal the total, 40 a category's count and 11 another
registry count (a surface, the meta-tools, the mutating or pipeline tools).

## Impact

Docs only, and nothing is wrong today: the local `check_mcp.py` reports 0 implausible counts,
and the exact checks above pass. A stale total would send a reader looking for tools that
don't exist, or miss new ones.

## Recommendation

Require a free-text total to equal `facts.total` unless its sentence names a category or a
surface:

1. Decide what wording counts as naming one: a category name (`analysis`, `discovery` and the
   rest), a surface (`direct`, `discovery`, "listed"), "meta-tools", "mutating", "pipeline",
   "open-world" and similar. That list is the design step.
2. In `mcp_count_problems`, check a count against `facts.total` when its sentence names none
   of them, and against `McpFacts.valid` otherwise.
3. Add a negative self-test on a synthetic snippet: "registers 66 tools" is reported, "66
   tools on the direct surface" is not.
