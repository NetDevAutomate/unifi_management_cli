"""Tests for uplink VLAN-transparency audit.

Modelled on the 2026-07-29 Lounge failure: a switch lost its trunk uplink, UniFi
elected an eero-facing *access* port as the replacement uplink, and every tagged
VLAN behind that switch (management 255, CCTV 10) was severed while the untagged
Home LAN kept working.
"""

from __future__ import annotations

from unifi_mapper.analysis.uplink_transparency import audit_uplink_transparency_from_data


HOME_LAN = {'_id': 'net-home', 'name': 'Home LAN', 'vlan': None, 'enabled': True}
CCTV = {'_id': 'net-cctv', 'name': 'CCTV', 'vlan': 10, 'enabled': True}
MGMT = {'_id': 'net-mgmt', 'name': 'Management', 'vlan': 255, 'enabled': True}
NETWORKS = [HOME_LAN, CCTV, MGMT]

TRUNK_PROFILE = {
    '_id': 'prof-trunk',
    'name': 'Trunk VLAN 1 Home 1 Gbps',
    'forward': 'all',
    'native_networkconf_id': 'net-home',
    'tagged_vlan_mgmt': 'auto',
}
ACCESS_PROFILE = {
    '_id': 'prof-access',
    'name': 'Access Port VLAN 1 Home 1Gbps',
    'forward': 'native',
    'native_networkconf_id': 'net-home',
    'tagged_vlan_mgmt': 'block_all',
}


def _switch(
    *,
    name: str = 'Mike2 USW Lite 16 PoE',
    mac: str = '02:00:fe:02:00:15',
    uplink_port_idx: int = 16,
    portconf_id: str = 'prof-trunk',
    uplink_mac: str = '02:00:fe:02:00:0b',
    state: int = 1,
) -> dict[str, object]:
    """Build a minimal switch device dict with one elected uplink port."""
    return {
        '_id': 'sw-lite16',
        'name': name,
        'mac': mac,
        'type': 'usw',
        'state': state,
        'ip': '203.0.113.32',
        'uplink': {'uplink_mac': uplink_mac, 'uplink_remote_port': 2, 'type': 'wire'},
        'port_table': [
            {
                'port_idx': uplink_port_idx,
                'name': 'uplink',
                'up': True,
                'is_uplink': True,
                'portconf_id': portconf_id,
            },
            {'port_idx': 1, 'name': 'camera', 'up': True, 'is_uplink': False, 'portconf_id': 'prof-access'},
        ],
    }


def _aggregation() -> dict[str, object]:
    """The healthy upstream switch the uplink should point at."""
    return {
        '_id': 'sw-flex8',
        'name': 'Mike2 USW Flex 2.5G 8 PoE',
        'mac': '02:00:fe:02:00:0b',
        'type': 'usw',
        'state': 1,
        'port_table': [],
    }


