---
title: "Every uvx launch installs the Protect, backup and ONVIF dependencies"
date: 2026-10-02
status: resolved
resolved_by: DOCS_HASH
severity: low
components: [pyproject.toml]
found_by: MCP uvx standards work
---

# Every uvx launch installs the Protect, backup and ONVIF dependencies

## Problem

All runtime dependencies are unconditional, including the ones only some features use:
`uiprotect` (Protect), `pycryptodome` and `pymongo` (UniFi backup decryption and BSON),
`onvif-zeep-async` (ONVIF cameras) and `asyncssh` (SSH helpers). A `uvx --from <path>
unifi-mcp` therefore resolves and installs all of them and their dependency trees.

## Impact

Slower first launch and a larger cached tool environment for users who only need the Network
tools. Nothing breaks.

## Recommended fix

Design decision D6 recommends **not now**: moving them to extras such as `[protect]` and
`[backup]` would break Protect users unless every client config adds `--with` or
`--from 'unifi-management-cli[protect] @ <path>'`, and the tools would need import guards that
return `[CONFIG_MISSING]`-style errors instead of `ImportError`. Revisit if install time becomes
a problem; if done, keep a `[all]` extra and make the guide's snippets use it.

## Decision (2026-10-13)

The Protect, backup and ONVIF dependencies stay in the core dependency set for 0.3.0: moving
them to extras would break every installed and `uvx` Protect user whose client config does not
add `--with`. The one new extra is `mqtt` for `aiomqtt`, which nothing installed before, so no
one breaks (issue 074). Decided by the 0.3.0 release council (D-014); resolved as a recorded
decision.
