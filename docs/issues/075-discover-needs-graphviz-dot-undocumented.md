---
title: "discover needs Graphviz's dot program for its PNG and SVG diagrams, undocumented, and exits 1 without it"
date: 2026-10-06
status: open
severity: low
components: [enhanced_network_topology, run_methods, README]
found_by: July port build loop, iteration 7 (live read-only run)
---

# discover needs Graphviz's dot program for its PNG and SVG diagrams, undocumented, and exits 1 without it

## Problem

`discover` (and the legacy entry points that run it) draws its topology diagram as a PNG by
default, through `NetworkTopology.generate_png_diagram` (or `generate_svg_diagram`) in
`enhanced_network_topology.py`. The `graphviz` Python package is a declared dependency, but it
only drives Graphviz's `dot` program, which nothing installs and neither the README nor the
runbook names as a prerequisite. Without `dot` on `PATH` the render raises graphviz's
`ExecutableNotFound` ("failed to execute ... dot, make sure the Graphviz executables are on
your systems' PATH"); the method logs it and re-raises, so the command exits 1 after the dry
run has already run and printed its plan. The `ImportError` branch beside it (the Python
package missing) writes a placeholder file and a warning instead.

Found when the host's Graphviz install went away between two read-only live runs: the four
live cases that run `discover` passed at one HEAD and exited 1 at the next, with the same
GET-only requests, while every other case passed.

## Impact

On a machine without Graphviz, `discover` fails at its last step with an error that names
neither the command to install it nor the way round it (`--format html` draws without
`dot`). Breaks fresh clones, CI or prod: a fresh clone without Graphviz, yes, for
`discover`'s default PNG output; the tests fake the render.

## Recommended fix

1. Docs: name Graphviz (`brew install graphviz`, `apt install graphviz`) as the prerequisite
   for PNG and SVG diagrams in the README's install section and the runbook, and say that
   `--format html` needs none.
2. Code: treat `graphviz.ExecutableNotFound` as the `ImportError` branch does, a warning that
   names the install and a placeholder, so the dry run's exit status stays 0; or check for
   `dot` before the run and refuse with that message. Either changes what `discover` does
   without Graphviz, so it needs sign-off as a user-visible change. Test both formats with
   `shutil.which('dot')` faked to None.
