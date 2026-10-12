---
title: "`unifi-cron.sh` writes launchd plists that are invalid XML, so macOS schedules never load"
date: 2026-10-03
status: resolved
resolved_by: a671761
severity: medium
components: [scripts/unifi-cron.sh]
found_by: MCP uvx standards work
---

# `unifi-cron.sh` writes launchd plists that are invalid XML, so macOS schedules never load

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

Either fix changes the text that `status_launchd`'s stale check looks for: it greps each
plist for the raw `<string>$(build_command "$cmd")</string>`. Switch that comparison to the
same encoding the writer uses (the escaped string, or the argv array), or every task is
reported stale after the fix. Extend `tests/test_unifi_cron.py` to match:
`test_macos_status_accepts_every_plist_that_install_writes` already fails if the two sides
disagree, and the literal `<string>…</string>` assertions in
`test_macos_status_flags_a_stale_plist_and_install_replaces_a_loaded_job` need the new
encoding.

## Resolution

Resolved 2026-10-12 in `a671761`: every plist `<string>` is XML-escaped (install and the
`status` stale check alike, with a plistlib round-trip test), and port naming is scheduled or run
only with `--with-port-naming`; the six default tasks only read or record locally.

## Decision needed (as filed)

Fixing this makes macOS schedules start running for the first time, including the
`port-naming` task, which writes port names to the controller every 30 minutes
(`--verify-updates --connected-devices --apply`). `scripts/unifi-cron.sh run-all` runs the same
command with `--apply` as its last step. Decide whether that task should stay in the default
schedule before the fix lands, or whether it should be opt-in (in `run-all` too).

Reinstalling the schedule to add the 0.2.0 port's read-only `wan-speedtest-record` task
(`b46a8db`) also installs `port-naming --apply`, because `install` writes every task.
