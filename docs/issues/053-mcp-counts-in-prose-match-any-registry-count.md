---
title: "A tool count in prose only has to match one of the registry's counts"
date: 2026-10-04
status: resolved
resolved_by: b131da0
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

## Resolution

Resolved on 2026-10-13 (`b131da0`). `mcp_count_problems` now requires a free-text tool count
to equal `ToolRegistry()`'s total unless its sentence names a category (`analysis`,
`diagnostics` and the rest, as the registry spells them), a surface (`direct`, `discovery`,
`listed`) or a kind (`meta-tools`, `mutating`, `pipeline`, `read-only`), in which case that
word's own counts are allowed as well; `categories`, `meta-tools` and `schemas` as the noun
name their own count outright. `McpFacts.qualified` holds the word-to-counts map and replaces
`McpFacts.valid`. That is the wording list of step 1; "open-world" and the idempotency counts
were dropped, since no doc states them and a count nobody writes needs no allowance.

The sentence is the wrapped prose around the line, joined with the lines before and after it
until a sentence ends or a block (heading, list item, table row, fence) starts; a table row
or a line inside a fenced code block stands alone, since a Mermaid label next to another
category's label must not borrow its name. Three gaps in the matching closed on the way:
`COUNT` tolerates a comma between the qualifier words (`73 non-mutating, non-pipeline
catalog tools` had never been matched), skips the `3` of a `13.3` section number (two
headings matched by luck and passed because 3 and 6 are registry counts), and
`TOTAL_AFTER_NOUN` checks the `Total registered tools: **87**` form.

"Nothing is wrong today" above was wrong: the tightened guard reported seven stale numbers,
all fixed in the same commit. Diagnostics has 12 tools, not 11 (`docs/architecture/README.md`
and the `use-cases-and-howto.md` diagram; 11 is the pipeline count, which is why they passed);
the direct catalog is 82 tools, not 73 (two lines of `architecture-overview.md`, hidden by
the comma); the registry holds 96 tools, not 87 (`providers/mcp-automation.md`, written after
the noun). Two labels now say what they count rather than failing the stricter rule: the
progressive-disclosure paragraph's "4 tools" are the 4 meta-tools, and the ToolkitAdapter
node in `architecture-overview.md` names the three functions it wraps instead of "3 tools",
a number that happened to equal the mutating count and is not a registry count at all. The
self-test reports a stale total that equals a category's count and accepts the same number
when the sentence names the category or surface, on the line before included.
