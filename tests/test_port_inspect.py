"""Unit tests for port_inspect core logic (no live controller)."""

from __future__ import annotations

import pytest
from unifi_mapper.port_inspect import (
    FreshnessReport,
    IdentityMatch,
    _compute_freshness,
    _resolve_mac,
    inspect_port,
    resolve_switch,
    resolve_switch_match,
)
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# resolve_switch
# ---------------------------------------------------------------------------


def _fake_client(devices):
    """Return a mocked UnifiApiClient whose get_devices yields the given list."""
    c = MagicMock()
    c.get_devices.return_value = {'data': devices}
    return c


def test_resolve_switch_by_name():
    """resolve_switch matches switches by case-insensitive name substring."""
    devices = [
        {'_id': '1', 'type': 'usw', 'name': 'Mike2 USW Flex 2.5G 8 PoE', 'model': 'USWED37'},
        {'_id': '2', 'type': 'usw', 'name': 'Hotel3 USW Lite 8 PoE', 'model': 'USL8LP'},
        {'_id': '3', 'type': 'uap', 'name': 'Lounge AP'},
    ]
    c = _fake_client(devices)
    got = resolve_switch(c, 'default', 'Lounge')
    assert got['_id'] == '1'


def test_resolve_switch_multi_token_finds_with_gaps():
    """resolve_switch matches when every token appears in the name, even with noise between."""
    devices = [
        {'_id': '1', 'type': 'usw', 'name': 'Mike2 USW Flex 2.5G 8 PoE', 'model': 'A'},
        {'_id': '2', 'type': 'usw', 'name': 'Mike2 USW Lite 8 PoE', 'model': 'B'},
    ]
    c = _fake_client(devices)
    got = resolve_switch(c, 'default', 'Lounge Flex 8')
    assert got['_id'] == '1'


def test_resolve_switch_ambiguous():
    """resolve_switch raises LookupError when multiple switches match."""
    devices = [
        {'_id': '1', 'type': 'usw', 'name': 'Lounge USW Flex 8', 'model': 'A'},
        {'_id': '2', 'type': 'usw', 'name': 'Lounge USW Lite 8', 'model': 'B'},
    ]
    c = _fake_client(devices)
    with pytest.raises(LookupError, match='Ambiguous'):
        resolve_switch(c, 'default', 'Lounge')


def test_resolve_switch_not_found():
    """resolve_switch raises LookupError with hint list when nothing matches."""
    devices = [{'_id': '1', 'type': 'usw', 'name': 'Office', 'model': 'X'}]
    c = _fake_client(devices)
    with pytest.raises(LookupError, match='No switch matched'):
        resolve_switch(c, 'default', 'nonexistent')


def test_resolve_switch_says_when_the_controller_returned_no_devices():
    """An empty device list (wrong site, no permission) is not reported as 'no match'."""
    with pytest.raises(LookupError, match='returned no devices'):
        resolve_switch(_fake_client([]), 'default', 'Office')


def test_resolve_switch_by_ip_or_mac():
    """resolve_switch also matches on IP and MAC substrings."""
    devices = [
        {
            '_id': '1',
            'type': 'usw',
            'name': 'A',
            'ip': '198.51.100.50',
            'mac': 'aa:bb:cc:dd:ee:ff',
        },
    ]
    c = _fake_client(devices)
    assert resolve_switch(c, 'default', '198.51.100.50')['_id'] == '1'
    assert resolve_switch(c, 'default', 'AA:BB:CC')['_id'] == '1'


