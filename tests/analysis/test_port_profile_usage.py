"""Tests for the port-profile usage audit (no live controller)."""

import pytest
from tests.fixtures_unifi import (
    NET_GUEST,
    NOW,
    OTHER_SWITCH_MAC,
    PROF_10G,
    PROF_AUTO,
    PROF_TRUNK,
    PROFILE_10G_NAME,
    PROFILE_AUTO_NAME,
    SITE,
    SWITCH_MAC,
    FakeSession,
    assert_no_secrets,
    default_routes,
    fake_client,
    fake_networkconf,
    fake_other_switch,
    fake_peer,
    fake_port,
    fake_portconf,
    fake_switch,
)
from typing import Any
from unifi_mapper.analysis import port_profile_usage
from unifi_mapper.analysis.port_profile_usage import (
    PortProfileUsageReport,
    ProfileUsageFinding,
    audit_port_profile_usage_from_data,
    collect_port_profile_usage,
)
from unifi_mapper.core.utils.readonly import ReadOnlySession, install_read_only_guard
from unifi_mapper.diagnostic_reads import Collection, ProfileNotFound
from unifi_mapper.port_diagnostics import profile_usage


pytestmark = pytest.mark.usefixtures('block_network')


def _clean(value: Any, path: str) -> Any:
    return Collection().clean(value, path)


def _devices(**switch_over: Any) -> list[dict[str, Any]]:
    return [
        _clean(fake_switch(**switch_over), 'device.raw'),
        _clean(fake_other_switch(), 'device.raw'),
        _clean(fake_peer(), 'device.raw'),
    ]


def _profiles(*extra: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p['_id']: p for p in _clean([*fake_portconf(), *extra], 'portconf')}


def _networks() -> dict[str, dict[str, Any]]:
    return {n['_id']: {'name': n['name'], 'vlan': n['vlan']} for n in fake_networkconf()}


def _audit(
    devices: list[dict[str, Any]] | None = None,
    profiles: dict[str, dict[str, Any]] | None = None,
    **kw: Any,
) -> PortProfileUsageReport:
    return audit_port_profile_usage_from_data(
        _devices() if devices is None else devices,
        _profiles() if profiles is None else profiles,
        _networks(),
        NOW,
        **kw,
    )


def _with_code(report: PortProfileUsageReport, code: str) -> list[ProfileUsageFinding]:
    return [f for f in report.findings if f.code == code]


def _auto_copy(**over: Any) -> dict[str, Any]:
    copy = dict(_profiles()[PROF_AUTO])
    copy.update(_id='0000000000000000000000b9', name='Auto copy', attr_hidden_id='other')
    copy.update(over)
    return copy


# ---------------------------------------------------------------------------
# Usage and per-profile facts
# ---------------------------------------------------------------------------


def test_usage_per_profile_comes_from_profile_usage():
    devices = _devices()
    report = _audit(devices)
    by_id = {p.id: p for p in report.profiles}
    for pid in (PROF_10G, PROF_AUTO, PROF_TRUNK):
        assert by_id[pid].ports == profile_usage(devices, pid)
    assert [(u.switch_mac, u.port_idx, u.source) for u in by_id[PROF_10G].ports] == [
        (OTHER_SWITCH_MAC, 1, 'override'),
        (SWITCH_MAC, 5, 'override'),
    ]
    forced = by_id[PROF_10G]
    assert forced.forces_speed is True and forced.forced_speed_mbps == 10000
    assert forced.autoneg is False
    assert forced.native_network_name == 'Management' and forced.native_vlan == 255
    assert by_id[PROF_AUTO].forces_speed is False and by_id[PROF_AUTO].autoneg is True
    assert [p.name for p in report.profiles] == [
        'Access Port VLAN 255 Management 10Gbps',
        'Access Port VLAN 255 Management Auto',
        'All',
    ]
    assert report.validation_passed is True


