# UniFi Management CLI — STP & Tooling Expansion Plan

**Date:** 2026-05-02
**Target env:** 17-switch UniFi network, UDM Pro Max gateway, 2× USW Flex XG pending install
**Prereq:** controller at `https://203.0.113.254`, config in `~/.config/unifi_network_mapper/prod.env`

---

## 1. Motivation

Live validation run (`unifi-mapper stp validate-10g`) produced `NOT_READY` with one
CRITICAL: recommended promoting `Xray3 USW-Lite-16-PoE` (1G access-class) to the STP
root alongside `Xray3 USW Flex XG 10G`. The current algorithm treats any
gateway-connected switch as Tier 0 / Core with priority 4096, ignoring hardware
capability. This blocks safe 10G expansion until the optimizer is
capability-aware and until several adjacent gaps (path-cost, BPDU guard,
rollback safety) are closed.

This plan is organised as phases. Each phase ends in a running,
test-covered increment. No phase breaks prior phases.

---

## 2. Guiding principles

1. **Deterministic Python for math, apply, and rollback**; agents/LLMs for
   synthesis, runbook generation, and natural-language triage only.
2. **Idempotent, reversible changes.** Every `stp optimize --apply` writes a
   `plan.json` that `stp rollback` can reverse.
3. **Human-in-the-loop for writes.** `--apply` requires an explicit plan file
   argument; agents never call it directly.
4. **Heuristics gated by config.** Thresholds (drops, dBm, temp) live in
   `~/.config/unifi_network_mapper/unifi_mapper.yaml`, not hard-coded.
5. **MCP server is the single contract surface** for all agent integrations.
   No per-agent Python fork.
6. **TDD for all model/tier/plan code.** `uv run pytest` green before each
   phase merges.

---

## 3. Phase 0 — Root-eligibility fix (blocking)

### Problem
`_calculate_hierarchy_tiers()` promotes any `connected_to_gateway=True` switch
to Tier 0 Core with priority 4096. In the target environment this misclassifies
`Xray3 USW-Lite-16-PoE` (USL16LPB, 1G access).

### Deliverables
- `src/unifi_mapper/core/models/stp.py`
  - Add `SwitchCapabilityClass` enum:
    `AGGREGATION`, `CORE_DISTRIBUTION`, `ACCESS_POE`, `ACCESS`, `GATEWAY`,
    `UNKNOWN`
  - Add `SwitchCapabilityClass` field to `SwitchSTPConfig`
  - Add `root_eligible: bool` derived field
- `src/unifi_mapper/analysis/model_capabilities.py` (new)
  - `classify_model(model: str) -> SwitchCapabilityClass`
  - Initial map covers every model already in the discovered topology:
    `USFXG`, `USAGGPRO`, `US24XG`, `US48XG`, `USXG` → AGGREGATION
    `UDMPROMAX`, `UDMPRO`, `UDM`, `UGW*`, `USG*` → GATEWAY
    `USL16LPB`, `USL8LP` → ACCESS_POE
    `USWED35`, `USWED37`, `US8P60`, `USM8P210` → ACCESS_POE
    `USC8`, `USS5` → ACCESS
    `*` (default) → UNKNOWN
  - Document capability matrix in module docstring
- `src/unifi_mapper/analysis/stp_optimizer.py`
  - `_calculate_hierarchy_tiers()` rewrite:
    - Tier 0 only if `capability in {AGGREGATION}` AND gateway-connected
      AND not in `force_access_macs` override
    - Gateway-connected but access-class → Tier 1 (Distribution-adjacent)
    - BFS from true Tier 0 set for remaining tiers
  - `calculate_optimal_priorities()` guard:
    - Refuse to emit priority < 8192 for switches with `capability in
      {ACCESS, ACCESS_POE}` even if override says otherwise; log WARNING
  - `generate_stp_report()` adds `root_candidates` list with reason per entry
