"""LAG detection on current switch firmware (issue 061).

Current firmware describes a LAG in ``link_aggregation_groups`` and on the master port
(``port_overrides`` ``op_mode: 'aggregate'``; ``port_table`` ``lacp_state`` and
``partner_system_id``), with each subordinate ``masked`` and ``aggregated_by`` the master.
Older firmware used ``port_aggregates``. The core reads both. Documentation values only
(RFC 5737 / RFC 7042).
"""

from __future__ import annotations

import copy
import pytest
from typing import Any
from unifi_mapper.analysis.lag_monitoring import (
    find_lag_candidates_from_data,
    monitor_lags_from_data,
)
from unifi_mapper.core.models import LACPState, LAGStatus
from unifi_mapper.core.utils.errors import ToolError


PEER_MAC = 'bb:bb:bb:bb:bb:bb'
PARTNER_SYSTEM_ID = '00:00:5e:00:53:02'


def _port(idx: int, **extra: Any) -> dict[str, Any]:
    """A current-firmware ``port_table`` entry: ``aggregated_by`` is ``False`` when not in a LAG."""
    port: dict[str, Any] = {
        'port_idx': idx,
        'name': f'Port {idx}',
        'up': True,
        'enable': True,
        'speed': 10000,
        'masked': False,
        'aggregated_by': False,
        'op_mode': 'switch',
        'rx_bytes': 1000,
        'tx_bytes': 1000,
    }
    port.update(extra)
    return port


