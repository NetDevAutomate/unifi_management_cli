"""Tests for the fleet-wide link-speed audit (no live controller)."""

import pytest
from tests.fixtures_unifi import (
    NOW,
    OTHER_SPEED_CAPS,
    OTHER_SWITCH_MAC,
    PEER_MAC,
    PROF_TRUNK,
    PROFILE_10G_NAME,
    SITE,
    SPEED_CAPS,
    SWITCH_MAC,
    SWITCH_NAME,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_networkconf,
    fake_other_switch,
    fake_peer,
    fake_port,
    fake_port_5,
    fake_portconf,
    fake_switch,
)
from typing import Any
from unifi_mapper.analysis import link_speed_audit
from unifi_mapper.analysis.link_speed_audit import (
    LinkSpeedAuditReport,
    LinkSpeedFinding,
    audit_link_speeds_from_data,
    collect_link_speed_audit,
)
from unifi_mapper.core.utils.readonly import ReadOnlySession, install_read_only_guard
from unifi_mapper.diagnostic_reads import Collection, SwitchNotFound
from unifi_mapper.port_diagnostics import IntegrationDevice, IntegrationPorts


pytestmark = pytest.mark.usefixtures('block_network')

AUTO_OVERRIDES = [{'port_idx': 2, 'portconf_id': PROF_TRUNK, 'name': 'Uplink'}]


def _clean(device: dict[str, Any]) -> dict[str, Any]:
    return Collection().clean(device, 'device.raw')


def _ports(*, port5: dict[str, Any] | None = None, **by_idx: dict[str, Any]) -> list[dict]:
    """The fixture switch's port table with per-port overrides (p1=..., p3=...)."""
    table = [
        fake_port(1, **by_idx.get('p1', {})),
        fake_port(
            2, portconf_id=PROF_TRUNK, forward='all', is_uplink=True, **by_idx.get('p2', {})
        ),
        fake_port(3, **by_idx.get('p3', {})),
        fake_port(4, up=False, speed_caps=OTHER_SPEED_CAPS),
        fake_port_5(**(port5 or {})),
    ]
    return table


def _devices(**switch_over: Any) -> list[dict[str, Any]]:
    return [_clean(fake_switch(**switch_over)), _clean(fake_other_switch()), _clean(fake_peer())]


def _integration(
    *devices: tuple[str, list[dict[str, Any]]], status: str = 'ok'
) -> IntegrationPorts:
    return IntegrationPorts(
        status=status,
        base_path_used='/proxy/network/integrations' if status == 'ok' else None,
        reason='' if status == 'ok' else 'Integration API not found',
        devices={
            mac: IntegrationDevice(device_id=f'id-{mac}', device={'interfaces': {'ports': ports}})
            for mac, ports in devices
        },
    )


UNAVAILABLE = IntegrationPorts(status='unavailable', reason='Integration API not found')
PORT5_10G = _integration((SWITCH_MAC, [{'idx': 5, 'maxSpeedMbps': 10000}]))


def _audit(
    devices: list[dict[str, Any]], integration: IntegrationPorts | None = UNAVAILABLE, **kw: Any
) -> LinkSpeedAuditReport:
    profiles = {p['_id']: p for p in Collection().clean(fake_portconf(), 'portconf')}
    networks = {n['_id']: {'name': n['name'], 'vlan': n['vlan']} for n in fake_networkconf()}
    mac_to_dev = {d['mac'].lower(): d for d in devices}
    return audit_link_speeds_from_data(
        devices, profiles, networks, mac_to_dev, {}, [], integration, NOW, **kw
    )


def _on(report: LinkSpeedAuditReport, mac: str, idx: int) -> LinkSpeedFinding | None:
    return next((f for f in report.findings if f.switch_mac == mac and f.port_idx == idx), None)


def _codes(report: LinkSpeedAuditReport) -> dict[tuple[str | None, int], str]:
    return {(f.switch_mac, f.port_idx): f.code for f in report.findings}


# ---------------------------------------------------------------------------
# UGREEN-shaped fixtures (a)-(e)
# ---------------------------------------------------------------------------


