"""Tests for the device input-power-budget audit.

Motivated by the 2026-07-29/30 incident: a USW-Flex-2.5G-8 (USWED36) on its stock
5V/3A (15W) adapter rebooted whenever a 5th port went active. Estimated load at that
point was ~13-15W against a 15W ceiling. Nothing in the toolkit looked at INPUT power
(`poe_budget` covers PoE *output*), so the fault took a day and a half to find.
"""

from __future__ import annotations

from unifi_mapper.analysis.power_budget import (
    PHY_WATT_ESTIMATES,
    audit_power_budget_from_data,
    estimate_port_load_watts,
)


def _switch(model: str, ports: list[tuple[int, int, str]], name: str = 'Test Switch') -> dict:
    """ports = list of (port_idx, speed, media)."""
    return {
        '_id': f'dev-{name}',
        'name': name,
        'mac': 'aa:bb:cc:dd:ee:ff',
        'model': model,
        'type': 'usw',
        'state': 1,
        'port_table': [
            {'port_idx': i, 'speed': spd, 'media': media, 'up': True}
            for i, spd, media in ports
        ],
    }


def test_max_consumption_is_never_treated_as_a_supply_ceiling() -> None:
    """A published 'max power consumption' figure is NOT a budget to compare a load against.

    Regression: the first live run flagged three USWED35 switches at 130-170% because
    `max_consumption_watts=6.4` (what the device draws in total) was used as a ceiling.
    Exceeding it means the load ESTIMATE is wrong, not that the switch is over budget.
    Only a published supply rating (`dc_supply_watts`) can be a ceiling.
    """
    dev = _switch('USWED35', [
        (1, 2500, '2P5GE'), (2, 1000, '2P5GE'), (5, 2500, '2P5GE'),
    ], name='Office Window USW Flex 2.5G 5')

    report = audit_power_budget_from_data([dev])

    assert report.findings == []
    assert report.validation_passed is True
    assert 'USWED35' in report.models_without_supply_rating


def test_per_model_base_watts_is_used_when_published() -> None:
    """A 5-port switch must not inherit an 8-port switch's base-load assumption."""
    from unifi_mapper.analysis.power_budget import MODEL_POWER

    assert MODEL_POWER['USWED35'].base_watts is not None
    assert MODEL_POWER['USWED35'].base_watts < MODEL_POWER['USWED36'].base_watts


def test_uswed36_at_incident_load_is_critical() -> None:
    """The exact failing configuration must be flagged against the 15W DC ceiling."""
    # p1 2500, p2 1000, p3 1000, p4 1000, p5 2500, p8 2500, p10 SFP+ -- the 7-port state
    dev = _switch('USWED36', [
        (1, 2500, '2P5GE'), (2, 1000, '2P5GE'), (3, 1000, '2P5GE'), (4, 1000, '2P5GE'),
        (5, 2500, '2P5GE'), (8, 2500, '2P5GE'), (10, 10000, 'SFP+'),
    ], name='Investigate  USW Flex 2.5G 8')

    report = audit_power_budget_from_data([dev])

    assert report.devices_analyzed == 1
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f.model == 'USWED36'
    assert f.dc_supply_watts == 15.0
    assert f.poe_input_supported is True
    assert f.active_ports == 7
    assert f.estimated_load_watts > 12.0
    assert f.dc_utilisation_pct is not None and f.dc_utilisation_pct > 80
    assert f.severity == 'CRITICAL'
    assert 'PoE' in f.recommendation


def test_uswed36_lightly_loaded_produces_no_finding() -> None:
    """Two active ports is comfortably inside the 15W ceiling."""
    dev = _switch('USWED36', [(1, 1000, '2P5GE'), (10, 10000, 'SFP+')])

    report = audit_power_budget_from_data([dev])

    assert report.findings == []
    assert report.validation_passed is True


def test_unknown_model_reports_load_but_asserts_no_ceiling() -> None:
    """An unlisted model must not have a wattage invented for it."""
    dev = _switch('NOT-A-REAL-MODEL', [(1, 2500, '2P5GE')] * 1)

    report = audit_power_budget_from_data([dev])

    assert report.devices_analyzed == 1
    assert report.findings == []
    assert report.unknown_models == ['NOT-A-REAL-MODEL']


def test_threshold_is_configurable() -> None:
    """A stricter threshold catches a moderate load."""
    dev = _switch('USWED36', [
        (1, 2500, '2P5GE'), (2, 2500, '2P5GE'), (10, 10000, 'SFP+'),
    ])

    lax = audit_power_budget_from_data([dev], warn_pct=80.0)
    strict = audit_power_budget_from_data([dev], warn_pct=50.0)

    assert lax.findings == []
    assert len(strict.findings) == 1
    assert strict.findings[0].severity == 'WARNING'


def test_load_estimate_uses_documented_constants() -> None:
    """Estimation is transparent: base + per-PHY, from a published constant table."""
    ports = [
        {'port_idx': 1, 'speed': 2500, 'media': '2P5GE', 'up': True},
        {'port_idx': 2, 'speed': 1000, 'media': '2P5GE', 'up': True},
        {'port_idx': 3, 'speed': 10000, 'media': 'SFP+', 'up': True},
        {'port_idx': 4, 'speed': 0, 'media': '2P5GE', 'up': False},  # ignored
    ]
    load = estimate_port_load_watts(ports, base_watts=7.0)

    expected = 7.0 + PHY_WATT_ESTIMATES[2500] + PHY_WATT_ESTIMATES[1000] + PHY_WATT_ESTIMATES['SFP+']
    assert abs(load - expected) < 0.001


def test_10gbase_t_costs_more_than_sfp_plus() -> None:
    """Encodes the real finding that moving 10G from RJ45 to SFP+ freed headroom."""
    assert PHY_WATT_ESTIMATES['10GE'] > PHY_WATT_ESTIMATES['SFP+']


def test_access_points_and_gateways_are_skipped() -> None:
    """Only switches have a port-count-driven PHY budget worth auditing."""
    ap = {'name': 'AP', 'model': 'U6PRO', 'type': 'uap', 'state': 1,
          'port_table': [{'port_idx': 1, 'speed': 1000, 'media': 'GE', 'up': True}]}
    gw = {'name': 'GW', 'model': 'UDMPROMAX', 'type': 'udmpro', 'state': 1,
          'port_table': [{'port_idx': 1, 'speed': 1000, 'media': 'GE', 'up': True}]}

    report = audit_power_budget_from_data([ap, gw])

    assert report.devices_analyzed == 0
    assert report.findings == []


def test_non_informing_device_is_skipped() -> None:
    """A stale device's port list is not evidence of current load."""
    dev = _switch('USWED36', [(i, 2500, '2P5GE') for i in range(1, 8)])
    dev['state'] = 0

    report = audit_power_budget_from_data([dev])

    assert report.findings == []
    assert report.skipped_not_informing == 1


def test_report_surfaces_poe_upgrade_path() -> None:
    """Where PoE-in is supported, the finding must say so with the higher budget."""
    dev = _switch('USWED36', [(i, 2500, '2P5GE') for i in range(1, 7)])

    report = audit_power_budget_from_data([dev])
    f = report.findings[0]

    assert f.poe_input_supported is True
    assert f.poe_input_watts is not None and f.poe_input_watts > f.dc_supply_watts
    assert 'PoE+' in f.recommendation