# The three-switch set that made 'USW Flex XG' ambiguous before exact matching existed.
FLEX_XG_SWITCHES = [
    {
        '_id': 'ab0000000000000000000001',
        'type': 'usw',
        'name': 'USW Flex XG',
        'model': 'USFXG',
        'mac': '02:00:00:00:00:01',
        'ip': '192.0.2.5',
    },
    {
        '_id': '0000000000000000000000a2',
        'type': 'usw',
        'name': 'Hotel3 USW Flex XG 10G',
        'model': 'USFXG',
        'mac': '02:00:00:00:00:02',
        'ip': '192.0.2.50',
    },
    {
        '_id': '0000000000000000000000a3',
        'type': 'usw',
        'name': 'Xray3 USW Flex XG 10G',
        'model': 'USFXG',
        'mac': '02:00:00:00:00:03',
        'ip': '192.0.2.51',
    },
    {'_id': '0000000000000000000000a4', 'type': 'uap', 'name': 'USW Flex XG AP', 'ip': '1'},
]


def test_resolve_switch_exact_name_beats_token_match():
    """An exact name wins even though two other names contain every token."""
    c = _fake_client(FLEX_XG_SWITCHES)
    switch, matched_by, candidates = resolve_switch_match(c, 'default', 'usw flex xg')
    assert switch['_id'] == 'ab0000000000000000000001'
    assert matched_by == 'exact_name'
    assert candidates == [switch]
    assert resolve_switch(c, 'default', 'USW Flex XG')['_id'] == 'ab0000000000000000000001'


@pytest.mark.parametrize('query', ['02:00:00:00:00:02', '02-00-00-00-00-02', '0200.0000.0002'])
def test_resolve_switch_exact_mac_in_any_notation_wins(query):
    """A full MAC resolves directly, whatever separator style is used."""
    c = _fake_client(FLEX_XG_SWITCHES)
    switch, matched_by, _ = resolve_switch_match(c, 'default', query)
    assert switch['name'] == 'Hotel3 USW Flex XG 10G'
    assert matched_by == 'mac'


def test_resolve_switch_exact_ip_beats_substring():
    """'192.0.2.5' is a substring of '192.0.2.50' and '.51', but the exact IP wins."""
    c = _fake_client(FLEX_XG_SWITCHES)
    switch, matched_by, _ = resolve_switch_match(c, 'default', '192.0.2.5')
    assert switch['name'] == 'USW Flex XG'
    assert matched_by == 'ip'


def test_resolve_switch_partial_name_stays_ambiguous_and_lists_candidates():
    """'Flex XG' matches all three switches; the error names each with MAC and model."""
    c = _fake_client(FLEX_XG_SWITCHES)
    with pytest.raises(LookupError, match='Ambiguous') as excinfo:
        resolve_switch(c, 'default', 'Flex XG')
    message = str(excinfo.value)
    for mac in ('02:00:00:00:00:01', '02:00:00:00:00:02', '02:00:00:00:00:03'):
        assert mac in message
    assert 'USFXG' in message
    assert 'USW Flex XG AP' not in message  # the AP is not a switch


def test_resolve_switch_match_can_consider_every_device_type():
    """device_types=None lets callers resolve APs and gateways too."""
    c = _fake_client(FLEX_XG_SWITCHES)
    device, matched_by, _ = resolve_switch_match(c, 'default', 'USW Flex XG AP', device_types=None)
    assert device['type'] == 'uap'
    assert matched_by == 'exact_name'
    with pytest.raises(LookupError, match='No switch matched'):
        resolve_switch(c, 'default', 'USW Flex XG AP 2')


# ---------------------------------------------------------------------------
# _resolve_mac
# ---------------------------------------------------------------------------


def test_resolve_mac_adopted_device():
    """_resolve_mac returns kind='device' for an adopted-UniFi-gear MAC."""
    dev_idx = {'02:00:10:00:00:01': {'name': 'UDM', 'model': 'UDMPROMAX', 'ip': '10.0.0.1'}}
    got = _resolve_mac('02:00:10:00:00:01', dev_idx, {})
    assert got.kind == 'device'
    assert got.name == 'UDM'
    assert got.model == 'UDMPROMAX'


