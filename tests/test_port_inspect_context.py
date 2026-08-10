"""Tests for the enriched port inspection context.

Covers VLAN/profile resolution, DHCP addressing verdicts, connected-device
identification for both UniFi and third-party hosts, and the serialisation
used by the MCP tool.
"""

from __future__ import annotations

from unifi_mapper.port_inspect import (
    ConnectedDevice,
    DhcpStatus,
    IdentityMatch,
    PortInspectionResult,
    PortProfile,
    _build_connected_device,
    _build_dhcp_status,
    _ip_in_range,
    _ip_to_int,
    _resolve_network,
    _resolve_profile,
    _strip_markup,
)


NAS_ID = 'net-nas'
HOME_ID = 'net-home'
MGMT_ID = 'net-mgmt'

NETWORKS = {
    NAS_ID: {
        '_id': NAS_ID,
        'name': 'NAS',
        'vlan': 15,
        'ip_subnet': '192.0.2.254/24',
        'enabled': True,
        'dhcpd_enabled': True,
        'dhcpd_start': '192.0.2.6',
        'dhcpd_stop': '192.0.2.254',
        'dhcp_relay_enabled': False,
    },
    HOME_ID: {
        '_id': HOME_ID,
        'name': 'Home LAN',
        'vlan': None,
        'ip_subnet': '198.51.100.254/24',
        'enabled': True,
        'dhcpd_enabled': True,
        'dhcpd_start': '198.51.100.51',
        'dhcpd_stop': '198.51.100.250',
        'dhcp_relay_enabled': False,
    },
    MGMT_ID: {
        '_id': MGMT_ID,
        'name': 'Management',
        'vlan': 255,
        'ip_subnet': '203.0.113.254/24',
        'enabled': True,
        'dhcpd_enabled': True,
        'dhcpd_start': '203.0.113.100',
        'dhcpd_stop': '203.0.113.250',
    },
}


# ---------------------------------------------------------------------------
# IPv4 helpers
# ---------------------------------------------------------------------------


def test_ip_to_int_round_trip_and_ordering():
    """_ip_to_int produces comparable integers for dotted-quad addresses."""
    assert _ip_to_int('0.0.0.0') == 0
    assert _ip_to_int('255.255.255.255') == (1 << 32) - 1
    assert _ip_to_int('192.0.2.6') < _ip_to_int('192.0.2.254')


def test_ip_to_int_rejects_malformed_input():
    """_ip_to_int returns None rather than raising on unparseable input."""
    for bad in (None, '', 'not-an-ip', '1.2.3', '1.2.3.4.5', '999.1.1.1', '1.2.3.-1', 'a.b.c.d'):
        assert _ip_to_int(bad) is None


def test_ip_in_range_is_inclusive():
    """_ip_in_range treats both pool boundaries as inside the range."""
    assert _ip_in_range('192.0.2.6', '192.0.2.6', '192.0.2.254')
    assert _ip_in_range('192.0.2.254', '192.0.2.6', '192.0.2.254')
    assert _ip_in_range('192.0.2.100', '192.0.2.6', '192.0.2.254')


def test_ip_in_range_excludes_outside_and_unparseable():
    """_ip_in_range is False outside the range and when any bound is invalid."""
    assert not _ip_in_range('192.0.2.5', '192.0.2.6', '192.0.2.254')
    assert not _ip_in_range('192.0.3.10', '192.0.2.6', '192.0.2.254')
    assert not _ip_in_range('192.0.2.10', None, '192.0.2.254')
    assert not _ip_in_range(None, '192.0.2.6', '192.0.2.254')


# ---------------------------------------------------------------------------
# _resolve_network
# ---------------------------------------------------------------------------


def test_resolve_network_populates_subnet_and_gateway():
    """_resolve_network derives the gateway address from the subnet CIDR."""
    ctx = _resolve_network(NAS_ID, NETWORKS)
    assert ctx.name == 'NAS'
    assert ctx.vlan == 15
    assert ctx.subnet == '192.0.2.254/24'
    assert ctx.gateway_ip == '192.0.2.254'
    assert ctx.dhcp_enabled is True


