---
title: "Open items from the archived improvement and STP plans"
date: 2026-10-05
status: open
severity: low
components: [analysis, typer_cli, monitors]
found_by: July port (plans and working notes kept in a local archive, not in the repo)
---

# Open items from the archived improvement and STP plans

## Problem

The July work carried an STP and tooling plan, an improvement plan and four sets of
working notes (2026-05-04, 2026-07-22, 2026-07-23 and 2026-07-24). They are kept in a local
archive (not in the repo). Each item was checked against this repository when this issue was
filed, at the start of the July port, and again at the port's last update: the port built none
of the items under "Still open", so all of them remain open. This issue lists only what is
still open, so the plans need not be carried forward.

Done or tracked elsewhere (not repeated below): root eligibility by model class, the STP
change plan with apply and rollback, Root Guard and TCN recommendations, path-cost audit, SFP
and MTU audits, the drops-only counter threshold, LAG candidates, VLAN coverage, the traffic
matrix, XDG state with STP snapshots and diffs, preflight simulation, PoE budget, STP drift,
the STP MCP tools, counter-reset detection, neighbour-aware channel scoring, the Phase D RF
strategy work, and MCP tools for link errors, roaming, config drift and neighbours (issues
[010](010-cwd-relative-state-files.md) and [018](018-read-only-tool-proposals.md)). The July
port adds two more: a one-shot STP priority audit (`stp audit-priorities`, landed in
`c82d52c`) and the VLAN traffic collector (`vlan-traffic sample`, `rollup`, `report` and
`coverage`, with the MCP readers `get_vlan_traffic_report` and `list_vlan_traffic_periods`,
landed in `ad846b6`).
The 2026-07-22 notes' other items were site operations, not repository work; its code
item was the July port itself. An unattended weekly `radio auto-channel --apply` is decision
W10 in issue [060](060-decisions-from-the-july-port.md).

## Still open

From the STP and tooling plan:

- **Traffic-aware LAG placement**: weight `find_lag_candidates`' proposals by measured uplink
  utilisation (the traffic matrix), not link count alone.
- **A fixture-based LAG integration test**: run `find_lag_candidates_from_data` over a
  fleet-sized fixture and pin the proposals. The anonymised 17-switch fleet,
  `tests/fixtures/fleet_17_switch_anonymised.json` (landed in `2b2f8aa`), can serve.
- **Mixed STP mode detection**: report switches whose `stp_mode` differs (RSTP, MSTP, STP).
- **Edge-port audit**: flag a port with only client neighbours that is not an edge port, and
  an edge port that sees BPDUs or topology changes (`stp guard` covers Root Guard and TCNs
  only).
- **`stp validate-10g --since <snapshot>`**: report only counter errors that are new since an
  STP snapshot.
- **Preflight input per planned switch**: named uplink and downlinks for each planned switch
  (today `--simulate-add MODEL:COUNT` and one `--uplink`), with predicted blocked ports and
  path cost per new link.
- **Firmware guardrail**: refuse `inventory update-firmware` while an STP change plan is
  partly applied.
- **Weekly report bundle**: STP state, drift, PoE, firmware, SFP, MTU, counter deltas and
  storms in one Markdown report (written under XDG state, never `reports/` by default).
- **Home Assistant publishing of STP state** (root bridge, blocked-port count, per-switch
  priority) through the existing MQTT bridge pattern.
- **An STP decision guide**: which STP command to run when, a change-window runbook and a
  model capability table.

From the improvement plan:

- **L2 STP diagram**: `diagram --l2` with STP roles, port states, path costs and link speeds on
  every edge (Mermaid and Graphviz).
- **Stale port-name cleanup**: clear a name on a down port whose last neighbour no longer
  matches the named device (a write: plan, review, apply under issue
  [019](019-write-capable-cli-ideas.md)'s rules).
- **Thresholds file**: move hard-coded alert thresholds (PoE, error rate, client density,
  minimum RSSI) to one config file, falling back to today's defaults.
- **`diagnose all` trend history**: append each run's results under XDG state and add a
  trend view of checks that degraded.

From the 2026-07-24 notes:

- **Directional VLAN A to B traffic** (best effort, from sampled conntrack subnet pairs),
  beside the per-VLAN aggregates the collector records (`vlan-traffic sample`, `ad846b6`).
- **Per-period Mermaid diagrams** for the VLAN traffic report.
- **Per-client retry and loss trend** over time.
- **An incident-window composite** correlating recent config changes and events with a
  given time window (`find_recent_config_changes` and `get_recent_events`, landed in
  `27f765c` and `709fdd7`, are the raw material).

## Recommendation

File each item as its own issue when it is picked up; close this one when all are filed or
dropped. Breaks fresh clones, CI or prod: no.
