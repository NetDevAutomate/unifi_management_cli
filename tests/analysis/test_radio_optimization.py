"""Tests for wireless radio optimisation analysis."""

from __future__ import annotations

from unifi_mapper.analysis.radio_optimization import analyze_radio_optimization_from_data


def test_flags_same_channel_nearby_aps() -> None:
    """Nearby APs on the same band/channel should be flagged."""
    devices = [
        {
            '_id': 'ap1',
            'name': 'Hall AP',
            'type': 'uap',
            'radio_table': [{'name': 'ng', 'channel': 36, 'tx_power_mode': 'high'}],
        },
        {
            '_id': 'ap2',
            'name': 'Office AP',
            'type': 'uap',
            'radio_table': [{'name': 'ng', 'channel': 36, 'tx_power_mode': 'high'}],
        },
    ]

    report = analyze_radio_optimization_from_data(devices)

    assert report.findings_count == 1
    assert report.findings[0].category == 'Channel Reuse'
    assert report.findings[0].severity == 'WARNING'


def test_flags_high_power_with_many_clients() -> None:
    """High power on APs with many clients is a review finding."""
    devices = [
        {
            '_id': 'ap1',
            'name': 'Hall AP',
            'type': 'uap',
            'radio_table': [{'name': 'na', 'channel': 44, 'tx_power_mode': 'high'}],
            'num_sta': 42,
        }
    ]

    report = analyze_radio_optimization_from_data(devices)

    assert any(f.category == 'Transmit Power' for f in report.findings)
