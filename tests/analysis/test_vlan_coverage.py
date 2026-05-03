"""Tests for VLAN coverage audit."""

from __future__ import annotations

from unifi_mapper.analysis.vlan_coverage import audit_vlan_coverage_from_data


def test_trunk_carrying_all_required_vlans_passes() -> None:
    """A trunk with every required VLAN should produce no findings."""
    report = audit_vlan_coverage_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Aggregation',
                'type': 'usw',
                'port_table': [
                    {
                        'port_idx': 1,
                        'name': 'Trunk to Core',
                        'up': True,
                        'is_trunk': True,
                        'allowed_vlans': [10, 20, 30],
                    }
                ],
            }
        ],
        required_vlans=[10, 20, 30],
    )

    assert report.validation_passed is True
    assert report.ports_analyzed == 1
    assert report.findings == []


def test_planned_flex_xg_uplink_missing_vlan_is_critical() -> None:
    """A planned Flex XG uplink missing required VLAN coverage is critical."""
    report = audit_vlan_coverage_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Office Switch',
                'type': 'usw',
                'port_table': [
                    {
                        'port_idx': 10,
                        'name': 'Planned Studio Flex XG uplink',
                        'up': True,
                        'is_trunk': True,
                        'allowed_vlans': '10,20',
                    }
                ],
            }
        ],
        required_vlans=[10, 20, 30],
        planned_uplinks=[{'name': 'Studio Flex XG', 'model': 'USW-Flex-XG'}],
    )

    assert report.validation_passed is False
    assert report.findings_count == 1
    finding = report.findings[0]
    assert finding.severity == 'CRITICAL'
    assert finding.device == 'Office Switch'
    assert finding.port == 10
    assert finding.missing_vlans == [30]
    assert '30' in finding.message


def test_non_flex_trunk_missing_vlan_is_warning() -> None:
    """Existing non-Flex trunks missing required VLANs should warn."""
    report = audit_vlan_coverage_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Office Switch',
                'type': 'usw',
                'port_table': [
                    {
                        'port_idx': 2,
                        'name': 'Trunk to Workshop',
                        'up': True,
                        'is_trunk': True,
                        'allowed_vlans': '10-20',
                    }
                ],
            }
        ],
        required_vlans=[10, 20, 30],
    )

    assert report.validation_passed is True
    assert report.findings_count == 1
    assert report.findings[0].severity == 'WARNING'
    assert report.findings[0].missing_vlans == [30]


def test_access_client_ports_are_ignored() -> None:
    """Client/access ports should not be audited for trunk VLAN coverage."""
    report = audit_vlan_coverage_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Access Switch',
                'type': 'usw',
                'port_table': [
                    {
                        'port_idx': 3,
                        'name': 'Laptop',
                        'up': True,
                        'is_access': True,
                        'vlan': 10,
                    }
                ],
            }
        ],
        required_vlans=[10, 20, 30],
    )

    assert report.validation_passed is True
    assert report.ports_analyzed == 0
    assert report.findings == []