def test_trunk_uplink_carrying_all_vlans_passes() -> None:
    """A switch uplinked through a proper trunk produces no findings."""
    report = audit_uplink_transparency_from_data(
        devices=[_switch(), _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
    )

    assert report.validation_passed is True
    assert report.findings == []
    assert report.uplinks_analyzed == 1
    assert report.tagged_vlans == [10, 255]


def test_access_port_uplink_severs_tagged_vlans_is_critical() -> None:
    """The Lounge failure: uplink via a block_all access port severs every tagged VLAN."""
    report = audit_uplink_transparency_from_data(
        devices=[
            _switch(uplink_port_idx=13, portconf_id='prof-access', uplink_mac='02:00:fe:02:00:05'),
            _aggregation(),
        ],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
    )

    assert report.validation_passed is False
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.severity == 'CRITICAL'
    assert finding.device == 'Mike2 USW Lite 16 PoE'
    assert finding.uplink_port == 13
    assert finding.severed_vlans == [10, 255]
    assert finding.forward_mode == 'native'
    assert finding.tagged_vlan_mgmt == 'block_all'
    assert 'tagged VLAN' in finding.message


def test_management_vlan_severed_is_called_out() -> None:
    """When the switch's own mgmt IP sits in a severed VLAN, say so explicitly."""
    report = audit_uplink_transparency_from_data(
        devices=[
            _switch(uplink_port_idx=13, portconf_id='prof-access', uplink_mac='02:00:fe:02:00:05'),
            _aggregation(),
        ],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
        mgmt_vlan=255,
    )

    finding = report.findings[0]
    assert finding.management_vlan_severed is True
    assert 'unreachable' in finding.recommendation.lower() or 'management' in finding.message.lower()


def test_foreign_bridge_uplink_is_flagged() -> None:
    """An uplink whose remote end is not an adopted UniFi device is a loop risk."""
    report = audit_uplink_transparency_from_data(
        devices=[_switch(uplink_mac='02:00:fe:02:00:05'), _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
    )

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.remote_is_unifi is False
    assert finding.severity == 'WARNING'
    assert 'not an adopted UniFi device' in finding.message


def test_unifi_uplink_is_not_flagged_as_foreign() -> None:
    """A trunk uplink to a known UniFi switch must not raise a foreign-bridge finding."""
    report = audit_uplink_transparency_from_data(
        devices=[_switch(), _aggregation()],
        port_profiles=[TRUNK_PROFILE],
        networks=NETWORKS,
    )

    assert report.findings == []


def test_stale_device_is_annotated_but_still_reported() -> None:
    """A non-informing switch is exactly the symptom, so still report and mark it stale."""
    report = audit_uplink_transparency_from_data(
        devices=[
            _switch(
                uplink_port_idx=13,
                portconf_id='prof-access',
                uplink_mac='02:00:fe:02:00:05',
                state=0,
            ),
            _aggregation(),
        ],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
    )

    finding = report.findings[0]
    assert finding.device_informing is False
    assert 'stale' in finding.message.lower()


def test_customize_forward_reports_only_missing_vlans() -> None:
    """forward=customize carrying an explicit VLAN subset flags just the absent ones."""
    partial = {
        '_id': 'prof-partial',
        'name': 'Partial trunk',
        'forward': 'customize',
        'native_networkconf_id': 'net-home',
        'tagged_vlan_mgmt': 'custom',
        'tagged_vlan_ids': [10],
    }
    report = audit_uplink_transparency_from_data(
        devices=[_switch(portconf_id='prof-partial'), _aggregation()],
        port_profiles=[partial],
        networks=NETWORKS,
    )

    assert report.validation_passed is False
    finding = report.findings[0]
    assert finding.severed_vlans == [255]


def test_unresolvable_custom_profile_warns_instead_of_failing() -> None:
    """A custom tagged profile with no enumerable VLAN set must not be reported as CRITICAL.

    This controller exposes only forward=native/all and tagged_vlan_mgmt=block_all/auto,
    so a 'custom' profile carrying network-id references cannot be resolved here. Guessing
    would produce a false CRITICAL on a healthy trunk, so it degrades to WARNING.
    """
    opaque = {
        '_id': 'prof-opaque',
        'name': 'Custom trunk',
        'forward': 'customize',
        'native_networkconf_id': 'net-home',
        'tagged_vlan_mgmt': 'custom',
    }
    report = audit_uplink_transparency_from_data(
        devices=[_switch(portconf_id='prof-opaque'), _aggregation()],
        port_profiles=[opaque],
        networks=NETWORKS,
    )

    assert report.validation_passed is True
    finding = report.findings[0]
    assert finding.severity == 'WARNING'
    assert 'could not be resolved' in finding.message


def test_access_point_is_not_treated_as_a_switch() -> None:
    """APs have a port_table and a native-only Data port; they are not switches.

    Regression: the first live run flagged 'Hotel3 U6 IW Kilo3' p5 as CRITICAL.
    """
    report = audit_uplink_transparency_from_data(
        devices=[
            {
                '_id': 'ap1',
                'name': 'Hotel3 U6 IW Kilo3',
                'mac': 'aa:bb:cc:dd:ee:ff',
                'type': 'uap',
                'state': 1,
                'uplink': {'uplink_mac': '02:00:fe:02:00:0b'},
                'port_table': [
                    {'port_idx': 5, 'name': 'Data', 'up': True, 'is_uplink': True, 'portconf_id': 'prof-access'}
                ],
            },
            _aggregation(),
        ],
        port_profiles=[ACCESS_PROFILE],
        networks=NETWORKS,
    )

    assert report.uplinks_analyzed == 0
    assert report.findings == []


def test_forward_all_without_explicit_tagged_mgmt_is_a_full_trunk() -> None:
    """forward=all carries every VLAN even when tagged_vlan_mgmt is absent.

    Regression: the first live run raised 'could not be resolved' WARNINGs against
    healthy 10G uplinks whose port payload had forward=all and no tagged_vlan_mgmt.
    """
    report = audit_uplink_transparency_from_data(
        devices=[
            {
                '_id': 'sw-flexxg',
                'name': 'Hotel3 USW Flex 2.5G 8',
                'mac': '02:00:fe:02:00:0e',
                'type': 'usw',
                'state': 1,
                'uplink': {'uplink_mac': '02:00:fe:02:00:0b'},
                'port_table': [
                    {'port_idx': 10, 'name': 'Port 10', 'up': True, 'is_uplink': True, 'forward': 'all'}
                ],
            },
            _aggregation(),
        ],
        port_profiles=[],
        networks=NETWORKS,
    )

    assert report.uplinks_analyzed == 1
    assert report.findings == []
    assert report.validation_passed is True


def test_lldp_on_elected_port_overrides_stale_uplink_mac() -> None:
    """LLDP for the elected uplink port wins over a stale device['uplink']['uplink_mac'].

    Regression: mid-recovery the Lite16 had re-homed onto its p16 trunk to the Flex8
    (LLDP proved it) while uplink_mac still named the old eero, producing a false
    third-party-bridge finding.
    """
    switch = _switch(uplink_port_idx=16, portconf_id='prof-trunk', uplink_mac='02:00:fe:02:00:05')
    switch['lldp_table'] = [{'local_port_idx': 16, 'chassis_id': '02:00:fe:02:00:0b'}]

    report = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE],
        networks=NETWORKS,
    )

    assert report.findings == []


