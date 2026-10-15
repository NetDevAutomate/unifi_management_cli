---
title: "`diagram` prints `✅ Diagram generated` after a placeholder render"
date: 2026-10-13
status: open
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
