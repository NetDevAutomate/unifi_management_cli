---
title: "The env-var guard counts a variable as read when any string in the code names it"
date: 2026-10-04
status: open
severity: low
components: [tests/test_docs_consistency.py]
found_by: docs and repo hygiene review (council, iteration 4)
---

# The env-var guard counts a variable as read when any string in the code names it

## Problem

`tests/test_docs_consistency.py` fails when a current doc names a `UNIFI_*`, `PROTECT_*` or
`XDG_*` variable that no code reads. `env_vars_read` decides what the code reads: in Python,
every string constant that isn't a docstring counts, and in shell and YAML files every line
that isn't a comment. `PREFIXED_READERS` adds the variables read through a prefix
(`from_env(prefix=...)` plus `get_env('KEY')`).

A string constant is not always a read. A variable named only in a user-facing message, such
as an error hint that tells the user to set it, counts as read, so a doc can keep naming a
variable that the code no longer reads, as long as some message still mentions it.

## Impact

Docs only, and nothing is wrong today: this review's local env-var check reports no doc-only
variable outside `docs/issues/`. The guard would miss a stale variable whose name survives in a
message.

## Recommendation

1. Add a negative self-test first: a synthetic source whose only mention of a variable is an
   error message must not count it as read. It fails until step 2 lands.
2. Narrow the Python reader to real reads: the first argument of `os.environ[...]`,
   `os.environ.get`, `os.getenv` and the project's own env helpers, plus
   `PREFIXED_READERS`, with an explicit allowlist for any other read the narrower rule
   misses.
3. Re-run the guard, and file or fix any doc that then names a variable no code reads.

The design step is the list of reader calls: the settings classes and the prefixed readers
have to keep working.
