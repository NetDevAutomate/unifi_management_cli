---
title: "`diagnose firewall` verdicts are placeholder heuristics, not derived from the rules"
date: 2026-10-15
status: open, decision needed
severity: high
components: [connectivity/firewall_check]
found_by: 0.4.0 lane 3 (issue 091 reshape) live check
---

# `diagnose firewall` verdicts are placeholder heuristics, not derived from the rules

## Problem

`src/unifi_mapper/connectivity/firewall_check.py` reports an `allow`/`deny` verdict for a
source/destination pair and a VLAN-to-VLAN `connectivity_matrix`, and both are produced by
code that says so itself:

- `_rule_matches_traffic` (line 191): after a protocol and a destination-port check, every
  rule matches. The source comment reads "Source/destination check - very simplified ... If we
  get here, assume it might match for demo purposes" and the function returns `True`. Rule
  source and destination network ids are never resolved against the pair.
- `_check_inter_vlan_rules` (line 270): returns `deny` for EVERY inter-VLAN pair as soon as any
  enabled rule's NAME contains `block` or `deny`, otherwise `allow` ("Default allow for demo").
  No rule's source, destination, zone or action is read.
- `_determine_verdict` (line 219) returns `allow` when nothing matched ("Default policy"),
  without reading the site's actual default inter-VLAN policy.

The MCP tool `firewall_check` returns the same result, and the Mermaid renderer draws the
matrix as edges, so an agent or a reader sees a confident verdict with no basis in the rules.

## Evidence

Live, read-only, 2026-10-15, on the maintainer's site: `diagnose firewall 1 1 --json` reports
16 networks and 256 pair records, every one `allow`, on a site that has inter-VLAN firewall
rules. The verdicts cannot be checked against the rules because the code never consults them
per pair.

## Impact

High for the one command a user would reach for to answer "can VLAN A reach VLAN B": the answer
is a heuristic the output does not label as such. A `deny` can appear for every pair because one
rule is named "Block IoT", and an `allow` appears for a pair the rules actually block. Nothing is
written to the controller. Breaks fresh clones, CI or prod: no.

## Recommended fix

Decision needed first: either (a) implement the check, resolving each rule's `src_networkconf_id`
/ `dst_networkconf_id` (and zone, for zone-based firewalls on Network 9+) against the pair,
honouring rule order, action and enabled state, and reading the site's default inter-VLAN
policy for the no-match case; or (b) until (a) lands, label the result honestly: the verdict
field becomes `verdict: 'not assessed'` with a `basis` field naming what was checked (protocol,
port), the Mermaid matrix is not drawn, and the command prints that the firewall check is not
yet rule-based. (b) is a one-day change and is the 0.4.0 recommendation; (a) needs a live
rule-shape capture from both the classic and the zone-based firewall before it can be designed.
Either way the first test asserts a pair the rules block is not reported `allow`.

## Decision needed

Whether 0.4.0 ships (b), labelling the output as not assessed, or defers both until (a) can be
designed from a live capture.
