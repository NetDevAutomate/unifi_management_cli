"""Tests for the read-only port diagnostic collectors and bundle (no live controller)."""

import json
import pytest
from pathlib import Path
from tests.fixtures_unifi import (
    API,
    FAKE_AUTHKEY,
    NAS_IP,
    NAS_MAC,
    NAS_MAC_2,
    NET_GUEST,
    NET_MGMT,
    NOW,
    OTHER_SWITCH_MAC,
    PEER_MAC,
    PROF_10G,
    PROF_AUTO,
    PROFILE_10G_NAME,
    PROFILE_AUTO_NAME,
    SITE,
    SPEED_CAPS,
    SWITCH_MAC,
    SWITCH_NAME,
    V2,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_devices,
    fake_portconf,
    fake_switch,
)
from unifi_mapper.core.utils.readonly import ReadOnlySession, ReadOnlyViolation
from unifi_mapper.core.utils.redact import strip_secrets
from unifi_mapper.diagnostic_reads import (
    Collection,
    PortNotFound,
    ProfileNotFound,
    SwitchNotFound,
)
from unifi_mapper.port_diagnostics import (
    BundleQuery,
    DeviceIdentity,
    build_port_diagnostic_bundle,
    build_profile_diff,
    collect_device_identity,
    collect_integration_snapshot,
    collect_override,
    collect_port_detail,
    diff_port_profiles,
    find_profile,
    get_client_history,
    list_switch_ports,
)


pytestmark = pytest.mark.usefixtures('block_network')

ALLOWED_POSTS = {
    f'{API}/stat/event',
    f'{V2}/system-log/device-alert',
    f'{V2}/system-log/admin-activity',
    f'{V2}/system-log/update-alert',
    f'{V2}/system-log/client-alert',
}


def _client(**routes):
    session = FakeSession(default_routes(**routes))
    return fake_client(session), session


def _clean_switch() -> tuple[dict, Collection]:
    ctx = Collection()
    return ctx.clean(fake_switch(), 'device.raw'), ctx


def _profiles() -> dict[str, dict]:
    ctx = Collection()
    return {p['_id']: p for p in ctx.clean(fake_portconf(), 'portconf')}


# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------


def test_identity_reports_every_field_with_generic_thermal_and_power_capture():
    client, _ = _client()
    device, ctx = _clean_switch()
    identity = collect_device_identity(client, SITE, device, ctx, now=lambda: NOW)
    assert set(identity.model_dump()) == set(DeviceIdentity.model_fields)
    assert identity.model == 'USFXG'
    assert identity.firmware_version == '7.0.0.10000'
    assert identity.upgradable is True and identity.upgrade_to_firmware == '7.0.1.10001'
    assert identity.uptime_seconds == 86400
    assert identity.state == 1 and identity.informing is True
    assert identity.data_age_seconds == 20.0
    assert identity.system_stats == {'cpu': '7.1', 'mem': '41.2', 'uptime': '86400'}
    assert identity.sys_stats == {'loadavg_1': '0.11', 'mem_total': 1000, 'mem_used': 400}
    assert identity.thermal_fields == {'fixture_board_temp_c': 48.5}
    assert identity.power_fields == {'fixture_power_budget_w': 12.0}
    assert identity.power_source_note == 'controller record has no power-source field'
    assert identity.raw is not None and 'x_authkey' not in identity.raw
    assert 'device.raw.x_authkey' in ctx.sanitised_paths
    assert 'device.raw.port_table[4].x_port_secret' in ctx.sanitised_paths


def test_display_model_is_unresolved_when_v2_models_is_unavailable():
    client, _ = _client()
    device, ctx = _clean_switch()
    identity = collect_device_identity(client, SITE, device, ctx, now=lambda: NOW)
    assert identity.display_model is None
    assert identity.display_model_source == 'unresolved'
    assert any(e.section == 'device.display_model' for e in ctx.errors)


