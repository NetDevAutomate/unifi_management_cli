---
title: "MQTT support needs aiomqtt, which the project does not declare, and its error says pip install"
date: 2026-10-06
status: open, decision needed
severity: low
components: [protect/mqtt, pyproject.toml]
found_by: July port build loop, iteration 7 (while fixing review SR6-N4)
---

# MQTT support needs aiomqtt, which the project does not declare, and its error says pip install

## Problem

`protect/mqtt.py` imports `aiomqtt` when an `MQTTBridge` starts, and without it raises
`ImportError: aiomqtt is required for MQTT support. Install with: pip install aiomqtt`.
`aiomqtt` is in neither `pyproject.toml`'s dependencies nor `uv.lock`, so `uv sync` never
installs it, and the hint is a pip command in a project that uses uv only (the runbook says
so). The README documents the bridge as a Python API ("MQTT Bridge for Home Assistant").

## Impact

Anyone who follows the README's MQTT example after `uv sync` gets the `ImportError`, and its
hint points them at pip. No CLI command or MCP tool uses MQTT, and the tests fake the import.
Breaks fresh clones, CI or prod: no.

## Recommended fix

Declare the package, then make the hint the uv command that installs it:

- as an optional extra (`mqtt = ["aiomqtt>=2,<3"]` under `[project.optional-dependencies]`,
  hint `uv sync --extra mqtt`), which is the question [issue 014](014-optional-dependency-extras.md)
  leaves open for Protect, backup and ONVIF; or
- as a plain dependency (hint `uv sync`), which every install then carries.

The decision needed is 014's: whether optional features get extras. Test: the `ImportError`'s
hint names the uv command, and the extra (if chosen) resolves in `uv.lock`.
