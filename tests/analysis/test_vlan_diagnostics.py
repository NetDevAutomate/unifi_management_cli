"""`diagnose_vlans` resolves each port's profile instead of reading an id as a name (issue 030).

Every switch port is audited (not only overridden ones), the profile comes from
``link_settings.effective_profile_id`` looked up in ``rest/portconf``, trunk-ness is judged
from the profile's ``forward`` and ``tagged_vlan_mgmt`` (as ``foreign_bridges`` does) and
its name, and the report carries profile names, never 24-hex-digit ids. Documentation values.
"""

from __future__ import annotations

import pytest
from tests.fake_controller import API, FakeController, legacy, serving
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.analysis.vlan_diagnostics import (
    diagnose_vlans,
    diagnose_vlans_from_data,
    is_trunk_profile,
)


LAN_ID = 'aaaaaaaaaaaaaaaaaaaaaaa1'
IOT_ID = 'aaaaaaaaaaaaaaaaaaaaaaa2'
CAMERAS_ID = 'aaaaaaaaaaaaaaaaaaaaaaa3'
VOICE_ID = 'aaaaaaaaaaaaaaaaaaaaaaa4'
UPLINK_PROFILE = 'bbbbbbbbbbbbbbbbbbbbbbb1'  # forward 'all': a trunk, nothing in its name says so
IOT_PROFILE = 'bbbbbbbbbbbbbbbbbbbbbbb2'  # an access profile on the IoT network
CAMERA_TRUNK = 'bbbbbbbbbbbbbbbbbbbbbbb3'  # 'customize' with tagged networks
BLOCKED_ALL = 'bbbbbbbbbbbbbbbbbbbbbbb4'  # forward 'all' but block_all: not a trunk

NETWORKS: list[dict[str, Any]] = [
    {'_id': LAN_ID, 'name': 'LAN', 'purpose': 'corporate', 'ip_subnet': '192.0.2.1/24'},
    {
        '_id': IOT_ID,
        'name': 'IoT',
        'vlan': 30,
        'ip_subnet': '198.51.100.1/24',
        'gateway_ip': '198.51.100.1',
    },
    {
        '_id': CAMERAS_ID,
        'name': 'Cameras',
        'vlan': 40,
        'ip_subnet': '203.0.113.1/24',
        'gateway_ip': '203.0.113.1',
    },
    {
        '_id': VOICE_ID,
        'name': 'Voice',
        'vlan': 50,
        'ip_subnet': '192.0.2.129/25',
        'gateway_ip': '192.0.2.129',
    },
]
PROFILES: list[dict[str, Any]] = [
    {
        '_id': UPLINK_PROFILE,
        'name': 'Uplink',
        'forward': 'all',
        'native_networkconf_id': LAN_ID,
        'tagged_vlan_mgmt': 'auto',
    },
    {
        '_id': IOT_PROFILE,
        'name': 'IoT access',
        'forward': 'native',
        'native_networkconf_id': IOT_ID,
        'tagged_vlan_mgmt': 'block_all',
    },
    {
        '_id': CAMERA_TRUNK,
        'name': 'Camera NVR',
        'forward': 'customize',
        'native_networkconf_id': LAN_ID,
        'tagged_vlan_mgmt': 'custom',
        'tagged_networkconf_ids': [CAMERAS_ID],
    },
    {
        '_id': BLOCKED_ALL,
        'name': 'Isolated',
        'forward': 'all',
        'native_networkconf_id': LAN_ID,
        'tagged_vlan_mgmt': 'block_all',
    },
]


def _switch() -> dict[str, Any]:
    """Four ports: 1 uplink (port-table id), 2 IoT via an override, 3 camera trunk, 4 isolated."""
    return {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': 'aa:aa:aa:aa:aa:aa',
        'type': 'usw',
        'port_table': [
            {'port_idx': 1, 'name': 'SFP+ 1', 'portconf_id': UPLINK_PROFILE},
            {'port_idx': 2, 'name': 'Port 2', 'portconf_id': UPLINK_PROFILE},
            {'port_idx': 3, 'name': 'Port 3', 'portconf_id': CAMERA_TRUNK},
            {'port_idx': 4, 'name': 'Port 4', 'portconf_id': BLOCKED_ALL},
        ],
        'port_overrides': [{'port_idx': 2, 'portconf_id': IOT_PROFILE}],
    }


def _by_port(report: Any) -> dict[int, Any]:
    return {port.port_idx: port for port in report.port_configs}


def test_every_switch_port_is_audited_not_only_the_overridden_ones() -> None:
    report = diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES)

    assert sorted(_by_port(report)) == [1, 2, 3, 4]