- New override file loader
  `src/unifi_mapper/core/utils/overrides.py`
  Reads `~/.config/unifi_network_mapper/stp_overrides.yaml`:
  ```yaml
  root_eligible_macs:
    - 02:00:fe:02:00:09
  force_access_macs:
    - 02:00:fe:02:00:13
  ```
- New validation finding: `ROOT_BRIDGE_CAPABILITY_MISMATCH` (CRITICAL) —
  emitted when current root is not AGGREGATION-class.

### Tests
`tests/analysis/test_stp_optimizer.py` additions:
- `test_access_class_gateway_neighbor_is_not_core` — models USL16LPB +
  USFXG both on gateway; assert USL16LPB tier != 0.
- `test_root_guard_refuses_priority_4096_for_access_class`
- `test_override_force_access_demotes_switch`
- `test_override_root_eligible_promotes_only_aggregation_class`
- `test_multiple_aggregation_switches_share_tier_0`
  (USFXG + USAGGPRO both gateway-connected)
- Fixture `tests/fixtures/topology_17_switch.json` capturing current live
  device list (sanitised: strip tokens, keep mac/model/type/port_table).

### Exit criteria
- All new + existing tests green: `uv run pytest -q`
- Live rerun:
  ```
  uv run unifi-mapper stp validate-10g --planned-switches 2
  ```
  Produces:
  - `Xray3 USW Flex XG 10G` as sole Tier 0 candidate
  - `Xray3 USW-Lite-16-PoE` demoted to Tier 1 with reason
    "access-class, gateway-adjacent"
  - No priority 4096 recommendation for USL16LPB
- Readiness remains `NOT_READY` on first rerun only because
  the 13 priority changes still need review — that is correct behaviour.

---

## 4. Phase 1 — Plan file + convergence-safe apply + rollback

Addresses plan items 9 + 10.

### Deliverables
- `src/unifi_mapper/core/models/stp_plan.py` (new)
  - `STPPlan` = metadata + ordered list of `STPPlanStep`
  - `STPPlanStep`: `device_id`, `mac`, `current_priority`, `new_priority`,
    `tier`, `phase` (`promote_root` | `demote_old_root` | `dist` | `access`),
    `executed_at?`, `result?`
- `stp plan` subcommand: computes and writes `plans/stp-YYYY-MM-DDTHH-MM.json`
  - Ordering algorithm:
    1. Identify *new* root (lowest priority among root-eligible)
    2. Step 1: set new root's priority (no effect if already lowest)
    3. Step 2: demote prior root if different
    4. Steps 3–N: distribution tier changes (ascending priority)
    5. Steps N+1–M: access tier changes (ascending priority)
  - Dry-run Mermaid diff: current → after-step-1 → after-all
- `stp apply --plan <file>` replaces existing `apply_stp_changes`
  - Executes steps sequentially
  - Between steps: wait `--stabilise-seconds` (default 30) then re-query and
    verify no new blocked ports, no root flip away from new root
  - On step failure: write executed state back into plan file, exit non-zero,
    print `unifi-mapper stp rollback <plan>` command
- `stp rollback <plan>` reverses any `executed_at`-marked step in reverse
  order, skips unexecuted.

### Tests
- `tests/analysis/test_stp_plan.py`
  - `test_plan_order_promotes_root_before_demotion`
  - `test_plan_order_distribution_before_access`
  - `test_plan_file_round_trip`
  - `test_rollback_reverses_only_executed_steps`
  - `test_apply_halts_on_blocked_port_spike` (mocked post-step topology)

### Exit criteria
- `stp plan` emits JSON matching schema
- `stp apply` + fault-injection test (mock failure at step 3) leaves network in
  rollback-able state
- Rollback brings all executed priorities back to pre-plan values

---

## 5. Phase 2 — Port-level STP hygiene (items 1, 2, 3, 14)