def test_resolve_network_warns_when_pool_contains_gateway():
    """A pool spanning the gateway address is flagged as a conflict risk."""
    ctx = _resolve_network(NAS_ID, NETWORKS)
    assert any('contains the gateway address' in w for w in ctx.warnings)


def test_resolve_network_no_warning_for_sane_pool():
    """A pool that stops short of the gateway produces no conflict warning."""
    ctx = _resolve_network(HOME_ID, NETWORKS)
    assert not any('gateway address' in w for w in ctx.warnings)


def test_resolve_network_warns_when_no_dhcp_and_no_relay():
    """A network with neither a DHCP server nor a relay is called out."""
    nets = {
        'x': {'_id': 'x', 'name': 'Static', 'dhcpd_enabled': False, 'dhcp_relay_enabled': False}
    }
    ctx = _resolve_network('x', nets)
    assert any('no DHCP server and no relay' in w for w in ctx.warnings)


def test_resolve_network_warns_when_network_disabled():
    """A disabled network is surfaced as a warning."""
    nets = {'x': {'_id': 'x', 'name': 'Old', 'enabled': False}}
    ctx = _resolve_network('x', nets)
    assert any('is disabled' in w for w in ctx.warnings)


def test_resolve_network_unknown_id_returns_empty_context():
    """An unresolvable network id yields a context with no name."""
    ctx = _resolve_network('missing', NETWORKS)
    assert ctx.name is None
    assert 'unresolved' in ctx.label


def test_network_context_label_for_untagged():
    """A network with no VLAN id is described as untagged rather than 'VLAN None'."""
    assert 'untagged' in _resolve_network(HOME_ID, NETWORKS).label


# ---------------------------------------------------------------------------
# _resolve_profile
# ---------------------------------------------------------------------------


def test_resolve_profile_prefers_port_override():
    """A per-port override wins over the profile referenced in port_table."""
    profiles = {
        'access': {
            '_id': 'access',
            'name': 'Access 15',
            'forward': 'native',
            'native_networkconf_id': NAS_ID,
        },
        'trunk': {
            '_id': 'trunk',
            'name': 'Trunk',
            'forward': 'all',
            'native_networkconf_id': HOME_ID,
        },
    }
    switch = {'port_overrides': [{'port_idx': 2, 'portconf_id': 'access'}]}
    got = _resolve_profile(switch, {'portconf_id': 'trunk'}, 2, profiles, NETWORKS)
    assert got.name == 'Access 15'
    assert got.source == 'override'
    assert got.native_network_id == NAS_ID


def test_resolve_profile_falls_back_to_port_table():
    """Without an override the profile comes from port_table."""
    profiles = {'trunk': {'_id': 'trunk', 'name': 'Trunk', 'forward': 'all'}}
    got = _resolve_profile({}, {'portconf_id': 'trunk'}, 5, profiles, NETWORKS)
    assert got.name == 'Trunk'
    assert got.source == 'port_table'


def test_resolve_profile_resolves_tagged_vlan_numbers():
    """tagged_networkconf_ids are mapped to their VLAN numbers."""
    profiles = {
        'custom': {
            '_id': 'custom',
            'name': 'Custom',
            'forward': 'customize',
            'native_networkconf_id': HOME_ID,
            'tagged_networkconf_ids': [NAS_ID, MGMT_ID],
        }
    }
    got = _resolve_profile({}, {'portconf_id': 'custom'}, 1, profiles, NETWORKS)
    assert sorted(got.tagged_vlans or []) == [15, 255]
    assert 'tagged [15, 255]' in got.carries


def test_resolve_profile_unknown_marks_source_unknown():
    """A port with no resolvable profile reports source 'unknown'."""
    got = _resolve_profile({}, {}, 3, {}, NETWORKS)
    assert got.source == 'unknown'
    assert got.name is None


def test_port_profile_carries_descriptions():
    """PortProfile.carries describes each forward mode in plain language."""
    assert 'trunk' in PortProfile(forward='all').carries
    assert 'access' in PortProfile(forward='native').carries
    assert 'disabled' in PortProfile(forward='disabled').carries


