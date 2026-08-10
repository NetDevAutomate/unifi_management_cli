"""Device INPUT power-budget audit for UniFi switches.

Distinct from `poe_budget`, which audits PoE **output** (how much a switch supplies to
powered devices). This module audits the **input** side: whether the switch's own power
source can run its active PHYs.

Motivating incident (2026-07-29/30): a `USW-Flex-2.5G-8` (USWED36) on its stock
5V/3A = **15W** adapter rebooted whenever a 5th port went active. Estimated load at that
point was ~13-15W against a 15W ceiling. Refitting with a PoE+ injector (~25.5W) made
7 active ports stable indefinitely. Nothing in the toolkit looked at input power, so the
fault survived several factory resets and a full firmware campaign before being found.

HONESTY BOUNDARIES -- read before extending:

* `MODEL_POWER` contains only figures traceable to a published Ubiquiti spec, with the
  quoted wording recorded in `source`. An unlisted model yields NO ceiling and appears in
  `report.unknown_models`. Do not invent wattages.
* `PHY_WATT_ESTIMATES` are *heuristics*, not vendor data. They are deliberately exposed as
  a module constant and overridable per call so callers can see and change them. Treat the
  output as "how close to the ceiling are we, roughly", never as a measurement.
* The controller does **not** report which power source is in use (there is no reliable
  `power_source` field on these models), so this audit cannot know whether a given switch
  is on DC or PoE. Findings are therefore phrased conditionally: "if DC-powered".
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any, cast
from unifi_mapper.core.utils.client import UniFiClient


# Heuristic per-PHY draw in watts. NOT vendor figures -- see HONESTY BOUNDARIES above.
# Ordering reflects the real finding that 10GBASE-T copper costs far more than SFP+.
PHY_WATT_ESTIMATES: dict[Any, float] = {
    100: 0.3,
    1000: 0.6,
    2500: 1.3,
    5000: 1.8,
    '10GE': 3.0,  # 10GBASE-T copper PHY
    10000: 3.0,  # speed-only fallback when media is unknown
    'SFP+': 1.0,  # optical / DAC
    'SFP': 0.8,
}

# Heuristic base draw (ASIC + CPU + fabric) for a compact multi-gig switch.
DEFAULT_BASE_WATTS = 7.0


class ModelPower(BaseModel):
    """Published power figures for one model. Every citable field records its wording.

    IMPORTANT SEMANTIC DISTINCTION:
    * `dc_supply_watts` is what the SUPPLY can deliver -- the only valid ceiling to judge a
      load against.
    * `max_consumption_watts` is what the DEVICE draws in total. It is NOT a budget. If an
      estimate exceeds it, the estimate is wrong, not the switch. Used only as a sanity
      bound on our own heuristics.
    * `base_watts` is a per-model base-load estimate; a 5-port unit must not inherit an
      8-port unit's assumption.
    """

    dc_supply_watts: float | None = None
    poe_input_watts: float | None = None
    max_consumption_watts: float | None = None
    base_watts: float = DEFAULT_BASE_WATTS
    source: str = ''


# Only models whose figures were read from a published Ubiquiti spec.
MODEL_POWER: dict[str, ModelPower] = {
    'USWED36': ModelPower(
        dc_supply_watts=15.0,  # "AC power adapter, 5V DC, 3A"
        poe_input_watts=25.5,  # "(1) PoE+"  -> 802.3at delivered
        base_watts=7.0,
        source='UniFi Flex 2.5G tech specs: power method "(1) AC power adapter, 5V DC, 3A", "(1) PoE+"',
    ),
    'USFXG': ModelPower(
        dc_supply_watts=25.0,  # "USB Type-C, 5V DC, 5A"
        poe_input_watts=25.5,  # "(1) PoE+"
        max_consumption_watts=25.0,
        base_watts=7.0,
        source='UniFi Flex 10 GbE tech specs: max power consumption 25W; power method "(1) PoE+", "(1) USB Type-C, 5V DC, 5A"',
    ),
    'USWED35': ModelPower(
        max_consumption_watts=6.4,  # "5W (AC/DC input) / 6.4W (PoE input)"
        poe_input_watts=6.4,
        # Whole device draws <=5W (AC/DC), so base must be small. 5 x 2.5G PHYs at ~1.3W
        # could not fit under 5W with a 7W base -- the 8-port assumption is invalid here.
        base_watts=2.5,
        source='UniFi Flex Mini 2.5G tech specs: max power consumption "5W (AC/DC input) 6.4W (PoE input)"',
    ),
    'USWED37': ModelPower(
        max_consumption_watts=17.0,  # excluding PoE output
        poe_input_watts=14.0,
        base_watts=7.0,
        source='UniFi Flex 2.5G PoE tech specs: "17W (Excluding PoE output) with AC adapter input", "PoE input: 14W"',
    ),
}

_NON_SWITCH_TYPES = ('uap', 'udm', 'udmpro', 'ugw', 'uxg', 'ubb', 'uph', 'uck')


class PowerBudgetFinding(BaseModel):
    """A switch whose estimated PHY load sits close to its published supply ceiling."""

    severity: str = Field(description='WARNING or CRITICAL')
    device: str
    device_mac: str = ''
    model: str = ''
    active_ports: int = 0
    port_detail: list[str] = Field(default_factory=lambda: [])
    estimated_load_watts: float = 0.0
    base_watts: float = DEFAULT_BASE_WATTS
    dc_supply_watts: float | None = None
    poe_input_watts: float | None = None
    poe_input_supported: bool = False
    dc_utilisation_pct: float | None = None
    spec_source: str = ''
    message: str
    recommendation: str


class PowerBudgetReport(BaseModel):
    """Input power-budget audit report."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    devices_analyzed: int = 0
    skipped_not_informing: int = 0
    unknown_models: list[str] = Field(default_factory=lambda: [])
    models_without_supply_rating: list[str] = Field(
        default_factory=lambda: [],
        description=(
            'Models with power data but no published SUPPLY rating. Not judged, because only '
            'a supply figure can be a ceiling.'
        ),
    )
    warn_pct: float = 80.0
    findings_count: int = 0
    validation_passed: bool = True
    findings: list[PowerBudgetFinding] = Field(default_factory=lambda: [])
    estimate_caveat: str = (
        'Per-PHY wattages are heuristics, not vendor measurements, and the controller does '
        'not report which power source is active. Treat utilisation as approximate and '
        'verify the physical power source before acting.'
    )