def test_a_forced_10g_port_that_is_down_is_forced_speed_link_down():
    devices = _devices(port_table=_ports(port5={'up': False, 'speed': 0}))
    report = _audit(devices, PORT5_10G)
    finding = _on(report, SWITCH_MAC, 5)
    assert finding and finding.code == 'FORCED_SPEED_LINK_DOWN' and finding.severity == 'HIGH'
    assert finding.forced_speed_mbps == 10000 and finding.autoneg is False
    assert finding.profile_name == PROFILE_10G_NAME
    assert finding.sources['forced_speed_mbps'] == 'profile'
    assert finding.sources['profile_id'] == 'override'
    assert report.validation_passed is False


def test_b_auto_at_5000_with_integration_max_10000_is_below_port_capability():
    report = _audit(_devices(port_overrides=AUTO_OVERRIDES), PORT5_10G)
    finding = _on(report, SWITCH_MAC, 5)
    assert finding and finding.code == 'BELOW_PORT_CAPABILITY' and finding.severity == 'WARNING'
    assert finding.capability_source == 'integration_api'
    assert finding.negotiated_mbps == 5000 and finding.local_max_mbps == 10000
    assert finding.peer_max_mbps is None
    assert 'unverified' in finding.message
    # Evidence is carried even though a stronger code fired.
    assert [p.port_idx for p in finding.same_caps_faster_ports] == [1, 2, 3]
    assert report.validation_passed is True
    assert report.integration.status == 'ok'


def test_c_integration_unavailable_falls_back_to_same_caps_peers():
    report = _audit(_devices(port_overrides=AUTO_OVERRIDES), UNAVAILABLE)
    finding = _on(report, SWITCH_MAC, 5)
    assert finding and finding.code == 'BELOW_PEER_PORTS_SAME_CAPS'
    assert finding.capability_source == 'unavailable' and finding.local_max_mbps is None
    faster = {p.port_idx: p.negotiated_mbps for p in finding.same_caps_faster_ports}
    assert faster[2] == 10000
    assert 'port 2 at 10000 Mbps' in finding.message
    assert 'not a decoded capability' in finding.message
    assert report.integration.status == 'unavailable'


@pytest.mark.parametrize('integration', [UNAVAILABLE, None, _integration((SWITCH_MAC, []))])
def test_d_no_capability_and_no_same_caps_peer_is_capability_unknown_only(integration):
    devices = _devices(port_overrides=AUTO_OVERRIDES, port_table=_ports(port5={'speed_caps': 999}))
    assert _on(_audit(devices, integration), SWITCH_MAC, 5) is None
    report = _audit(devices, integration, include_ok=True)
    finding = _on(report, SWITCH_MAC, 5)
    assert finding and finding.code == 'CAPABILITY_UNKNOWN' and finding.severity == 'INFO'
    assert all(f.code != 'BELOW_PORT_CAPABILITY' for f in report.findings)


def test_e_speed_caps_is_carried_verbatim_and_never_decoded():
    devices = _devices(port_overrides=AUTO_OVERRIDES)
    before = _audit(devices, UNAVAILABLE, include_ok=True)
    assert _on(before, SWITCH_MAC, 5).speed_caps_raw == SPEED_CAPS  # type: ignore[union-attr]

    remap = {SPEED_CAPS: 'opaque-a', OTHER_SPEED_CAPS: 'opaque-b'}
    for device in devices:
        for entry in device.get('port_table') or []:
            entry['speed_caps'] = remap[entry['speed_caps']]
    after = _audit(devices, UNAVAILABLE, include_ok=True)
    assert _codes(after) == _codes(before)
    assert _on(after, SWITCH_MAC, 5).speed_caps_raw == 'opaque-a'  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# One fixture per remaining code
# ---------------------------------------------------------------------------


def test_half_duplex_is_critical():
    report = _audit(_devices(port_table=_ports(p3={'full_duplex': False, 'speed': 100})))
    finding = _on(report, SWITCH_MAC, 3)
    assert finding and finding.code == 'HALF_DUPLEX' and finding.severity == 'CRITICAL'
    assert report.validation_passed is False


