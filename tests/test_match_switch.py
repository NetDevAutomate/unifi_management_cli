"""Tests for the pure switch matcher shared by `ports` commands and the fleet audits."""

import pytest
from tests.fixtures_unifi import (
    OTHER_SWITCH_NAME,
    SITE,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    default_routes,
    fake_client,
    fake_devices,
)
from unifi_mapper.port_inspect import match_switch, resolve_switch_match


pytestmark = pytest.mark.usefixtures('block_network')


def _dev(name: str, mac: str, ip: str, model: str = 'USFXG', type_: str = 'usw') -> dict:
    return {'name': name, 'mac': mac, 'ip': ip, 'model': model, 'type': type_}


DEVICES = [
    _dev('USW Flex XG', '02:00:00:00:00:01', '192.0.2.10'),
    _dev('Hotel3 USW Flex XG 10G', '02:00:00:00:00:02', '192.0.2.11'),
    _dev('Mike2 USW Flex 2.5G 8 PoE', '02:00:00:00:00:03', '192.0.2.12', model='USWF8'),
    _dev('Mike2 AP', '02:00:00:00:00:04', '192.0.2.13', model='U7PRO', type_='uap'),
]


def test_exact_name_beats_a_token_match():
    device, matched_by, candidates = match_switch(DEVICES, 'usw flex xg')
    assert device['name'] == 'USW Flex XG'
    assert matched_by == 'exact_name' and candidates == [device]


@pytest.mark.parametrize(
    'query', ['02:00:00:00:00:02', '02-00-00-00-00-02', '0200.0000.0002', '020000000002']
)
def test_mac_matches_in_any_notation(query):
    device, matched_by, _ = match_switch(DEVICES, query.upper())
    assert device['name'] == 'Hotel3 USW Flex XG 10G' and matched_by == 'mac'


def test_ip_then_tokens_then_substring():
    assert match_switch(DEVICES, '192.0.2.12')[1] == 'ip'
    assert match_switch(DEVICES, 'Mike2 Flex 8')[1] == 'tokens'
    assert match_switch(DEVICES, 'USWF8')[1] == 'substring'


def test_ambiguity_lists_every_candidate():
    with pytest.raises(LookupError) as e:
        match_switch(DEVICES, 'flex')
    message = str(e.value)
    assert "Ambiguous match for 'flex' (substring)" in message
    for device in DEVICES[:3]:
        assert repr(device['name']) in message and device['mac'] in message
    assert 'Mike2 AP' not in message
    assert 'Pass the exact name or the MAC address.' in message


def test_no_match_lists_known_switches_or_devices():
    with pytest.raises(LookupError, match=r"No switch matched 'nope'\. Known switches: "):
        match_switch(DEVICES, 'nope')
    with pytest.raises(LookupError, match=r"No device matched 'nope'\. Known devices: .*Mike2 AP"):
        match_switch(DEVICES, 'nope', device_types=None)


def test_device_types_none_considers_every_device_and_junk_is_ignored():
    device, matched_by, _ = match_switch(['junk', None, *DEVICES], 'mike2 ap', device_types=None)
    assert device['name'] == 'Mike2 AP' and matched_by == 'exact_name'
    with pytest.raises(LookupError):
        match_switch(DEVICES, 'mike2 ap')


def test_an_empty_list_is_a_no_match_not_a_crash():
    with pytest.raises(LookupError, match='No switch matched'):
        match_switch([], SWITCH_NAME)


@pytest.mark.parametrize('query', [SWITCH_NAME, SWITCH_MAC, OTHER_SWITCH_NAME, 'flex xg 10g'])
def test_resolve_switch_match_is_fetch_plus_match_switch(query):
    session = FakeSession(default_routes())
    assert resolve_switch_match(fake_client(session), SITE, query) == match_switch(
        fake_devices(), query
    )
    assert session.paths('GET') == ['/proxy/network/api/s/default/stat/device']