def test_resolve_mac_historical_client():
    """_resolve_mac returns kind='client' for a historical client MAC."""
    user_idx = {
        '02:00:1c:00:00:02': {
            'name': 'axis-cam-1',
            'hostname': 'axis',
            'oui': 'Axis Communications',
        }
    }
    got = _resolve_mac('02:00:1c:00:00:02', {}, user_idx)
    assert got.kind == 'client'
    assert got.name == 'axis-cam-1'
    assert got.vendor == 'Axis Communications'


def test_resolve_mac_unknown():
    """_resolve_mac returns kind='unknown' when MAC is in neither index."""
    got = _resolve_mac('de:ad:be:ef:00:01', {}, {})
    assert got.kind == 'unknown'


def test_resolve_mac_none():
    """_resolve_mac handles a None input without raising."""
    got = _resolve_mac(None, {'anything': {}}, {'else': {}})
    assert got.kind == 'unknown'


def test_identity_label_device():
    """IdentityMatch.label for a device includes name and model."""
    m = IdentityMatch(kind='device', name='UDM', model='UDMPROMAX', ip='10.0.0.1')
    assert 'UDM' in m.label and 'UDMPROMAX' in m.label


# ---------------------------------------------------------------------------
# inspect_port (higher-level integration with mocked client)
# ---------------------------------------------------------------------------


def test_inspect_port_end_to_end_with_mocks():
    """inspect_port populates result fields and resolves last_connection MAC."""
    device_id = 'sw-abc'
    switch = {
        '_id': device_id,
        'name': 'Lounge Flex 8',
        'model': 'USWED37',
        'mac': '02:00:17:00:00:01',
        'type': 'usw',
    }
    port_table = [
        {
            'port_idx': 7,
            'up': False,
            'enable': True,
            'port_poe': True,
            'poe_class': 'Class 3',
            'last_connection': {
                'connected': False,
                'mac': '02:00:10:00:00:01',
                'connected_at': 1768400179,
                'last_seen': 1768400196,
                'ip': '192.0.2.1',
            },
        },
    ]

    c = MagicMock()
    c.is_unifi_os = True
    c.base_url = 'https://1.2.3.4'
    c.timeout = 5

    c.get_device_details.return_value = {'port_table': port_table}
    c.get_lldp_info.return_value = {}  # port down, no LLDP
    c.get_devices.return_value = {
        'data': [
            switch,
            {
                '_id': 'udm',
                'type': 'udm',
                'name': 'UDM Pro Max',
                'model': 'UDMPROMAX',
                'mac': '02:00:10:00:00:01',
                'ip': '1.2.3.5',
            },
        ]
    }

    # Two HTTP GETs: rest/user (for mac_to_user) and stat/sta (active client)
    user_resp = MagicMock()
    user_resp.json.return_value = {'data': []}
    user_resp.raise_for_status.return_value = None

    sta_resp = MagicMock()
    sta_resp.json.return_value = {'data': []}
    sta_resp.raise_for_status.return_value = None

    c.session.get.side_effect = [user_resp, sta_resp]

    result = inspect_port(c, 'default', switch, 7)
    assert result.port_idx == 7
    assert result.up is False
    assert result.last_connection['mac'] == '02:00:10:00:00:01'
    assert result.identity is not None
    assert result.identity.kind == 'device'
    assert result.identity.name == 'UDM Pro Max'
    assert result.active_client is None


def test_inspect_port_invalid_port_raises():
    """inspect_port raises LookupError for a port not in the device's port_table."""
    switch = {'_id': 'x', 'name': 's', 'model': 'm', 'mac': 'aa:bb:cc:dd:ee:ff', 'type': 'usw'}
    c = MagicMock()
    c.get_device_details.return_value = {'port_table': [{'port_idx': 1}, {'port_idx': 2}]}
    c.get_lldp_info.return_value = {}
    c.get_devices.return_value = {'data': [switch]}
    with pytest.raises(LookupError, match='Port 99 not found'):
        inspect_port(c, 'default', switch, 99)


