---
title: "`firewall_check` reads `rest/firewallrule`, empty on a zone-based controller, and `FirewallRule.action` rejects every real action value"
date: 2026-10-15
status: open
severity: medium
components: [connectivity/firewall_check, core/models/firewall]
found_by: 0.4.0 council pass B disposition (093 live check)
---

# `firewall_check` reads `rest/firewallrule`, empty on a zone-based controller, and `FirewallRule.action` rejects every real action value

## Problem

Issue 093 made `diagnose firewall` honest about what it assesses (nothing; it lists the enabled
rules whose protocol and destination port match as the `basis`). Two things keep even that basis
empty or broken:

1. `firewall_check.py:79` reads the classic `rest/firewallrule` endpoint. A controller running the
   zone-based firewall (Network 9 and later) keeps its policies at the v2 endpoint
   `firewall-policies`; the classic endpoint answers 200 with an empty list.
2. `FirewallRule.action` (`core/models/firewall.py:12`) is `Literal['allow', 'deny', 'reject']`.
   The classic endpoint's values are `accept`, `drop` and `reject`; the zone-based endpoint's are
   `ALLOW` and `BLOCK`. `_find_matching_rules` builds a `FirewallRule` straight from the record
   (`firewall_check.py:185`), so on a legacy controller with any enabled rule the model raises a
   `ValidationError` and the command fails; on a zone-based controller it reads no rules at all.

## Evidence

Live, read-only, 2026-10-15, against the maintainer's current controller: `rest/firewallrule`
answered 200 with 0 rules; `v2/api/site/<site>/firewall-policies` answered 200 with 288 policies,
actions `ALLOW` (114) and `BLOCK` (174). Neither value is in the model's `Literal`.

## Impact

`diagnose firewall` and the MCP tool `firewall_check` report `basis: []` on every current
controller (nothing matched because nothing was read), and raise on a legacy controller that
has rules. The verdict is `not assessed` either way (issue 093), so no wrong answer is given,
but the tool cannot do the one thing it still claims to do.

## Recommended fix

Read `firewall-policies` first and fall back to `rest/firewallrule` when it answers 404 (a
legacy controller); map both shapes onto one model whose `action` accepts the controller's own
values (`accept`/`drop`/`reject`, `ALLOW`/`BLOCK`) and normalises them for the renderer; pin
both shapes against the fake controller and the zone-based one against a live read. The
zone-based policy carries source and destination *zones* rather than networks, so the matching
in `_rule_matches_traffic` needs the zone-to-network mapping (`firewall-zones`) as well. This is a
0.5.0 item: it changes what the tool reads and the model's public `action` type.
