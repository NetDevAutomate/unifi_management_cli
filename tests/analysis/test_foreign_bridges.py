"""Tests for foreign (third-party) bridge detection.

Motivated by the 2026-07-29 incident: an eero mesh was wired into the UniFi L2 domain at
six points. One eero bridged `Flex8 p8` to `Flex 2.5G 5 p3` while a direct link also
existed, closing an L2 loop that RSTP could not break because eeros forward no BPDUs.
Four of those eero ports were on TRUNK profiles, so every VLAN was bridged across the
mesh. Nothing in the toolkit looked for wired third-party bridges.
"""

from __future__ import annotations

from unifi_mapper.analysis.foreign_bridges import detect_foreign_bridges_from_data


FLEX8 = '02:00:17:00:00:01'
FLEX5 = '02:00:19:00:00:01'
EERO = '02:00:11:00:00:01'
EERO2 = '02:00:13:00:00:01'

TRUNK = {
    '_id': 'prof-trunk',
    'name': 'Trunk VLAN 1 Home 1 Gbps',
    'forward': 'all',
    'tagged_vlan_mgmt': 'auto',
}
ACCESS = {
    '_id': 'prof-access',
    'name': 'Access Port VLAN 1 Home 1Gbps',
    'forward': 'native',
    'tagged_vlan_mgmt': 'block_all',
}


def _switch(mac: str, name: str, ports: list[dict]) -> dict:
    return {
        '_id': f'dev-{mac}',
        'mac': mac,
        'name': name,
        'type': 'usw',
        'state': 1,
        'port_table': ports,
    }


def _port(idx: int, profile: str, last_mac: str | None = None, name: str = '') -> dict:
    p = {'port_idx': idx, 'up': True, 'portconf_id': profile, 'name': name or f'Port {idx}'}
    if last_mac:
        p['last_connection'] = {'mac': last_mac}
    return p


def test_clean_network_has_no_foreign_bridges() -> None:
    """All clients attributed to adopted UniFi switches -> nothing to report."""
    devices = [_switch(FLEX8, 'Lounge Flex8', [_port(1, 'prof-access')])]
    clients = [{'mac': 'aa:bb:cc:00:00:01', 'sw_mac': FLEX8, 'sw_port': 1, 'ip': '203.0.113.10'}]

    report = detect_foreign_bridges_from_data(devices, clients, [ACCESS])

    assert report.bridges_found == 0
    assert report.findings == []
    assert report.validation_passed is True


