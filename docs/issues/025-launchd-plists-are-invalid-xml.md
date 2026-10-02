---
title: "unifi-cron.sh writes launchd plists that are invalid XML, so macOS schedules never load"
date: 2026-10-03
status: open, decision needed
severity: medium
components: [scripts/unifi-cron.sh]
found_by: MCP uvx standards work (convergence fixer, iteration 2, while fixing code-review F5)
---

# unifi-cron.sh writes launchd plists that are invalid XML, so macOS schedules never load

## Problem

`install_launchd` writes each task's command into the plist verbatim:

```xml
<string>cd /path/to/repo && /path/to/uv run unifi-mapper analyze link-errors --record</string>
```

A bare `&` is not valid in XML; it must be `&amp;`. `plutil -lint` on a plist of this shape
reports `Encountered unknown ampersand-escape sequence`, so `launchctl load` rejects every
generated plist. The script runs `launchctl load "$plist_path" 2>/dev/null || true`, which
hides the error, then logs `Installed: <task>` and `✅ All tasks installed via launchd`.

Checked on this machine (2026-10-03): `plutil -lint` on a sample plist with `cd /tmp && echo
hi` fails as above; no `com.unifi-management.*` job is loaded (`launchctl list`), and no
plist is installed. The Linux crontab path is unaffected.

## Impact

On macOS, `./scripts/unifi-cron.sh install` (and `update`) reports success but schedules
nothing: no 5-minute counter history, no hourly drift/health/radio reports and no 30-minute
port naming. `status` shows `❌ … not loaded` for every task, which is the only signal.

It doesn't break fresh clones, CI or the MCP server.

## Recommended fix

Escape the command for XML before writing it (`&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`), or
drop the shell wrapper and write `ProgramArguments` as the argv array with
`WorkingDirectory` doing the `cd`. Stop swallowing the `launchctl load` error, and run
`plutil -lint` on each plist before loading it. Add a test that every generated plist passes
`plutil -lint` (skipped off macOS).

## Decision needed

Fixing this makes macOS schedules start running for the first time, including the
`port-naming` task, which writes port names to the controller every 30 minutes
(`--verify-updates --connected-devices --apply`). Decide whether that task should stay in
the default schedule before the fix lands, or whether it should be opt-in.
