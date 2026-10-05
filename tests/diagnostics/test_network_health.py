"""Tests for the network health score and its uplink check (``diagnose health``).

Ported from the July work (a local archive, not in the repo) with generic names. A healthy
network scores 100; an uplink counts as down only when its state says so explicitly.
"""

import pytest
from unifi_mapper.diagnostics.network_health import (
    _analyze_network_health,
    _calculate_health_score,
    _is_uplink_down,
)


def test_network_health_clean_network_can_be_healthy() -> None:
    """A fully online network with no issues should score as healthy."""
    report = _analyze_network_health(
        devices_data=[
            {
                'name': 'Switch A',
                'state': 1,
                'adopted': True,
                'system-stats': {'cpu': 10, 'mem': 20, 'loadavg_1': 0.1},
            }
        ],
        clients_data=[],
        health_data=[],
    )

    assert report.overall_score == 100
    assert report.status == 'healthy'


def test_network_health_accepts_string_metrics() -> None:
    """UniFi sometimes returns CPU, memory, and load metrics as strings."""
    report = _analyze_network_health(
        devices_data=[
            {
                'name': 'Switch A',
                'state': 1,
                'adopted': True,
                'system-stats': {'cpu': '81.5', 'mem': '96', 'loadavg_1': '2.25'},
            }
        ],
        clients_data=[],
        health_data=[],
    )

    assert report.high_cpu_devices == ['Switch A (81.5%)']
    assert report.high_memory_devices == ['Switch A (96%)']
    assert report.high_load_devices == ['Switch A (2.25)']
    assert 'critical memory usage: 96%' in report.critical_issues[0]


def test_network_health_does_not_flag_uplinks_without_explicit_state() -> None:
    """UniFi wired uplink records can omit the up key while the link is active."""
    report = _analyze_network_health(
        devices_data=[
            {
                'name': 'Switch B',
                'state': 1,
                'adopted': True,
                'uplink': {
                    'type': 'wire',
                    'uplink_device_name': 'Switch A',
                    'speed': 1000,
                    'rx_bytes-r': 1200.0,
                    'tx_bytes-r': 500.0,
                },
            }
        ],
        clients_data=[],
        health_data=[],
    )

    assert report.uplink_issues == []
    assert report.critical_issues == []


def test_network_health_flags_explicitly_down_uplink() -> None:
    """Explicit false uplink state should remain a critical issue."""
    report = _analyze_network_health(
        devices_data=[{'name': 'Switch B', 'state': 1, 'adopted': True, 'uplink': {'up': False}}],
        clients_data=[],
        health_data=[],
    )

    assert report.uplink_issues == ['Switch B has uplink problems']
    assert report.critical_issues == ['Device Switch B uplink is down']


def test_network_health_ignores_unparseable_metrics() -> None:
    """Bad controller metric values should not fail the whole audit."""
    report = _analyze_network_health(
        devices_data=[
            {
                'name': 'AP 1',
                'state': 1,
                'adopted': True,
                'system-stats': {'cpu': 'unknown', 'mem': None, 'loadavg_1': ''},
            }
        ],
        clients_data=[],
        health_data=[],
    )

    assert report.high_cpu_devices == []
    assert report.high_memory_devices == []
    assert report.high_load_devices == []


@pytest.mark.parametrize(
    'uplink',
    [{'up': False}, {'up': 'false'}, {'up': 'FALSE'}, {'up': 'down'}, {'up': '0'}, {'up': 0}],
)
def test_an_uplink_is_down_only_when_its_state_says_so(uplink: dict) -> None:
    assert _is_uplink_down(uplink) is True


@pytest.mark.parametrize(
    'uplink',
    [{}, {'type': 'wire'}, {'up': True}, {'up': 'true'}, {'up': None}, {'up': 1}, None],
)
def test_an_uplink_without_a_down_state_is_not_down(uplink: dict | None) -> None:
    assert _is_uplink_down(uplink) is False


@pytest.mark.parametrize(
    ('online', 'offline', 'expected'),
    [(4, 0, 100), (3, 1, 92), (2, 2, 85), (0, 4, 70)],
)
def test_the_score_starts_from_100_and_loses_up_to_30_for_offline_devices(
    online: int, offline: int, expected: int
) -> None:
    total = online + offline
    assert _calculate_health_score(total, online, offline, 0, 0, 0, 0, 0) == expected


def test_the_score_of_no_devices_is_zero() -> None:
    assert _calculate_health_score(0, 0, 0, 0, 0, 0, 0, 0) == 0
