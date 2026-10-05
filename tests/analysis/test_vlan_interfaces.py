"""Matching VLAN networks to the gateway's live interfaces by subnet (``vlan_interfaces``).

Ported from the July work's sampler tests (a local archive, not in the repo) with
documentation values. Pure: no controller, no SSH.
"""

from unifi_mapper.analysis.vlan_interfaces import resolve_vlan_interfaces


LIVE = [
    {'ifname': 'lo', 'addr_info': [{'local': '127.0.0.1'}]},
    {'ifname': 'br0', 'addr_info': [{'local': '192.0.2.1'}, {'local': '2001:db8::1'}]},
    {'ifname': 'br7', 'addr_info': [{'local': '198.51.100.1'}]},  # not br30: never by name
    {'ifname': 'eth9', 'addr_info': [{'local': 'not an address'}]},
    {'addr_info': [{'local': '203.0.113.1'}]},  # no ifname: ignored
]


def test_each_lan_network_maps_to_the_interface_holding_an_address_in_its_subnet() -> None:
    networks = [
        {'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
        {'name': 'IoT', 'purpose': 'guest', 'vlan': '30', 'ip_subnet': '198.51.100.1/24'},
    ]
    result = resolve_vlan_interfaces(networks, LIVE)
    assert result['resolved'] == [
        {'vlan_id': 1, 'network_name': 'LAN', 'iface': 'br0', 'subnet': '192.0.2.0/24'},
        {'vlan_id': 30, 'network_name': 'IoT', 'iface': 'br7', 'subnet': '198.51.100.0/24'},
    ]
    assert result['unresolved'] == []


def test_a_network_with_no_live_match_or_no_vlan_or_a_bad_subnet_is_unresolved() -> None:
    networks = [
        {'name': 'Lab', 'purpose': 'corporate', 'vlan': 40, 'ip_subnet': '203.0.113.1/24'},
        {'name': 'Odd', 'purpose': 'corporate', 'vlan': 'x', 'ip_subnet': '192.0.2.1/24'},
        {'purpose': 'corporate', 'vlan': 50, 'ip_subnet': 'not a subnet'},
    ]
    result = resolve_vlan_interfaces(networks, LIVE)
    assert result['resolved'] == []
    assert result['unresolved'] == [
        {'vlan_id': 40, 'network_name': 'Lab', 'subnet': '203.0.113.0/24'},
        {'vlan_id': None, 'network_name': 'Odd', 'subnet': '192.0.2.1/24'},
        {'vlan_id': 50, 'network_name': 'VLAN 50', 'subnet': 'not a subnet'},
    ]


def test_disabled_wan_vpn_and_subnetless_networks_are_out_of_scope() -> None:
    networks = [
        {'name': 'Off', 'purpose': 'corporate', 'enabled': False, 'ip_subnet': '192.0.2.1/24'},
        {'name': 'WAN', 'purpose': 'wan', 'ip_subnet': '198.51.100.1/24'},
        {'name': 'VPN', 'purpose': 'remote-user-vpn', 'ip_subnet': '203.0.113.1/24'},
        {'name': 'Bare', 'purpose': 'corporate'},
        {'name': 'Tagged', 'purpose': 'corporate', 'vlan_enabled': True, 'ip_subnet': ''},
    ]
    assert resolve_vlan_interfaces(networks, LIVE) == {'resolved': [], 'unresolved': []}


def test_an_untagged_vlan_enabled_network_without_a_vlan_id_is_unresolved() -> None:
    networks = [
        {
            'name': 'Tagged',
            'purpose': 'corporate',
            'vlan_enabled': True,
            'ip_subnet': '192.0.2.1/24',
        }
    ]
    result = resolve_vlan_interfaces(networks, LIVE)
    assert result['unresolved'] == [
        {'vlan_id': None, 'network_name': 'Tagged', 'subnet': '192.0.2.1/24'}
    ]
