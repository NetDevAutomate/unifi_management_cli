---
title: "The env-var guard counts a variable as read when any string in the code names it"
date: 2026-10-04
status: resolved
resolved_by: ff69dc6
severity: low
components: [tests/test_docs_consistency.py]
found_by: docs and repo hygiene review
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

## Resolution

Resolved on 2026-10-13 (`ff69dc6`). `env_vars_read` reads a Python source's AST and counts a
variable only at a real read. The reader list (the design step):

- the subscript of `os.environ[...]`, and the first argument of `.get`, `.pop` or
  `.setdefault` on the environment: `os.environ`, `environ`, an injected `env` mapping
  (`load_server_settings(env=None)`) or `(os.environ if env is None else env)`;
- the first argument of `os.getenv` / `getenv`;
- the left side of `in` / `not in` against the environment;
- the key argument of a same-file helper whose own body reads that parameter from the
  environment, found from the helper rather than listed (`_bounded_number(env, key, ...)` in
  `mcp/config.py`);
- an option's `envvar=`;
- `PREFIXED_READERS`, unchanged.

The key may be a string or a module-level constant (`CALL_AUDIT_ENV`, `SURFACE_ENV`,
`CAMERA_HOSTS_VAR`). A module-level assignment whose string constants are exact variable
names also counts, whether one constant or a table (`CREDENTIAL_KEYS`, `_HOST_KEYS`,
`_TOKEN_KEYS`), because the code reads those keys by the constant's name or by iterating the
table, in another file at times; a message constant is not an exact name and does not count.
That is the "explicit allowlist for any other read" of step 2, expressed as a shape rather
than a list of names. A name that appears only in a message, hint, help text, f-string,
docstring or comment is not read.

The self-test (step 1) gives one source with every read form and six message-only mentions
and expects exactly the twelve reads; it failed under the old reader, which counted the
messages. Over `src/` and `scripts/` the narrower reader yields the same 51 variables as the
old one, so every variable a message names is also read somewhere, and no doc needed a
change (step 3).