def test_ports_are_capped_at_50_with_ports_truncated():
    ports = [fake_port(i) for i in range(1, 52)]
    devices = [_clean(fake_switch(port_overrides=[], port_table=ports), 'device.raw')]
    entry = next(p for p in _audit(devices).profiles if p.id == PROF_AUTO)
    assert entry.port_count == 51 and len(entry.ports) == 50
    assert entry.ports_truncated is True
    assert entry.ports == profile_usage(devices, PROF_AUTO)[:50]


# ---------------------------------------------------------------------------
# One fixture per code
# ---------------------------------------------------------------------------


def test_forced_speed_profile_cites_audit_link_speeds():
    (finding,) = _with_code(_audit(), 'FORCED_SPEED_PROFILE')
    assert finding.severity == 'WARNING' and finding.profile_id == PROF_10G
    assert '10000 Mbps on 2 port(s)' in finding.message
    assert 'audit_link_speeds' in finding.recommendation


def test_dangling_profile_ref_is_high():
    ports = [fake_port(1), fake_port(3, portconf_id='0000000000000000000000ff')]
    report = _audit(_devices(port_table=ports))
    (finding,) = _with_code(report, 'DANGLING_PROFILE_REF')
    assert finding.severity == 'HIGH' and finding.port_idx == 3
    assert finding.switch_mac == SWITCH_MAC
    assert report.validation_passed is False


def test_an_empty_profile_table_is_not_reported_as_dangling():
    assert _with_code(_audit(profiles={}), 'DANGLING_PROFILE_REF') == []


@pytest.mark.parametrize(
    ('override', 'fields'),
    [
        ({'autoneg': False, 'speed': 1000}, ['autoneg', 'forced_speed_mbps']),
        ({'native_networkconf_id': NET_GUEST}, ['native_network_id']),
        ({'autoneg': True}, []),  # same as the profile: nothing shadowed
        ({'name': 'label only'}, []),
    ],
)
def test_override_shadows_profile(override, fields):
    overrides = [*fake_switch()['port_overrides'], {'port_idx': 3, **override}]
    report = _audit(_devices(port_overrides=overrides))
    found = _with_code(report, 'OVERRIDE_SHADOWS_PROFILE')
    if not fields:
        assert found == []
        return
    (finding,) = found
    assert finding.severity == 'WARNING' and finding.port_idx == 3
    assert finding.profile_id == PROF_AUTO and finding.shadowed_fields == fields


def test_duplicate_profiles_ignore_identity_and_attr_keys():
    (finding,) = _with_code(_audit(profiles=_profiles(_auto_copy())), 'DUPLICATE_PROFILES')
    assert finding.severity == 'INFO'
    assert {finding.profile_id, finding.other_profile_id} == {
        PROF_AUTO,
        '0000000000000000000000b9',
    }


@pytest.mark.parametrize(
    'copy',
    [_auto_copy(poe_mode='auto'), _auto_copy(speed=1000), _auto_copy(name=PROFILE_AUTO_NAME)],
)
def test_one_differing_key_or_the_same_name_is_not_a_duplicate(copy):
    assert _with_code(_audit(profiles=_profiles(copy)), 'DUPLICATE_PROFILES') == []


def test_unused_profile_and_hide_unused():
    unused = {'_id': '0000000000000000000000b8', 'name': 'Spare', 'forward': 'disabled'}
    report = _audit(profiles=_profiles(unused))
    (finding,) = _with_code(report, 'UNUSED_PROFILE')
    assert finding.profile_id == unused['_id'] and finding.severity == 'INFO'
    assert unused['_id'] in {p.id for p in report.profiles}

    hidden = _audit(profiles=_profiles(unused), include_unused=False)
    assert _with_code(hidden, 'UNUSED_PROFILE') == []
    assert unused['_id'] not in {p.id for p in hidden.profiles}


# ---------------------------------------------------------------------------
# Reuse: the sibling's helpers are called, not reimplemented
# ---------------------------------------------------------------------------