def test_client_behind_non_adopted_mac_reveals_a_bridge() -> None:
    """A client whose sw_mac is not an adopted device means a foreign bridge."""
    devices = [_switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-access', last_mac=EERO)])]
    clients = [
        {
            'mac': EERO,
            'sw_mac': FLEX8,
            'sw_port': 8,
            'ip': '203.0.113.181',
            'oui': 'eero inc.',
            'hostname': 'eero',
        },
        {'mac': 'aa:bb:cc:00:00:02', 'sw_mac': EERO, 'sw_port': 1, 'ip': '203.0.113.50'},
    ]

    report = detect_foreign_bridges_from_data(devices, clients, [ACCESS])

    assert report.bridges_found == 1
    bridge = report.bridges[0]
    assert bridge.mac == EERO
    assert bridge.oui == 'eero inc.'
    assert bridge.downstream_clients == 1
    assert bridge.attached_to == [('Lounge Flex8', 8)]
    assert report.findings[0].severity == 'WARNING'


def test_foreign_bridge_on_trunk_port_is_critical() -> None:
    """Handing a full trunk to a third-party bridge exports every VLAN to its fabric."""
    devices = [_switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-trunk', last_mac=EERO)])]
    clients = [
        {'mac': EERO, 'sw_mac': FLEX8, 'sw_port': 8, 'oui': 'eero inc.'},
        {'mac': 'aa:bb:cc:00:00:02', 'sw_mac': EERO, 'sw_port': 1},
    ]

    report = detect_foreign_bridges_from_data(devices, clients, [TRUNK])

    assert report.validation_passed is False
    f = [x for x in report.findings if 'trunk' in x.message.lower()]
    assert f and f[0].severity == 'CRITICAL'
    assert 'Trunk VLAN 1 Home 1 Gbps' in f[0].message


def test_same_bridge_on_two_switch_ports_is_a_loop() -> None:
    """The decisive signal: one foreign bridge attached to two switches = L2 loop path."""
    devices = [
        _switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-trunk', last_mac=EERO)]),
        _switch(FLEX5, 'Lounge Flex 2.5G 5', [_port(3, 'prof-trunk', last_mac=EERO)]),
    ]
    clients = [
        {'mac': EERO, 'sw_mac': FLEX8, 'sw_port': 8, 'oui': 'eero inc.'},
        {'mac': 'aa:bb:cc:00:00:02', 'sw_mac': EERO, 'sw_port': 1},
    ]

    report = detect_foreign_bridges_from_data(devices, clients, [TRUNK])

    loop = [x for x in report.findings if x.loop_risk]
    assert loop, 'a bridge spanning two switches must be flagged as a loop risk'
    assert loop[0].severity == 'CRITICAL'
    assert report.validation_passed is False
    assert len(report.bridges[0].attached_to) == 2


def test_bridge_behind_bridge_is_reported() -> None:
    """A foreign bridge whose sw_mac is another foreign bridge proves transit bridging."""
    devices = [_switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-access', last_mac=EERO)])]
    clients = [
        {'mac': EERO, 'sw_mac': FLEX8, 'sw_port': 8, 'oui': 'eero inc.'},
        {'mac': EERO2, 'sw_mac': EERO, 'sw_port': 13, 'oui': 'eero inc.'},
        {'mac': 'aa:bb:cc:00:00:03', 'sw_mac': EERO2, 'sw_port': 1},
    ]

    report = detect_foreign_bridges_from_data(devices, clients, [ACCESS])

    macs = {b.mac for b in report.bridges}
    assert EERO in macs and EERO2 in macs
    nested = [b for b in report.bridges if b.behind_another_bridge]
    assert nested and nested[0].mac == EERO2


def test_adopted_switch_is_never_called_a_foreign_bridge() -> None:
    """Clients behind a legitimate UniFi switch must not be flagged."""
    devices = [
        _switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-trunk', last_mac=FLEX5)]),
        _switch(FLEX5, 'Lounge Flex 2.5G 5', [_port(1, 'prof-access')]),
    ]
    clients = [{'mac': 'aa:bb:cc:00:00:04', 'sw_mac': FLEX5, 'sw_port': 1}]

    report = detect_foreign_bridges_from_data(devices, clients, [TRUNK, ACCESS])

    assert report.bridges_found == 0


def test_bridge_location_unknown_is_still_reported() -> None:
    """A bridge we cannot locate on any port is still worth surfacing."""
    devices = [_switch(FLEX8, 'Lounge Flex8', [_port(1, 'prof-access')])]
    clients = [{'mac': 'aa:bb:cc:00:00:05', 'sw_mac': '11:22:33:44:55:66', 'sw_port': 2}]

    report = detect_foreign_bridges_from_data(devices, clients, [ACCESS])

    assert report.bridges_found == 1
    assert report.bridges[0].attached_to == []


def test_an_override_trunk_profile_is_the_one_judged() -> None:
    """Issue 026: the port table says access, but the override the switch runs is a trunk."""
    switch = _switch(FLEX8, 'Lounge Flex8', [_port(8, 'prof-access', last_mac=EERO)])
    switch['port_overrides'] = [{'port_idx': 8, 'portconf_id': 'prof-trunk'}]
    clients = [
        {'mac': EERO, 'sw_mac': FLEX8, 'sw_port': 8, 'oui': 'eero inc.'},
        {'mac': 'aa:bb:cc:00:00:02', 'sw_mac': EERO, 'sw_port': 1},
    ]

    report = detect_foreign_bridges_from_data([switch], clients, [ACCESS, TRUNK])

    assert report.bridges[0].trunk_ports == ['Trunk VLAN 1 Home 1 Gbps']
    trunk = [x for x in report.findings if 'trunk' in x.message.lower()]
    assert trunk and trunk[0].severity == 'CRITICAL'
    assert 'Trunk VLAN 1 Home 1 Gbps' in trunk[0].message
