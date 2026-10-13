---
title: "`configure_logging` is never called, so `UNIFI_MAPPER_DEBUG` does nothing"
date: 2026-10-04
status: resolved
resolved_by: 70bbf8b
severity: low
components: [core]
found_by: docs and repo hygiene review (environment variable check)
---

# `configure_logging` is never called, so `UNIFI_MAPPER_DEBUG` does nothing

## Problem

`core/utils/logging.configure_logging` (`src/unifi_mapper/core/utils/logging.py:10`) sets up
loguru with a JSON-lines file sink under `~/.unifi-mapper/logs/` (10 MB rotation, 7 days
retention), and adds a stderr sink when `include_console` is true or `UNIFI_MAPPER_DEBUG` is
set (`:45`). It is exported from `unifi_mapper.core` (`src/unifi_mapper/core/__init__.py:30`)
and `unifi_mapper.core.utils` (`src/unifi_mapper/core/utils/__init__.py:5`), but nothing in
`src/`, `tests/` or `scripts/` calls it.

So `UNIFI_MAPPER_DEBUG` has no effect, and no log file is ever written there. The working
logging paths are:

- the CLI: `typer_cli.setup_logging`, stdlib logging through a Rich handler, at `DEBUG` with
  the root `--debug` and `INFO` otherwise;
- the MCP server: `server._configure_logging`, loguru on stderr at `UNIFI_MCP_LOG_LEVEL`
  (default `WARNING`).

The docs don't mention `UNIFI_MAPPER_DEBUG`; this issue is the only place it is named, so
nobody is told to set a variable that does nothing.

## Impact

None at run time: the function is dead code. The risk is a future caller (or a user reading
the source) expecting `UNIFI_MAPPER_DEBUG` to work, or a call added later that starts writing
a log file in the home directory unannounced.

## Decision needed

Recommendation: delete `configure_logging`, its two re-exports and the variable, since the
CLI and the MCP server each have their own working setup. The alternative is to wire it into
the CLI (for example behind `--debug`) and document the log file it writes.

Why this needs a decision: deleting it removes a public name from `unifi_mapper.core`, and
wiring it in changes what the CLI writes to disk.

## Resolution

Resolved on 2026-10-13 (`70bbf8b`), the recommended way: `configure_logging` is deleted from
`core/utils/logging.py` together with its re-exports from `unifi_mapper.core` and
`unifi_mapper.core.utils`, and with it the only read of `UNIFI_MAPPER_DEBUG`. The claims
held: nothing in `src/`, `tests/` or `scripts/` called the function, and no document outside
this issue named the variable (the architecture overview and the codemap said as much and
now record the removal without naming it, so the docs' environment-variable check stays
clean). `replace_default_loguru_handler`, which both CLIs call, `get_logger` and the
tool-call helpers stay.

Deliberately not changed: the public name is removed rather than wired into `--debug`,
because the CLI and the MCP server each have a working setup and a JSON log file in the home
directory would be a new behaviour to document and secure. Tests:
`tests/test_configure_logging_removed.py` asserts the name is gone from the three modules,
the loguru helper stays, and the variable is named nowhere but under `docs/issues/`.
