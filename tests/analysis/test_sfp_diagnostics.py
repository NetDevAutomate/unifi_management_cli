"""Tests for SFP diagnostics."""

from __future__ import annotations

from unifi_mapper.analysis.sfp_diagnostics import audit_sfp_diagnostics_from_data


def test_sfp_diagnostics_extracts_dom_reading() -> None:
    """SFP diagnostics should extract module identity and DOM values."""
    report = audit_sfp_diagnostics_from_data(
        [
            {
                'name': 'Core',
                'port_table': [
                    {
                        'port_idx': 10,
                        'name': 'Uplink',
                        'media': 'SFP+',
                        'speed': 10000,
                        'sfp_found': True,
                        'sfp_vendor': 'OEM',
                        'sfp_part': 'SFP-10G-SR',
                        'sfp_serial': 'ABC123',
                        'sfp_temperature': 42.5,
                        'sfp_txpower': -2.5,
                        'sfp_rxpower': -4.0,
                        'sfp_rx_los': False,
                        'sfp_tx_fault': False,
                    }
                ],
            }
        ]
    )

    assert report.modules_found == 1
    assert report.diagnostics_available is True
    assert report.modules[0].vendor == 'OEM'
    assert report.modules[0].rx_power_dbm == -4.0
    assert report.findings == []


def test_sfp_diagnostics_flags_weak_rx_power_and_faults() -> None:
    """Weak receive power and fault flags should produce findings."""
    report = audit_sfp_diagnostics_from_data(
        [
            {
                'name': 'Core',
                'port_table': [
                    {
                        'port_idx': 11,
                        'media': 'SFP+',
                        'sfp_found': True,
                        'sfp_vendor': 'OEM',
                        'sfp_rxpower': -12.0,
                        'sfp_rx_los': True,
                        'sfp_tx_fault': True,
                    }
                ],
            }
        ]
    )

    categories = {finding.category for finding in report.findings}

    assert report.findings_count == 3
    assert {'Optical Signal', 'Transceiver Fault', 'Optical Power'} <= categories
