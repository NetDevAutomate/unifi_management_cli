---
title: "Add an LLDP consistency audit (`audit_lldp_consistency` / `analyze lldp`)"
date: 2026-10-02
status: open
severity: low
components: [analysis, typer_cli, mcp/manifests/analysis.yaml]
found_by: MCP uvx standards work
---

# Add an LLDP consistency audit (`audit_lldp_consistency` / `analyze lldp`)

## Problem

Nothing checks that the controller's view of the switch fabric agrees with what LLDP reports.
A stale `uplink` record, a one-sided LLDP adjacency or two ends of an inter-switch link
negotiating different speeds (a media converter, or stale telemetry) only shows up when
someone compares `ports inspect` output by hand. This was the design's tool T3 (priority P2),
deferred by plan decision P4 after T1/T2 and the four exposures landed.

## Impact

Topology mistakes and asymmetric links go unnoticed until they cause a fault. The CLI and MCP
have no single call that answers "is the LLDP picture consistent?".

## Recommended fix

The design's spec (MCP_STANDARDS_REVIEW.md §3 T3), on the same pieces T1 (`audit_link_speeds`)
uses:

- Module `analysis/lldp_consistency.py`: a pure `audit_lldp_consistency_from_data(...)` core
  plus the MCP handler
  `audit_lldp_consistency(switch: str | None = None, limit: int = 100, offset: int = 0)`,
  validated like `audit_link_speeds` (`limit` 1–1000, `offset` ≥ 0, `switch` resolved by
  `port_inspect.match_switch`, unknown or ambiguous → `DEVICE_NOT_FOUND` with candidates).
- Data: the same sync guarded fetch as T1 without the Integration API: `get_devices`,
  `load_profiles`, `_load_networks`, `_build_mac_index` → `(mac_to_dev, mac_to_user)`,
  `stat/sta`; per-port LLDP (`PortSummary.lldp`: `chassis_id`, `port_id`, `resolved_kind`,
  `resolved_name`) and negotiated speed from `summarise_ports`, plus each device's `uplink`
  block.
- Findings:

  | Code | Severity | Meaning |
  | --- | --- | --- |
  | `UPLINK_LLDP_MISMATCH` | HIGH | Controller `uplink` (`uplink_mac`/`uplink_remote_port`) disagrees with the LLDP neighbour on the uplink port |
  | `ASYMMETRIC_LINK` | HIGH | A sees B on p1, but B's LLDP doesn't see A on the reciprocal port |
  | `INTER_SWITCH_SPEED_ASYMMETRY` | HIGH | Both ends adopted and their negotiated speeds differ |
  | `MISSING_LLDP_INTER_SWITCH` | WARNING | An inter-switch link with no LLDP on one side |
  | `NON_UNIFI_LLDP_ON_TRUNK` | WARNING | A non-UniFi LLDP speaker on a trunk port |

- Overlap: `detect_foreign_bridges` covers bridges that don't speak LLDP; this reports
  LLDP-speaking peers only.
- CLI: `analyze lldp [-s NAME] [--json]`, `--json` equal to `model_dump(mode='json')`, exit 2
  when any HIGH finding exists (as `analyze link-speeds` does); add a README Command Reference
  row.
- Manifest: `analysis.yaml`, `credentials: controller`, explicit title, P2; bump
  `test_registry_totals`; the parity tests cover the rest.
- Tests: offline fixtures from `tests/fixtures_unifi.py` (frozen module clock), one case per
  finding code, CLI JSON parity.
