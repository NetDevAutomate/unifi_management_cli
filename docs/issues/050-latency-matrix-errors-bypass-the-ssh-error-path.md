---
title: "`diagnose latency-matrix` reports errors on stdout and unredacted, unlike `diagnose bandwidth`"
date: 2026-10-04
status: resolved
resolved_by: 8308183
severity: low
components: [typer_cli, latency_matrix]
found_by: docs and repo hygiene review (SSH error documentation)
---

# `diagnose latency-matrix` reports errors on stdout and unredacted, unlike `diagnose bandwidth`

## Problem

The two gateway SSH commands report a failure in different ways:

| | `diagnose bandwidth` | `diagnose latency-matrix` |
| --- | --- | --- |
| Path | `_run_gateway_ssh` → `_fail` in `typer_cli.py` | its own `except Exception` in `typer_cli.diagnose_latency_matrix` |
| Stream | stderr | stdout |
| Prefix | `❌` | `Error:` |
| Wrapping | none (`soft_wrap=True`) | Rich wraps at the terminal width |
| Unexpected errors | text passed through `redact_text`; traceback only with `--debug`, without local variables | printed as they are, without redaction or markup escaping |

Both exit 1, and for a missing `UNIFI_SSH_PASSWORD` both print the same
`[CONFIG_MISSING] …` message and `💡 Suggestion:` line. The CLI test
(`tests/analysis/test_gateway_ssh.py`, `test_cli_without_ssh_password_says_what_to_set`)
checks only that text, so it passes for both. The README and the runbook describe the
difference.

## Impact

A script that reads stderr for errors misses the latency matrix's. An unexpected exception
from the SSH layer is printed without the redaction the bandwidth command applies, so a
secret in the exception text would reach the terminal. Nothing is known to leak today. It
doesn't break fresh clones, contributors or CI.

## Recommended fix

Run the latency matrix through `_run_gateway_ssh`, as `diagnose bandwidth` does:

```python
report = _run_gateway_ssh(
    lambda: run_latency_matrix(
        ping_count=ping_count, timeout=timeout, include_clients=not devices_only
    )
)
```

Then extend the CLI test to assert, for both commands, that the error goes to stderr with
the `❌` prefix, and add a case for an unexpected exception whose text holds a secret
assignment. After the fix, change the README and runbook to describe one behaviour again.

## Resolution

Fixed as recommended, in the July port: `diagnose latency-matrix` now runs through
`_run_gateway_ssh`, as `diagnose bandwidth` does, so both report a failure on stderr with the
`❌` prefix, unwrapped, and an unexpected error's text redacted (a traceback only with
`--debug`, without local variables). Since the July port's SSH refactor, both connect
messages read "SSH connection to {host} failed: …", redacted.

Tests: `tests/analysis/test_gateway_ssh.py` runs both commands through a refused connect and
through an unexpected exception whose text holds a password assignment, and checks stderr,
stdout and the redaction for each. The two latency-matrix cases failed before the fix.