def _modern_switch(
    *,
    with_groups: bool = True,
    with_override: bool = True,
    lacp_state: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A switch with a two-port LAG (ports 1 and 2, master 1) in the current firmware shape."""
    if lacp_state is None:
        lacp_state = [
            {'member_port': 1, 'active': True, 'speed': 10000},
            {'member_port': 2, 'active': True, 'speed': 10000},
        ]
    device: dict[str, Any] = {
        '_id': 'switch-a',
        'name': 'Switch A',
        'mac': 'aa:aa:aa:aa:aa:aa',
        'type': 'usw',
        'port_table': [
            _port(
                1,
                op_mode='aggregate',
                lacp_state=lacp_state,
                partner_system_id=PARTNER_SYSTEM_ID,
                aggregate_members=[1, 2],
                lag_idx=1,
            ),
            # The subordinate forwards traffic but reports a cosmetic down link.
            _port(2, up=False, speed=0, masked=True, aggregated_by=1),
            _port(3),
            _port(4),
        ],
        'port_overrides': [],
        'lldp_table': [
            {'local_port_idx': 1, 'chassis_id': PEER_MAC, 'port_id': '1'},
            {'local_port_idx': 2, 'chassis_id': PEER_MAC, 'port_id': '2'},
        ],
    }
    if with_groups:
        device['link_aggregation_groups'] = [
            {'lag_idx': 1, 'aggregate_members': [1, 2], 'type': 'lag'}
        ]
    else:
        device['link_aggregation_groups'] = []
    if with_override:
        device['port_overrides'] = [
            {'port_idx': 1, 'op_mode': 'aggregate', 'aggregate_members': [1, 2], 'lag_idx': 1}
        ]
    return device


def _legacy_switch() -> dict[str, Any]:
    return {
        '_id': 'switch-legacy',
        'name': 'Switch Legacy',
        'mac': 'cc:cc:cc:cc:cc:cc',
        'type': 'usw',
        'port_aggregates': [{'_id': 'agg-1', 'name': 'Uplink LAG', 'member_ports': [3, 4]}],
        'port_table': [
            {'port_idx': 3, 'up': True, 'enable': True, 'speed': 1000},
            {'port_idx': 4, 'up': True, 'enable': True, 'speed': 1000},
        ],
    }


def test_a_lag_declared_in_link_aggregation_groups_is_found() -> None:
    report = monitor_lags_from_data([_modern_switch()])

    assert report.total_lags == 1
    lag = report.lag_groups[0]
    assert lag.expected_members == 2
    assert sorted(member.port_idx for member in lag.members) == [1, 2]
    assert lag.device_name == 'Switch A'


def test_a_masked_subordinate_takes_its_state_from_the_masters_lacp_state() -> None:
    report = monitor_lags_from_data([_modern_switch()])

    lag = report.lag_groups[0]
    subordinate = next(member for member in lag.members if member.port_idx == 2)
    assert subordinate.is_active is True
    assert subordinate.link_up is True
    assert subordinate.speed_mbps == 10000
    assert subordinate.lacp_state == LACPState.ACTIVE
    assert lag.active_members == 2
    assert lag.active_bandwidth_mbps == 20000
    assert lag.status == LAGStatus.HEALTHY


def test_a_healthy_lag_makes_the_report_healthy() -> None:
    report = monitor_lags_from_data([_modern_switch()])

    assert (report.healthy_lags, report.degraded_lags, report.critical_lags) == (1, 0, 0)
    assert report.network_healthy is True
    assert report.active_lag_bandwidth_gbps == 20.0


def test_an_inactive_lacp_state_entry_degrades_the_lag() -> None:
    device = _modern_switch(
        lacp_state=[
            {'member_port': 1, 'active': True, 'speed': 10000},
            {'member_port': 2, 'active': False, 'speed': 0},
        ]
    )

    report = monitor_lags_from_data([device])

    lag = report.lag_groups[0]
    assert lag.active_members == 1
    assert lag.status == LAGStatus.DEGRADED
    assert report.network_healthy is False
    assert report.degraded_lags == 1
    subordinate = next(member for member in lag.members if member.port_idx == 2)
    assert subordinate.lacp_state == LACPState.SUSPENDED


def test_the_partner_system_id_is_surfaced_from_the_master_port() -> None:
    report = monitor_lags_from_data([_modern_switch()])

    assert report.lag_groups[0].partner_system_id == PARTNER_SYSTEM_ID


def test_a_lag_declared_only_in_port_overrides_is_still_found() -> None:
    report = monitor_lags_from_data([_modern_switch(with_groups=False)])

    assert report.total_lags == 1
    assert sorted(member.port_idx for member in report.lag_groups[0].members) == [1, 2]


def test_a_lag_declared_in_both_shapes_is_reported_once() -> None:
    report = monitor_lags_from_data([_modern_switch(with_groups=True, with_override=True)])

    assert report.total_lags == 1


def test_legacy_port_aggregates_still_work() -> None:
    report = monitor_lags_from_data([_legacy_switch()])

    assert report.total_lags == 1
    lag = report.lag_groups[0]
    assert lag.lag_name == 'Uplink LAG'
    assert sorted(member.port_idx for member in lag.members) == [3, 4]
    assert lag.status == LAGStatus.HEALTHY


def test_no_lag_gives_an_empty_report_with_a_recommendation() -> None:
    device = {
        '_id': 'plain',
        'name': 'Plain',
        'mac': 'dd:dd:dd:dd:dd:dd',
        'type': 'usw',
        'link_aggregation_groups': [],
        'port_table': [_port(1), _port(2)],
    }

    report = monitor_lags_from_data([device])

    assert report.devices_analyzed == 1
    assert report.total_lags == 0
    assert report.lag_groups == []
    assert any('No LAGs found' in line for line in report.recommendations)


def test_an_unknown_device_id_raises_tool_error() -> None:
    with pytest.raises(ToolError) as excinfo:
        monitor_lags_from_data([_modern_switch()], device_id='not-a-switch')

    assert 'not found' in excinfo.value.message


def test_lag_candidates_exclude_ports_already_in_a_modern_lag() -> None:
    peer = {
        '_id': 'switch-b',
        'name': 'Switch B',
        'mac': PEER_MAC,
        'type': 'usw',
        'link_aggregation_groups': [],
        'port_table': [_port(1), _port(2)],
    }
    # Both ports look like healthy parallel links to the same peer; they already form a LAG.
    device = _modern_switch()
    device['port_table'][1].update(up=True, speed=10000)

    report = find_lag_candidates_from_data([device, peer])

    assert report.candidate_count == 0


def test_the_core_does_not_mutate_its_input() -> None:
    devices = [_modern_switch(), _legacy_switch()]
    before = copy.deepcopy(devices)

    monitor_lags_from_data(devices)
    find_lag_candidates_from_data(devices)

    assert devices == before
