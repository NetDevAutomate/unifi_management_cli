"""One trunk rule for every analysis (issue 089).

``vlan_diagnostics.is_trunk_profile``, ``foreign_bridges._is_trunk`` and
``vlan_coverage._is_trunk`` each decided trunk-ness with a different rule, so ``diagnose
vlans`` and ``analyze vlan-coverage`` could call the same port a trunk and an access port.
``is_trunk_profile`` is now the one rule and the other two call it. The first test feeds it
every shape the three accepted; the rest run the three reports over one live-shaped switch
(documentation values) and check that they agree.
"""

from __future__ import annotations

import pytest
from typing import Any
from unifi_mapper.analysis.foreign_bridges import detect_foreign_bridges_from_data
from unifi_mapper.analysis.vlan_coverage import audit_vlan_coverage_from_data
from unifi_mapper.analysis.vlan_diagnostics import diagnose_vlans_from_data, is_trunk_profile


NET_10 = 'aaaaaaaaaaaaaaaaaaaaaa10'
NET_20 = 'aaaaaaaaaaaaaaaaaaaaaa20'


@pytest.mark.parametrize(
    ('settings', 'trunk'),
    [
        # vlan_diagnostics: the controller's forward / tagged_vlan_mgmt, and the name
        ({'forward': 'all', 'tagged_vlan_mgmt': 'auto'}, True),
        ({'forward': 'all'}, True),
        ({'forward': 'all', 'tagged_vlan_mgmt': 'block_all'}, False),
        ({'forward': 'native', 'tagged_vlan_mgmt': 'block_all'}, False),
        (
            {
                'forward': 'customize',
                'tagged_vlan_mgmt': 'custom',
                'tagged_networkconf_ids': [NET_10],
            },
            True,
        ),
        ({'forward': 'customize', 'tagged_networkconf_ids': []}, False),
        ({'forward': 'native', 'name': 'Trunk to NVR'}, True),
        ({}, False),
        # vlan_diagnostics' caller also called a port that tags a network a trunk
        ({'forward': 'native', 'tagged_networkconf_ids': [NET_10]}, True),
        (
            {'forward': 'native', 'tagged_vlan_mgmt': 'block_all', 'voice_networkconf_id': NET_20},
            True,
        ),
        # block_all tags nothing, whatever ids linger (diagnose vlans lists no tagged VLAN)
        (
            {
                'forward': 'customize',
                'tagged_vlan_mgmt': 'block_all',
                'tagged_networkconf_ids': [NET_10],
            },
            False,
        ),
        # foreign_bridges: forward 'all' unless block_all (a live profile named for access)
        ({'forward': 'all', 'tagged_vlan_mgmt': 'auto', 'name': 'Access cameras'}, True),
        # vlan_coverage: hand-built records with explicit flags or VLAN lists
        ({'is_trunk': True, 'allowed_vlans': [10, 20, 30]}, True),
        ({'trunk': 'yes'}, True),
        ({'is_access': True, 'vlan': 10}, False),
        ({'access': 'true', 'tagged_vlans': [10]}, False),
        ({'name': 'Client laptop', 'vlan': 10}, False),
        ({'portconf_name': 'Access', 'allowed_vlans': '10-20'}, False),
        ({'name': 'Desk', 'allowed_vlans': '10,20'}, True),
        ({'profile_name': 'Core trunk'}, True),
        # with the controller's forward, a VLAN key alone makes no trunk
        ({'forward': 'native', 'native_vlan': 10}, False),
    ],
)
def test_one_rule_for_every_shape(settings: dict[str, Any], trunk: bool) -> None:
    assert is_trunk_profile(settings) is trunk


ACCESS = 'bbbbbbbbbbbbbbbbbbbbbbb1'
ALL = 'bbbbbbbbbbbbbbbbbbbbbbb2'
PROFILES: list[dict[str, Any]] = [
    {'_id': ACCESS, 'name': 'Desk', 'forward': 'native', 'tagged_vlan_mgmt': 'block_all'},
    # a live shape: forward 'all' under a name that says access
    {'_id': ALL, 'name': 'Access cameras', 'forward': 'all', 'tagged_vlan_mgmt': 'auto'},
]
NETWORKS: list[dict[str, Any]] = [
    {'_id': NET_10, 'name': 'Ten', 'vlan': 10, 'purpose': 'corporate', 'enabled': True},
    {'_id': NET_20, 'name': 'Twenty', 'vlan': 20, 'purpose': 'corporate', 'enabled': True},
]
BRIDGE = '02:00:00:00:0b:01'


def _port(idx: int, **extra: Any) -> dict[str, Any]:
    """A live-shaped port table row: the controller reports forward 'all' on most rows."""
    return {
        'port_idx': idx,
        'name': f'Port {idx}',
        'up': True,
        'is_uplink': False,
        'forward': 'all',
        'last_connection': {'mac': BRIDGE},
        **extra,
    }


def _switch() -> dict[str, Any]:
    """Port 1 an access profile (its row still says forward 'all'), port 2 the 'Access
    cameras' all-VLAN profile, port 3 no profile but an override with forward 'all', port 4 no
    profile and no override: its row's forward 'all' is its running config (issue 097)."""
    return {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': '02:00:00:00:0a:01',
        'type': 'usw',
        'port_table': [
            _port(1, portconf_id=ACCESS),
            _port(2, portconf_id=ALL),
            _port(3),
            _port(4),
        ],
        'port_overrides': [{'port_idx': 3, 'forward': 'all', 'name': 'Shed link'}],
    }


TRUNK_PORTS = {2, 3, 4}  # port 1's row says forward 'all' too, but its access profile wins


def test_diagnose_vlans_and_vlan_coverage_name_the_same_trunks() -> None:
    diagnosis = diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES)
    assert {p.port_idx for p in diagnosis.port_configs if p.is_trunk} == TRUNK_PORTS

    coverage = audit_vlan_coverage_from_data(
        [_switch()], required_vlans=[10, 20], port_profiles=PROFILES, networks=NETWORKS
    )
    # No LLDP and no uplink: a port is audited only because it is a trunk.
    assert coverage.ports_analyzed == len(TRUNK_PORTS)
    # Both trunks carry every VLAN, as diagnose vlans says; neither is reported missing one.
    assert coverage.findings == []


def test_foreign_bridges_names_the_same_trunks() -> None:
    clients = [{'mac': '00:00:5e:00:53:01', 'sw_mac': BRIDGE, 'is_wired': True}]
    report = detect_foreign_bridges_from_data([_switch()], clients, PROFILES)

    (bridge,) = report.bridges
    assert sorted(bridge.trunk_ports) == ['Access cameras', 'port override', 'port table']