# ---------------------------------------------------------------------------
# _build_dhcp_status
# ---------------------------------------------------------------------------


def test_dhcp_status_no_client():
    """With no client record the verdict is no_client."""
    got = _build_dhcp_status(None, None, _resolve_network(NAS_ID, NETWORKS))
    assert got.verdict == 'no_client'


def test_dhcp_status_leased_when_lease_expiry_present():
    """A lease expiry timestamp is treated as proof of a working DHCP exchange."""
    client = {
        'mac': 'aa:bb:cc:dd:ee:ff',
        'ip': '192.0.2.248',
        'ipv4_lease_expiration_timestamp_seconds': 1786441200,
    }
    got = _build_dhcp_status(client, None, _resolve_network(NAS_ID, NETWORKS))
    assert got.verdict == 'leased'
    assert got.lease_expires_at == 1786441200
    assert got.in_dhcp_pool is True
    assert 'DHCP lease' in got.label


def test_dhcp_status_static_when_address_but_no_lease():
    """An address with no lease is reported as configured on the host."""
    client = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.0.2.5'}
    got = _build_dhcp_status(client, None, _resolve_network(NAS_ID, NETWORKS))
    assert got.verdict == 'static'
    assert got.in_dhcp_pool is False
    assert any('configured on the host' in n for n in got.notes)
    assert any('outside the DHCP pool' in n for n in got.notes)


def test_dhcp_status_static_from_unifi_reservation():
    """use_fixedip attributes the address to a UniFi reservation."""
    client = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': '192.0.2.20', 'use_fixedip': True}
    got = _build_dhcp_status(client, None, _resolve_network(NAS_ID, NETWORKS))
    assert got.verdict == 'static'
    assert any('fixed-IP reservation' in n for n in got.notes)


