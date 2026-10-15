---
title: "`get_recent_events` reads every page before keeping the newest; an early stop changes what the result reports"
date: 2026-10-15
status: open, decision needed
severity: low
components: [mcp/tools, diagnostics/events]
found_by: issue 021 (0.2.0 port review), carried out of 021 by the 0.4.0 council (D-021-EVENTS)
---

# `get_recent_events` reads every page before keeping the newest; an early stop changes what the result reports

## Problem

`collect_recent_events` pages each source to its page cap (`stat/event` 20 pages of 1000,
`list/alarm` once, the four system-log classes 20 pages of 100 each) and only then sorts and
keeps the newest `max_events`. With no filter, a one-year window on a busy site is up to 101
sequential requests behind one login per call. `stat/event` is requested newest first
(`_sort: -time`), so with no `category`, `severity` or `contains` filter the read could stop
once it holds `max_events` records.

## Why it is a decision, not a fix

Stopping early changes the result: `matched_total` would count only the records read, not
every match in the window, and the source's `truncated` flag would turn true. The system log's
page order has to be checked, read-only, before it could stop early too. The 0.4.0 council
(pass A, D-021-EVENTS) kept the full read and had this filed on its own so the choice is made
deliberately rather than inside an unrelated lane. The 101-request ceiling is documented as a
request cap in the MCP guide.

## Options

1. Keep the full read (current): `matched_total` is exact for the window; cost up to 101
   requests per unfiltered call.
2. Stop `stat/event` early when unfiltered and `max_events` is reached: cheaper on a busy
   site; `matched_total` becomes "at least" and `truncated` is set, which the guide and the
   result's field descriptions would say.
3. Both: a `complete: bool` parameter, default true, so an agent can choose.

Recommended: option 3 with the default unchanged, so no existing reading changes and a caller
who wants the cheap read asks for it. 0.5.0.
