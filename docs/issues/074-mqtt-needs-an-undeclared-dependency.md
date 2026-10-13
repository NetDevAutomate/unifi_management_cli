---
title: "MQTT support needs aiomqtt, which the project does not declare"
date: 2026-10-06
status: resolved
resolved_by: df3d905
severity: low
components: [protect/mqtt, pyproject.toml]
found_by: 0.2.0 port (while fixing a review finding)
---

# MQTT support needs aiomqtt, which the project does not declare

## Problem

`protect/mqtt.py` imports `aiomqtt` when an `MQTTBridge` starts, and without it raises
`ImportError`. `aiomqtt` is in neither `pyproject.toml`'s dependencies nor `uv.lock`, so
`uv sync` never installs it. The README documents the bridge as a Python API ("MQTT Bridge
for Home Assistant").

The error's hint used to be a pip command (`pip install aiomqtt`) in a project that uses uv
only. It now says `Add it with: uv add aiomqtt`, as the use-cases guide already did, and the
README states the prerequisite beside its MQTT example: `uv add aiomqtt`, or
`uv run --with aiomqtt python <script>` for a run that changes no project file. The
declaration itself is still open.

## Impact

Anyone who runs the README's MQTT example after `uv sync` alone still gets the
`ImportError`, though its hint and the README now name the uv command. No CLI command or MCP
tool uses MQTT, and the tests fake the import. Breaks fresh clones, CI or prod: no.

## Recommended fix

Declare the package, then make the hint the command that installs it:

- as an optional extra (`mqtt = ["aiomqtt>=2,<3"]` under `[project.optional-dependencies]`,
  hint `uv sync --extra mqtt`), which is the question [issue 014](014-optional-dependency-extras.md)
  leaves open for Protect, backup and ONVIF; or
- as a plain dependency (hint `uv sync`), which every install then carries.

The decision needed is 014's: whether optional features get extras. Test: the `ImportError`'s
hint names that uv command, and the extra (if chosen) resolves in `uv.lock`.

## Resolution

Resolved on 2026-10-13 (`df3d905`) with the first option: `aiomqtt` is the optional extra
`mqtt = ["aiomqtt>=2,<3"]` under `[project.optional-dependencies]`, resolved in `uv.lock`
(aiomqtt 2.5.1 with paho-mqtt 2.1.0); a plain `uv sync` still leaves it out, so every
install does not carry an MQTT client it may never use. The `ImportError` hint now reads
`Install it with: uv sync --extra mqtt`, and the README's limitation bullet, the Protect
guide and the use-cases guide (prerequisite and error table) name that command instead of
`uv add aiomqtt` / `uv run --with aiomqtt`.

This answers [issue 014](014-optional-dependency-extras.md)'s question for MQTT only; the
Protect, backup and ONVIF extras it asks about are not decided here. Test:
`tests/protect/test_mqtt.py::TestMQTTBridgeLifecycle::test_start_without_aiomqtt_raises`
asserts the hint names `uv sync --extra mqtt` and no longer `uv add aiomqtt`.
