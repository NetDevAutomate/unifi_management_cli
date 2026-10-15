"""Issue 097: a profile-less port's own running `forward` is honoured, and by every analysis.

The port table row is the only source of a profile-less port's running VLAN mode, so a row
that says ``forward: 'all'`` with no profile and no override is a trunk carrying every VLAN
for ``diagnose vlans``, ``vlan-coverage`` and ``foreign-bridges`` alike. Under a profile the
profile wins and the row's copy is ignored: a live controller reports ``forward: 'all'`` on
rows under access profiles, which is why the row was dropped wholesale before (and why the
maintainer's three profile-less uplinks were reported as missing every VLAN).
"""

from __future__ import annotations

from typing import Any
from unifi_mapper.analysis.foreign_bridges import detect_foreign_bridges_from_data
from unifi_mapper.analysis.vlan_coverage import audit_vlan_coverage_from_data
from unifi_mapper.analysis.vlan_diagnostics import diagnose_vlans_from_data, running_vlan_settings


NET_10 = 'aaaaaaaaaaaaaaaaaaaaaaa1'
NET_20 = 'aaaaaaaaaaaaaaaaaaaaaaa2'
ACCESS = 'bbbbbbbbbbbbbbbbbbbbbbb1'
PROFILES: list[dict[str, Any]] = [
    {'_id': ACCESS, 'name': 'Desk', 'forward': 'native', 'tagged_vlan_mgmt': 'block_all'},
]
NETWORKS: list[dict[str, Any]] = [
    {'_id': NET_10, 'name': 'Ten', 'vlan': 10, 'purpose': 'corporate', 'enabled': True},
    {'_id': NET_20, 'name': 'Twenty', 'vlan': 20, 'purpose': 'corporate', 'enabled': True},
]
BRIDGE = '02:00:00:00:0b:01'


def _port(idx: int, **extra: Any) -> dict[str, Any]:
    return {
        'port_idx': idx,
        'name': f'Port {idx}',
        'up': True,
        'is_uplink': False,
        'forward': 'all',  # the live shape: most rows say so, whatever the profile
        'last_connection': {'mac': BRIDGE},
        **extra,
    }


def _switch() -> dict[str, Any]:
    """Port 1: access profile (its row still says forward all) -> access port.
    Port 2: no profile, no override, row forward all, no LLDP, not an uplink -> trunk.
    Port 3: no profile, override forward native -> access port (the override wins the row)."""
    return {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': '02:00:00:00:0a:01',
        'type': 'usw',
        'port_table': [_port(1, portconf_id=ACCESS), _port(2), _port(3)],
        'port_overrides': [{'port_idx': 3, 'forward': 'native', 'tagged_vlan_mgmt': 'block_all'}],
    }


def test_running_settings_come_from_the_row_only_when_no_profile_applies() -> None:
    row = {'port_idx': 2, 'forward': 'all', 'tagged_vlan_mgmt': 'auto', 'up': True}
    profile = {'forward': 'native', 'tagged_vlan_mgmt': 'block_all'}
    override = {'forward': 'customize', 'tagged_networkconf_ids': [NET_20]}

    assert running_vlan_settings(row, None, None) == {'forward': 'all', 'tagged_vlan_mgmt': 'auto'}
    assert running_vlan_settings(row, profile, None) == profile  # the row's copy is noise
    assert running_vlan_settings(row, profile, override) == {**profile, **override}
    # no profile but an override: the override's fields over the row's
    assert running_vlan_settings(row, None, override) == {
        'forward': 'customize',
        'tagged_vlan_mgmt': 'auto',
        'tagged_networkconf_ids': [NET_20],
    }


def test_every_analysis_calls_the_profile_less_forward_all_port_a_trunk() -> None:
    diagnosis = diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES)
    trunks = {p.port_idx for p in diagnosis.port_configs if p.is_trunk}
    assert trunks == {2}, (
        'the profile-less row is a trunk; the access profile and the override are not'
    )

    coverage = audit_vlan_coverage_from_data(
        [_switch()], required_vlans=[10, 20], port_profiles=PROFILES, networks=NETWORKS
    )
    assert coverage.ports_analyzed == 1  # port 2, audited as a trunk with no LLDP and no uplink
    assert coverage.findings == [], 'a forward-all trunk carries every VLAN; nothing is missing'

    clients = [{'mac': '00:00:5e:00:53:01', 'sw_mac': BRIDGE, 'is_wired': True}]
    bridges = detect_foreign_bridges_from_data([_switch()], clients, PROFILES)
    (bridge,) = [b for b in bridges.bridges if b.mac.lower() == BRIDGE]
    # attached to all three ports (same last_connection mac); only port 2 grants a trunk
    assert sorted(idx for _, idx in bridge.attached_to) == [1, 2, 3]
    assert bridge.trunk_ports == ['port table']


def test_a_profile_less_uplink_with_forward_all_is_not_reported_missing_every_vlan() -> None:
    """The maintainer's three standing findings: profile-less uplinks with forward all."""
    switch = _switch()
    switch['port_table'] = [_port(5, is_uplink=True)]
    switch['port_overrides'] = []
    coverage = audit_vlan_coverage_from_data(
        [switch], required_vlans=[10, 20], port_profiles=PROFILES, networks=NETWORKS
    )
    assert coverage.ports_analyzed == 1
    assert coverage.findings == []
