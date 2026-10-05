---
title: "Tracebacks can print secrets: loguru's `diagnose` and Typer's frame locals are on"
date: 2026-10-05
status: resolved
severity: medium
components: [src/unifi_mapper/mcp/server.py, src/unifi_mapper/typer_cli.py, src/unifi_mapper/inventory_cli.py, src/unifi_mapper/core/utils/logging.py]
found_by: July-port design review (revision 5, M1 and M2)
---

# Tracebacks can print secrets: loguru's `diagnose` and Typer's frame locals are on

## Problem

Two traceback formatters print the values of variables in failing frames. A credential read
from the env file, or passed as an argument, is one of those variables.

- **Typer frame locals (live in both CLIs).** `pyproject.toml` pins `typer>=0.21,<0.22`, and
  0.21.0 is locked. Before 0.23.0, Typer's `pretty_exceptions_show_locals` defaults to True.
  None of the 8 `typer.Typer(...)` apps in `src/` sets it, so an unhandled exception in
  `unifi-mapper` or `unifi-inventory` prints the frame locals. Checked at `ef150e2`: both apps
  report True.
- **loguru `diagnose` (live in the MCP server).** It annotates each traceback line with
  variable values when an exception is logged.
  - `mcp/server.py:669` replaces loguru's handlers with a stderr sink that keeps the default,
    which is on. The MCP client captures that stderr in its own logs.
  - Commands that never configure loguru use its default stderr handler, which is also on.
  - `core/utils/logging.py` sets `diagnose=True` on a rotated JSON file sink (`:41`), but
    `configure_logging` is never called (issue
    [045](045-configure-logging-is-never-called.md)). It is a trap for whoever wires it up.

## Impact

Any unhandled exception in a command that holds a credential can write it to the terminal
(and from there into pasted error reports or recorded sessions), or into the MCP client's log.
No such leak has been observed. This is about the defaults.

## Recommendation

1. Pass `pretty_exceptions_show_locals=False` to every `typer.Typer(...)`, sub-apps included.
2. Set `diagnose=False` on every `logger.add` in `src/`, and remove loguru's default handler in
   the CLI entry points before anything logs. Deleting `configure_logging` (045) removes the
   file sink.
3. Add tests: one imports each Typer app and asserts the flag is False; one logs an exception
   whose frame holds a sentinel credential and asserts the sentinel isn't in the output.
4. Fix it before the next push. The planned July-port changes already include it.

## Resolution

Fixed as recommended, in the July port, before any tool that returns config objects:

- Every `typer.Typer(...)` in `src/` (the 7 in `typer_cli.py` and `inventory_app`) passes
  `pretty_exceptions_show_locals=False`; the 24 `print_exception(show_locals=True)` debug paths
  pass `False`.
- `_diagnostic_errors()` ends any other exception as one redacted `Error:` line on stderr
  (exit 1), after re-raising `typer.Exit` and `typer.Abort`, so the nine sync diagnostic
  commands never reach Typer's traceback.
- `UnifiConfig.password` and `api_token` are `field(repr=False)`.
- `diagnose=False` on `server._configure_logging`'s handler and on both `logger.add` calls in
  `core/utils/logging.py`. Both CLIs replace loguru's default handler with a `diagnose=False`
  stderr handler at the same level before anything logs
  (`core/utils/logging.replace_default_loguru_handler`).

A follow-up from the July port's M2 council closed the rest of the CLI's error output: `_fail`
redacts its text (a `ToolError` can carry a lower layer's exception text), every `Error: …`
line that showed a caught exception goes through `redact_text` (`typer_cli._error_text`), and
`--debug` prints its traceback through `typer_cli._print_debug_traceback`, which keeps every
frame but redacts each exception message. An AST test fails on any CLI print of a caught
exception that isn't redacted, and on any `print_exception` call in either CLI.

Tests: `tests/test_error_output.py` asserts the flag on all 8 apps and, by AST, that every
`typer.Typer(` and `logger.add(` in `src/` sets it off and no `show_locals=True` remains; that
the config's repr holds no password; and that a `logger.exception` from a frame holding a
sentinel credential writes no sentinel, after the server's setup and after the CLI's swap.
`tests/test_ports_cli.py` runs `ports list` through the real `_readonly_client` on a password
config: an unexpected error is one redacted `Error:` line, and a login failure still prints
exactly one `❌` line.