def test_display_model_comes_from_controller_data_only():
    client, _ = _client(models={'model_list': [{'model': 'USFXG', 'name': 'Fake Flex XG'}]})
    device, ctx = _clean_switch()
    identity = collect_device_identity(client, SITE, device, ctx, now=lambda: NOW)
    assert (identity.display_model, identity.display_model_source) == ('Fake Flex XG', 'v2.models')

    named = collect_device_identity(client, SITE, {**device, 'model_name': 'Named'}, Collection())
    assert (named.display_model, named.display_model_source) == ('Named', 'device.model_name')


def test_state_other_than_one_is_not_informing():
    client, _ = _client()
    identity = collect_device_identity(client, SITE, fake_switch(state=0), Collection())
    assert identity.state == 0 and identity.informing is False


# ---------------------------------------------------------------------------
# Port detail and override
# ---------------------------------------------------------------------------


def test_port_detail_copies_the_raw_entry_and_key_fields():
    device, _ = _clean_switch()
    detail = collect_port_detail(device, 5)
    assert detail.raw['speed'] == 5000 and 'x_port_secret' not in detail.raw
    fields = detail.key_fields
    assert fields['speed'] == 5000 and fields['autoneg'] is True
    assert fields['op_mode'] == 'switch'
    assert fields['flowctrl_rx'] is False and fields['flowctrl_tx'] is False
    assert fields['forward'] == 'native'
    assert fields['poe']['port_poe'] is False
    assert fields['counters']['rx_errors'] == 7
    assert fields['counters']['rx_crc_errors'] == 3  # read from port_stats
    assert fields['counters']['other'] == {
        'port_stats.rx_crc_errors': 3,
        'port_stats.rx_pause_frames': 0,
    }
    assert 'anomalies' in detail.absent_keys
    assert 'speed' not in detail.absent_keys


def test_speed_caps_is_reported_raw_and_never_decoded():
    device, _ = _clean_switch()
    caps = collect_port_detail(device, 5).speed_caps
    assert caps.raw == SPEED_CAPS
    assert caps.hex == hex(SPEED_CAPS) and caps.binary == bin(SPEED_CAPS)
    assert caps.decoded is None
    assert caps.decode_status == 'raw - no authoritative mapping'
    assert caps.same_value_ports == [1, 2, 3]


def test_port_detail_carries_raw_lldp_and_port_scoped_mac_table():
    device, _ = _clean_switch()
    assert collect_port_detail(device, 2).lldp[0]['chassis_id'] == PEER_MAC.upper()
    detail = collect_port_detail(device, 5)
    assert detail.lldp == []
    assert detail.mac_table.source == 'device'
    assert [e['mac'] for e in detail.mac_table.entries] == [NAS_MAC]
    assert detail.last_connection and detail.last_connection['mac'] == NAS_MAC


def test_port_detail_rejects_a_missing_port_with_valid_ports_listed():
    device, _ = _clean_switch()
    with pytest.raises(PortNotFound, match=r'valid ports: \[1, 2, 3, 4, 5\]'):
        collect_port_detail(device, 9)


def test_override_shows_both_profile_ids_and_flags_disagreement():
    device, _ = _clean_switch()
    override = collect_override(device, 5, _profiles(), (PROF_10G, PROF_AUTO))
    assert override.present is True
    assert override.raw == {
        'port_idx': 5,
        'portconf_id': PROF_10G,
        'name': 'NAS 10G',
        'setting_preference': 'auto',
    }
    assigned = override.profile_assigned
    assert (assigned.id, assigned.name, assigned.source) == (
        PROF_10G,
        PROFILE_10G_NAME,
        'override',
    )
    assert assigned.override_portconf_id == PROF_10G
    assert assigned.port_table_portconf_id == PROF_AUTO
    assert assigned.ids_disagree is True
    assert assigned.matches_compare_profile == 'a'
    assert override.assigned_profile_raw and 'x_pw_test' not in override.assigned_profile_raw


def test_port_without_override_uses_the_port_table_profile():
    device, _ = _clean_switch()
    override = collect_override(device, 3, _profiles())
    assert override.present is False and override.raw is None
    assert override.profile_assigned.source == 'port_table'
    assert override.profile_assigned.ids_disagree is False


# ---------------------------------------------------------------------------
# All ports
# ---------------------------------------------------------------------------


