---
title: "The async read-only guard judges and audits a different path when the raw path starts with `//`"
date: 2026-10-03
status: open
severity: low
components: [core/utils/readonly]
found_by: review follow-ups (issue 024 planning)
---

# The async read-only guard judges and audits a different path when the raw path starts with `//`

## Problem

`ReadOnlyAsyncTransport` hands the policy `request.url.raw_path`, a path with no scheme or
host. `_normalised_path` runs it through `urlsplit`, which reads a raw path starting with
`//` as a network-path reference: the first segment becomes the netloc and is dropped. The
guard then judges, and audits, a path that is not the one sent.

Reproduced offline (`httpx.MockTransport` as the inner transport, audit sink on):

| Request | Inner transport received | Judged and audited as |
| --- | --- | --- |
| `POST https://192.0.2.1//evil/proxy/network/api/s/default/stat/event` (site policy) | `//evil/proxy/network/api/s/default/stat/event` | `/proxy/network/api/s/default/stat/event` (allowed: on the POST allowlist) |
| `GET https://192.0.2.1//evil/proxy/network/integrations/v1/sites` (GET-only policy) | `//evil/proxy/network/integrations/v1/sites` | `/proxy/network/integrations/v1/sites` |

`request_allowed('POST', '//evil/proxy/network/api/s/default/stat/event', 'default')`
returns `(True, '/proxy/network/api/s/default/stat/event')`. `ReadOnlyProtectApiClient`
passes uiprotect's relative `url` to `get_only_request_allowed` the same way. The sync
guard (`ReadOnlySession`) gets absolute URLs, so `urlsplit` keeps the whole path and it is
unaffected.

## Impact

Nothing in the package builds such a URL: every client joins fixed `/api/…`, `/proxy/…` or
`/sites/…` paths to a base URL. The judged path is always a suffix of the sent one, and the
verb is judged correctly, so a write verb is still refused. But for an allowlisted read the
audit can record a path that was never sent, which weakens the audit as proof of what a
session did.

## Recommended fix

In `_normalised_path`, refuse a URL whose `urlsplit` has a netloc but no scheme (a relative
URL that parses as a network-path reference), with the same "path traversal or encoded
path" style of message. Add tests to `tests/utility/test_readonly_guard.py` for both
policies and for `ReadOnlyProtectApiClient`, including the two rows above.
