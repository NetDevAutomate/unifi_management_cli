---
title: "security_audit rates its own adopted devices and every IoT vendor as medium risk"
date: 2026-10-13
status: resolved
resolved_by: 6cf067e
severity: medium
components: [diagnostics/security_audit]
found_by: live run of `diagnose security` after issue 079 was fixed
---

# `security_audit` rates its own adopted devices and every IoT vendor as medium risk

## Problem

With the rogue heuristic fixed (issue
[079](079-security-audit-counts-every-neighbour-ap-as-a-critical-rogue.md)), the live report
on 2026-10-13 still showed 48 medium risks, 2 high, 105 unknown devices and 11 MAC anomalies
on a healthy home site. Read from the report's flags:

- **24 of the 48 mediums are the site's own adopted UniFi devices.** `stat/device` records
  carry no `oui`, so `_analyze_device_security` reads the vendor as `'Unknown'`, and
  `_is_suspicious_vendor` lists `'Unknown'` as a security-sensitive vendor. Every switch and
  AP the controller manages is therefore "Device from security-sensitive vendor: Unknown".
- **The other mediums are IoT vendors.** `_is_suspicious_vendor` flags `Espressif`,
  `Realtek` and `Ralink` as "common in IoT/hacking devices": that is every smart plug, bulb
  and sensor on the network, flagged for the chipset it was built on.
- **Randomised MACs are a risk flag.** `_is_randomized_mac` (the locally-administered bit)
  marks a phone's private Wi-Fi address, the default on every current phone, as "Possible
  randomized MAC address"; combined with a traffic flag it reaches high.
- **"Suspiciously similar MACs" are devices bought together.** The 11 remaining anomalies are
  the site's own UniFi devices, whose MACs are sequential from the same production batch.
- **105 "unknown" devices** are every client: `is_authorized` is `None` for a client unless
  something sets it, and nothing does (there is no authorised list to check against).

## Impact

The headline numbers still cannot be read at a glance: a healthy site reports two high risks,
48 medium and 105 unknowns. The two real signals the audit has (an adopted device that is
*not* adopted, i.e. pending; a client on the guest network for more than a day) are the same
colour as a smart bulb.

## Recommended fix

- Vendor: drop the vendor-blacklist rule. An infrastructure record with no `oui` is an
  adopted UniFi device, not an unknown vendor; a client's chipset vendor says nothing about
  intent. If a vendor rule is wanted at all, make it an allowlist the operator supplies
  (`UNIFI_AUDIT_TRUSTED_VENDORS`) and report vendors outside it as *info*, not medium.
- Randomised MAC: information only (it is the platform default), never a risk level.
- MAC similarity: skip pairs where both MACs belong to adopted devices (sequential batch
  MACs), and compare within the client population only.
- Unknown: report `authorized`/`unauthorized` only when there is a source of truth (the
  controller's `blocked` and `noted` client flags, and a future operator allowlist); drop the
  `unknown` count rather than counting every client as unknown.

## Decision needed

Whether the audit should take an operator allowlist of vendors or MACs at all (a config
setting, like `UNIFI_RADIO_CHANNEL_MOVES`), or stay a controller-data-only report whose
risks are the three things the controller itself can show: pending adoption, guest-network
overstay, and the rogue classification of issue 079.

## Resolution

Resolved on 2026-10-13 (`6cf067e`). The decision was taken by the 0.3.0 release council: the
audit stays a **controller-data-only report** with no operator allowlist of vendors or MACs.
An allowlist is day-one setup every new site must build before the report means anything (this
site alone would have needed two dozen entries), while a controller-data-only report is correct
on any site immediately. An allowlist can be added later; removing one is harder.

What changed in `diagnostics/security_audit.py`:

- **Vendor rule dropped entirely.** `_is_suspicious_vendor` and the "security-sensitive
  vendor" finding are gone; there is no allowlist and no INFO-level vendor flag either. An
  adopted device's `vendor` is now its `model` (the records carry no `oui`), a client's stays
  the OUI lookup.
- **Adoption is `stat/device` membership.** A record in `stat/device` is an adopted device, or
  one pending adoption when `adopted` is false (high, unauthorised). Nothing is inferred from
  a missing `oui`.
- **Randomised MAC is information.** The flag stays, reworded ("information only"); it never
  sets or raises a risk level. The flag-count escalation (one flag medium, two high, three
  critical) that made it a risk is removed; each rule sets its own level.
- **The other heuristics are gone as risks**: the suspicious-name rule, the 1 GB traffic rule
  and the fake-MAC-pattern rule. The brief's remaining risks are exactly pending adoption,
  guest-network overstay and the issue-079 rogue classes, and the code now has exactly those.
- **Guest overstay is a medium risk** (`is_guest` or a network named guest, `uptime` over a
  day) with a flag, rather than a bare entry in `guest_violations` at risk level low. This is a
  small strengthening of a kept rule, not a new one: the issue names it as one of the two real
  signals.
- **`is_authorized` is the controller's verdict only**: True for an adopted device or a `noted`
  client, False for a pending device, a `blocked` client or a rogue AP, None otherwise (not
  assessed). A blocked client is the controller doing its job, so it is a verdict, not a risk.
  The `unknown_devices` count is removed from the model, the CLI header and the MCP result.
- **MAC similarity within the clients only.** `_detect_mac_anomalies` now receives the
  `stat/sta` MACs; adopted devices (sequential batch MACs) and rogue BSSIDs are excluded.
- **`limitations`** is a new field on the report, printed by the CLI as a final block and
  carried in the MCP result: the findings are controller-derived signals, not proof that a
  device is authorised or of the absence of compromise; and a read the audit can do without
  (`stat/rogueap`, `rest/wlanconf`, `rest/networkconf`) that fails is reported as "not
  assessed" with the error, instead of failing the whole audit (`stat/rogueap`) or being
  silently read as an empty list (the other two). `stat/device` and `stat/sta` failing still
  fail the audit: there is nothing to audit without them.

Live before and after, same site, same day: 129 devices, 0 critical, 2 high, 48 medium,
105 unknown, 11 MAC anomalies became 130 devices (35 authorised, 0 unauthorised, 0 anomalous),
0 critical, 0 high, 0 medium, no unknown count, 9 MAC anomalies, 0 rogues, 629 neighbours.
The 9 remaining anomalies are all "similar MACs" pairs of clients sharing an OUI (devices from
one vendor batch, or one device with two radios); they are reported to the coordinator as a
follow-up, not changed here, because the council's decision was the client population.

Tests: `tests/diagnostics/test_security_audit_controller_data_only.py`: one per dropped rule
on the fixture that used to trigger it, the controller's verdicts (`blocked`, `noted`, pending
adoption), guest overstay, client-only MAC similarity, the limitations text, and a failed
`stat/rogueap` read reported as not assessed with the audit still running on the rest.
`tests/test_cli_parity_commands.py` renders the Limitations block and asserts the unknown
count is gone from the header.
