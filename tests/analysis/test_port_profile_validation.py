"""Tests for UniFi port profile validation."""

from __future__ import annotations

from unifi_mapper.analysis.port_profile_validation import validate_port_profiles_from_data


def test_client_only_port_without_edge_is_warning() -> None:
    """Client-only access ports should use STP edge."""
    report = validate_port_profiles_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Switch',
                'port_table': [
                    {
                        'port_idx': 1,
                        'name': 'Client Port',
                        'up': True,
                        'is_uplink': False,
                        'portconf_id': 'profile1',
                    }
                ],
                'lldp_table': [],
            }
        ],
        port_profiles=[
            {
                '_id': 'profile1',
                'name': 'Access',
                'stp_edge': False,
                'bpdu_guard': True,
            }
        ],
    )

    assert report.findings_count == 1
    finding = report.findings[0]
    assert finding.severity == 'WARNING'
    assert finding.category == 'STP Edge'
    assert finding.device_name == 'Switch'
    assert finding.port_idx == 1


def test_edge_port_receiving_bpdu_is_critical() -> None:
    """Edge ports receiving BPDUs indicate a loop or infrastructure device."""
    report = validate_port_profiles_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Switch',
                'port_table': [
                    {
                        'port_idx': 2,
                        'name': 'Unexpected Switch',
                        'up': True,
                        'portconf_id': 'profile1',
                        'bpdu_detected': True,
                    }
                ],
            }
        ],
        port_profiles=[
            {
                '_id': 'profile1',
                'name': 'Edge With Guard',
                'stp_edge': True,
                'bpdu_guard': True,
            }
        ],
    )

    assert report.validation_passed is False
    assert any(f.severity == 'CRITICAL' and f.category == 'BPDU Guard' for f in report.findings)


def test_uplink_port_set_to_edge_is_warning() -> None:
    """Infrastructure uplinks should not use STP edge."""
    report = validate_port_profiles_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Switch',
                'port_table': [
                    {
                        'port_idx': 10,
                        'name': 'Uplink',
                        'up': True,
                        'is_uplink': True,
                        'portconf_id': 'profile1',
                    }
                ],
                'lldp_table': [{'local_port_idx': 10, 'chassis_id': 'aa:bb:cc:dd:ee:ff'}],
            }
        ],
        port_profiles=[
            {
                '_id': 'profile1',
                'name': 'Accidental Edge',
                'stp_edge': True,
                'bpdu_guard': False,
            }
        ],
    )

    assert any(f.category == 'Uplink Edge' and f.severity == 'WARNING' for f in report.findings)


def test_unknown_profile_is_info() -> None:
    """Missing profile data should be informational, not a false failure."""
    report = validate_port_profiles_from_data(
        devices=[
            {
                '_id': 'switch1',
                'name': 'Switch',
                'port_table': [
                    {
                        'port_idx': 1,
                        'name': 'Client Port',
                        'up': True,
                        'portconf_id': 'missing',
                    }
                ],
            }
        ],
        port_profiles=[],
    )

    assert report.validation_passed is True
    assert report.findings[0].severity == 'INFO'
    assert report.findings[0].category == 'Port Profile'
