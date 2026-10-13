---
title: "`unifi-mapper install-completions` accepts `fish` and `all` but installs only bash and zsh"
date: 2026-10-04
status: resolved
resolved_by: 3951920
severity: low
components: [typer_cli, completions]
found_by: docs and repo hygiene review (README install section)
---

# `unifi-mapper install-completions` accepts `fish` and `all` but installs only bash and zsh

## Problem

The command's argument help offers `bash/zsh/fish/all`, and the command accepts those four
(`src/unifi_mapper/typer_cli.py:369-383`). It then hands the shell to the legacy installer,
`completions.install_completions` (`src/unifi_mapper/completions.py:215-240`), which knows
`bash`, `zsh` and `both`:

- `fish` and `all` print `Unsupported shell` from the installer, then `Manual completion
  installation failed`.
- `both`, the one value that installs bash and zsh together, is refused by the command
  before the installer runs.
- A failed installation still exits 0, because the command only prints the failure.

`unifi-network-toolkit install-completions` takes `bash`, `zsh` or `both`, which the
installer does handle. Typer's own `unifi-mapper --install-completion` works for the
current shell, fish included.

## Impact

`unifi-mapper install-completions fish` or `all` looks like it ran, exits 0 and installs
nothing for fish. A script that checks the exit status can't tell. The README now
documents bash and zsh only, and points to `--install-completion` for other shells.

## Fix

Recommended: map `all` to the installer's `both`, refuse `fish` with a pointer to
`--install-completion` (or add a fish installer), exit 1 when installation fails, and make
the argument help list what works. A test should run each accepted value through the
command with the installers faked.

## Resolution

Resolved on 2026-10-13 (`3951920`). `unifi-mapper install-completions` now takes `bash`,
`zsh` or `all` (`both`, the installer's and `unifi-network-toolkit`'s name for the same
thing, is accepted too); `all` maps to the installer's `both`, so bash and zsh are installed
together. `fish` is refused with a pointer to `unifi-mapper --install-completion`, Typer's
own installer, which is the one path that covers fish; no fish script was added, because
Typer already generates one. An installer that returns `False` or raises now exits 1 instead
of printing the failure and exiting 0. The argument help, the command docstring and the
`docs/reference/cli.md` and runbook rows list what works.

Deliberately not changed: the manual bash and zsh scripts themselves (`completions.py`),
which still complete only the legacy `discover` options; `--install-completion` is the
complete alternative. Tests: `tests/test_install_completions.py`, each accepted value
through the command with both installers faked.