def test_the_profile_name_is_reported_and_the_override_wins() -> None:
    ports = _by_port(diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES))

    assert ports[1].profile_name == 'Uplink'
    assert ports[2].profile_name == 'IoT access'  # the override's profile, not the table's
    assert ports[3].profile_name == 'Camera NVR'
    assert {port.profile_name for port in ports.values()} == {
        'Uplink',
        'IoT access',
        'Camera NVR',
        'Isolated',
    }


def test_trunk_ness_comes_from_forward_and_tagged_vlan_mgmt() -> None:
    ports = _by_port(diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES))

    assert ports[1].is_trunk is True  # forward 'all', though 'Uplink' names no trunk
    assert ports[2].is_trunk is False  # an access profile
    assert ports[3].is_trunk is True  # 'customize' with a tagged network
    assert ports[4].is_trunk is False  # forward 'all' but block_all


def test_native_and_tagged_vlans_follow_the_resolved_profile() -> None:
    ports = _by_port(diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES))

    assert (ports[1].native_vlan, sorted(ports[1].tagged_vlans)) == (1, [30, 40, 50])
    assert (ports[2].native_vlan, ports[2].tagged_vlans) == (30, [])
    assert (ports[3].native_vlan, ports[3].tagged_vlans) == (1, [40])


def test_an_override_that_sets_vlans_itself_beats_the_profile() -> None:
    device = _switch()
    device['port_overrides'] = [
        {
            'port_idx': 1,
            'portconf_id': UPLINK_PROFILE,
            'native_networkconf_id': IOT_ID,
            'excluded_networkconf_ids': [VOICE_ID],
            'voice_networkconf_id': VOICE_ID,
        }
    ]

    port = _by_port(diagnose_vlans_from_data(NETWORKS, [device], PROFILES))[1]

    assert port.native_vlan == 30
    assert sorted(port.tagged_vlans) == [40, 50]  # auto minus Voice, plus the voice VLAN


def test_the_consistency_check_names_profiles_not_ids() -> None:
    device = _switch()
    device['port_table'].append({'port_idx': 5, 'name': 'Port 5', 'portconf_id': UPLINK_PROFILE})
    device['port_overrides'].append(
        {'port_idx': 5, 'portconf_id': UPLINK_PROFILE, 'native_networkconf_id': IOT_ID}
    )

    report = diagnose_vlans_from_data(NETWORKS, [device], PROFILES)

    check = next(c for c in report.diagnostic_checks if c.check_name == 'Port Profile Consistency')
    assert check.status == 'WARNING'
    assert check.details['inconsistent_profiles'] == ['Uplink']


def test_a_forward_all_trunk_covers_every_vlan() -> None:
    report = diagnose_vlans_from_data(NETWORKS, [_switch()], PROFILES)

    check = next(c for c in report.diagnostic_checks if c.check_name == 'Trunk VLAN Coverage')
    assert check.status == 'PASS'
    assert check.details['trunk_count'] == 2


def test_a_port_with_an_unknown_profile_id_keeps_the_id_visible() -> None:
    device = _switch()
    device['port_table'].append({'port_idx': 6, 'portconf_id': 'ccccccccccccccccccccccc9'})
    device['port_table'].append({'port_idx': 7})

    ports = _by_port(diagnose_vlans_from_data(NETWORKS, [device], PROFILES))

    assert ports[6].profile_name == 'ccccccccccccccccccccccc9' and ports[6].is_trunk is False
    assert ports[7].profile_name == 'Default' and ports[7].is_trunk is False


@pytest.mark.parametrize(
    ('settings', 'trunk'),
    [
        ({'forward': 'all', 'tagged_vlan_mgmt': 'auto'}, True),
        ({'forward': 'all'}, True),
        ({'forward': 'all', 'tagged_vlan_mgmt': 'block_all'}, False),
        ({'forward': 'native'}, False),
        ({'forward': 'customize', 'tagged_networkconf_ids': [CAMERAS_ID]}, True),
        ({'forward': 'customize', 'tagged_networkconf_ids': []}, False),
        ({'forward': 'native', 'name': 'Trunk to NVR'}, True),
        ({}, False),
    ],
)
def test_is_trunk_profile(settings: dict[str, Any], trunk: bool) -> None:
    assert is_trunk_profile(settings) is trunk


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)


@pytest.mark.usefixtures('_env')
async def test_diagnose_vlans_reads_the_profiles_and_only_reads() -> None:
    controller = FakeController(
        {
            f'{API}/rest/networkconf': legacy(NETWORKS),
            f'{API}/stat/device': legacy([_switch()]),
            f'{API}/rest/portconf': legacy(PROFILES),
        }
    )
    async with serving(controller):
        report = await diagnose_vlans()

    assert ('GET', f'{API}/rest/portconf') in controller.reads
    assert controller.methods == {'GET'}
    assert _by_port(report)[1].profile_name == 'Uplink'