def test_forced_speed_up_at_another_rate_is_a_mismatch():
    finding = _on(_audit(_devices(), PORT5_10G), SWITCH_MAC, 5)
    assert finding and finding.code == 'FORCED_SPEED_MISMATCH' and finding.severity == 'HIGH'
    assert finding.negotiated_mbps == 5000 and finding.forced_speed_mbps == 10000


def _peer_with_reciprocal_lldp() -> dict[str, Any]:
    peer = fake_peer()
    peer['lldp_table'] = [{'local_port_idx': 9, 'chassis_id': SWITCH_MAC.upper()}]
    return _clean(peer)


@pytest.mark.parametrize(('peer_max', 'expected'), [(10000, 'BELOW_BOTH_ENDS'), (2500, None)])
def test_below_both_ends_needs_both_integration_maxima(peer_max, expected):
    switch = _clean(fake_switch(port_table=_ports(p2={'speed': 2500})))
    devices = [switch, _clean(fake_other_switch()), _peer_with_reciprocal_lldp()]
    integration = _integration(
        (SWITCH_MAC, [{'idx': 2, 'maxSpeedMbps': 10000}, {'idx': 5, 'maxSpeedMbps': 10000}]),
        (PEER_MAC, [{'idx': 9, 'maxSpeedMbps': peer_max}]),
    )
    finding = _on(_audit(devices, integration), SWITCH_MAC, 2)
    if expected is None:
        assert finding is None
        return
    assert finding and finding.code == expected and finding.severity == 'HIGH'
    assert finding.peer_max_mbps == peer_max and finding.peer_name == 'Test Gateway'


def test_peer_capability_needs_the_reciprocal_lldp_entry():
    switch = _clean(fake_switch(port_table=_ports(p2={'speed': 2500})))
    devices = [switch, _clean(fake_peer())]
    integration = _integration(
        (SWITCH_MAC, [{'idx': 2, 'maxSpeedMbps': 10000}]),
        (PEER_MAC, [{'idx': 9, 'maxSpeedMbps': 10000}]),
    )
    finding = _on(_audit(devices, integration), SWITCH_MAC, 2)
    assert finding and finding.code == 'BELOW_PORT_CAPABILITY' and finding.peer_max_mbps is None


def test_include_ok_lists_healthy_up_ports_only():
    report = _audit(_devices(), PORT5_10G, include_ok=True)
    codes = _codes(report)
    assert codes[(SWITCH_MAC, 1)] == 'OK' and codes[(OTHER_SWITCH_MAC, 1)] == 'OK'
    assert (SWITCH_MAC, 4) not in codes  # down, autoneg: nothing to audit
    assert codes[(SWITCH_MAC, 5)] == 'FORCED_SPEED_MISMATCH'
    assert report.findings[0].severity == 'HIGH'  # severity order


def test_disabled_ports_are_skipped():
    devices = _devices(port_table=_ports(port5={'enable': False, 'up': False, 'speed': 0}))
    report = _audit(devices, PORT5_10G, include_ok=True)
    assert _on(report, SWITCH_MAC, 5) is None
    assert report.ports_analyzed == 4 + 2  # 4 enabled on the switch, 2 on the other one


# ---------------------------------------------------------------------------
# Freshness, scope and pagination
# ---------------------------------------------------------------------------


def test_stale_devices_are_excluded_and_named():
    report = _audit(_devices(last_seen=NOW - 7200), PORT5_10G, include_ok=True)
    assert all(f.switch_mac != SWITCH_MAC for f in report.findings)
    assert report.switches_analyzed == 1
    assert len(report.data_freshness_warnings) == 1
    assert SWITCH_NAME in report.data_freshness_warnings[0]
    assert 'excluded' in report.data_freshness_warnings[0]


def test_switch_scope_audits_one_switch():
    report = _audit(_devices(), PORT5_10G, include_ok=True, switch_mac=OTHER_SWITCH_MAC)
    assert {f.switch_mac for f in report.findings} == {OTHER_SWITCH_MAC}
    assert report.switches_analyzed == 1


