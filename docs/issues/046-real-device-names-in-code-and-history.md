---
title: "Tests, scripts and unpushed commits carry device names from the live network"
date: 2026-10-04
status: open, decision needed
severity: medium
components: [tests, scripts, radio_config]
found_by: docs and repo hygiene review (privacy scan)
---

# Tests, scripts and unpushed commits carry device names from the live network

## Problem

A privacy scan compared the names in tracked files with the device, port, network and SSID
names in local captures of the live network. The docs were cleaned in `e6a6aae`, but the
scan had never looked at code. This file gives locations and counts only, never a name.

The scan treats every captured name alike, so a few hits may be generic words rather than
names chosen for this site.

**Source docstrings** (3 names on 7 lines in 5 files): replaced with placeholder names in
`3afa3bc`, together with two client MACs and a subnet in the same docstrings. No code or
test changed.

`src/` also has one runtime rule written for this site: the radio optimisation plan moves any
access point whose name contains a room word off channel 36
(`src/unifi_mapper/analysis/radio_config.py:331-333`, described at `:306`). The scan doesn't
flag it because no captured name equals that word, and a few other examples in `src/`
docstrings and descriptions use room words the same way.

**Tests** (12 files, 57 hits):

| File | Hits |
| --- | ---: |
| `tests/analysis/test_link_error_tracking_unadopted.py` | 1 |
| `tests/analysis/test_port_naming_plan.py` | 19 |
| `tests/analysis/test_stp_optimizer.py` | 6 |
| `tests/analysis/test_stp_preflight.py` | 4 |
| `tests/analysis/test_uplink_transparency.py` | 4 |
| `tests/fixtures_unifi.py` | 1 |
| `tests/test_apply_ap_channel_plan.py` | 3 |
| `tests/test_apply_ap_tx_power_auto.py` | 1 |
| `tests/test_match_switch.py` | 3 |
| `tests/test_port_diagnostics.py` | 1 |
| `tests/test_port_inspect.py` | 7 |
| `tests/test_port_naming.py` | 7 |

**Scripts** (3 files, 30 hits). These are runtime literals: each script targets the site's
own devices by name.

| File | Hits |
| --- | ---: |
| `scripts/apply_ap_channel_plan.py` | 10 |
| `scripts/apply_stp_priorities_custom.py` | 16 |
| `scripts/remediate_stp_post_apply.py` | 4 |

**Unpushed history.** Five commits after `d045079` add a line with such a name: `085bcbf`,
`3a6e8f4`, `2f6acf4`, `79e24e7` and `ab1f32a` (tests, two source docstrings and, in
`3a6e8f4`, the README, which `e6a6aae` cleaned).

## Impact

The names describe one private network (rooms, owners, locations); they are not
credentials. Nothing breaks for fresh clones, CI or users. Once pushed, the history copies
can't be removed without rewriting published commits.

## Decision needed

Recommendation:

1. Tests: replace each name with a neutral placeholder that keeps the model (as `e6a6aae`
   did in the docs), where the assertions allow it. Check each test first: several match on
   the name itself (switch resolution, port-label planning), so the fixture and its
   assertions change together.
2. Scripts: move the site-specific one-offs out of the tracked tree, into a git-ignored
   local directory, or make them read their targets from the environment or a config file,
   as `15b0f60` did for the ONVIF scripts ([issue 041](041-onvif-scripts-hard-code-cameras.md)).
3. History: the user has asked for a history rewrite that removes the two passwords
   ([issue 041](041-onvif-scripts-hard-code-cameras.md),
   [issue 051](051-verify-cli-help-example-held-a-password.md)). Decide, before the unpushed
   commits are pushed, whether the same rewrite also covers these five and `062a0e5`
   ([issue 040](040-real-identifiers-in-tests.md)). A rewrite changes every later commit
   hash, including the `resolved_by` hashes the issue files record.
4. The radio rule: drop the room-word channel move from `build_optimisation_plan`, or read it
   from a config file, so `radio optimize` makes the same plan on any site.

Why this needs a decision: the test data drives matching assertions, moving or rewriting the
scripts changes how they are run, dropping the radio rule changes the plan `radio optimize`
proposes, and a history rewrite is the user's call.

Related: [issue 040](040-real-identifiers-in-tests.md) (MACs and addresses in tests),
[issue 041](041-onvif-scripts-hard-code-cameras.md) (the ONVIF scripts).
