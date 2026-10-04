---
title: "`discover --format mermaid` and `--format dot` write a placeholder, not a diagram"
date: 2026-10-04
status: open, decision needed
severity: low
components: [run_methods, enhanced_network_topology, typer_cli, network_cli, cli]
found_by: docs and repo hygiene review (runbook command check)
---

# `discover --format mermaid` and `--format dot` write a placeholder, not a diagram

## Problem

`unifi-mapper discover --format mermaid` and `--format dot` finish without an error, but the
diagram file holds one line of text, `Mermaid diagram would be generated here` or
`DOT diagram would be generated here`:

- `run_port_mapper` sends both formats to `generate_mermaid_diagram` and
  `generate_dot_diagram` (`src/unifi_mapper/run_methods.py:817-820`).
- Both methods write that line and nothing else
  (`src/unifi_mapper/enhanced_network_topology.py:888-906`).

`png`, `svg` and `html` render a real diagram. `unifi-network-toolkit discover` and the
legacy `python -m unifi_mapper.cli` reach the same code through `run_port_mapper`, so they
behave the same way. `unifi-mapper diagram` offers only `png`, `svg` and `html`.

The formats are advertised in:

- the `discover --format` help (`src/unifi_mapper/typer_cli.py:223`:
  `png, svg, html, mermaid, dot`), and the `--format` choices of `unifi-network-toolkit
  discover` (`src/unifi_mapper/network_cli.py:121`) and `python -m unifi_mapper.cli`
  (`src/unifi_mapper/cli.py:134`);
- the use-cases guide and the runbook, which offered `--format mermaid` as a way to get
  Mermaid source to embed in Markdown. The docs review that filed this issue switched those
  examples to `svg` or `html` and links here wherever the two formats are listed.

## Impact

A user who asks for Mermaid source, or DOT to post-process, gets a file that looks like a
success but holds no diagram. Nothing is written to the controller, and the port-mapping
report is unaffected.

## Decision needed

Recommendation: implement both, since the pieces exist.

- DOT: write the source `_generate_dot_source()` already builds for the png and svg
  renderers (`enhanced_network_topology.py:466`).
- Mermaid: reuse the topology renderer in `src/unifi_mapper/utility/render_mermaid.py`
  (`_render_topology_diagram`), which already turns topology data into a Mermaid `graph`.

The alternative is to drop `mermaid` and `dot` from the `--format` choices of all three
entry points, so they refuse the two formats instead of writing a placeholder.

Why this needs a decision: either option changes what `discover` writes for an existing
command line, or what its `--format` help offers.