def estimate_port_load_watts(
    ports: list[dict[str, Any]],
    base_watts: float = DEFAULT_BASE_WATTS,
    phy_watts: dict[Any, float] | None = None,
) -> float:
    """Estimate total draw: base load plus one PHY estimate per ACTIVE port."""
    table = phy_watts or PHY_WATT_ESTIMATES
    total = base_watts
    for port in ports:
        if not port.get('up'):
            continue
        total += _phy_watts(port, table)
    return total


def _phy_watts(port: dict[str, Any], table: dict[Any, float]) -> float:
    """Media takes precedence over speed: SFP+ at 10G is far cheaper than 10GBASE-T."""
    media = str(port.get('media') or '')
    if media in table:
        return table[media]
    speed = port.get('speed')
    if speed in table:
        return cast(float, table[speed])
    return 1.0


async def audit_power_budget(
    warn_pct: float = 80.0,
    base_watts: float | None = None,
) -> PowerBudgetReport:
    """Fetch devices and audit each switch's input power headroom."""
    async with UniFiClient() as client:
        devices = await client.get_devices()
    return audit_power_budget_from_data(devices, warn_pct=warn_pct, base_watts=base_watts)


def audit_power_budget_from_data(
    devices: list[dict[str, Any]],
    warn_pct: float = 80.0,
    base_watts: float | None = None,
    phy_watts: dict[Any, float] | None = None,
) -> PowerBudgetReport:
    """Audit input power headroom from already-fetched UniFi device dictionaries."""
    findings: list[PowerBudgetFinding] = []
    analyzed = 0
    skipped_stale = 0
    unknown: list[str] = []
    no_supply: list[str] = []

    for device in devices:
        if str(device.get('type') or '').lower() in _NON_SWITCH_TYPES:
            continue
        ports = _port_table(device)
        if not ports:
            continue

        if device.get('state') is not None and int(device.get('state') or 0) != 1:
            skipped_stale += 1
            continue

        analyzed += 1
        model = str(device.get('model') or '')
        spec = MODEL_POWER.get(model)
        if spec is None:
            if model and model not in unknown:
                unknown.append(model)
            continue

        active = [p for p in ports if p.get('up')]
        effective_base = spec.base_watts if base_watts is None else base_watts
        load = estimate_port_load_watts(ports, base_watts=effective_base, phy_watts=phy_watts)

        # ONLY a published supply rating is a valid ceiling. `max_consumption_watts`
        # describes the device's own draw and must never be used as a budget.
        ceiling = spec.dc_supply_watts
        if not ceiling:
            if model not in no_supply:
                no_supply.append(model)
            continue

        pct = 100.0 * load / ceiling
        if pct < warn_pct:
            continue

        finding = _build_finding(
            device=device,
            model=model,
            spec=spec,
            active=active,
            load=load,
            base_watts=effective_base,
            ceiling=ceiling,
            pct=pct,
            phy_watts=phy_watts or PHY_WATT_ESTIMATES,
        )
        findings.append(finding)

    return PowerBudgetReport(
        devices_analyzed=analyzed,
        skipped_not_informing=skipped_stale,
        unknown_models=unknown,
        models_without_supply_rating=no_supply,
        warn_pct=warn_pct,
        findings_count=len(findings),
        validation_passed=not any(f.severity == 'CRITICAL' for f in findings),
        findings=findings,
    )


