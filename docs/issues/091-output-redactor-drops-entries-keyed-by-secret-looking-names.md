---
title: "The output redactor drops entries of any map keyed by a name that looks like a secret"
date: 2026-10-15
status: open, decision needed
severity: low
components: [core/utils/redact, typer_cli._emit_json, mcp results]
found_by: issue 066 fix (a real backup's report lost 27 documents)
---

# The output redactor drops entries of any map keyed by a name that looks like a secret

## Problem

`strip_secrets` removes every mapping key that `is_secret_key` matches: any key that starts
with `x_`, or contains `password`, `secret`, `token`, `authkey`, `psk`, `pre-shared`,
`passphrase`, `api_key` or `private_key` (case-insensitive), or ends in `community`,
`syslog_key` or `lcm_tracker_seed`. It also drops the `value` of a `{key|name: <secret-looking>,
value: ...}` pair. That rule is right for API objects, where the keys are schema field names.
It is wrong for a report whose mapping keys are data: names the operator or the controller
chose.

`--json` output goes through `strip_secrets` (`typer_cli._emit_json`), so an entry keyed by such
a name vanishes with no warning. Found while fixing issue 066: `backup verify` keyed its counts
by collection name, and `api_key`, `api_key_privilege`, `ssooauthtoken` and `teleport_token`
were stripped, so the JSON reported 2,513 of a real backup's 2,540 documents. 066 worked around
it for that one output, by counting those names as `other`.

A probe on 2026-10-15 shows ordinary names it would strip: `Office-Token-Ring`, `tokens`,
`secret garden`, `password_hint`, `privatekey`, `x_passphrase`. So would an SSID or network
named, for example, `IoT-PSK` or `Guest-Token`.

## Impact

Any JSON output that is a mapping keyed by an operator-chosen name (a network, SSID, device,
AP or profile name) can lose entries on a site whose names happen to match the rule. Totals
then disagree with the controller, and nothing says why. Candidates found by a search, not yet
audited: `clients_by_network` (`analysis/dhcp_pool.py`), `by_ap` (`analysis/neighbour_scan.py`),
`required_priorities` (`analysis/stp_preflight.py`). Most outputs are lists of records, which
lose a field only through the pair rule. It is not a leak: data is removed, never exposed.
Breaks fresh clones, CI or prod: no.

## Recommended fix

Keep the rule for API objects and stop it seeing data keys.

1. Reports key nothing by a user-chosen name. Name-keyed maps become lists of records whose
   name field is not `key` or `name` (for example `{'network': ..., 'clients': ...}`), so
   neither rule applies to it.
2. A test walks every registered command's `--json` output (and every MCP tool's result) over a
   fake site whose names all match `is_secret_key`, and checks that each name and count survives.

The decision needed: whether (1) is worth the output-shape change (Breaking for `--json`
consumers) on the outputs the audit finds affected, or whether a documented limitation is
enough.
