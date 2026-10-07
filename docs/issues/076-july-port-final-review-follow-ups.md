---
title: "Follow-ups from the July port's final review that were not fixed on the branch"
date: 2026-10-06
status: open, decision needed
severity: low
components: [analysis, diagnostics, mcp, core/utils/redact, tests, docs/issues]
found_by: July port final council and iteration-8 review (final-fix triage)
---

# Follow-ups from the July port's final review that were not fixed on the branch

## Problem

The final council's 89 non-blocking findings, the iteration-8 review's and the standards
review's SR8-S1 were triaged in the final-fix run. The ones whose fix was a few lines were
fixed on the branch; findings already fixed by the final-fix commits, or contradicted by the
code, are recorded in the port's verification record. These remain, each with the fix to
make; item 8 was fixed on the branch after it was filed and keeps its number, and items 30
and 31 came from the final-fix review. References in brackets are the council bundle and
finding (`04/F1`) or the review id.

### Behaviour: each changes what a command reports, so each needs sign-off

1. **`diagnose ap-health` measures another SSID under the tracked SSID's name** (04/F1,
   AGG8-1). When an AP has no 2.4 GHz VAP with the tracked SSID, `pick_vap` falls back to the
   busiest VAP, so a mistyped or 5 GHz-only `--essid` is accepted, and a reference AP without
   the SSID is measured on its busiest one. Fix: refuse an `--essid` that is not on the
   target's 2.4 GHz VAPs (exit 2, naming the SSIDs it has), and report a reference AP without
   it as "no rate (SSID not present)"; test both.
2. **The ap-health retry note says pings ran when they didn't** (04/F5). `RETRY_NOTE` always
   ends "Pings run from the gateway to 2.4 GHz clients on each AP at sample time", without
   `--ping-clients` too, and the pings also reach clients whose radio isn't reported. Fix:
   move that sentence to a note added only with `--ping-clients`, worded as the selection
   is; test the report with and without it.