def test_list_switch_ports_summarises_every_port():
    client, _ = _client()
    report = list_switch_ports(client, SITE, fake_switch(), now=lambda: NOW)
    assert [p.port_idx for p in report.ports] == [1, 2, 3, 4, 5]
    port2, port4, port5 = report.ports[1], report.ports[3], report.ports[4]
    assert port2.lldp and port2.lldp.resolved_kind == 'device'
    assert port2.lldp.resolved_name == 'Test Gateway'
    assert port2.profile_name == 'All' and port2.has_override is True
    assert port4.up is False and port4.speed == 0
    assert port5.speed == 5000 and port5.profile_name == PROFILE_10G_NAME
    assert [c.mac for c in port5.clients] == [NAS_MAC] and port5.client_count == 1
    assert port5.rx_crc_errors == 3
    assert report.device.raw is None  # raw only with include_raw
    assert_no_secrets(report.to_json_dict())


# ---------------------------------------------------------------------------
# Profile diff
# ---------------------------------------------------------------------------


def test_profile_diff_separates_settings_from_metadata():
    client, _ = _client()
    diff = diff_port_profiles(client, SITE, PROFILE_10G_NAME, PROFILE_AUTO_NAME.lower())
    assert [(d.key, d.a, d.b) for d in diff.differences] == [('autoneg', False, True)]
    assert diff.only_in_a == ['speed'] and diff.only_in_b == []
    assert {d.key for d in diff.metadata_differences} == {
        '_id',
        'name',
        'attr_no_delete',
        'attr_hidden_id',
    }
    assert diff.identical_key_count == 7
    assert 'x_pw_test' not in diff.a.raw
    assert 'portconf[0].x_pw_test' in diff.sanitised_paths
    assert diff.network_refs[NET_MGMT]['vlan'] == 255
    assert diff.network_refs[NET_GUEST]['name'] == 'Guest'
    used_a = {(u.switch, u.port_idx, u.source) for u in diff.used_by['a']}
    assert used_a == {(SWITCH_NAME, 5, 'override'), ('Hotel3 USW Flex XG 10G', 1, 'override')}
    assert {u.port_idx for u in diff.used_by['b'] if u.switch == SWITCH_NAME} == {1, 3, 4}
    assert_no_secrets(diff.to_json_dict())


def test_profile_lookup_by_id_and_missing_profile_lists_names():
    profiles = _profiles()
    assert find_profile(profiles, PROF_AUTO)['name'] == PROFILE_AUTO_NAME
    with pytest.raises(ProfileNotFound) as excinfo:
        find_profile(profiles, 'Nope')
    for name in (PROFILE_10G_NAME, PROFILE_AUTO_NAME, 'All'):
        assert name in str(excinfo.value)


def test_build_profile_diff_is_pure():
    a, b = _profiles()[PROF_10G], _profiles()[PROF_AUTO]
    diff = build_profile_diff(a, b, {}, fake_devices())
    assert diff.network_refs[NET_MGMT]['vlan'] is None  # unresolved, never guessed


# ---------------------------------------------------------------------------
# Client history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('identifier', [NAS_MAC, NAS_MAC.upper().replace(':', '-'), NAS_IP])
def test_client_history_resolves_by_mac_or_ip(identifier):
    client, _ = _client()
    history = get_client_history(client, SITE, identifier, switch=fake_switch(), port_idx=5)
    assert history.resolved_macs == [NAS_MAC]
    [record] = history.records
    assert record.location and record.location.source == 'stat_sta'
    assert (record.location.sw_mac, record.location.sw_port) == (SWITCH_MAC, 5)
    assert record.location.sw_name == SWITCH_NAME
    assert record.matches_target is True
    assert record.link['wired_rate_mbps'] == 5000
    assert (record.vlan, record.ip, record.uptime_seconds) == (255, NAS_IP, 3600)
    assert record.stat_user and record.stat_user['mac'] == NAS_MAC


def test_client_history_matches_target_is_independent_of_the_lookup():
    client, _ = _client()
    history = get_client_history(client, SITE, NAS_MAC, switch=fake_switch(), port_idx=3)
    assert history.records[0].matches_target is False


