"""Tests for link error tracking robustness against unadopted devices.

Regression (2026-07-29): after factory-resetting a switch it sat in the controller with
state=2 / adopted=False and NO '_id' key. Both the snapshot builder and the comparison
indexed ``d["_id"]`` directly, so a single pending device killed error tracking for the
whole site with ``KeyError: '_id'``.
"""

from __future__ import annotations

import asyncio
import json
from unifi_mapper.analysis import link_error_tracking


ADOPTED = {
    '_id': 'dev-adopted',
    'name': 'Hotel3 USW Flex XG 10G',
    'type': 'usw',
    'uptime': 5000,
    'port_table': [
        {'port_idx': 1, 'name': 'uplink', 'rx_errors': 10, 'tx_errors': 0,
         'rx_dropped': 0, 'tx_dropped': 0, 'rx_bytes': 100, 'tx_bytes': 100},
    ],
}

# Factory-reset switch awaiting adoption: the controller returns no '_id' at all.
UNADOPTED = {
    'name': 'USW Flex 2.5G 5',
    'mac': '02:00:fe:02:00:0d',
    'type': 'usw',
    'state': 2,
    'adopted': False,
    'uptime': 60,
    'port_table': [
        {'port_idx': 1, 'name': 'Port 1', 'rx_errors': 0, 'tx_errors': 0,
         'rx_dropped': 0, 'tx_dropped': 0, 'rx_bytes': 0, 'tx_bytes': 0},
    ],
}


def _mock_client(devices: list[dict]):
    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_devices(self):
            return devices

    return _MockClient


def test_snapshot_skips_unadopted_device(monkeypatch, tmp_path) -> None:
    """A pending device has no stable id to anchor a baseline to, so it is skipped."""
    monkeypatch.setattr(link_error_tracking, 'UniFiClient', _mock_client([ADOPTED, UNADOPTED]))
    out = tmp_path / 'baseline.json'

    snapshot = asyncio.run(link_error_tracking.snapshot_link_errors(str(out)))

    assert [d['device_id'] for d in snapshot['devices']] == ['dev-adopted']
    assert json.loads(out.read_text())['devices'][0]['device_id'] == 'dev-adopted'


def test_compare_tolerates_unadopted_device(monkeypatch, tmp_path) -> None:
    """Comparison must not raise when a pending device is present alongside real ones."""
    monkeypatch.setattr(link_error_tracking, 'UniFiClient', _mock_client([ADOPTED]))
    out = tmp_path / 'baseline.json'
    asyncio.run(link_error_tracking.snapshot_link_errors(str(out)))

    grown = {
        **ADOPTED,
        'uptime': 5600,
        'port_table': [
            {'port_idx': 1, 'name': 'uplink', 'rx_errors': 40, 'tx_errors': 0,
             'rx_dropped': 0, 'tx_dropped': 0, 'rx_bytes': 900, 'tx_bytes': 900},
        ],
    }
    monkeypatch.setattr(link_error_tracking, 'UniFiClient', _mock_client([grown, UNADOPTED]))

    report = asyncio.run(link_error_tracking.compare_link_errors(baseline_path=str(out)))

    assert report['ports_with_new_errors'] == 1
    assert report['all_deltas'][0]['rx_errors_delta'] == 30


def test_compare_with_only_unadopted_device_is_empty_not_error(monkeypatch, tmp_path) -> None:
    """An all-pending device list yields no deltas rather than an exception."""
    monkeypatch.setattr(link_error_tracking, 'UniFiClient', _mock_client([ADOPTED]))
    out = tmp_path / 'baseline.json'
    asyncio.run(link_error_tracking.snapshot_link_errors(str(out)))

    monkeypatch.setattr(link_error_tracking, 'UniFiClient', _mock_client([UNADOPTED]))
    report = asyncio.run(link_error_tracking.compare_link_errors(baseline_path=str(out)))

    assert report['ports_with_new_errors'] == 0
    assert report['flagged'] == []
