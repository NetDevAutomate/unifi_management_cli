"""Tests for MTU consistency audit."""

from __future__ import annotations

from unifi_mapper.analysis.mtu_audit import audit_mtu_consistency_from_data


def test_flags_inter_switch_mtu_mismatch() -> None:
    """Inter-switch endpoints should agree on MTU."""
    devices = [
        {
            '_id': 'a',
            'name': 'Switch A',
            'mac': 'aa:aa:aa:aa:aa:aa',
            'type': 'usw',
            'port_table': [{'port_idx': 1, 'up': True, 'speed': 10000, 'mtu': 9000}],
            'lldp_table': [
                {'local_port_idx': 1, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '2'}
            ],
        },
        {
            '_id': 'b',
            'name': 'Switch B',
            'mac': 'bb:bb:bb:bb:bb:bb',
            'type': 'usw',
            'port_table': [{'port_idx': 2, 'up': True, 'speed': 10000, 'mtu': 1500}],
        },
    ]

    report = audit_mtu_consistency_from_data(devices)

    assert report.findings_count == 1
    assert report.findings[0].severity == 'WARNING'
    assert report.findings[0].category == 'MTU Mismatch'


def test_matching_mtu_passes() -> None:
    """Matching MTU on both endpoints produces no findings."""
    devices = [
        {
            '_id': 'a',
            'name': 'Switch A',
            'mac': 'aa:aa:aa:aa:aa:aa',
            'type': 'usw',
            'port_table': [{'port_idx': 1, 'up': True, 'speed': 10000, 'mtu': 9000}],
            'lldp_table': [
                {'local_port_idx': 1, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '2'}
            ],
        },
        {
            '_id': 'b',
            'name': 'Switch B',
            'mac': 'bb:bb:bb:bb:bb:bb',
            'type': 'usw',
            'port_table': [{'port_idx': 2, 'up': True, 'speed': 10000, 'mtu': 9000}],
        },
    ]

    report = audit_mtu_consistency_from_data(devices)

    assert report.validation_passed is True
    assert report.findings == []