### Deliverables
- `src/unifi_mapper/analysis/stp_port_hygiene.py` (new)
  - `audit_edge_ports(topology) -> list[EdgePortFinding]`
    - Port has client-only LLDP (not in `mac_to_device`) AND `port_profile`
      not edge → WARNING
    - Edge port with `stp_tc_count > 0` or observed BPDU ingress → CRITICAL
  - `audit_path_costs(topology) -> list[PathCostFinding]`
    - Compute expected IEEE long path cost: 10G=2000, 1G=20000, 2.5G=8000
    - Detect legacy mode: if 10G port reports `stp_pathcost <= 20` → CRITICAL
  - `recommend_root_guard(topology) -> list[RootGuardRecommendation]`
    - Core/dist downlink ports → suggest root-guard enable
  - `audit_tcn_counters(topology) -> list[TCNFinding]`
    - `stp_tc_count` per port; flag top-N highest + anything >50/hour via
      baseline (phase 5 integration)
- New CLI: `unifi-mapper stp port-hygiene`
- Feeds into `stp validate-10g` as additional findings

### Tests
- `tests/analysis/test_stp_port_hygiene.py` — fixture-driven
  (no live controller required)

### Exit criteria
- Live run produces table of edge/BPDU/path-cost/TCN findings
- Zero findings on a correctly-configured trunk port; findings on any
  misconfigured edge in the target env

---

## 6. Phase 3 — Physical-layer diagnostics (items 4, 6, 15)

### Deliverables
- `src/unifi_mapper/diagnostics/sfp_diagnostics.py` (new)
  - Pull `port_table.sfp_*` fields; structured `SFPReport` per module
  - Flags: `temp_c > 70`, `tx_dbm < -10 or > -3`, `rx_dbm < -10 or > -3`,
    unknown vendor
  - `unifi-mapper diag sfp` command (text + markdown output)
- `src/unifi_mapper/diagnostics/cable_test.py` (new, optional runtime)
  - Wraps controller cable-test endpoint; opt-in per-port via flag
- `src/unifi_mapper/diagnostics/mtu_consistency.py` (new)
  - Compare MTU / jumbo-frame per device + per-port along inter-switch links
  - Flag mismatches on 10G uplinks (CRITICAL), 1G uplinks (WARNING)
- Refactor error-counter heuristic in
  `build_10g_expansion_validation_report`:
  - Split into three findings:
    - `CRC/rx_errors > 0` → CRITICAL
    - `rx_dropped > --drops-threshold (default 10000)` → WARNING
    - drops below threshold → no finding
  - Config knob in YAML: `port_error_thresholds.drops`, `.crc`, `.errors`
  - Severity mapping table documented in module docstring

### Tests
- Fixture test for each finding type
- Regression test: original 14 drop-only warnings in live env collapse to
  INFO severity once drops threshold configured

### Exit criteria
- `diag sfp` output for all fibre-connected ports on the two USW Flex XG
- `diag mtu` clean on all inter-switch links
- Rerun `validate-10g`: only `Xray3 USW Flex XG 10G port 3` error remains
  flagged (legitimate `errors=1`)

---

## 7. Phase 4 — LAG + traffic-aware placement (items 5, 11, 12, 13)

### Deliverables
- `src/unifi_mapper/analysis/lag_candidates.py`
  - Detect parallel LLDP edges between same device pair
  - Propose `networkconf` / `portconf` LAG patch (LACP active, L3+L4 hash)
  - Special-case 2× USW Flex XG: propose LAG between them on the 10G ports
- `src/unifi_mapper/analysis/stp_mode.py`
  - Query `stp_mode` (`rstp` / `mstp` / `stp`) per switch; flag mixed mode
- `src/unifi_mapper/analysis/vlan_coverage.py`
  - Per-trunk `tagged_vlans` set; compute desired set from attached access
    switch VLAN membership; flag missing VLANs on uplink trunks
- `src/unifi_mapper/analysis/traffic_matrix.py`
  - Pull `stat/report/5minutes.site` + per-switch `stat/device` uplink bytes
  - Output top 20 flows + switch uplink utilisation; Mermaid-weighted edges

