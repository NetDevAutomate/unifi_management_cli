"""`analyze_mac_table` tells a trunk from an access port by its resolved profile (issue 030).

``_is_trunk_port`` read the port table's raw ``portconf_id`` as if it were a profile name, so
no port was ever a trunk through its profile and a healthy inter-switch link with many MACs
was flagged as a suspicious access port. The profile now comes from
``link_settings.effective_profile_id`` looked up in ``rest/portconf``. Documentation values.
"""

from __future__ import annotations

import pytest
from tests.fake_controller import API, FakeController, legacy, serving
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.analysis.mac_analyzer import analyze_mac_table


UPLINK_PROFILE = 'bbbbbbbbbbbbbbbbbbbbbbb1'
ACCESS_PROFILE = 'bbbbbbbbbbbbbbbbbbbbbbb2'
PROFILES: list[dict[str, Any]] = [
    {'_id': UPLINK_PROFILE, 'name': 'Uplink', 'forward': 'all', 'tagged_vlan_mgmt': 'auto'},
    {'_id': ACCESS_PROFILE, 'name': 'Desk', 'forward': 'native', 'tagged_vlan_mgmt': 'block_all'},
]


def _macs(count: int, prefix: str) -> list[dict[str, Any]]:
    return [{'mac': f'{prefix}:{i:02x}', 'port_idx': 0, 'vlan': 1} for i in range(count)]


def _switch() -> dict[str, Any]:
    """Port 1 is a trunk by profile (nothing in the id says so), port 2 an access port by
    override; both see eight MACs."""
    trunk_macs = [{**m, 'port_idx': 1} for m in _macs(8, '00:00:5e:00:53')]
    access_macs = [{**m, 'port_idx': 2} for m in _macs(8, '00:00:5e:00:54')]
    return {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': 'aa:aa:aa:aa:aa:aa',
        'type': 'usw',
        'port_table': [
            {'port_idx': 1, 'name': 'SFP+ 1', 'portconf_id': UPLINK_PROFILE},
            {'port_idx': 2, 'name': 'Port 2', 'portconf_id': UPLINK_PROFILE},
        ],
        'port_overrides': [{'port_idx': 2, 'portconf_id': ACCESS_PROFILE}],
        'mac_table': trunk_macs + access_macs,
    }


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)


@pytest.mark.usefixtures('_env')
async def test_a_trunk_by_profile_is_not_an_overloaded_access_port() -> None:
    controller = FakeController(
        {
            f'{API}/stat/device': legacy([_switch()]),
            f'{API}/stat/sta': legacy([]),
            f'{API}/rest/portconf': legacy(PROFILES),
        }
    )
    async with serving(controller):
        report = await analyze_mac_table(max_macs_per_port=5)

    by_port = {count.port_idx: count for count in report.port_mac_counts}
    assert by_port[1].is_trunk is True and by_port[1].exceeds_threshold is False
    assert by_port[2].is_trunk is False and by_port[2].exceeds_threshold is True
    assert ('GET', f'{API}/rest/portconf') in controller.reads
    assert controller.methods == {'GET'}
