"""Issue 096: `get_lldp_info` reads LLDP from the site-wide `stat/device` record.

On a current controller the per-device `stat/device/<_id>` answer carried no `lldp_table` for
any of 13 switches while the site-wide `stat/device` answer carried 43 rows across them, so
every diagram lost its LLDP links. The site-wide record is already fetched for the MAC-to-name
cache; LLDP is read from it first, and the per-device fetch is only a fallback.
"""

from __future__ import annotations

from tests.fixtures_unifi import (
    API_RE,
    PEER_MAC,
    SITE,
    SWITCH_ID,
    FakeSession,
    default_routes,
    fake_client,
    fake_switch,
)


def _routes_where_the_per_device_path_knows_nothing_by_id() -> dict:
    """The live shape: the site-wide record has the LLDP rows; the per-_id path answers a record
    without them (so a fallback that only fires on an EMPTY answer never runs)."""
    trimmed = {k: v for k, v in fake_switch().items() if k != 'lldp_table'}
    return default_routes(device={'data': [trimmed]})


def test_lldp_comes_from_the_site_wide_record_when_the_per_device_path_has_none() -> None:
    session = FakeSession(_routes_where_the_per_device_path_knows_nothing_by_id())
    client = fake_client(session)

    lldp = client.get_lldp_info(SITE, SWITCH_ID)

    assert set(lldp) == {'2'}, "the switch's one LLDP neighbour, on local port 2"
    assert lldp['2']['chassis_id'].lower() == PEER_MAC.lower()
    # One site-wide request serves both the MAC cache and the LLDP rows; the per-device path
    # is not consulted when the site-wide record has the table.
    assert session.paths('GET').count(f'/proxy/network/api/s/{SITE}/stat/device') == 1
    assert f'/proxy/network/api/s/{SITE}/stat/device/{SWITCH_ID}' not in session.paths('GET')


def test_the_per_device_fetch_is_still_the_fallback_when_the_site_wide_record_has_no_table() -> (
    None
):
    bare = {k: v for k, v in fake_switch().items() if k != 'lldp_table'}
    routes = default_routes(devices={'data': [bare]})
    session = FakeSession(routes)
    client = fake_client(session)

    lldp = client.get_lldp_info(SITE, SWITCH_ID)

    assert set(lldp) == {'2'}  # from the per-device answer, which still carries the table
    assert f'/proxy/network/api/s/{SITE}/stat/device/{SWITCH_ID}' in session.paths('GET')


def test_a_hyphenated_uuid_id_still_finds_its_site_wide_record() -> None:
    """A current controller's _id is a UUID; _validate_device_id strips the hyphens before the
    lookup, which is what hid every switch's LLDP live (36-character ids, 0 of 12 found)."""
    uuid_id = '4bff3306-5ae7-42ee-b88d-51601ca988b0'
    switch = {**fake_switch(), '_id': uuid_id}
    routes = default_routes(devices={'data': [switch]})
    routes[('GET', rf'^{API_RE}/stat/device/[0-9a-f]+$')] = (400, {'meta': {'rc': 'error'}})
    routes[('GET', rf'^{API_RE}/rest/device/[0-9a-f]+$')] = (404, {'meta': {'rc': 'error'}})
    session = FakeSession(routes)
    client = fake_client(session)

    lldp = client.get_lldp_info(SITE, uuid_id)

    assert set(lldp) == {'2'}
    assert not [p for p in session.paths('GET') if '/stat/device/' in p or '/rest/device/' in p]
