---
title: "Tests and scripts carried device names from the live network; the history and two source rules still do"
date: 2026-10-04
status: open, decision needed
severity: medium
components: [tests, scripts, radio_config, protect_monitor, history]
found_by: docs and repo hygiene review (privacy scan)
---

# Tests and scripts carried device names from the live network; the history and two source rules still do

## Status

- Fixed at HEAD for `tests/` and `scripts/`. The repository is public, so this review
  replaced the names:
  - `e5696b5`: the device, client and port names in 13 test files are placeholders. Each
    keeps its model, and each room, owner or custom word in it became one NATO word, the
    same in every file, so the tests keep their meaning.
  - `99c3856`: the three site scripts no longer hold a target. They read their devices and
    ports from `site-targets.json`, outside the repository, through `scripts/site_targets.py`,
    and stop with exit code 2, before they read the controller config, when the file is
    missing or malformed. The repository keeps placeholders only, in
    `scripts/site-targets.example.json` ([codemap, section 22](../architecture/codemap.md#22-scripts-directory)).
  - `4845976`: the docs guard also reads every tracked test and script, so a captured name
    there fails the suite. A name that equals a model the code classifies counts as generic.
- Still open: the history (item 3) and the site-specific code in `src/` (items 4 and 5).

## Problem

As found, at `80c11fe`: a privacy scan compared the names in tracked files with the device,
port, network and SSID names in local captures of the live network. The docs were cleaned in
`e6a6aae`, but the scan had never looked at code. This file gives locations and counts only,
never a name.

The scan treats every captured name alike, so a few hits may be generic words rather than
names chosen for this site.

**Source docstrings** (3 names on 7 lines in 5 files): replaced with placeholder names in
`3afa3bc`, together with two client MACs and a subnet in the same docstrings. No code or
test changed.

`src/` also has one runtime rule written for this site: the radio optimisation plan moves any
access point whose name contains a room word off channel 36
(`src/unifi_mapper/analysis/radio_config.py:331-333`, described at `:306`). A few other
examples in `src/` docstrings and descriptions use room words the same way.

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

**Scripts** (3 files, 30 hits). These were runtime literals: each script targeted the site's
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

1. Tests: done in `e5696b5`.
2. Scripts: done in `99c3856`. To run one, copy `scripts/site-targets.example.json` to
   `~/.config/unifi_management_cli/site-targets.json` (under `$XDG_CONFIG_HOME` when it is
   set), or pass `--targets PATH`, and fill in the site's names. Keep the file out of the
   repository.
3. History: the user has asked for a history rewrite that removes the two passwords
   ([issue 041](041-onvif-scripts-hard-code-cameras.md),
   [issue 051](051-verify-cli-help-example-held-a-password.md)). Decide, before the unpushed
   commits are pushed, whether the same rewrite also covers the names: the five commits above,
   the pushed history of the scripts' literals, and the removed lines of `e5696b5` and
   `99c3856`, which hold the names they replaced. `a78d403` also changed three lines that
   still held a name, which `e5696b5` then replaced. A rewrite changes every later commit
   hash, including the `resolved_by` hashes the issue files record.
4. Two runtime rules in `src/` were written for this site, and changing either changes what
   the code does, which decision 11 doesn't authorize:
   - the radio rule above: drop the room-word channel move from `build_optimisation_plan`, or
     read it from a config file, so `radio optimize` makes the same plan on any site;
   - `src/unifi_mapper/monitors/protect_monitor.py:541` tracks only the cameras whose host
     contains one of the site's subnet prefixes (or that are third-party). The scan can't see
     it, because the prefix isn't a full address. Take the prefix from an option or a config
     file instead.
5. Addresses in `src/`: 22 lines in 14 files hold 23 addresses in subnets the site has
   configured. 20 are generic examples in the UniFi default subnet, and 3 are in other site
   subnets. 17 of the lines are docstrings and 2 are help text (argparse epilogs); those
   could move to documentation ranges without changing what the code does. The other 3 are
   strings the code returns at run time: an error hint, a model field description and an
   error suggestion. Changing them changes what users see. Decision 11 covers `tests/` and
   `scripts/` only, so this review changed none of them.

Related: [issue 040](040-real-identifiers-in-tests.md) (MACs and addresses in tests),
[issue 041](041-onvif-scripts-hard-code-cameras.md) (the ONVIF scripts).