3. **The VLAN traffic reports say peaks are smoothed; they aren't** (05/N1). An hourly peak
   is the largest sample rate in the hour and a daily peak the largest hourly peak, so no
   tier smooths a peak beyond the sampling interval. The daily caveat ("so it smooths out
   short bursts more than a raw or hourly view would"), the `get_vlan_traffic_report`
   manifest description ("whose peaks are smoothed"), `vlan-traffic report`'s help
   ("smoothed peaks") and the tool's docstring say otherwise. Fix: say each tier's peak is
   the largest sample rate in its window and that bursts shorter than the sampling interval
   are under-represented in every tier; regenerate the MCP guide's tool row.
4. **`diagnose latency-matrix` reads a ping that could not run as a lost target** (04/F12).
   `_ping_single` parses stdout without checking the exit status, so a missing or refused
   `ping` (exit 127 or 2, nothing on stdout) shows as 100% loss. Fix: check the status as the
   gateway probes do (`check_exit_status(result, 'ping', (0, 1))`) and report any other
   status as an error for that target; test exit 127 and an empty stdout.
5. **The STP audit's tie warning skips a core switch tied with an access switch** (04/F13).
   `_tie_warning` returns nothing when any tied switch is aggregation- or core-class, so a
   core switch and an access switch tied at the lowest priority leave the root to MAC order
   unwarned. Its docstring states the rule but not this case. Fix: warn unless every tied
   switch is aggregation- or core-class, or document the case as accepted.
6. **Free text with "pre-shared" spellings is not masked** (06/N6). `SECRET_KEY_RE` and the
   free-text pattern match `preshared` but not `pre-shared`, `pre_shared` or `pre shared`.
   Fix: `pre[-_ ]?shared` in both, test first with each spelling.
7. **The speedtest history keeps a permissive mode it finds** (found with final council F6).
   `diagnostics/wan_history.py` writes with `file_mode=0o600` and `dir_mode=0o700` but no
   `enforce_modes`, so an existing history or directory with group or other bits stays
   readable, the gap the MCP call log had. Fix: pass `enforce_modes=True`; decide what a file
   or directory owned by another user does there (the recording command would then fail).
8. **Fixed on the branch: a call log path's own directory was made private, whatever it was**
   (found with final council F6; the final-fix review's FFA-1). With `UNIFI_MCP_CALL_AUDIT`
   set to a path, its directory was set to `0o700` on every write, so `~/mcp-audit.jsonl`
   changed the home directory's mode. Now only the default state directory is kept `0o700`.
   A given path's existing directory is never changed: when another user owns it, or it has
   a group or other write bit, the log turns off with one warning and writes nothing. The
   file is still kept `0o600`, and `tests/mcp/test_call_audit.py` pins each case.
9. **`get_wan_speedtest_history`'s description lacks the CLI pointer its siblings have**
   (06/N4). Fix: compare it with the other WAN tools' descriptions and add the matching
   `unifi-mapper diagnose wan-history` reference; regenerate the MCP guide's tool row and
   recheck the tools/list size test.

Filed by the final-fix review:

30. **A gateway with no `br*` interface fails the VLAN sample with a misleading message**
    (FFA-3, SR-FF-2). `SAMPLE_SCRIPT` (`analysis/vlan_traffic.py:47-52`) loops over
    `/sys/class/net/br*`. With no match, POSIX `sh` keeps the literal glob, so the script
    prints a `br*` line with empty counters, and `parse_bridge_counters` fails the sample
    with "printed a bridge line without two integer counters" and the read-access
    suggestion, where "no bridge interfaces" is meant. The exit status (1) and "nothing
    stored" are right; only the message misleads, and every UniFi OS gateway has `br0`. Fix,
    test first: add `[ -e "$i" ] || continue` to the loop (a change to the script the
    gateway runs, so it needs sign-off), or treat a literal `br*` line as no bridges.

### Tests and guards

10. **The SSH "only door" scan misses aliases** (08/NB-1). The AST scan in
    `tests/analysis/test_gateway_ssh.py` matches the name `asyncssh` only. Fix: resolve
    `import asyncssh as x` and `from asyncssh import connect`, with a self-test.
11. **It proves the connect is confined, not the commands** (08/NB-3). Fix: also flag an
    SSH connection's `.run(` outside `gateway_ssh.run_gateway_command`.
12. **An STP optimise test patches a loader `typer_cli` doesn't use** (08/NB-4).
    `test_stp_optimize_prints_one_line_per_skipped_gateway` patches
    `unifi_mapper.cli.load_env_from_config`, but `typer_cli` binds its own name at import;
    patching that one makes the test fail, since it relies on the real loader. Fix: give the
    test an env file of its own in `tmp_path`, or drop the patch.
13. **One ap-health capture test checks many things** (08/NB-6). Fix: split
    `test_the_capture_samples_both_aps_through_reads_only` into timing, SSID choice and
    read-only/redaction tests.
14. **The network ban doesn't cover UDP** (09/NB-1). The autouse fixture in
    `tests/conftest.py` blocks connects, not `sendto`. Fix: patch outbound AF_INET/AF_INET6
    `socket.socket.sendto` too, with a self-test, or narrow its docstring.
15. **A WAN check sits in the VLAN store tests** (09/NB-3). Fix: move the
    `get_wan_speedtest_history` coroutine assertion to `tests/diagnostics/test_wan_history.py`.
16. **The SSH fake answers any command like a ping** (10/NB-1). With `replies` set,
    `tests/fake_ssh.py` returns a success-shaped ping reply for an unknown command. Fix: raise
    `AssertionError(command)` for a first word not in `replies`, keep the defaults only when
    `replies` is None, and fix any test that relied on it.
17. **A concurrent-writer test drops its threads' exceptions** (10/NB-2,
    `tests/diagnostics/test_wan_history.py`). Fix: run the writers through
    `concurrent.futures` and call `result()` on each.
18. **The recent-events test pins POST methods, not paths** (10/NB-3,
    `tests/diagnostics/test_recent_events.py`). Fix: assert each POST's (method, path).
19. **The controller-client AST scan misses aliases** (11/NB-2, `tests/test_cli_guard.py`).
    Fix: resolve import aliases, with an aliased-constructor self-test.
20. **The exit-2 README ratchet knows one call shape** (11/NB-3,
    `tests/test_cli_documentation.py`). Fix: also read `code=`, a bare `Exit` and async
    commands, and fail when it finds fewer commands than expected.
21. **A lock test waits a fixed time** (12/NB-2, `tests/utility/test_jsonl.py`). Fix: wait
    on a `threading.Event` the worker sets once it holds the lock.
22. **A test name promises cleanup it doesn't check** (12/NB-3,
    `test_the_password_config_exports_no_login_past_the_test` in `tests/test_ports_cli.py`).
    Fix: rename it for what it checks, or assert the keys are gone in a fixture finalizer.