# ---------------------------------------------------------------------------
# _compute_freshness
# ---------------------------------------------------------------------------


def test_freshness_clean_when_port_is_up():
    """No suspicion when port_table.up is true."""
    pt = {'up': True, 'last_connection': {'connected': True, 'last_seen': 1_700_000_000}}
    r = _compute_freshness(pt, active_client=None, now_epoch=1_700_000_000)
    assert r.is_suspicious is False
    assert r.reasons == []


def test_freshness_flags_stale_cache_scenario():
    """Replays the real 09:37 anomaly: up=false yet PoE flowing + recent last_seen."""
    pt = {
        'up': False,
        'port_poe': True,
        'poe_power': '3.58',
        'last_connection': {
            'connected': True,
            'last_seen': 1_700_000_000,
            'mac': '02:00:1c:00:00:02',
        },
    }
    active = {'mac': '02:00:1c:00:00:02', 'sw_port': 7}
    r = _compute_freshness(pt, active_client=active, now_epoch=1_700_000_000)
    assert r.is_suspicious is True
    # Should fire all four rules
    assert len(r.reasons) == 4
    assert any('last_connection.connected=true' in x for x in r.reasons)
    assert any('PoE draw' in x for x in r.reasons)
    assert any('stat/sta' in x for x in r.reasons)
    assert any('last_seen' in x for x in r.reasons)


def test_freshness_respects_recent_threshold():
    """last_seen older than threshold should NOT flag staleness on its own."""
    now = 1_700_000_000
    pt = {
        'up': False,
        'last_connection': {'connected': False, 'last_seen': now - 3600},
    }
    r = _compute_freshness(pt, active_client=None, now_epoch=now)
    assert r.is_suspicious is False
    assert r.last_seen_age_seconds == 3600


def test_freshness_handles_missing_last_connection():
    """Down port with no last_connection block is not suspicious."""
    r = _compute_freshness({'up': False}, active_client=None, now_epoch=1_700_000_000)
    assert r.is_suspicious is False
    assert r.last_seen_age_seconds is None


def test_freshness_label():
    """FreshnessReport.label summarises suspicion in one line."""
    clean = FreshnessReport(is_suspicious=False)
    assert clean.label == 'consistent'
    dirty = FreshnessReport(is_suspicious=True, reasons=['a', 'b'])
    assert dirty.label == 'possibly stale: a; b'


def test_freshness_poe_rule_requires_port_poe_flag():
    """PoE draw rule only fires when the port is PoE-capable."""
    # Non-PoE port with a poe_power artefact: don't trip.
    pt = {'up': False, 'poe_power': '2.0', 'last_connection': {}}
    r = _compute_freshness(pt, active_client=None, now_epoch=1_700_000_000)
    assert r.is_suspicious is False


def test_inspect_port_populates_freshness():
    """inspect_port must attach a FreshnessReport to its result."""
    switch = {'_id': 'x', 'name': 's', 'model': 'm', 'mac': 'aa:bb:cc:dd:ee:ff', 'type': 'usw'}
    c = MagicMock()
    c.is_unifi_os = True
    c.base_url = 'https://host'
    c.timeout = 5
    c.get_device_details.return_value = {
        'port_table': [{'port_idx': 1, 'up': True, 'last_connection': {}}]
    }
    c.get_lldp_info.return_value = {}
    c.get_devices.return_value = {'data': [switch]}
    user_resp = MagicMock()
    user_resp.json.return_value = {'data': []}
    user_resp.raise_for_status.return_value = None
    sta_resp = MagicMock()
    sta_resp.json.return_value = {'data': []}
    sta_resp.raise_for_status.return_value = None
    c.session.get.side_effect = [user_resp, sta_resp]

    result = inspect_port(c, 'default', switch, 1)
    assert isinstance(result.freshness, FreshnessReport)
    assert result.freshness.is_suspicious is False
