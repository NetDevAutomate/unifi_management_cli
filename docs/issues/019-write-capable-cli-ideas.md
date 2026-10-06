---
title: "Write-capable CLI ideas (plan, review, apply; never over MCP)"
date: 2026-10-02
status: open, decision needed
severity: low
components: [typer_cli, inventory_cli]
found_by: MCP uvx standards work
---

# Write-capable CLI ideas (plan, review, apply; never over MCP)

## Problem

Several fixes that the read-only tools now diagnose still need a hand-made change in the UniFi
UI. The design's backlog lists write-capable commands that would close those loops (W1–W5).
They change production, so each needs a decision before it is built.

| ID | Command | Closes the loop on |
| --- | --- | --- |
| W1 | `ports set-profile SWITCH PORT PROFILE --dry-run`: shows the override diff, then applies | `audit_link_speeds` / `ports profile-diff` findings (for example moving a port between a forced-speed and an auto profile) |
| W2 | `ports power-cycle SWITCH PORT`: a PoE bounce, with confirmation | A wedged PoE device found by `inspect_switch_port` |
| W3 | `inventory upgrade --drifted --dry-run`: schedules firmware upgrades for the devices T4 reports as behind (alongside the existing `inventory update-firmware`) | Issue 017's `devices_behind` |
| W4 | `profiles merge`: merge duplicate port profiles and repoint their ports | `audit_port_profile_usage`'s `DUPLICATE_PROFILES` |
| W5 | `devices provision NAME`: force-provision one device | Stuck configuration after a change |

The July work's write ideas (W6 to W10: `wlan set-option`, `wlan ap-group`, `radio
spectrum-scan`, the AP-health PoE power cycle and an unattended `radio auto-channel --apply`)
are in issue [060](060-decisions-from-the-july-port.md); the rules below apply to them too.

## Impact

Operators switch to the UI for each fix, so there's no reviewable plan, no audit trail and no
rollback file. Nothing breaks today.

## Decision needed

Which of W1–W5, if any, to build. Whatever is built must follow the rules the design set:

- **CLI only.** Never registered over MCP: if a manifest entry is ever added it must carry
  `mutates: true`, so the catalog never builds it and `execute_tool` refuses it with
  `MUTATION_REFUSED`.
- **Plan → review → apply**, as `stp optimize --plan` / `stp apply --plan` and
  `ports refresh --apply` do: a dry run by default that writes a reversible plan, an explicit
  `--apply`, and a re-read afterwards to verify.
- Respect held configuration: for example, port 5 on 'USW Flex XG' is held on its forced
  10 Gbps profile for an open vendor case, and W1 must never be pointed at it without the
  operator saying so.