def test_client_history_by_hostname_includes_offline_history():
    client, _ = _client()
    history = get_client_history(client, SITE, 'UGREEN-NAS', switch=fake_switch(), port_idx=5)
    assert history.resolution == 'name'
    assert history.resolved_macs == [NAS_MAC, NAS_MAC_2]
    offline = history.records[1]
    assert offline.v2_history and offline.v2_history['hostname'] == 'ugreen-nas-eth1'
    assert offline.location and offline.location.source == 'v2_history'
    assert offline.location.sw_port == 3 and offline.matches_target is False
    assert {r['source'] for r in history.on_target_port} == {'stat_sta', 'v2_active'}


def test_client_history_with_no_target_leaves_matches_target_unknown():
    client, _ = _client()
    history = get_client_history(client, SITE, NAS_MAC)
    assert history.target is None and history.records[0].matches_target is None


def test_client_history_for_an_unknown_client_is_empty_not_an_error():
    client, _ = _client()
    history = get_client_history(client, SITE, 'no-such-host')
    assert history.resolved_macs == [] and history.records == []
    assert history.resolution == 'none'


# ---------------------------------------------------------------------------
# Integration API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(('unifi_os', 'auth'), [(True, 'username_password'), (False, 'token')])
def test_integration_is_skipped_without_unifi_os_token_auth(unifi_os, auth):
    session = FakeSession(default_routes())
    client = fake_client(session, unifi_os=unifi_os, auth=auth)
    snapshot = collect_integration_snapshot(client, SITE, SWITCH_MAC, 5, Collection())
    assert snapshot.status == 'skipped'
    assert not any('/v1/' in p for p in session.paths())


def test_integration_tries_the_documented_base_before_the_plural_one():
    client, session = _client()
    ctx = Collection()
    snapshot = collect_integration_snapshot(client, SITE, SWITCH_MAC, 5, ctx)
    info_calls = [p for p in session.paths() if p.endswith('/v1/info')]
    assert info_calls == [
        '/proxy/network/integration/v1/info',
        '/proxy/network/integrations/v1/info',
    ]
    assert snapshot.status == 'ok'
    assert snapshot.base_path_used == '/proxy/network/integrations'
    assert snapshot.application_version == '10.0.162'
    assert snapshot.port and snapshot.port['maxSpeedMbps'] == 10000
    assert snapshot.statistics_latest and snapshot.statistics_latest['cpuUtilizationPct'] == 7.1
    assert not ctx.errors  # the expected 404 on the first base is not an error


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


def _bundle(tmp_path: Path, query: BundleQuery | None = None, **routes):
    client, session = _client(**routes)
    sleeps: list[float] = []
    bundle = build_port_diagnostic_bundle(
        client,
        SITE,
        query or BundleQuery(switch=SWITCH_NAME, port=5, counter_samples=1),
        sleep=sleeps.append,
        now=lambda: NOW,
        link_error_baseline_path=str(tmp_path / 'link-error-baseline.json'),
        port_counter_store_path=tmp_path / 'port-counters.json',
    )
    return bundle, client, session


def test_bundle_is_read_only_and_audited(tmp_path):
    bundle, client, session = _bundle(tmp_path)
    assert isinstance(client.session, ReadOnlySession)
    assert bundle.request_audit, 'the audit must list the requests that were made'
    methods = {entry['method'] for entry in bundle.request_audit}
    assert methods <= {'GET', 'POST'}
    posts = {e['path'] for e in bundle.request_audit if e['method'] == 'POST'}
    assert posts and posts <= ALLOWED_POSTS
    assert all(set(e) == {'method', 'path'} for e in bundle.request_audit)
    assert all('192.0.2.1' not in e['path'] for e in bundle.request_audit)
    assert session.paths('PUT') == session.paths('DELETE') == []


