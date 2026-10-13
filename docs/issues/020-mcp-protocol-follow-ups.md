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
| — | Record what an **unpinned** `uvx --from <path> unifi-mcp` picks as its interpreter (the docs pin `--python 3.12`, the tested interpreter; `requires-python` is `>=3.12`), and whether the suite passes on it | Recorded by the verify step at `5b1d2f2` on the maintainer's macOS machine: unpinned `uvx --refresh --from <checkout>` picked CPython 3.13.13 (the uv-managed 3.13, even with Homebrew 3.14 on PATH), `unifi-mcp --version` worked, and the full suite passed on 3.13.13 (2778 passed, 3 skipped, 1 xfailed). The pick depends on which interpreters a machine has, so the docs keep `--python 3.12`; 3.14 is untested. Remaining work: a CI job on the newest supported Python |
| — | `unifi-mcp --check` writes loguru DEBUG lines to stderr (for example "optimize_radio_channels has no structured return type") because logging is configured only on the serving path | Fixed in `7e0da0e`: `main()` now sets the stderr sink to `UNIFI_MCP_LOG_LEVEL` (default `WARNING`) right after parsing the arguments, before `--check` or the direct surface builds the catalog; `--version` and `--help` still log nothing (`tests/mcp/test_log_level.py`) |
| — | Whatever `UNIFI_MCP_LOG_LEVEL` says, the server writes the SDK's `INFO Processing request of type …` to stderr for every request, and any library's INFO records too, such as httpx's `HTTP Request: GET <url>` for each controller call. Building the module-level FastMCP server at import calls `logging.basicConfig(level='INFO')` with a Rich handler on stderr (FastMCP's `log_level` default) | Found while fixing the row above; stderr only, stdout is unaffected. `UNIFI_MCP_LOG_LEVEL` is documented as a loguru level, so applying it to stdlib logging changes what clients' logs show and needs a decision. Recommended: `_configure_logging` also sets the stdlib root logger to the same numeric level (`logger.level(name).no`, which covers TRACE and SUCCESS) |
| — | `python -m unifi_mapper.mcp.server` prints runpy's "found in sys.modules" RuntimeWarning on stderr, because `mcp/__init__.py` imports `server` | Pre-existing; the `unifi-mcp` console script is unaffected. Make `mcp/__init__.py` import lazily (PEP 562) or document the console script as the only entry point |
| — | A token or password changed in the config file needs a server restart. Since code-review F8 the shared client logs in again after a 401 and re-runs the credential chain, but the chain reads the process environment first, and the config file was loaded into it at start-up | Re-reading the config file on a 401 changes config resolution (plan item 4), so it needs its own change: re-run `resolve_mcp_config` for the controller family before the fresh login, under the holder's lock |

## Impact

None of these breaks a client today. B12 and the unpinned-interpreter check protect the uvx
launch path from silent regressions; B15 decides whether `audit_link_speeds` can report true
port capability on this controller.

## Recommended fix

Take them one at a time, smallest first: the runpy warning (small, in `mcp/__init__.py`) and
the stdlib log level (a decision, then a few lines in `mcp/server.py`), then B12, B11 (as a
decision: it changes a default), B15 once the live capability read has been tried, B4 with
the next SDK migration (issue 008), and B2 only on demand.

## Progress

2026-10-13 (`eded7e8`): the runpy warning row is done. `mcp/__init__.py` resolves `mcp`,
`get_registry`, `search_tools` and `list_categories` lazily (PEP 562 `__getattr__` and
`__dir__`, with a `TYPE_CHECKING` import so pyright still sees the names in `__all__`), so
`python -m unifi_mapper.mcp.server` no longer imports `server` through the package first;
`-W error::RuntimeWarning` exits 0 where it exited 1. `from unifi_mapper.mcp import mcp`
behaves as before. `tests/mcp/test_module_entry.py` pins both.

The stdlib log-level row was re-verified the same day and is still open: a stdio session
on the default `UNIFI_MCP_LOG_LEVEL` (WARNING) writes `INFO Processing request of type
ListToolsRequest` / `CallToolRequest` to stderr for every request. The recommendation
above (set the stdlib root logger to the loguru level's number in `_configure_logging`) is
a few lines but changes what every client's log shows, so it waits for the decision this
row asks for. B2, B4, B11, B12, B15 and the config re-read on 401 are unchanged.
