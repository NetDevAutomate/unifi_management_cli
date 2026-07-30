"""Tests for device freshness (stale-telemetry) detection.

Motivated by the 2026-07-29 incident: `stat/device` returned a complete, plausible port
table for a switch that had stopped informing three hours earlier. Reading `p13: forwarding`
from it described 07:17Z, not the present, and cost several hours of misdirected diagnosis.

The reliable test is comparative: a live device advances `last_seen` AND its cumulative
counters between two samples, and healthy peers act as the control.
"""

from __future__ import annotations

from unifi_mapper.analysis.device_freshness import (
    check_device_freshness_from_samples,
    summarise_freshness_from_data,
)


def _dev(mac: str, name: str, last_seen: int, rx: int, uptime: int, state: int = 1) -> dict:
    return {
        '_id': f'dev-{mac}', 'mac': mac, 'name': name, 'type': 'usw',
        'state': state, 'last_seen': last_seen, 'uptime': uptime,
        'port_table': [{'port_idx': 1, 'up': True, 'rx_bytes': rx}],
    }


def test_advancing_device_is_fresh() -> None:
    """last_seen and counters both move -> live."""
    s1 = [_dev('aa', 'Healthy', 1000, 500, 100)]
    s2 = [_dev('aa', 'Healthy', 1080, 900, 180)]

    report = check_device_freshness_from_samples(s1, s2)

    assert report.stale_count == 0
    assert report.fresh_count == 1
    assert report.validation_passed is True


def test_frozen_device_is_stale_while_peers_advance() -> None:
    """The Lite16 case: everything frozen while peers move."""
    s1 = [_dev('aa', 'Stranded', 1000, 500, 100), _dev('bb', 'Peer', 1000, 500, 100)]
    s2 = [_dev('aa', 'Stranded', 1000, 500, 100), _dev('bb', 'Peer', 1080, 900, 180)]

    report = check_device_freshness_from_samples(s1, s2)

    assert report.stale_count == 1
    assert report.validation_passed is False
    f = report.findings[0]
    assert f.device == 'Stranded'
    assert f.last_seen_delta == 0
    assert f.uptime_delta == 0
    assert f.peers_advancing is True
    assert 'not advancing' in f.message.lower()


def test_all_devices_frozen_blames_the_controller_not_the_devices() -> None:
    """If nothing advanced, the sample window was too short or the controller stalled."""
    s1 = [_dev('aa', 'A', 1000, 500, 100), _dev('bb', 'B', 1000, 500, 100)]
    s2 = [_dev('aa', 'A', 1000, 500, 100), _dev('bb', 'B', 1000, 500, 100)]

    report = check_device_freshness_from_samples(s1, s2)

    assert report.no_peer_advanced is True
    assert report.findings == []
    assert report.validation_passed is True
    assert 'inform interval' in report.message.lower()


def test_device_absent_from_second_sample_is_reported() -> None:
    """A device that vanished between samples is a distinct condition."""
    s1 = [_dev('aa', 'Gone', 1000, 500, 100), _dev('bb', 'Peer', 1000, 500, 100)]
    s2 = [_dev('bb', 'Peer', 1080, 900, 180)]

    report = check_device_freshness_from_samples(s1, s2)

    assert 'Gone' in report.disappeared


def test_reboot_is_detected_by_uptime_going_backwards() -> None:
    """A reboot resets uptime; that is not staleness and must be labelled correctly."""
    s1 = [_dev('aa', 'Rebooted', 1000, 5000, 9000)]
    s2 = [_dev('aa', 'Rebooted', 1080, 20, 30)]

    report = check_device_freshness_from_samples(s1, s2)

    assert report.rebooted == ['Rebooted']
    assert report.stale_count == 0


def test_single_sample_summary_flags_disconnected_state() -> None:
    """Cheap single-shot mode: state != 1 OR an old last_seen means data is a snapshot.

    Note both conditions matter independently — a device can report state=1 while its
    last_seen is hours old, and that data is still untrustworthy.
    """
    now = 1_000_000
    devices = [
        _dev('aa', 'Live', now - 30, 500, 100, state=1),
        _dev('bb', 'Disconnected', now - 4 * 3600, 500, 100, state=0),
    ]

    summary = summarise_freshness_from_data(devices, now=now)

    assert summary.not_informing == ['Disconnected']
    stale = [d for d in summary.devices if d.device == 'Disconnected'][0]
    assert stale.data_age_seconds is not None and stale.data_age_seconds >= 4 * 3600
    assert stale.trustworthy is False
    live = [d for d in summary.devices if d.device == 'Live'][0]
    assert live.trustworthy is True


def test_state_ok_but_ancient_last_seen_is_untrustworthy() -> None:
    """The trap in its purest form: looks connected, data is hours old."""
    now = 1_000_000
    devices = [_dev('cc', 'LooksFine', now - 3 * 3600, 500, 100, state=1)]

    summary = summarise_freshness_from_data(devices, now=now)

    rec = summary.devices[0]
    assert rec.trustworthy is False
    assert 'last_seen' in rec.reason
    assert summary.not_informing == []
