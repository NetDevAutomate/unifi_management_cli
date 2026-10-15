---
title: "`diagram` prints `✅ Diagram generated` after a placeholder render"
date: 2026-10-13
status: resolved
resolved_by: 98dc733
severity: low
components: [typer_cli, enhanced_network_topology]
found_by: the 0.3.0 CLI lane (issue 075)
---

# `diagram` prints `✅ Diagram generated` after a placeholder render

## Problem

Since issue 075, a missing Graphviz `dot` makes `generate_png_diagram` / `generate_svg_diagram`
write a placeholder and return normally. `typer_cli.py` line ~3265 prints the success line
without inspecting the result, so `diagram` reports a diagram that is a placeholder.

## Impact

A single-purpose command appears to succeed while producing no image; the warning the renderer
logs is easy to miss under the green success line.

## Recommended fix

Have the renderers return whether a real image was written (or expose the placeholder marker)
and print a yellow warning line instead of the success line when it was not; exit 0 either way
per issue 075's decision.

## Resolution (2026-10-15)

`generate_png_diagram` and `generate_svg_diagram` now return `None` when they drew the image
and the placeholder's text, the reason, when they did not (no `dot` on `PATH`, or no
`graphviz` package). `discover` ignores the value, so issue 075's behaviour there (report
written, exit 0) is unchanged.

`diagram` no longer prints the success line after a placeholder. It prints a yellow
`No diagram drawn: <path> holds a placeholder.` line with the reason in its place, then the
device summary, and exits 0, as issue 075 decided: a placeholder is a warning, not a
failure, and the exit code is unchanged from 0.3.0. Its `--help` says so.

Pinned by `tests/cli/test_diagram_command.py` (PNG and SVG without `dot`: the warning, no
success line, the placeholder written, exit 0; with a fake `dot`: the success line and exit
0) and `tests/test_enhanced_network_topology_render_result.py` (the renderers' return value
without `dot`, without the package, and after a drawing).

A user without Graphviz sees a yellow warning naming the install instead of a green success
line; a script sees the same exit 0 it did before.
