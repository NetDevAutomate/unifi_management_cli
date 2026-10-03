---
title: "The Protect MCP tools are unverified live: no Protect account is configured"
date: 2026-10-03
status: open, decision needed
severity: low
components: [mcp/tools/protect, protect/client]
found_by: review follow-ups live checks at 7ef13c2 (L4)
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

- `.kiro/review-followups/live-checks.json` (`protect_guarded`) and
  `.kiro/review-followups/live-checks/run-7ef13c2/attempt-1-mcp/` (both git-ignored).
- `.kiro/review-followups/live-findings.md` (L4).

## Impact

The live checks can't pass the 10 Protect cases. The refused logins weren't writes and every
audit holds 0 violations, but repeated failed admin logins can lock or flag the account. It
doesn't break fresh clones or CI.

## Decision needed

Which account Protect should use for live verification:

- (b, recommended) None on this branch: accept offline-only verification of the Protect
  guard, as the plan's baseline did. The 10 live Protect cases then expect
  `CONFIG_MISSING` with 0 requests.
- (a) A dedicated local, view-only Protect account, set in `PROTECT_*`, so the 10 cases run
  read-only.

Either way, `PROTECT_*` must never again be derived from the controller account; the review
follow-ups' live harness (git-ignored) now refuses to. Also check the console's security log
for a lockout or alert around 04:52–04:53Z on 2026-10-03.
