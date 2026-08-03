"""Tests for atomic per-device radio writes and channel type coercion.

Two defects found while applying a hand-built radio plan on 2026-08-03:

1. `apply_radio_config` fetched devices once, then rebuilt every PUT payload from that
   same cached device dict. Passing two changes for one AP (e.g. `ng` width and `na`
   channel) meant the second PUT was built from the *original* radio_table and silently
   reverted the first. Changes must be merged into one payload per device.

2. Fixed channels are stored as `int` by the controller (`Lounge na=60`,
   `Puzzle na=157`); only the sentinel `'auto'` is a string. Writing `'149'` as a string
   is the silent-no-op class of failure this repo exists to catch, so the builder
   coerces channel to int.
"""

from __future__ import annotations

from unifi_mapper.analysis.radio_config import build_radio_table_updates


def _ap(name: str, radios: list[dict]) -> dict:
    return {
        '_id': f'id-{name}',
        'mac': f'mac-{name}',
        'name': name,
        'type': 'uap',
        'radio_table': radios,
    }


def _radio(radio_id: str, **kw) -> dict:
    base = {'radio': radio_id, 'channel': 'auto', 'ht': '80'}
    base.update(kw)
    return base


# ─── Defect: two changes to one device must merge into a single payload ───────


def test_two_radio_changes_to_one_device_produce_one_payload() -> None:
    devices = [_ap('AP1', [_radio('ng', channel=6, ht='40'), _radio('na')])]
    changes = [
        {'device_id': 'id-AP1', 'radio': 'ng', 'ht': '20'},
        {'device_id': 'id-AP1', 'radio': 'na', 'channel': 132},
    ]

    plans, missing = build_radio_table_updates(devices, changes)

    assert missing == []
    assert len(plans) == 1, 'expected a single merged payload per device'


def test_both_radio_changes_survive_the_merge() -> None:
    """The regression: the na change used to overwrite the ng change."""
    devices = [_ap('AP1', [_radio('ng', channel=6, ht='40'), _radio('na')])]
    changes = [
        {'device_id': 'id-AP1', 'radio': 'ng', 'ht': '20'},
        {'device_id': 'id-AP1', 'radio': 'na', 'channel': 132},
    ]

    plans, _ = build_radio_table_updates(devices, changes)
    table = {r['radio']: r for r in plans[0]['radio_table']}

    assert table['ng']['ht'] == '20'
    assert table['na']['channel'] == 132


def test_untouched_radios_are_preserved_verbatim() -> None:
    """A tri-band AP's 6e radio must pass through unchanged."""
    devices = [
        _ap('AP1', [_radio('ng', channel=11, ht='20'), _radio('na'), _radio('6e', ht='320')])
    ]
    changes = [{'device_id': 'id-AP1', 'radio': 'na', 'channel': 36}]

    plans, _ = build_radio_table_updates(devices, changes)
    table = {r['radio']: r for r in plans[0]['radio_table']}

    assert table['6e']['ht'] == '320'
    assert table['ng']['channel'] == 11
    assert len(plans[0]['radio_table']) == 3


# ─── Defect: channel must be written as int, not str ──────────────────────────


def test_channel_is_coerced_to_int() -> None:
    devices = [_ap('AP1', [_radio('na')])]
    changes = [{'device_id': 'id-AP1', 'radio': 'na', 'channel': '149'}]

    plans, _ = build_radio_table_updates(devices, changes)
    ch = plans[0]['radio_table'][0]['channel']

    assert ch == 149
    assert isinstance(ch, int)


def test_auto_channel_sentinel_is_preserved_as_string() -> None:
    devices = [_ap('AP1', [_radio('na', channel=36)])]
    changes = [{'device_id': 'id-AP1', 'radio': 'na', 'channel': 'auto'}]

    plans, _ = build_radio_table_updates(devices, changes)

    assert plans[0]['radio_table'][0]['channel'] == 'auto'


# ─── Payload shape and error handling ────────────────────────────────────────


def test_payload_carries_identity_and_config_version() -> None:
    devices = [_ap('AP1', [_radio('na')])]
    devices[0]['config_version'] = 'cfg-7'
    changes = [{'device_id': 'id-AP1', 'radio': 'na', 'channel': 36}]

    plans, _ = build_radio_table_updates(devices, changes)
    payload = plans[0]['payload']

    assert payload['_id'] == 'id-AP1'
    assert payload['mac'] == 'mac-AP1'
    assert payload['config_version'] == 'cfg-7'
    assert 'radio_table' in payload


def test_unknown_device_is_reported_not_silently_dropped() -> None:
    devices = [_ap('AP1', [_radio('na')])]
    changes = [{'device_id': 'id-GHOST', 'radio': 'na', 'channel': 36}]

    plans, missing = build_radio_table_updates(devices, changes)

    assert plans == []
    assert missing == [{'device_id': 'id-GHOST', 'status': 'NOT_FOUND'}]


def test_changes_to_different_devices_stay_separate() -> None:
    devices = [_ap('AP1', [_radio('na')]), _ap('AP2', [_radio('na')])]
    changes = [
        {'device_id': 'id-AP1', 'radio': 'na', 'channel': 36},
        {'device_id': 'id-AP2', 'radio': 'na', 'channel': 52},
    ]

    plans, _ = build_radio_table_updates(devices, changes)

    assert len(plans) == 2
    assert {p['payload']['_id'] for p in plans} == {'id-AP1', 'id-AP2'}


def test_radios_touched_are_tracked_for_result_reporting() -> None:
    devices = [_ap('AP1', [_radio('ng', channel=6), _radio('na')])]
    changes = [
        {'device_id': 'id-AP1', 'radio': 'ng', 'ht': '20'},
        {'device_id': 'id-AP1', 'radio': 'na', 'channel': 132},
    ]

    plans, _ = build_radio_table_updates(devices, changes)

    assert sorted(plans[0]['radios']) == ['na', 'ng']
    assert plans[0]['name'] == 'AP1'
