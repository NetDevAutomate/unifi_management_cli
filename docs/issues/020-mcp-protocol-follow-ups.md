---
title: "MCP protocol and runtime follow-ups"
date: 2026-10-02
status: open
severity: low
components: [mcp/server, mcp/runner, connectivity/traceroute, analysis/link_speed_audit, tests/mcp]
found_by: MCP uvx standards work
---

# MCP protocol and runtime follow-ups

## Problem

Smaller follow-ups left after the MCP uvx standards work, each independent:

| ID | Item | Why it was deferred |
| --- | --- | --- |
| B2 | Streamable HTTP transport | Local stdio is the safer default; only worth adding bound to 127.0.0.1 with authentication |
| B4 | `report_progress` from multi-device loops (fleet audits, counter sampling) | Handlers don't receive the request context; the shared client (plan P3) is the first half |
| B11 | `traceroute` default `source='gateway'` | Changes a handler default |
| B12 | Startup-time regression test (`python -X importtime`, a 1.5 s budget for the direct surface) | Needed the catalog to land first |
| B15 | `audit_link_speeds` capability fallback: when the Integration API read of `maxSpeedMbps` gets 401/403 with the console token, read it through the `network_api` family (`UNIFI_NETWORK_API_KEY`) if that family is ready for the same host | Unverified whether this controller accepts the console token there; until then the tool degrades to `BELOW_PEER_PORTS_SAME_CAPS` / `CAPABILITY_UNKNOWN`, never a false capability finding |
| — | Record what an **unpinned** `uvx --from <path> unifi-mcp` picks as its interpreter (the docs pin `--python 3.12`, the tested interpreter; `requires-python` is `>=3.12`), and whether the suite passes on it | Plan P13: the workflow's verify step records the result; add it here |
| — | `unifi-mcp --check` writes loguru DEBUG lines to stderr (for example "optimize_radio_channels has no structured return type") because logging is configured only on the serving path | Found while documenting `--check`; stderr only, the JSON on stdout is unaffected. Configure the stderr sink at `UNIFI_MCP_LOG_LEVEL` before `--check` builds the catalog |
| — | `python -m unifi_mapper.mcp.server` prints runpy's "found in sys.modules" RuntimeWarning on stderr, because `mcp/__init__.py` imports `server` | Pre-existing; the `unifi-mcp` console script is unaffected. Make `mcp/__init__.py` import lazily (PEP 562) or document the console script as the only entry point |
| — | A token or password changed in the config file needs a server restart. Since code-review F8 the shared client logs in again after a 401 and re-runs the credential chain, but the chain reads the process environment first, and the config file was loaded into it at start-up | Re-reading the config file on a 401 changes config resolution (plan item 4), so it needs its own change: re-run `resolve_mcp_config` for the controller family before the fresh login, under the holder's lock |

## Impact

None of these breaks a client today. B12 and the unpinned-interpreter check protect the uvx
launch path from silent regressions; B15 decides whether `audit_link_speeds` can report true
port capability on this controller.

## Recommended fix

Take them one at a time, smallest first: the `--check` log sink and the runpy warning (small,
in `mcp/server.py` / `mcp/__init__.py`), then B12, B11 (as a decision: it changes a default),
B15 once the live capability read has been tried, B4 with the next SDK migration (issue 008),
and B2 only on demand.
