"""Tests for the single port-profile precedence rule (analysis/link_settings)."""

import ast
import copy
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from tests.fixtures_unifi import (
    NET_MGMT,
    NOW,
    PROF_10G,
    PROF_AUTO,
    PROF_TRUNK,
    PROFILE_10G_NAME,
    SITE,
    SWITCH_NAME,
    FakeSession,
    default_routes,
    fake_client,
    fake_networkconf,
    fake_portconf,
    fake_switch,
)
from typing import Any
from unifi_mapper import port_inspect
from unifi_mapper.analysis import link_settings
from unifi_mapper.analysis.link_settings import (
    effective_port_settings,
    effective_profile_id,
    port_override,
)
from unifi_mapper.diagnostic_reads import Collection, find_port_entry, int_or_none, str_or_none
from unifi_mapper.port_diagnostics import collect_override, profile_usage, summarise_ports


pytestmark = pytest.mark.usefixtures('block_network')

GOLDEN = Path(__file__).resolve().parent.parent / 'data' / 'inspect_switch_port_golden.json'
COERCER_VALUES: list[Any] = [None, True, False, 0, 5, 5.0, '5', '5.7', 'x', '']


def _device(overrides: list[Any]) -> dict[str, Any]:
    return {'port_overrides': overrides}


def _clean_switch(**over: Any) -> dict[str, Any]:
    return Collection().clean(fake_switch(**over), 'device.raw')


def _profiles() -> dict[str, dict[str, Any]]:
    return {p['_id']: p for p in Collection().clean(fake_portconf(), 'portconf')}


def _networks() -> dict[str, dict[str, Any]]:
    return {n['_id']: n for n in fake_networkconf()}


# ---------------------------------------------------------------------------
# Precedence table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('overrides', 'entry', 'expected'),
    [
        ([{'port_idx': 5, 'portconf_id': 'o'}], {'portconf_id': 't'}, ('o', 'override')),
        ([{'port_idx': 5, 'name': 'no id'}], {'portconf_id': 't'}, ('t', 'port_table')),
        ([], {'portconf_id': 't'}, ('t', 'port_table')),
        ([], {}, (None, 'unknown')),
        ([{'port_idx': 5, 'portconf_id': ''}], {'portconf_id': ''}, (None, 'unknown')),
        ([{'port_idx': 5, 'portconf_id': ''}], {'portconf_id': 't'}, ('t', 'port_table')),
        ([{'port_idx': 5, 'portconf_id': None}], {}, (None, 'unknown')),
        (
            [{'port_idx': 5, 'portconf_id': 'first'}, {'port_idx': 5, 'portconf_id': 'second'}],
            {},
            ('first', 'override'),
        ),
        (['junk', None, 7, {'port_idx': 5, 'portconf_id': 'o'}], {}, ('o', 'override')),
        ([{'port_idx': '5', 'portconf_id': 'o'}], {}, ('o', 'override')),
        ([{'port_idx': 5.0, 'portconf_id': 'o'}], {}, ('o', 'override')),
        ([{'port_idx': 4, 'portconf_id': 'o'}], {'portconf_id': 't'}, ('t', 'port_table')),
    ],
)
def test_effective_profile_id_precedence(overrides, entry, expected):
    assert effective_profile_id(_device(overrides), entry, 5) == expected


def test_port_idx_true_matches_nothing():
    device = _device([{'port_idx': True, 'portconf_id': 'o'}])
    assert port_override(device, 1) is None
    assert effective_profile_id(device, {'portconf_id': 't'}, 1) == ('t', 'port_table')


def test_port_idx_none_matches_nothing():
    device = _device([{'portconf_id': 'no idx'}, {'port_idx': None, 'portconf_id': 'none'}])
    assert port_override(device, None) is None
    assert effective_profile_id(device, {'portconf_id': 't'}, None) == ('t', 'port_table')


def test_port_override_ignores_missing_or_non_list_overrides():
    assert port_override({}, 5) is None
    assert port_override({'port_overrides': None}, 5) is None


@pytest.mark.parametrize('value', COERCER_VALUES, ids=repr)
def test_private_coercers_equal_the_diagnostic_reads_originals(value):
    assert link_settings._int_or_none(value) == int_or_none(value)
    assert link_settings._str_or_none(value) == str_or_none(value)


