---
title: "discover needs Graphviz's dot program for its PNG and SVG diagrams and exits 1 without it, writing no report"
date: 2026-10-06
status: open
severity: low
components: [enhanced_network_topology, run_methods, README]
found_by: 0.2.0 port (live read-only run)
---

# discover needs Graphviz's dot program for its PNG and SVG diagrams and exits 1 without it, writing no report

## Problem

`discover` (and the legacy entry points that run it) draws its topology diagram as a PNG by
default, through `NetworkTopology.generate_png_diagram` (or `generate_svg_diagram`) in
`enhanced_network_topology.py`; `diagram` does the same. The `graphviz` Python package is a
declared dependency, but it only drives Graphviz's `dot` program, which nothing installs.
Without `dot` on `PATH` the render raises graphviz's `ExecutableNotFound` ("failed to
execute PosixPath('dot'), make sure the Graphviz executables are on your systems' PATH");
the method logs it and re-raises, so the command exits 1 after the dry run has already run
and printed its plan. The `ImportError` branch beside it (the Python package missing) writes
a placeholder file and a warning instead.

A failed render costs two more things:

- **The `-o` report is never written.** `run_port_mapper` (`run_methods.py`) draws the
  diagram before it writes the port-mapping report, so the error ends the run first.
- **The DOT source is left behind.** graphviz saves the source at the diagram path minus its
  extension (the method strips `.png` or `.svg`) and deletes it only after `dot` succeeds,
  so it stays there, with the site's device names: `./diagrams/network_diagram` by default.

Found when the host's Graphviz install went away between two read-only live runs: the four
live cases that run `discover` passed at one HEAD and exited 1 at the next, with the same
GET-only requests, while every other case passed.

## Impact

On a machine without Graphviz, `discover` fails at its last step, writes no report, and
leaves the DOT source in `./diagrams/` (or beside the `-d` path). Its error names neither
the command to install Graphviz nor the way round it (`--format html` draws without `dot`).
Breaks fresh clones, CI or prod: a fresh clone without Graphviz, yes, for `discover`'s
default PNG output; the tests fake the render.

Already done: `.gitignore` ignores everything under the repository root's `diagrams/` but
`.gitkeep`, so an ordinary `git add` doesn't stage a source left there (the rules, like the
`reports/` ones, are anchored at the root: a run from a subdirectory writes where none
applies, which issue 010's working-directory decision covers, and `git add -f` still can); `scripts/network-audit.sh` passes `discover` a `-d` in its own
private output directory; and the README, the use-cases guide and the runbook name Graphviz
(`brew install graphviz`, `sudo apt install graphviz`) as the prerequisite for PNG and SVG
diagrams, say that `--format html` needs none, and describe the failure.

## Recommended fix

The code half, still open: treat `graphviz.ExecutableNotFound` as the `ImportError` branch
does, a warning that names the install and a placeholder, and write the report anyway, so
the dry run's exit status stays 0; or check for `dot` before the run and refuse with that
message. Either changes what `discover` does without Graphviz, so it needs sign-off as a
user-visible change. Test both formats with `shutil.which('dot')` faked to None, and remove
the DOT source a failed render leaves.

Done since: both methods used to strip the extension with `str.replace`,
which removed `.png` (or `.svg`) anywhere in the path, so a `-d` under a directory such as
`site.png.d/` rendered into `site.d/`, outside the directory the audit script checks. They
now strip only a final suffix that matches the format (`Path.with_suffix('')`), and
`tests/test_diagram_render.py` pins it for a directory whose name holds the extension.
