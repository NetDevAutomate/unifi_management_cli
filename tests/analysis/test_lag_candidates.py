"""Tests for LAG candidate detection."""

from __future__ import annotations

from unifi_mapper.analysis.lag_monitoring import find_lag_candidates_from_data


def test_parallel_flex_xg_links_create_lag_candidate() -> None:
    """Two healthy same-speed links between the same switches should be a candidate."""
    devices = [
        {
            '_id': 'a',
            'name': 'Flex XG A',
            'mac': 'aa:aa:aa:aa:aa:aa',
            'type': 'usw',
            'port_table': [
                {'port_idx': 1, 'up': True, 'enabled': True, 'speed': 10000},
                {'port_idx': 2, 'up': True, 'enabled': True, 'speed': 10000},
            ],
            'lldp_table': [
                {'local_port_idx': 1, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '1'},
                {'local_port_idx': 2, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '2'},
            ],
        },
        {
            '_id': 'b',
            'name': 'Flex XG B',
            'mac': 'bb:bb:bb:bb:bb:bb',
            'type': 'usw',
            'port_table': [
                {'port_idx': 1, 'up': True, 'enabled': True, 'speed': 10000},
                {'port_idx': 2, 'up': True, 'enabled': True, 'speed': 10000},
            ],
        },
    ]

    report = find_lag_candidates_from_data(devices)

    assert report.candidate_count == 1
    candidate = report.candidates[0]
    assert candidate.device_a == 'Flex XG A'
    assert candidate.device_b == 'Flex XG B'
    assert candidate.device_a_ports == [1, 2]
    assert candidate.link_count == 2
    assert candidate.total_capacity_mbps == 20000


def test_existing_lag_ports_are_excluded() -> None:
    """Ports already in a configured aggregate are not candidates."""
    devices = [
        {
            '_id': 'a',
            'name': 'Switch A',
            'mac': 'aa:aa:aa:aa:aa:aa',
            'type': 'usw',
            'port_aggregates': [{'member_ports': [1, 2]}],
            'port_table': [
                {'port_idx': 1, 'up': True, 'enabled': True, 'speed': 10000},
                {'port_idx': 2, 'up': True, 'enabled': True, 'speed': 10000},
            ],
            'lldp_table': [
                {'local_port_idx': 1, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '1'},
                {'local_port_idx': 2, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '2'},
            ],
        },
        {'_id': 'b', 'name': 'Switch B', 'mac': 'bb:bb:bb:bb:bb:bb', 'type': 'usw'},
    ]

    report = find_lag_candidates_from_data(devices)

    assert report.candidate_count == 0


def test_reciprocal_lldp_entries_are_not_counted_as_parallel_links() -> None:
    """A single physical link reported by both ends should not become a candidate."""
    devices = [
        {
            '_id': 'a',
            'name': 'Switch A',
            'mac': 'aa:aa:aa:aa:aa:aa',
            'type': 'usw',
            'port_table': [{'port_idx': 1, 'up': True, 'enabled': True, 'speed': 10000}],
            'lldp_table': [
                {'local_port_idx': 1, 'chassis_id': 'bb:bb:bb:bb:bb:bb', 'port_id': '2'},
            ],
        },
        {
            '_id': 'b',
            'name': 'Switch B',
            'mac': 'bb:bb:bb:bb:bb:bb',
            'type': 'usw',
            'port_table': [{'port_idx': 2, 'up': True, 'enabled': True, 'speed': 10000}],
            'lldp_table': [
                {'local_port_idx': 2, 'chassis_id': 'aa:aa:aa:aa:aa:aa', 'port_id': '1'},
            ],
        },
    ]

    report = find_lag_candidates_from_data(devices)

    assert report.candidate_count == 0