def test_link_settings_imports_only_stdlib_typing_and_pydantic():
    tree = ast.parse(Path(link_settings.__file__).read_text())
    imported = {
        (node.module or '').split('.')[0] if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {'pydantic', 'typing'}


# ---------------------------------------------------------------------------
# UGREEN precedence parity across every caller
# ---------------------------------------------------------------------------


def _no_id_variant() -> dict[str, Any]:
    device = _clean_switch()
    device['port_overrides'][0].pop('portconf_id')
    return device


@pytest.mark.parametrize(
    ('device_factory', 'idx', 'expected_id', 'expected_source'),
    [
        (_clean_switch, 5, PROF_10G, 'override'),
        (_clean_switch, 2, PROF_TRUNK, 'override'),
        (_clean_switch, 3, PROF_AUTO, 'port_table'),
        (_no_id_variant, 5, PROF_AUTO, 'port_table'),
    ],
    ids=['port5-disagreeing', 'port2-both-trunk', 'port3-no-override', 'port5-override-no-id'],
)
def test_every_caller_resolves_the_same_profile(device_factory, idx, expected_id, expected_source):
    device = device_factory()
    profiles, networks = _profiles(), _networks()
    entry = find_port_entry(device, idx)

    settings = effective_port_settings(device, entry, idx, profiles, networks)
    assigned = collect_override(device, idx, profiles).profile_assigned
    row = next(r for r in summarise_ports(device, profiles, {}, {}, []) if r.port_idx == idx)
    usage = [u for u in profile_usage([device], settings.profile_id or '') if u.port_idx == idx]
    inspected = port_inspect._resolve_profile(device, entry, idx, profiles, networks)

    assert settings.profile_id == assigned.id == row.portconf_id == expected_id
    assert settings.source == assigned.source == inspected.source == expected_source
    assert inspected.profile_id == expected_id
    assert [u.source for u in usage] == [expected_source]


# ---------------------------------------------------------------------------
# Field precedence
# ---------------------------------------------------------------------------


def test_forced_10g_profile_reports_forced_speed_from_the_profile():
    device = _clean_switch()
    settings = effective_port_settings(
        device, find_port_entry(device, 5), 5, _profiles(), _networks()
    )
    assert settings.autoneg is False and settings.forced_speed_mbps == 10000
    assert settings.full_duplex is True
    assert settings.sources['autoneg'] == 'profile'
    assert settings.sources['forced_speed_mbps'] == 'profile'
    assert settings.sources['profile_id'] == 'override'
    assert settings.native_network_id == NET_MGMT
    assert settings.sources['native_network_id'] == 'profile'


def test_auto_profile_has_no_forced_speed():
    device = _clean_switch()
    settings = effective_port_settings(
        device, find_port_entry(device, 3), 3, _profiles(), _networks()
    )
    assert settings.autoneg is True and settings.forced_speed_mbps is None
    assert settings.sources['forced_speed_mbps'] == 'unknown'


def test_override_negotiation_keys_beat_the_profile():
    overrides = [{'port_idx': 5, 'portconf_id': 'auto', 'autoneg': False, 'speed': 2500}]
    profiles = {'auto': {'_id': 'auto', 'autoneg': True, 'full_duplex': True}}
    settings = effective_port_settings(_device(overrides), {}, 5, profiles, {})
    assert settings.autoneg is False and settings.forced_speed_mbps == 2500
    assert settings.sources['autoneg'] == 'override'
    assert settings.sources['forced_speed_mbps'] == 'override'
    assert settings.full_duplex is True and settings.sources['full_duplex'] == 'profile'


def test_port_table_is_the_last_negotiation_fallback_but_never_a_forced_speed():
    entry = {'autoneg': False, 'full_duplex': False, 'speed': 1000}
    settings = effective_port_settings({}, entry, 5, {}, {})
    assert settings.autoneg is False and settings.sources['autoneg'] == 'port_table'
    assert settings.full_duplex is False and settings.sources['full_duplex'] == 'port_table'
    assert settings.forced_speed_mbps is None
    assert settings.source == 'unknown' and settings.profile_id is None


def test_inspect_field_precedence_is_kept():
    overrides = [
        {
            'port_idx': 1,
            'portconf_id': 'p',
            'forward': 'customize',
            'native_networkconf_id': 'net-o',
            'poe_mode': 'off',
        }
    ]
    profiles = {
        'p': {
            '_id': 'p',
            'name': 'P',
            'forward': 'all',
            'native_networkconf_id': 'net-p',
            'poe_mode': 'auto',
            'tagged_networkconf_ids': ['net-a', 'net-missing', 'net-novlan'],
        }
    }
    networks = {'net-a': {'vlan': 30}, 'net-novlan': {'vlan': None}}
    settings = effective_port_settings(
        _device(overrides), {'native_networkconf_id': 'net-t'}, 1, profiles, networks
    )
    assert settings.forward == 'all' and settings.sources['forward'] == 'profile'
    assert settings.native_network_id == 'net-o'
    assert settings.poe_mode == 'off' and settings.sources['poe_mode'] == 'override'
    assert settings.tagged_vlans == [30]
    assert settings.name == 'P'

    bare = effective_port_settings(
        _device([{'port_idx': 1, 'forward': 'native'}]),
        {'native_networkconf_id': 'net-t'},
        1,
        {},
        {},
    )
    assert bare.forward == 'native' and bare.sources['forward'] == 'override'
    assert bare.native_network_id == 'net-t'
    assert bare.sources['native_network_id'] == 'port_table'
    assert bare.tagged_vlans is None


# ---------------------------------------------------------------------------
# Golden: inspect_switch_port output is unchanged by the routing
# ---------------------------------------------------------------------------


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return datetime.fromtimestamp(NOW, tz=tz or timezone.utc)


def test_inspect_switch_port_output_matches_the_golden(monkeypatch):
    monkeypatch.setattr(port_inspect, 'datetime', _FrozenDatetime)
    got: dict[str, Any] = {}
    for idx in (2, 3, 5):
        client = fake_client(FakeSession(default_routes()))
        switch = port_inspect.resolve_switch(client, SITE, SWITCH_NAME)
        got[str(idx)] = port_inspect.inspect_port(client, SITE, switch, idx).to_dict()
    # Parsed comparison: the pretty-format-json hook re-sorts the file's keys.
    assert json.loads(json.dumps(got)) == json.loads(GOLDEN.read_text())


def test_fixture_switch_is_not_mutated_by_resolution():
    device = _clean_switch()
    before = copy.deepcopy(device)
    effective_port_settings(device, find_port_entry(device, 5), 5, _profiles(), _networks())
    assert device == before


# ---------------------------------------------------------------------------
# Every analysis that picks a port's profile uses the one precedence rule (issue 026)
# ---------------------------------------------------------------------------


def test_validate_port_profiles_uses_the_effective_profile_for_port_5():
    from unifi_mapper.analysis.port_profile_validation import validate_port_profiles_from_data

    profiles = fake_portconf()
    for profile in profiles:
        if profile['_id'] in (PROF_10G, PROF_AUTO):
            profile['stp_edge'] = False  # port 5 is client-only, so each yields a finding

    report = validate_port_profiles_from_data([fake_switch()], profiles)

    port_5 = [finding.profile_name for finding in report.findings if finding.port_idx == 5]
    assert port_5 == [PROFILE_10G_NAME]  # the override's profile, not the port table's Auto


def test_the_module_docstring_names_every_caller():
    doc = ' '.join((link_settings.__doc__ or '').split())
    for module in (
        'port_profile_validation',
        'foreign_bridges',
        'uplink_transparency',
        'vlan_coverage',
    ):
        assert module in doc
    assert 'Not yet routed' not in doc
    assert 'issue 026' not in doc
    assert 'issue 030' in doc


SRC = Path(__file__).resolve().parents[2] / 'src' / 'unifi_mapper'
PROFILE_ID_KEYS = frozenset({'portconf_id', 'port_conf_id'})
# The only modules that may read a profile id themselves, and why.
READS_A_PROFILE_ID = {
    'analysis/link_settings.py': 'the precedence rule itself',
    'port_diagnostics.py': (
        'collect_override reports the raw override and port-table ids beside the effective one'
    ),
}


def _reads_a_profile_id(tree: ast.AST) -> bool:
    """``.get('portconf_id', …)``, ``['portconf_id']`` or a literal key list holding it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            first = node.args[0] if node.args else None
            if node.func.attr == 'get' and isinstance(first, ast.Constant):
                if first.value in PROFILE_ID_KEYS:
                    return True
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
            if isinstance(node.slice, ast.Constant) and node.slice.value in PROFILE_ID_KEYS:
                return True
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            if any(isinstance(e, ast.Constant) and e.value in PROFILE_ID_KEYS for e in node.elts):
                return True
    return False


def test_only_link_settings_resolves_a_portconf_id():
    readers = {
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob('*.py'))
        if _reads_a_profile_id(ast.parse(path.read_text(encoding='utf-8')))
    }
    assert readers == set(READS_A_PROFILE_ID), (
        'route profile lookups through link_settings.effective_profile_id; '
        f'unexpected: {sorted(readers - set(READS_A_PROFILE_ID))}, '
        f'no longer reading (drop from the allowlist): {sorted(set(READS_A_PROFILE_ID) - readers)}'
    )
    # The scan finds each shape it looks for, so an empty difference means something.
    assert _reads_a_profile_id(ast.parse("p.get('portconf_id')"))
    assert _reads_a_profile_id(ast.parse("p['port_conf_id']"))
    assert _reads_a_profile_id(ast.parse("for k in ('profile_id', 'portconf_id'): pass"))
    assert not _reads_a_profile_id(ast.parse("payload = {'portconf_id': pid}"))
