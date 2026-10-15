"""`analyze_mac_table` reads the client list when a switch sends no `mac_table` (issue 088).

No ``stat/device`` record on a current controller carries ``mac_table``; each port has only
``mac_table_count``. The wired clients in ``stat/sta`` name the switch and port they are
learned on (``sw_mac``, ``sw_port``), so the analysis builds its entries from them, and says
so. The shapes below are the live controller's (2026-10-15) with every MAC, name and id
replaced by documentation values.
"""

from __future__ import annotations

import pytest
from tests.fake_controller import API, FakeController, legacy, serving
from tests.fixtures_unifi import FAKE_TOKEN
from typing import Any
from unifi_mapper.analysis.mac_analyzer import analyze_mac_table


SWITCH_MAC = '02:00:00:00:0a:01'
OTHER_SWITCH_MAC = '02:00:00:00:0a:02'
ACCESS_PROFILE = 'bbbbbbbbbbbbbbbbbbbbbbb2'
PROFILES: list[dict[str, Any]] = [
    {'_id': ACCESS_PROFILE, 'name': 'Desk', 'forward': 'native', 'tagged_vlan_mgmt': 'block_all'},
]


def _switch() -> dict[str, Any]:
    """A live-shaped switch record: ports carry ``mac_table_count``, the device no ``mac_table``."""
    return {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': SWITCH_MAC.upper(),
        'type': 'usw',
        'model': 'USWED37',
        'port_table': [
            {'port_idx': 1, 'name': 'Port 1', 'portconf_id': ACCESS_PROFILE, 'mac_table_count': 1},
            {
                'port_idx': 3,
                'name': 'Desk hub',
                'portconf_id': ACCESS_PROFILE,
                'mac_table_count': 7,
            },
        ],
    }


def _wired(index: int, port: int, sw_mac: str = SWITCH_MAC, **extra: Any) -> dict[str, Any]:
    """A wired ``stat/sta`` row in the live key set."""
    return {
        'mac': f'00:00:5e:00:53:{index:02x}',
        'is_wired': True,
        'sw_mac': sw_mac,
        'sw_port': port,
        'sw_depth': 1,
        'last_uplink_mac': sw_mac,
        'network_id': 'cccccccccccccccccccccccc',
        'last_connection_network_id': 'cccccccccccccccccccccccc',
        'last_seen': 1_760_000_000,
        'uptime': 3600,
        **extra,
    }


CLIENTS: list[dict[str, Any]] = [
    _wired(1, 1, vlan=20),
    *(_wired(10 + i, 3) for i in range(7)),
    # a wireless client: no sw_mac / sw_port, so not on any switch port here
    {'mac': '00:00:5e:00:53:f0', 'is_wired': False, 'last_uplink_mac': OTHER_SWITCH_MAC},
    # a wired client on a switch outside the analysis
    _wired(0xF1, 2, sw_mac=OTHER_SWITCH_MAC),
]


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)


def _controller(devices: list[dict[str, Any]]) -> FakeController:
    return FakeController(
        {
            f'{API}/stat/device': legacy(devices),
            f'{API}/stat/sta': legacy(CLIENTS),
            f'{API}/rest/portconf': legacy(PROFILES),
        }
    )


@pytest.mark.usefixtures('_env')
async def test_without_a_mac_table_the_wired_clients_fill_the_ports() -> None:
    controller = _controller([_switch()])
    async with serving(controller):
        report = await analyze_mac_table(max_macs_per_port=5)

    assert report.devices_analyzed == 1
    assert report.total_mac_entries == 8
    assert report.unique_mac_addresses == 8
    by_port = {count.port_idx: count for count in report.port_mac_counts}
    assert by_port[1].mac_count == 1 and by_port[1].exceeds_threshold is False
    assert by_port[3].mac_count == 7 and by_port[3].exceeds_threshold is True
    assert by_port[3].port_name == 'Desk hub'
    (alert,) = report.alerts
    assert alert.device_name == 'Switch A' and alert.port_idx == 3
    assert sorted(alert.details['macs']) == [f'00:00:5e:00:53:{10 + i:02x}' for i in range(7)]
    assert report.ports_exceeding_threshold == 1
    assert any('client list' in line for line in report.recommendations), report.recommendations
    assert controller.methods == {'GET'}


@pytest.mark.usefixtures('_env')
async def test_one_switch_by_mac_reads_only_its_own_clients() -> None:
    controller = _controller([_switch()])
    async with serving(controller):
        report = await analyze_mac_table(device_id=SWITCH_MAC.upper(), max_macs_per_port=5)

    assert report.devices_analyzed == 1
    assert report.total_mac_entries == 8


@pytest.mark.usefixtures('_env')
async def test_a_switch_that_sends_mac_table_is_read_from_it() -> None:
    """The old field still wins where a controller sends it: it is the switch's own table."""
    switch = _switch()
    switch['mac_table'] = [{'mac': '00:00:5e:00:54:01', 'port_idx': 1, 'vlan': 1}]
    controller = _controller([switch])
    async with serving(controller):
        report = await analyze_mac_table(max_macs_per_port=5)

    assert report.total_mac_entries == 1
    assert [(c.port_idx, c.mac_count) for c in report.port_mac_counts] == [(1, 1)]
    assert not any('client list' in line for line in report.recommendations)