def _build_finding(
    *,
    device: dict[str, Any],
    model: str,
    spec: ModelPower,
    active: list[dict[str, Any]],
    load: float,
    base_watts: float,
    ceiling: float,
    pct: float,
    phy_watts: dict[Any, float],
) -> PowerBudgetFinding:
    name = str(device.get('name') or device.get('mac') or 'Unknown')
    poe_supported = spec.poe_input_watts is not None
    poe_better = (
        poe_supported
        and spec.dc_supply_watts is not None
        and (cast(float, spec.poe_input_watts) > spec.dc_supply_watts)
    )
    severity = 'CRITICAL' if pct >= 90.0 else 'WARNING'

    detail = [
        f'p{p.get("port_idx")}={p.get("speed")}/{p.get("media")}(~{_phy_watts(p, phy_watts)}W)'
        for p in active
    ]

    message = (
        f'{name} ({model}) has {len(active)} active port(s) with an estimated draw of '
        f'~{load:.1f}W (base ~{base_watts:.0f}W + PHYs), which is ~{pct:.0f}% of its '
        f'published {ceiling:.1f}W supply ceiling. If this switch is running on its DC '
        f'adapter, it is at or beyond its power budget: activating a further port can '
        f'brown it out and cause a reboot loop.'
    )
    if poe_better:
        message += (
            f' This model also accepts PoE+ input (~{spec.poe_input_watts:.1f}W), which is '
            f'{cast(float, spec.poe_input_watts) - cast(float, spec.dc_supply_watts):.1f}W more headroom.'
        )

    if poe_better:
        recommendation = (
            'Power this switch from PoE+ instead of its DC adapter (a UniFi PoE+ injector or '
            'a PoE+ switch port). Where the model has a 10G RJ45 / SFP+ combo pair, feed PoE '
            'into the RJ45 and run data over SFP+ - that is both the vendor-recommended '
            'arrangement and the lowest-power one.'
        )
    elif poe_supported:
        recommendation = (
            'Reduce active port count or link speeds, or verify the power source is healthy. '
            'PoE+ input is supported but offers no additional headroom on this model.'
        )
    else:
        recommendation = (
            'Reduce active port count or negotiated link speeds. No higher-capacity input '
            'method is published for this model.'
        )

    return PowerBudgetFinding(
        severity=severity,
        device=name,
        device_mac=str(device.get('mac') or ''),
        model=model,
        active_ports=len(active),
        port_detail=detail,
        estimated_load_watts=round(load, 2),
        base_watts=base_watts,
        dc_supply_watts=spec.dc_supply_watts,
        poe_input_watts=spec.poe_input_watts,
        poe_input_supported=poe_supported,
        dc_utilisation_pct=round(pct, 1),
        spec_source=spec.source,
        message=message,
        recommendation=recommendation,
    )


def _port_table(device: dict[str, Any]) -> list[dict[str, Any]]:
    value = device.get('port_table')
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
