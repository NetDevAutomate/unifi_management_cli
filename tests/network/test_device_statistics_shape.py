"""``DeviceStatistics`` parses what ``.../devices/{id}/statistics/latest`` sends (issue 081).

Two payloads pin the model:

* ``LIVE_SWITCH`` is a USW Flex 2.5G 8 PoE's answer on Network 10.x, captured read-only
  through ``ports diagnose`` on 2026-10-15 (an empty ``interfaces`` object: a switch has no
  radios).
* ``REFERENCE`` is the example Ubiquiti's Network API reference gives for the endpoint, the
  only source of the load-average and radio keys (the captured switch sends neither).

Before the fix the model read ``uptimeSeconds``, ``lastSeen`` and ``cpuMemory``, none of which
the endpoint sends, and declared ``interfaces`` a list, so the live answer failed validation.
"""

from __future__ import annotations

import httpx
from datetime import datetime, timezone
from pydantic import SecretStr
from tests.fixtures_unifi import FAKE_TOKEN, fake_statistics_latest
from unifi_mapper.network.client import UniFiNetworkClient
from unifi_mapper.network.config import NetworkConfig
from unifi_mapper.network.models import DeviceStatistics
from unifi_mapper.network.statistics import DeviceMetricsCollector
from unittest.mock import AsyncMock, MagicMock


SITE_ID = '00000000-0000-0000-0000-0000000000f1'
DEVICE_ID = '00000000-0000-0000-0000-0000000000f2'

LIVE_SWITCH = {
    'uptimeSec': 3636624,
    'lastHeartbeatAt': '2026-10-15T18:16:45Z',
    'nextHeartbeatAt': '2026-10-15T18:18:02Z',
    'cpuUtilizationPct': 11.0,
    'memoryUtilizationPct': 83.9,
    'uplink': {'txRateBps': 0, 'rxRateBps': 0},
    'interfaces': {},
}

REFERENCE = {
    'uptimeSec': 120,
    'lastHeartbeatAt': '2024-01-01T00:00:00Z',
    'nextHeartbeatAt': '2024-01-01T00:00:30Z',
    'loadAverage1Min': 0.5,
    'loadAverage5Min': 0.25,
    'loadAverage15Min': 0.125,
    'cpuUtilizationPct': 3.5,
    'memoryUtilizationPct': 40.0,
    'uplink': {'txRateBps': 1000, 'rxRateBps': 2000},
    'interfaces': {'radios': [{'frequencyGHz': '2.4', 'txRetriesPct': 1.5}]},
}


def test_the_live_switch_answer_parses_into_its_values() -> None:
    stats = DeviceStatistics.model_validate(LIVE_SWITCH)

    assert stats.uptime_seconds == 3636624
    assert stats.cpu_utilization_pct == 11.0
    assert stats.memory_utilization_pct == 83.9
    assert stats.last_heartbeat_at == datetime(2026, 10, 15, 18, 16, 45, tzinfo=timezone.utc)
    assert stats.next_heartbeat_at == datetime(2026, 10, 15, 18, 18, 2, tzinfo=timezone.utc)
    assert stats.uplink is not None
    assert (stats.uplink.tx_rate_bps, stats.uplink.rx_rate_bps) == (0, 0)
    assert stats.interfaces.radios == []


def test_the_reference_example_parses_load_averages_and_radios() -> None:
    stats = DeviceStatistics.model_validate(REFERENCE)

    assert (stats.load_average_1m, stats.load_average_5m, stats.load_average_15m) == (
        0.5,
        0.25,
        0.125,
    )
    assert stats.uplink is not None
    assert (stats.uplink.tx_rate_bps, stats.uplink.rx_rate_bps) == (1000, 2000)
    [radio] = stats.interfaces.radios
    assert (radio.frequency_ghz, radio.tx_retries_pct) == ('2.4', 1.5)


def test_absent_figures_are_none_rather_than_zero() -> None:
    """A field the device did not send must not read as a measured 0 % CPU."""
    stats = DeviceStatistics.model_validate({'uptimeSec': 5})

    assert stats.cpu_utilization_pct is None
    assert stats.memory_utilization_pct is None
    assert stats.uplink is None


def test_an_unknown_key_is_kept_not_dropped() -> None:
    stats = DeviceStatistics.model_validate({**LIVE_SWITCH, 'newFigure': 1})

    assert stats.model_extra == {'newFigure': 1}


def test_the_shared_fixture_has_the_live_shape() -> None:
    """``tests/fixtures_unifi.py`` carries the keys the live endpoint sends, and they parse."""
    payload = fake_statistics_latest()

    assert set(payload) == set(LIVE_SWITCH)
    stats = DeviceStatistics.model_validate(payload)
    assert stats.uptime_seconds == 86400
    assert stats.cpu_utilization_pct == 7.1
    assert stats.memory_utilization_pct == 41.2


async def test_the_client_returns_the_live_values() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith('/v1/info'):
            return httpx.Response(200, json={'applicationVersion': '10.6.106'})
        return httpx.Response(200, json=LIVE_SWITCH)

    config = NetworkConfig(host='192.0.2.1', api_key=SecretStr(FAKE_TOKEN), site_id=SITE_ID)
    async with UniFiNetworkClient(config, transport=httpx.MockTransport(handle)) as client:
        stats = await client.get_device_statistics(DEVICE_ID)

    assert stats.device_id == DEVICE_ID
    assert stats.uptime_seconds == 3636624
    assert stats.cpu_utilization_pct == 11.0


async def test_the_metrics_collector_reports_the_live_cpu_and_memory() -> None:
    client = MagicMock()
    client.get_device_statistics = AsyncMock(
        return_value=DeviceStatistics.model_validate({**LIVE_SWITCH, 'deviceId': DEVICE_ID})
    )

    snapshot = await DeviceMetricsCollector(client).collect_once(DEVICE_ID)

    assert snapshot.uptime_seconds == 3636624
    assert snapshot.cpu_percent == 11.0
    assert snapshot.memory_percent == 83.9
