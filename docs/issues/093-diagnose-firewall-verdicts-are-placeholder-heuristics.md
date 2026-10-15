---
title: "`diagnose firewall` verdicts are placeholder heuristics, not derived from the rules"
date: 2026-10-15
status: resolved
resolved_by: 3c142a5
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

## Decision and resolution (2026-10-15)

Option (b), decided by the 0.4.0 validation council (pass B, D-093, unanimous) and verified in
source by the agent; the maintainer can revert before the release merges. Option (a), the
rule-based evaluation, is 0.5.0 work after a read-only capture of one classic and one
zone-based rule set.

The verdict and every matrix cell are `not assessed`; a `basis` field says exactly what was
checked (the enabled rules whose protocol and destination port match, in evaluation order) and
what was not (each rule's source and destination networks against the pair; the site's default
policy). The two heuristic functions are deleted. The recommendations say what the listed rules
are and are not evidence of. The CLI prints the verdict and the basis and its `--help` no
longer promises a verdict; the Mermaid matrix draws the networks and no verdict edge, with a
note; the MCP manifest description says the same.

Pinned by `tests/connectivity/test_firewall_not_assessed.py`: the result over the fake
controller (a rule whose name says block no longer turns any cell `deny`), the CLI JSON and
human output, the Mermaid rendering, and the help text.

What a user sees: on the maintainer's site, read-only, `diagnose firewall` reports 256 pair
records all `not assessed` where every one read `allow`. Consumers of the `verdict` field and
of the matrix cells see the new value; listed under Breaking.