def test_pagination():
    devices = _devices(port_table=_ports(p1={'full_duplex': False}, p3={'full_duplex': False}))
    full = _audit(devices, PORT5_10G)
    assert full.findings_total == 3 and not full.truncated and full.next_offset is None
    first = _audit(devices, PORT5_10G, limit=2)
    assert [f.port_idx for f in first.findings] == [1, 3]
    assert first.truncated is True and first.next_offset == 2 and first.findings_total == 3
    second = _audit(devices, PORT5_10G, limit=2, offset=2)
    assert [f.port_idx for f in second.findings] == [5]
    assert second.truncated is False and second.next_offset is None
    assert second.validation_passed is False  # judged over every finding, not the page


@pytest.mark.parametrize(('limit', 'offset'), [(0, 0), (1001, 0), (10, -1), (True, 0)])
def test_out_of_range_paging_is_a_value_error(limit, offset):
    with pytest.raises(ValueError):
        _audit(_devices(), limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Fetch over the fake controller
# ---------------------------------------------------------------------------


def _guarded(**routes: Any):
    session = FakeSession(default_routes(**routes))
    client = fake_client(session)
    install_read_only_guard(client)
    return client, session


def test_collect_reads_every_source_once_and_only_gets():
    client, session = _guarded()
    report = collect_link_speed_audit(client, SITE, now=lambda: NOW)
    assert isinstance(client.session, ReadOnlySession)
    assert {c['method'] for c in session.calls} == {'GET'}
    paths = session.paths()
    assert paths.count('/proxy/network/api/s/default/rest/portconf') == 1
    assert paths.count('/proxy/network/api/s/default/rest/networkconf') == 1
    assert paths.count('/proxy/network/api/s/default/stat/sta') == 1
    assert paths.count('/proxy/network/integrations/v1/sites') == 1
    assert report.integration.status == 'ok'
    assert report.integration.base_path_used == '/proxy/network/integrations'
    finding = _on(report, SWITCH_MAC, 5)
    assert finding and finding.code == 'FORCED_SPEED_MISMATCH'
    assert finding.local_max_mbps == 10000 and finding.capability_source == 'integration_api'
    assert report.switches_analyzed == 2 and not report.errors
    assert 'device.raw.x_authkey' in report.sanitised_paths
    assert_no_secrets(report.model_dump(mode='json'))


def test_collect_scopes_to_an_exact_switch_name():
    client, _ = _guarded()
    report = collect_link_speed_audit(
        client, SITE, switch=SWITCH_NAME, include_ok=True, now=lambda: NOW
    )
    assert {f.switch_mac for f in report.findings} == {SWITCH_MAC}


def test_collect_unknown_switch_lists_candidates():
    client, _ = _guarded()
    with pytest.raises(SwitchNotFound, match='Known switches'):
        collect_link_speed_audit(client, SITE, switch='nope', now=lambda: NOW)


def test_collect_without_unifi_os_skips_the_integration_api():
    session = FakeSession(default_routes())
    client = fake_client(session, unifi_os=False)
    report = collect_link_speed_audit(client, SITE, now=lambda: NOW)
    assert report.integration.status == 'skipped'
    assert not any('/v1/' in p for p in session.paths())
    finding = _on(report, SWITCH_MAC, 5)
    assert finding.capability_source == 'unavailable'  # type: ignore[union-attr]


def test_collect_records_an_empty_device_list():
    client, _ = _guarded(devices={'data': []})
    report = collect_link_speed_audit(client, SITE, now=lambda: NOW)
    assert report.switches_analyzed == 0 and report.findings == []
    assert [e.section for e in report.errors] == ['devices']
    assert report.integration.status == 'skipped'


def test_collect_uses_the_module_clock_by_default(monkeypatch):
    monkeypatch.setattr(link_speed_audit, '_now', lambda: NOW + 7200)
    client, _ = _guarded()
    report = collect_link_speed_audit(client, SITE)
    assert report.data_freshness_warnings and report.switches_analyzed == 1
