---
title: "The Protect MCP tools are unverified live: no Protect account is configured"
date: 2026-10-03
status: open
severity: low
components: [mcp/tools/protect, protect/client]
found_by: review follow-ups, live checks at 85551d1
---

# The Protect MCP tools are unverified live: no Protect account is configured

## Problem

Neither config file defines `PROTECT_*`, so the five Protect MCP tools return
`CONFIG_MISSING`, and the issue 024 guard on them (`ReadOnlyProtectApiClient`) is proven
only offline (its guard tests and a mutation run). No live Protect data has been read
through the guarded client.

The first live attempt built a Protect family from the controller's `UNIFI_USERNAME` and
`UNIFI_PASSWORD`, for its child process only. The console refused every login: `403
Forbidden` on `/api/auth/login` for the first 4 calls, then `429 Too Many Requests` for the
other 6, at about 04:52–04:53Z on 2026-10-03. Each call had first recorded one audited
`GET /proxy/protect/api/bootstrap` (the guard records a read before uiprotect's lazy login),
and there was no `READ_ONLY_VIOLATION`. The second attempt built no Protect family, and all
10 calls returned `CONFIG_MISSING` with 0 requests.

## Evidence

- Local evidence, not in the repo: the read-only live checks recorded at `85551d1` (the
  `protect_guarded` check and its first MCP attempt, finding L4).

## Impact

Until a Protect account is configured, the Protect tools can't be verified live. The
refused logins weren't writes and every audit holds 0 violations, but repeated failed admin
logins can lock or flag the account. It doesn't break fresh clones or CI.

## Decision (2026-10-03)

Option (b), taken by the maintainer: verify the Protect guard offline only, as the plan's
baseline did.

- The live checks expect each of the 10 Protect cases (five tools on the discovery and the
  direct surface) to return `CONFIG_MISSING` with zero requests, and count exactly that as
  a pass. Any request, login or other error code fails the case.
- `PROTECT_*` is never derived from the controller account, and the live harness makes no
  Protect login at all. The harness (git-ignored) refuses to build `PROTECT_*` itself and
  asserts, before any request, that nothing it exports starts with `PROTECT_`.

Live verification stays open as a user action, the recipe below. It doesn't block a merge.

## Security log check (2026-10-03)

A read-only check of the console looked for traces of the refused logins. It used
`UNIFI_CONSOLE_API_TOKEN` only (a token login, so no password login was possible), behind
the read-only guard: 9 audited requests (7 allowlisted system-log query POSTs and 2 GETs),
0 violations.

- The Network application's v2 system log (`admin-activity` and `device-alert`) has no entry
  between 04:40 and 05:10Z. The query returns data otherwise: 252 and 157 entries in the 7
  days before, the newest at 02:04Z and 02:15Z. No failed-login, lockout, blocked-IP or alert
  entry was found.
- The refused logins went to UniFi OS (`/api/auth/login`), which the Network application's
  log doesn't record, and no allowlisted endpoint reads the UniFi OS security log. Check the
  console's own notifications and email (UniFi OS, Admins & Users) for a lockout or alert.
- The controller family still answers normally on its token: `stat/health` reports all five
  subsystems `ok` and `stat/device-basic` lists 24 devices.

Local evidence, not in the repo, recorded at `a0f95e0`.

## Recipe: verify Protect live with a view-only account (user action)

1. In UniFi OS, under Admins & Users, add a local user restricted to local access, with the
   Protect role "View Only" and no Network or other application role. Don't reuse the
   controller admin.
2. Add the account to the env file the MCP client loads (its `UNIFI_CONFIG`):

   ```bash
   PROTECT_HOST=<console address, as in UNIFI_URL>
   PROTECT_USERNAME=<the view-only user>
   PROTECT_PASSWORD=<its password>
   PROTECT_VERIFY_SSL=<true or false, as UNIFI_VERIFY_SSL>
   PROTECT_STORE_SESSIONS=false   # optional: keep no session file on disk
   ```

3. Check readiness (key names only, no request):
   `UNIFI_CONFIG=<file> uvx --python 3.12 --from /ABS/PATH/TO/unifi_management_cli
   unifi-mcp --check` must report `protect` as `ready: true`.
4. Start the server with `UNIFI_MCP_REQUEST_AUDIT=<audit.jsonl>` and run the 10 cases: on
   the `discovery` surface, `execute_tool` with `params: {}` and each of `get_cameras`,
   `get_nvr_info`, `get_sensors`, `get_lights` and `get_doorbells`; then, with
   `UNIFI_MCP_TOOL_SURFACE=direct`, the same five tools.
5. Pass: every result is data with no `error` and no `READ_ONLY_VIOLATION`, and the audit
   file holds only GET and HEAD lines under `/proxy/protect/` (the session login is sent but
   not recorded). Then mark this issue resolved with that evidence.

## Status (2026-10-13)

Blocked on operator input: a Protect account must be configured on the maintainer's console
before the five Protect tools can be verified live. No code change in 0.3.0; the tools raise on
failure like every other tool since issue 011.
