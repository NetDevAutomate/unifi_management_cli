---
title: "security_audit rates its own adopted devices and every IoT vendor as medium risk"
date: 2026-10-13
status: open, decision needed
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