### Tests
- Fixture-driven per analyzer
- Integration test: LAG candidate run against `topology_17_switch.json`
  produces one proposed LAG (between the two USW Flex XG after they're added)

### Exit criteria
- Markdown report per analyzer
- LAG proposal JSON usable as apply payload (phase 1 `stp plan` harness
  extends easily to port-config plans)

---

## 8. Phase 5 — State, baselines, snapshot/replay (items 17, 19)

### Deliverables
- `~/.local/state/unifi_mapper/` state dir conforming to XDG
- `src/unifi_mapper/utility/state_store.py`
  - Snapshots: timestamped JSON of STP topology + port counters
  - `stp snapshot` writes; `stp diff <snap>` compares
  - Counter deltas computed per-port: new CRC, new drops, new TCNs
- Port-error baseline auto-updates nightly if cron wrapper enabled
- `stp validate-10g` gains `--since <snap>` flag: flag only new errors

### Tests
- `tests/utility/test_state_store.py`: write/read/delta math

### Exit criteria
- `stp snapshot` + `stp diff` produces deltas, not cumulative totals

---

## 9. Phase 6 — Planner & preflight simulation (item 18, 16)

### Deliverables
- `stp preflight simulate-add <yaml>` subcommand
  - YAML input:
    ```yaml
    planned_switches:
      - name: Aggregation Flex XG #1
        model: USFXG
        uplink_to: { device: Xray3 USW Flex XG 10G, port: 1 }
        downlinks:
          - { device: Mike2 USW Flex 2.5G 8 PoE, port: 9 }
      - name: Aggregation Flex XG #2
        model: USFXG
        uplink_to: { device: Dream Machine Pro Max, port: 11 }
        downlinks:
          - { device: Hotel3 USW Lite 8 PoE, port: 1 }
    ```
  - Output: tier assignment, predicted root, pre/post Mermaid,
    predicted blocked-port count, predicted path-cost per new link
- `stp optimize --plan` renders colored diff (rich) and estimated
  convergence window based on STP mode + port count

### Tests
- Simulation returns deterministic results for a given YAML
- Root election matches `calculate_optimal_priorities` on actual post-insert
  topology (re-run in live env after install)

### Exit criteria
- Preflight YAML for the actual Flex XG install exists in
  `specs/flex_xg_preflight.yaml`
- Preflight run produces READY with predicted root = `Xray3 USW Flex XG 10G`

---

## 10. Phase 7 — PoE budget, firmware guardrails (items 7, 8)

### Deliverables
- `src/unifi_mapper/analysis/poe_budget.py`
  - Sum `poe_power` per switch; compare to `total_max_power` from model spec
  - Project: given `planned_devices` list, predict post-install draw
- Extend `src/unifi_mapper/analysis/firmware_advisor.py`:
  - `--block-if-stp-changes-pending` flag
  - Cross-check `plans/*.json` for in-flight plans; refuse upgrade if any
    step `executed_at` set but not all steps complete
- Model-spec table (dataclass per model with `total_max_power`,
  `poe_ports`, `sfp_plus_ports`, `sfp28_ports`) lives in
  `src/unifi_mapper/analysis/model_specs.py` — shared with
  `model_capabilities.py` where possible

### Tests
- PoE projection math
- Firmware guardrail triggers on pending plan fixture

### Exit criteria
- Live report: PoE headroom per switch
- Upgrade blocked during in-flight plan (tested with fake plan file)

---

## 11. Phase 8 — Intent + drift (item 22)

### Deliverables
- `~/.config/unifi_network_mapper/stp_intent.yaml`
  ```yaml
  root_bridge:
    mac: 02:00:fe:02:00:09  # Xray3 USW Flex XG 10G
    priority: 4096
  priorities:
    - mac: 78:45:58:62:f1:4a
      priority: 8192
    # …
  path_cost_mode: long
  ```
- `stp drift` command
  - Compares live topology to intent
  - Outputs findings (CRITICAL if root bridge differs, WARNING for priority
    drift)
- Optional cron wrapper writes `reports/drift-YYYY-MM-DD.md`

### Tests
- Drift detection on mutated fixture

### Exit criteria
- `stp drift` clean immediately after `stp apply --plan` + no changes

---

## 12. Phase 9 — Reporting + weekly bundle (item 23)

### Deliverables
- `src/unifi_mapper/reporting/weekly.py`
  - Aggregates: STP state, drift, PoE, firmware, SFP, MTU, port-error deltas,
    storm detection
  - Emits `reports/weekly/YYYY-WW.md` + optional PDF via `weasyprint`
- Sections: summary, red-findings table, Mermaid topology, trend charts
  (text-based sparkline or matplotlib svg)

### Exit criteria
- Manual run produces readable markdown report for current week

---

## 13. Phase 10 — Home Assistant publishing (item 21)

### Deliverables
- `src/unifi_mapper/monitors/ha_stp_bridge.py`
  - Reuses existing `protect/MQTTBridge` pattern
  - Publishes: root bridge mac, blocked port count, per-switch STP priority,
    port-error deltas
  - HA discovery topics; sensors:
    `sensor.unifi_stp_root_bridge`, `binary_sensor.unifi_stp_root_changed`,
    `sensor.unifi_blocked_ports`
- Daemon mode: poll every N minutes; publish delta only if change

### Exit criteria
- HA sees sensors; triggering a priority change flips
  `binary_sensor.unifi_stp_root_changed` briefly

---

## 14. Phase 11 — MCP surface + agent adapters (items 20 + Q2)

### Why now, not earlier
Every phase above adds an analyzer with a clean function signature and
pydantic model output. Wrapping each as MCP tool is a thin final layer —
wait until signatures are stable to avoid churn in manifests.

### Deliverables
- `src/unifi_mapper/mcp/manifests/analysis.yaml` additions:
  - `stp_preflight_simulate_add`
  - `stp_port_hygiene`
  - `stp_lag_candidates`
  - `stp_path_cost_audit`
  - `stp_snapshot_diff`
  - `sfp_diagnostics`
  - `mtu_consistency`
  - `poe_budget`
  - `stp_drift`
  - `weekly_report_generate`
- Each manifest entry: input schema (pydantic-derived), output schema,
  read-only flag, example payload, 1-paragraph prompt hint for LLM consumers
- Apply/rollback tools remain **read-only in MCP** by default. Optional
  `--enable-write` server flag unlocks `stp_apply` + `stp_rollback`; gated
  behind an operator-set env var `UNIFI_MCP_ALLOW_WRITE=1`.

### Agent adapters
Directory: `docs/integrations/agents/`

One file per target agent, each ≈30 lines. Contract identical: all agents
connect to the same `unifi-mcp` server. Difference is launcher config +
sample prompt.

| Agent           | Adapter path                                 | Notes |
|-----------------|----------------------------------------------|-------|
| Claude Code     | `.claude/mcp.json` (global already exists)   | Add `unifi-mcp` server entry + ready-made prompt in `.claude/prompts/unifi-stp.md` |
| Codex CLI       | `docs/integrations/agents/codex.md`          | `codex mcp add unifi-mcp` one-liner |
| Gemini CLI      | `docs/integrations/agents/gemini.md`         | `~/.gemini/settings.json` MCP stanza |
| kiro-cli        | `docs/integrations/agents/kiro.md`           | Kiro-style tool registration |
| opencode        | `docs/integrations/agents/opencode.md`       | opencode agent manifest pointing at MCP server |

Each adapter doc includes:
- Install snippet
- Minimal smoke prompt: "Validate STP and show readiness for 10G expansion"
- Example synthesis prompt: "Given current port-hygiene, PoE, and firmware
  reports, produce a 1-page maintenance runbook for tonight's change window"

### Tests
- `tests/mcp/test_manifest_schema.py` — each manifest entry has input +
  output schema, matches implementation signature
- Smoke test: start `unifi-mcp` in subprocess, list tools, call one
  read-only tool, expect pydantic JSON

### Exit criteria
- All new tools callable from MCP
- At least one agent adapter (Claude Code) exercised end-to-end with a
  synthesis prompt that reads >2 tool outputs and produces a readable runbook
- Write-capable tools gated behind `UNIFI_MCP_ALLOW_WRITE=1`

### Where LLM adds value vs not
| Tool call | LLM wrapper value? |
|---|---|
| `stp_validate_10g` | Low — structured output already useful |
| `stp_path_cost_audit` | Low |
| `stp_preflight_simulate_add` | Low on its own; **high** when LLM composes with hygiene + PoE |
| Triage of N findings across M tools | **High** — LLM synthesises runbook |
| `stp_apply` | **Zero** — deterministic, reversible, human-gated |
| "Should I add LAG between the two Flex XG?" | **Medium-high** — LLM considers hash mode + traffic matrix + VLAN list |
| "Summarise weekly health" | **High** — LLM narrative from bundle |

---

## 15. Cross-cutting items

### Config file
`~/.config/unifi_network_mapper/unifi_mapper.yaml` (new) — holds thresholds,
overrides, intent location, state dir. Documented in README.

### Pre-commit / CI
- Add pyright to lint: `uv run pyright src tests`
- `uv run pytest --cov=unifi_mapper --cov-fail-under=80`
- GitHub Actions already present at `.github/workflows/` — extend

### Docs
- `docs/stp/` new directory:
  - `README.md` — decision tree: "when to run which tool"
  - `change-window-runbook.md` — standard ops runbook template
  - `capability-matrix.md` — model → class table
- Link from main README

### Out of scope (documented, deferred)
- MSTP/PVST+ automation (UniFi doesn't expose MST region config via API)
- Vendor-interop path-cost reconciliation with non-UniFi switches
- VXLAN/EVPN

---

## 16. Recommended execution order

| # | Phase | Days (est) | Blocks install? |
|---|---|---|---|
| 0 | Root-eligibility fix + tests | 0.5 | **Yes** |
| 1 | Plan file + safe apply + rollback | 1 | **Yes** (needed to apply priorities safely) |
| 2 | Port hygiene + path cost + TCN | 1 | **Yes** (path-cost audit must clear before install) |
| 3 | SFP / MTU / error heuristic | 0.5 | No (but reduces noise) |
| *install window* | — | — | — |
| 4 | LAG + VLAN + STP-mode + traffic | 1 | No |
| 5 | Snapshot/replay + baselines | 0.5 | No |
| 6 | Preflight simulation | 0.5 | No (ran before install; spec lands after) |
| 7 | PoE budget + firmware guardrail | 0.5 | No |
| 8 | Intent + drift | 0.5 | No |
| 9 | Weekly report | 0.5 | No |
| 10 | HA MQTT | 0.5 | No |
| 11 | MCP surface + agent adapters | 1 | No |

Total: ~8 engineering days to full completion.
Install window can open after phase 2 exit criteria pass.

---

## 17. First actionable step

Implement **Phase 0** now:

1. Write `model_capabilities.py` + tests
2. Modify `stp_optimizer.py` tier algorithm + root guard
3. Add `stp_overrides.yaml` loader
4. Capture current live topology as test fixture
5. Run `uv run pytest -q` (expect green)
6. Rerun `uv run unifi-mapper stp validate-10g --planned-switches 2`
7. Confirm `Xray3 USW Flex XG 10G` = sole Tier 0
8. Commit with message:
   `fix(stp): capability-aware root election, refuse 4096 for access-class`

Phase 1 (plan/apply/rollback) follows immediately — required before any live
priority changes.
