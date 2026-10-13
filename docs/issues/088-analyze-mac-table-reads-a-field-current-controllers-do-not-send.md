---
title: "`analyze mac-table` reads `device['mac_table']`, which current controllers do not send, so it reports nothing"
date: 2026-10-13
status: open
severity: medium
components: [analysis/mac_analyzer]
found_by: the 0.3.0 analysis lane, live run during issue 030
---

# `analyze mac-table` reads `device['mac_table']`, which current controllers do not send, so it reports nothing

## Problem

`analysis/mac_analyzer.py` line ~122 reads `device.get('mac_table', [])` from `stat/device`. On
the maintainer's controller no device record carries `mac_table`, before or after issue 030, so
the tool reports 0 ports with MAC addresses live while its fixture tests pass.

## Impact

`analyze mac-table` and `analyze_mac_table` are empty on current controllers: a user gets a
clean-looking report with no data and no warning.

## Recommended fix

Derive per-port MACs from `stat/sta` (`sw_mac` and `sw_port` per client) when `mac_table` is
absent, and say in the report which source was used; a live capture should pin the shape.
Record the controller version the field disappeared in if a capture shows it.