def test_profile_usage_and_build_profile_diff_are_the_landed_helpers(monkeypatch):
    usage_calls: list[str] = []
    diff_calls: list[tuple[str, str, list]] = []
    real_usage = port_profile_usage.profile_usage
    real_diff = port_profile_usage.build_profile_diff

    def usage_spy(devices, profile_id):
        usage_calls.append(profile_id)
        return real_usage(devices, profile_id)

    def diff_spy(a, b, networks, devices):
        diff_calls.append((a['_id'], b['_id'], list(devices)))
        return real_diff(a, b, networks, devices)

    monkeypatch.setattr(port_profile_usage, 'profile_usage', usage_spy)
    monkeypatch.setattr(port_profile_usage, 'build_profile_diff', diff_spy)
    _audit()
    assert sorted(usage_calls) == sorted([PROF_10G, PROF_AUTO, PROF_TRUNK])
    assert [(a, b) for a, b, _ in diff_calls] == [
        (PROF_10G, PROF_AUTO),
        (PROF_10G, PROF_TRUNK),
        (PROF_AUTO, PROF_TRUNK),
    ]
    assert all(devices == [] for _, _, devices in diff_calls)


# ---------------------------------------------------------------------------
# Scope and pagination
# ---------------------------------------------------------------------------


def test_profile_scope_reports_one_profile_and_its_findings():
    report = _audit(profile_id=PROF_10G)
    assert [p.id for p in report.profiles] == [PROF_10G]
    assert {f.code for f in report.findings} == {'FORCED_SPEED_PROFILE'}


def test_pagination_pages_profiles_but_keeps_every_finding():
    first = _audit(limit=2)
    assert len(first.profiles) == 2 and first.truncated and first.next_offset == 2
    assert first.profiles_total == 3 and first.findings_total == len(first.findings) == 1
    second = _audit(limit=2, offset=2)
    assert [p.id for p in second.profiles] == [PROF_TRUNK]
    assert not second.truncated and second.next_offset is None


@pytest.mark.parametrize(('limit', 'offset'), [(0, 0), (1001, 0), (5, -1)])
def test_out_of_range_paging_is_a_value_error(limit, offset):
    with pytest.raises(ValueError):
        _audit(limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Fetch over the fake controller
# ---------------------------------------------------------------------------


def _guarded(**routes: Any):
    session = FakeSession(default_routes(**routes))
    client = fake_client(session)
    install_read_only_guard(client)
    return client, session


def test_collect_reads_three_sources_once_and_only_gets():
    client, session = _guarded()
    report = collect_port_profile_usage(client, SITE, now=lambda: NOW)
    assert isinstance(client.session, ReadOnlySession)
    assert sorted(session.paths('GET')) == sorted(
        [
            '/proxy/network/api/s/default/stat/device',
            '/proxy/network/api/s/default/rest/portconf',
            '/proxy/network/api/s/default/rest/networkconf',
        ]
    )
    assert {c['method'] for c in session.calls} == {'GET'}
    assert report.profiles_total == 3 and report.devices_analyzed == 2
    assert not report.errors
    assert 'portconf[0].x_pw_test' in report.sanitised_paths
    assert_no_secrets(report.model_dump(mode='json'))


def test_collect_finds_a_profile_by_name_case_insensitively():
    client, _ = _guarded()
    report = collect_port_profile_usage(client, SITE, profile=PROFILE_10G_NAME.upper())
    assert [p.id for p in report.profiles] == [PROF_10G]


def test_collect_unknown_profile_lists_names():
    client, _ = _guarded()
    with pytest.raises(ProfileNotFound, match=PROFILE_AUTO_NAME):
        collect_port_profile_usage(client, SITE, profile='nope')


def test_collect_records_a_failed_profile_read():
    client, _ = _guarded(portconf=(500, {'error': 'boom'}))
    report = collect_port_profile_usage(client, SITE, now=lambda: NOW)
    assert [e.section for e in report.errors] == ['profiles']
    assert report.profiles == [] and report.validation_passed is True