def test_lldp_confirming_foreign_bridge_still_flags() -> None:
    """LLDP naming a non-UniFi chassis on the uplink port is a genuine finding."""
    switch = _switch(uplink_port_idx=13, portconf_id='prof-trunk', uplink_mac='02:00:fe:02:00:0b')
    switch['lldp_table'] = [{'local_port_idx': 13, 'chassis_id': '02:00:fe:02:00:05'}]

    report = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE],
        networks=NETWORKS,
    )

    assert len(report.findings) == 1
    assert report.findings[0].remote_is_unifi is False
    assert report.findings[0].remote_uplink_mac == '02:00:fe:02:00:05'


def test_long_stale_device_does_not_assert_topology() -> None:
    """A device that stopped informing hours ago must not have its snapshot asserted.

    The check exists to catch the trap of trusting stale UniFi port data, so it must not
    fall into that trap itself. An 8-hour-old snapshot naming a since-removed third-party
    bridge is not evidence of current topology.
    """
    switch = _switch(uplink_port_idx=5, portconf_id='prof-access', uplink_mac='02:00:fe:02:00:05', state=0)
    switch['last_seen'] = 1_000_000  # 8 hours before `now` below

    report = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
        now=1_000_000 + 8 * 3600,
    )

    assert report.validation_passed is True
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.severity == 'WARNING'
    assert finding.device_informing is False
    assert finding.severed_vlans == []
    assert finding.remote_is_unifi is None
    assert finding.topology_verifiable is False
    assert finding.data_age_seconds is not None and finding.data_age_seconds >= 8 * 3600
    assert 'too old to verify' in finding.message.lower()
    assert 'not assessed' in finding.message.lower()


def test_recently_offline_device_is_still_asserted() -> None:
    """Data only minutes old is still trustworthy, so a real fault must still be CRITICAL."""
    switch = _switch(uplink_port_idx=13, portconf_id='prof-access', uplink_mac='02:00:fe:02:00:05', state=0)
    switch['last_seen'] = 1_000_000

    report = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
        now=1_000_000 + 300,  # 5 minutes
    )

    finding = report.findings[0]
    assert finding.severity == 'CRITICAL'
    assert finding.severed_vlans == [10, 255]
    assert finding.topology_verifiable is True
    assert 'stale' in finding.message.lower()


def test_staleness_threshold_is_configurable() -> None:
    """The cutoff can be tuned per call."""
    switch = _switch(uplink_port_idx=13, portconf_id='prof-access', uplink_mac='02:00:fe:02:00:05', state=0)
    switch['last_seen'] = 1_000_000

    strict = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
        now=1_000_000 + 300,
        stale_after_seconds=60,
    )
    assert strict.findings[0].topology_verifiable is False

    lax = audit_uplink_transparency_from_data(
        devices=[switch, _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
        now=1_000_000 + 300,
        stale_after_seconds=3600,
    )
    assert lax.findings[0].topology_verifiable is True


def test_informing_device_is_always_verifiable() -> None:
    """A healthy device's data is current regardless of last_seen arithmetic."""
    report = audit_uplink_transparency_from_data(
        devices=[_switch(uplink_port_idx=13, portconf_id='prof-access'), _aggregation()],
        port_profiles=[TRUNK_PROFILE, ACCESS_PROFILE],
        networks=NETWORKS,
    )

    finding = report.findings[0]
    assert finding.topology_verifiable is True
    assert finding.severity == 'CRITICAL'


def test_gateway_without_uplink_is_skipped() -> None:
    """The gateway has no uplink port and must not be analysed."""
    report = audit_uplink_transparency_from_data(
        devices=[
            {
                '_id': 'udm',
                'name': 'Dream Machine Pro Max',
                'mac': '02:00:fe:02:00:01',
                'type': 'udm',
                'state': 1,
                'port_table': [{'port_idx': 1, 'name': 'wan', 'up': True}],
            }
        ],
        port_profiles=[TRUNK_PROFILE],
        networks=NETWORKS,
    )

    assert report.uplinks_analyzed == 0
    assert report.findings == []


def test_no_tagged_vlans_on_site_means_nothing_to_sever() -> None:
    """A flat untagged network cannot suffer this failure."""
    report = audit_uplink_transparency_from_data(
        devices=[_switch(portconf_id='prof-access'), _aggregation()],
        port_profiles=[ACCESS_PROFILE],
        networks=[HOME_LAN],
    )

    assert report.tagged_vlans == []
    assert [f for f in report.findings if f.severity == 'CRITICAL'] == []