def test_dhcp_status_no_address_hints_at_vlan_path():
    """A client with no IP on a DHCP-enabled network points at the VLAN path."""
    client = {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': None}
    got = _build_dhcp_status(client, None, _resolve_network(NAS_ID, NETWORKS))
    assert got.verdict == 'no_address'
    assert any('every hop of the uplink path' in n for n in got.notes)
    assert 'NO IP' in got.label


def test_dhcp_status_no_address_when_dhcp_disabled():
    """With DHCP off, a missing address is explained as needing a static config."""
    nets = {'x': {'_id': 'x', 'name': 'Static', 'dhcpd_enabled': False}}
    got = _build_dhcp_status({'mac': 'a', 'ip': None}, None, _resolve_network('x', nets))
    assert got.verdict == 'no_address'
    assert any('needs a static address' in n for n in got.notes)


def test_dhcp_status_falls_back_to_basic_client():
    """The stat/sta record is used when the richer v2 record is unavailable."""
    got = _build_dhcp_status(
        None, {'mac': 'a', 'ip': '192.0.2.99'}, _resolve_network(NAS_ID, NETWORKS)
    )
    assert got.verdict == 'static'
    assert got.ip == '192.0.2.99'


# ---------------------------------------------------------------------------
# _build_connected_device
# ---------------------------------------------------------------------------


def test_connected_device_third_party_carries_fingerprint_confidence():
    """A non-UniFi host keeps the fingerprint model guess and its confidence."""
    rich = {
        'mac': '02:00:00:00:00:02',
        'hostname': 'aabbccddeeff',
        'oui': 'Winstars Technology Ltd',
        'model_name': 'Apple MacBook Pro 14" M4',
        'fingerprint': {'confidence': 76},
        'ip': '192.0.2.248',
        'ipv6_address': ['fe80::1'],
        'network_name': 'NAS',
        'vlan': 15,
        'wired_rate_mbps': 2500,
        'unifi_device': False,
    }
    got = _build_connected_device(rich, None, None, {})
    assert got.is_unifi_device is False
    assert got.model == 'Apple MacBook Pro 14" M4'
    assert got.fingerprint_confidence == 76
    assert got.vendor == 'Winstars Technology Ltd'
    assert got.ipv6 == ['fe80::1']
    assert 'third-party host' in got.label


def test_connected_device_recognises_adopted_unifi_gear():
    """A MAC in the adopted-device index is reported as UniFi gear with its model."""
    mac_to_dev = {'02:00:00:00:00:01': {'name': 'Office XG', 'model': 'USFXG', 'ip': '10.0.0.5'}}
    rich = {'mac': '02:00:00:00:00:01', 'unifi_device': True}
    got = _build_connected_device(rich, None, None, mac_to_dev)
    assert got.is_unifi_device is True
    assert got.name == 'Office XG'
    assert got.model == 'USFXG'
    assert 'UniFi device' in got.label


def test_connected_device_falls_back_to_remembered_identity():
    """With no live client, the switch's remembered peer is reported instead."""
    identity = IdentityMatch(kind='device', name='Office XG', model='USFXG', ip='10.0.0.5')
    got = _build_connected_device(None, None, identity, {}, '02:00:00:00:00:01')
    assert got.mac == '02:00:00:00:00:01'
    assert got.is_unifi_device is True
    assert got.name == 'Office XG'


def test_connected_device_empty_when_nothing_known():
    """A port with no client and no remembered identity reports nothing attached."""
    got = _build_connected_device(None, None, IdentityMatch(kind='unknown'), {})
    assert got.mac is None
    assert 'nothing detected' in got.label


def test_connected_device_normalises_non_list_ipv6():
    """A scalar ipv6_address value is coerced into a list."""
    got = _build_connected_device({'mac': 'a', 'ipv6_address': 'fe80::9'}, None, None, {})
    assert got.ipv6 == ['fe80::9']


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_strip_markup_removes_rich_tags():
    """_strip_markup leaves only human-readable text."""
    assert _strip_markup('[bold]Office XG[/bold] (UniFi device)') == 'Office XG (UniFi device)'
    assert _strip_markup('plain') == 'plain'


def test_to_dict_shape_is_json_serialisable():
    """to_dict exposes every section the MCP tool documents."""
    import json

    result = PortInspectionResult(
        switch_name='SW',
        switch_model='M',
        switch_mac='aa:bb:cc:dd:ee:ff',
        port_idx=2,
        port_table={'up': True, 'speed': 2500, 'port_poe': False, 'name': 'Port 2'},
        network=_resolve_network(NAS_ID, NETWORKS),
        profile=PortProfile(name='Access 15', forward='native'),
        dhcp=DhcpStatus(verdict='leased', ip='192.0.2.248', lease_expires_at=1786441200),
        connected=ConnectedDevice(mac='02:00:00:00:00:02', hostname='nas'),
        lldp_identity=IdentityMatch(kind='device', name='Peer', model='USFXG'),
    )
    d = result.to_dict()

    for section in (
        'switch',
        'port_idx',
        'link',
        'profile',
        'network',
        'connected_device',
        'addressing',
        'lldp',
        'counters',
        'poe',
        'freshness',
    ):
        assert section in d, f'missing section {section}'

    assert d['addressing']['verdict'] == 'leased'
    assert d['network']['vlan'] == 15
    assert d['poe'] == {'capable': False}
    assert d['lldp']['resolved']['name'] == 'Peer'
    # Must survive a real JSON round-trip for MCP transport.
    assert json.loads(json.dumps(d))['port_idx'] == 2


def test_to_dict_addressing_summary_has_no_markup():
    """The serialised addressing summary is free of Rich markup."""
    result = PortInspectionResult(
        switch_name='SW',
        switch_model='M',
        switch_mac='aa',
        port_idx=1,
        dhcp=DhcpStatus(verdict='no_address'),
    )
    summary = result.to_dict()['addressing']['summary']
    assert '[' not in summary and ']' not in summary


def test_to_dict_includes_poe_detail_when_capable():
    """A PoE-capable port serialises its electrical detail."""
    result = PortInspectionResult(
        switch_name='SW',
        switch_model='M',
        switch_mac='aa',
        port_idx=1,
        port_table={'port_poe': True, 'poe_power': '6.5', 'poe_class': 'Class 3'},
    )
    poe = result.to_dict()['poe']
    assert poe['capable'] is True
    assert poe['power_w'] == '6.5'
