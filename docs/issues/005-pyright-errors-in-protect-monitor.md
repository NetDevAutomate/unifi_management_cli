---
title: "pyright reports 3 errors in monitors/protect_monitor.py"
date: 2026-10-02
status: open
severity: low
components: [monitors/protect_monitor]
found_by: port diagnostics verification
---

# pyright reports 3 errors in `monitors/protect_monitor.py`

## Problem

`uv run pyright src/` reports 3 errors, all in `monitors/protect_monitor.py` `main()`
(lines 669-671 when filed). `base_url`, `username` and `password` are typed `str | None`
when they're passed to `ProtectMonitor(...)`, which expects `str`. The errors predate the
port diagnostics work.

At runtime none of the three is ever `None`. The `missing` check calls `parser.error()`,
which exits. pyright can't narrow three separate variables through that list
comprehension.

## Impact

`.pre-commit-config.yaml` runs pyright at the `pre-push` stage. For anyone who has the
hooks installed, every push fails until this is fixed. There's no CI workflow in
`.github/`, so CI isn't affected. Production behaviour isn't affected either.

## Recommended fix

Narrow the types after the check without changing behaviour:

```python
if missing:
    parser.error('missing required credentials: ' + ', '.join(missing))
# parser.error() exits, so all three are set from here on.
assert base_url and username and password
```
