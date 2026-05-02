"""Tests for inter-VLAN endpoint routing checks."""

from __future__ import annotations

from unifi_mapper.connectivity.inter_vlan import check_inter_vlan_routing_from_data


NETWORKS = [
    {'_id': 'net10', 'name': 'Users', 'vlan': 10, 'ip_subnet': '198.51.100.0/24'},
    {'_id': 'net20', 'name': 'Cameras', 'vlan': 20, 'ip_subnet': '203.0.113.0/24'},
]


def test_same_vlan_endpoint_check_allows_without_routing() -> None:
    """Same-VLAN endpoint checks do not require inter-VLAN routing."""
    report = check_inter_vlan_routing_from_data(
        source='198.51.100.10',
        destination='198.51.100.20',
        clients=[
            {'ip': '198.51.100.10', 'mac': 'aa:aa:aa:aa:aa:10', 'vlan': 10, 'hostname': 'laptop'},
            {'ip': '198.51.100.20', 'mac': 'aa:aa:aa:aa:aa:20', 'vlan': 10, 'hostname': 'printer'},
        ],
        devices=[],
        networks=NETWORKS,
        firewall_rules=[],
    )

    assert report.route_required is False
    assert report.verdict == 'allow'
    assert report.source_vlan == 10
    assert report.destination_vlan == 10


def test_inter_vlan_drop_rule_denies_endpoint_routing() -> None:
    """First matching enabled LAN rule determines an inter-VLAN deny."""
    report = check_inter_vlan_routing_from_data(
        source='laptop',
        destination='camera',
        clients=[
            {'ip': '198.51.100.10', 'mac': 'aa:aa:aa:aa:aa:10', 'vlan': 10, 'hostname': 'laptop'},
            {'ip': '203.0.113.50', 'mac': 'bb:bb:bb:bb:bb:50', 'vlan': 20, 'hostname': 'camera'},
        ],
        devices=[],
        networks=NETWORKS,
        firewall_rules=[
            {
                '_id': 'rule1',
                'name': 'Block users to cameras',
                'enabled': True,
                'action': 'drop',
                'rule_index': 100,
                'ruleset': 'LAN_IN',
                'src_networkconf_id': 'net10',
                'dst_networkconf_id': 'net20',
                'protocol': 'all',
            }
        ],
    )

    assert report.route_required is True
    assert report.verdict == 'deny'
    assert report.blocking_rule == 'Block users to cameras'
    assert report.matching_rules == ['Block users to cameras']


def test_inter_vlan_allow_rule_allows_specific_protocol() -> None:
    """Protocol-specific allow rules can authorize inter-VLAN checks."""
    report = check_inter_vlan_routing_from_data(
        source='198.51.100.10',
        destination='203.0.113.50',
        protocol='tcp',
        port='443',
        clients=[
            {'ip': '198.51.100.10', 'mac': 'aa:aa:aa:aa:aa:10', 'vlan': 10},
            {'ip': '203.0.113.50', 'mac': 'bb:bb:bb:bb:bb:50', 'vlan': 20},
        ],
        devices=[],
        networks=NETWORKS,
        firewall_rules=[
            {
                '_id': 'rule1',
                'name': 'Allow users to camera UI',
                'enabled': True,
                'action': 'accept',
                'rule_index': 10,
                'ruleset': 'LAN_IN',
                'src_networkconf_id': 'net10',
                'dst_networkconf_id': 'net20',
                'protocol': 'tcp',
                'dst_port': '443',
            }
        ],
    )

    assert report.verdict == 'allow'
    assert report.matching_rules == ['Allow users to camera UI']


def test_unresolved_endpoint_returns_unknown_verdict() -> None:
    """Missing endpoints should return an unknown verdict with a recommendation."""
    report = check_inter_vlan_routing_from_data(
        source='missing',
        destination='203.0.113.50',
        clients=[{'ip': '203.0.113.50', 'mac': 'bb:bb:bb:bb:bb:50', 'vlan': 20}],
        devices=[],
        networks=NETWORKS,
        firewall_rules=[],
    )

    assert report.verdict == 'unknown'
    assert report.validation_passed is False
    assert any('source endpoint' in recommendation.lower() for recommendation in report.recommendations)