def test_bundle_collects_every_section(tmp_path):
    query = BundleQuery(
        switch=SWITCH_NAME,
        port=5,
        clients=[NAS_MAC],
        compare_profiles=[PROFILE_10G_NAME, PROFILE_AUTO_NAME],
        counter_samples=1,
    )
    bundle, _, _ = _bundle(tmp_path, query)
    assert bundle.schema_version == 1
    assert bundle.switch_resolution.matched_by == 'exact_name'
    assert bundle.controller and bundle.controller.application_version == '10.0.162'
    assert bundle.device and bundle.device.integration_statistics == {
        'cpuUtilizationPct': 7.1,
        'memoryUtilizationPct': 41.2,
        'uptimeSec': 86400,
        'lastHeartbeatAt': '2026-09-21T14:13:00Z',
    }
    assert bundle.port and bundle.port.integration_port
    assert bundle.port.integration_port['maxSpeedMbps'] == 10000
    assert bundle.override and bundle.override.profile_assigned.matches_compare_profile == 'a'
    assert bundle.inspection and bundle.inspection['port_idx'] == 5
    assert bundle.profiles and bundle.profiles.differences[0].key == 'autoneg'
    assert bundle.clients and bundle.clients[0].records[0].matches_target is True
    assert bundle.clients_derived_from_port is False
    assert bundle.events and bundle.events.matched_total >= 1
    assert bundle.counters and bundle.counters.verdict == 'single_sample'
    assert bundle.switch_ports and len(bundle.switch_ports) == 5
    assert bundle.integration and bundle.integration.status == 'ok'


def test_bundle_leaks_no_secrets_and_the_final_pass_finds_nothing(tmp_path):
    bundle, _, _ = _bundle(tmp_path)
    data = bundle.to_json_dict()
    assert_no_secrets(data)
    assert FAKE_AUTHKEY not in json.dumps(data)
    assert not any(p.startswith('final:') for p in data['sanitised_paths'])
    assert strip_secrets(data)[1] == []
    assert 'device.raw.x_authkey' in data['sanitised_paths']


def test_a_failed_source_is_recorded_while_other_sections_survive(tmp_path):
    def system_log(path, **_):
        if path.endswith('/update-alert'):
            return 403, {'error': 'forbidden'}
        return {'data': [], 'totalElements': 0}

    bundle, _, _ = _bundle(tmp_path, system_log=system_log)
    assert any(e.section == 'events.system_log.update-alert' for e in bundle.errors)
    assert (
        bundle.events and bundle.events.sources.system_log['update-alert'].status == 'unavailable'
    )
    assert bundle.device and bundle.port and bundle.switch_ports


def test_bundle_derives_clients_from_the_port_when_none_are_given(tmp_path):
    bundle, _, _ = _bundle(tmp_path)
    assert bundle.clients_derived_from_port is True
    assert [h.query for h in bundle.clients] == [NAS_MAC]


def test_bundle_fails_fast_on_an_unknown_switch_or_port(tmp_path):
    with pytest.raises(SwitchNotFound, match='No switch matched'):
        _bundle(tmp_path, BundleQuery(switch='nope', port=5))
    with pytest.raises(SwitchNotFound, match='Ambiguous'):
        _bundle(tmp_path, BundleQuery(switch='Flex XG', port=5))
    with pytest.raises(PortNotFound):
        _bundle(tmp_path, BundleQuery(switch=OTHER_SWITCH_MAC, port=5))


def test_bundle_rejects_bad_parameters_before_any_request(tmp_path):
    with pytest.raises(ValueError, match='exactly two'):
        _bundle(tmp_path, BundleQuery(switch=SWITCH_NAME, port=5, compare_profiles=['A']))
    session = FakeSession(default_routes())
    for query in (
        BundleQuery(switch=SWITCH_NAME, port=5, counter_samples=9),
        BundleQuery(switch=SWITCH_NAME, port=5, interval_seconds=5),
        BundleQuery(switch=SWITCH_NAME, port=5, since_days=0),
    ):
        with pytest.raises(ValueError):
            build_port_diagnostic_bundle(fake_client(session), SITE, query)
    assert session.calls == []


def test_a_collector_that_tries_to_write_aborts_the_bundle(tmp_path, monkeypatch):
    import unifi_mapper.port_diagnostics as module

    def writer(client, site, ctx):
        client.session.put(f'{client.base_url}{API}/rest/device/x', json={})

    monkeypatch.setattr(module, 'collect_controller_info', writer)
    with pytest.raises(ReadOnlyViolation):
        _bundle(tmp_path)