Filed by the final-fix review:

31. **Nothing pins the codemap's command total** (FFA-4, SR-FF-3, delta council FF-3).
    `docs/architecture/codemap.md` says "80 commands in all" for `typer_cli.py`. A script
    kept outside the repository derived it from `typer.main.get_command(app)`, and the
    figure has gone stale before (it said 68). Fix: pin the "N commands in all" figure in
    `tests/test_docs_consistency.py` against a walk of `typer.main.get_command(app)`, the
    way that module's prose tool-count guard (issue 053) pins the README's tool counts.

### Issue line references the branch moved

23. Line references filed against `main` that the branch's code changes moved (found by
    the final-fix run; issue 044's two `enhanced_network_topology.py` references were
    corrected there). Fix, after the merge: re-point each, then add a check that every
    `src/...py:N` reference in `docs/issues/` still lands on the line it quotes.

    | Issue line | Reference | The quoted line is now at |
    | --- | --- | --- |
    | 015:18 | `network_cli.py:300` | 299 |
    | 015:19 | `cli.py:235` | 243 |
    | 017:17 | `inventory_cli.py:135` | 115, 128 or 139 (check) |
    | 038:15-16 | `analysis/latency_matrix.py:183`, `analysis/bandwidth_test.py:104` | rewritten: the connect is in `gateway_ssh.gateway_session` now |
    | 042:17, 042:24 | `config.py:109`, `config.py:106` | 112, 109 |
    | 042:18 | `cli.py:188-201` | 196-209 |
    | 043:19 | `inventory_cli.py:95-100` | 99-104 |
    | 044:29, 044:31, 044:32 | `typer_cli.py:223`, `network_cli.py:121`, `cli.py:134` | 279, 122, 138 |
    | 045:14 | `core/utils/logging.py:10` | 41 |
    | 047:15 | `typer_cli.py:369-383` | 425-439 |

    Issue 058's `mcp/server.py:669` is in a resolved issue's history; leave it.

### Optional, style only

24. README's "87 MCP Tools" feature line could name the two surfaces' counts (01/F7); check
    it against the prose-count guard (issue 053) first.
25. The July-port issue files mix tenses for "the July port" (03/F9): one pass to the past
    tense.
26. Issue 074's index row is long (03/F11): tighten it once 074 is decided.
27. The Protect tools' error payloads name the exception class (07/N6); a class name holds
    no value, so map it to a category only if that is ever judged a leak.
28. `server.get_runner()` sets a module global (07/N10): inject the runner if a second one
    is ever needed. No change now.
29. `tests/test_error_output.py` holds several guards in one module (12/NB-4): split it by
    topic when it is next edited.

## Impact

Items 1 to 4 and 30 report wrong or misleading figures or messages in rare cases (a wrong
SSID, a note, a caveat's wording, a ping that could not run, a gateway without bridges); 5 to
7 leave a warning, a secret spelling or a file mode short of what is intended; the rest are
test strength, stale line numbers and style. Nothing is written to the controller, and no
known path prints a secret today: UniFi's own pre-shared key fields start with `x_` and are
always masked, but free text that spells it `pre-shared`, `pre_shared` or `pre shared` is
not (item 6). Breaks fresh clones, CI or prod: no.

## Recommended fix

As listed for each item. Items 1 to 7, 9 and 30 change what a command or tool reports or
does, so each needs sign-off first (item 8 is fixed); items 10 to 29 and 31 can land as they
are, test first where they change a test's behaviour.
