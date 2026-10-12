---
title: "Tests, scripts and docstrings carried the site's device and room names; the history and some runtime strings still do"
date: 2026-10-04
status: open, decision needed
severity: medium
components: [tests, scripts, radio_config, enhanced_network_topology, protect_monitor, history]
found_by: docs and repo hygiene review (privacy scan)
---

# Tests, scripts and docstrings carried the site's device and room names; the history and some runtime strings still do

## Status

- Fixed at HEAD for `tests/`, `scripts/` and the `src/` docstrings. The repository is public,
  so this review replaced the names:
  - `e99e5f2`: the device, client and port names in 13 test files are placeholders. Each
    keeps its model, and each room, owner or custom word in it became one NATO word, the
    same in every file, so the tests keep their meaning.
  - `9d98dcb`: the three site scripts no longer hold a target. They read their devices and
    ports from `site-targets.json`, outside the repository, through `scripts/site_targets.py`,
    and stop with exit code 2, before they read the controller config, when the file is
    missing or malformed. The repository keeps placeholders only, in
    `scripts/site-targets.example.json` ([codemap, section 22](../architecture/codemap.md#22-scripts-directory)).
  - `d3b817e`: the docs guard also reads every tracked test and script, so a captured name
    there fails the suite. A name that equals a model the code classifies counts as generic.
  - `cbe2560`: the site's room words on six docstring lines in five `src/` files are
    placeholders. Switch names take the ones `d379f2d` used (`Switch A`, `Switch B`), access
    points become `AP B` to `AP D`, the `_extract_location` example uses two generic words
    from that method's own location list, and the radio rule's description no longer names
    its word. No code changed.
- Still open: the history (item 3), and the site-specific rules and runtime strings in `src/`
  (items 4 and 5).

## Problem

As found, at `9f04bfa`: a privacy scan compared the names in tracked files with the device,
port, network and SSID names in local captures of the live network. The docs were cleaned in
`fb3e1f3`, but the scan had never looked at code. This file gives locations and counts only,
never a name.

The scan treats every captured name alike, so a few hits may be generic words rather than
names chosen for this site.

**Source docstrings** (3 names on 7 lines in 5 files): replaced with placeholder names in
`d379f2d`, together with two client MACs and a subnet in the same docstrings. No code or
test changed.

`src/` also has one runtime rule written for this site: the radio optimisation plan moves any
access point whose name contains one particular room word off channel 36
(`src/unifi_mapper/analysis/radio_config.py:332-334`, described at `:306-307`). Six more
docstring lines used the site's room words, in examples and in that rule's description;
`cbe2560` replaced them. The runtime strings that still hold room words are listed in item 4.

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

The table is the `9f04bfa` scan's. The wider scan behind the fix also found names in
`tests/test_new_analysis_tools.py` and `tests/test_port_inspect_context.py`, so `e99e5f2`
changed 13 test files. `tests/test_apply_ap_channel_plan.py` isn't one of them: `9d98dcb`
rewrote it together with the scripts.

**Scripts** (3 files, 30 hits). These were runtime literals: each script targeted the site's
own devices by name.

| File | Hits |
| --- | ---: |
| `scripts/apply_ap_channel_plan.py` | 10 |
| `scripts/apply_stp_priorities_custom.py` | 16 |
| `scripts/remediate_stp_post_apply.py` | 4 |

**Unpushed history.** Five commits after `1c58b5d` add a line with such a name: `5049a28`,
`c7534eb`, `7341069`, `041b427` and `f71925c` (tests, two source docstrings and, in
`c7534eb`, the README, which `fb3e1f3` cleaned). A sixth, `b65cf1d`, adds a room word in a
docstring example, which `cbe2560` replaced.

## Impact

The names describe one private network (rooms, owners, locations); they are not
credentials. Nothing breaks for fresh clones, CI or users. Once pushed, the history copies
can't be removed without rewriting published commits.

## Decision needed

1. Tests: done in `e99e5f2`.
2. Scripts: done in `9d98dcb`. To run one, copy `scripts/site-targets.example.json` to
   `~/.config/unifi_management_cli/site-targets.json` (under `$XDG_CONFIG_HOME` when it is
   set), or pass `--targets PATH`, and fill in the site's names. Keep the file out of the
   repository.
3. History: the user has asked for a history rewrite that removes the two passwords
   ([issue 041](041-onvif-scripts-hard-code-cameras.md),
   [issue 051](051-verify-cli-help-example-held-a-password.md)). The user has approved
   removing the network details in the unpushed commits in the same rewrite. Only the names
   in the pushed history are still to decide. The orchestrator sets the exact commit list.
   The copies are:
   - the six commits above, and the pushed history of the scripts' literals;
   - the removed lines of `e99e5f2` and `9d98dcb`, which hold the names they replaced.
     `a91e62a` also changed three lines that still held a name, which `e99e5f2` then
     replaced;
   - the removed lines of the doc and docstring scrubs, most of them public since before
     this review:
     - `fb3e1f3`: 19 doc lines that held a captured device name or a room word, 17 of them
       on `origin/main`: `README.md` 4 (2 on `origin/main`),
       `docs/guides/use-cases-and-howto.md` 4,
       `docs/operations/troubleshooting-and-runbook.md` 1,
       `docs/solutions/analysis/port-label-drift.md` 9 and
       `docs/solutions/analysis/radio-wlan-write-path-correctness.md` 1;
     - `d379f2d`: 12 docstring lines in five `src/` files, 8 of them on `origin/main`;
     - `cbe2560`: 6 docstring lines in five `src/` files, 5 of them on `origin/main`.

   A rewrite changes every later commit hash, including the `resolved_by` hashes the issue
   files record.
4. Runtime code and strings in `src/` were written for this site, and changing them changes
   what the code does or shows, which decision 11 doesn't authorize:
   - the radio rule above: drop the room-word channel move from `build_optimisation_plan`, or
     read it from a config file, so `radio optimize` makes the same plan on any site;
   - `src/unifi_mapper/monitors/protect_monitor.py:541` tracks only the cameras whose host
     contains one of the site's subnet prefixes (or that are third-party). The scan can't see
     it, because the prefix isn't a full address. Take the prefix from an option or a config
     file instead;
   - other runtime strings and comments that hold the site's room words, counted after
     `cbe2560`: 25 lines in 8 files besides the rule's own condition:
     - `src/unifi_mapper/enhanced_network_topology.py`: 17 string lines and 1 comment. The
       location keyword lists of `NetworkTopology._extract_location` and
       `generate_html_diagram` hold the site's room words beside generic ones, and the
       core-location check in `_extract_location` holds one more site word;
     - help text and descriptions whose switch-name example holds a room word, 1 line each:
       `src/unifi_mapper/typer_cli.py` (a `--switch` help),
       `src/unifi_mapper/network_cli.py` (an epilog example),
       `src/unifi_mapper/diagnostics/inspect_port.py` (a model field description) and
       `src/unifi_mapper/mcp/manifests/diagnostics.yaml` (an MCP tool description);
     - `src/unifi_mapper/browser_verification.py`: 1 page selector;
     - comments: `src/unifi_mapper/analysis/radio_config.py` 1 (the rule's own) and
       `src/unifi_mapper/analysis/rf_strategy.py` 1.

     Replacing the help text and descriptions with placeholders changes only what users
     read; the location lists and the selector change what the code matches.
5. Addresses in `src/`: 22 lines in 14 files hold 23 addresses in subnets the site has
   configured. 20 are generic examples in the UniFi default subnet, and 3 are in other site
   subnets. 17 of the lines are docstrings and 2 are help text (argparse epilogs); those
   could move to documentation ranges without changing what the code does. The other 3 are
   strings the code returns at run time: an error hint, a model field description and an
   error suggestion. Changing them changes what users see. Decision 11 covers `tests/` and
   `scripts/` only, so this review changed none of them.

Related: [issue 040](040-real-identifiers-in-tests.md) (MACs and addresses in tests),
[issue 041](041-onvif-scripts-hard-code-cameras.md) (the ONVIF scripts).
