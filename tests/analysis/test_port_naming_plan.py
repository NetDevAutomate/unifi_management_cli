"""Tests for the port label refresh plan.

Every guard here corresponds to a rename that was observed to be wrong while building the
plan against a live 11-switch estate on 2026-08-03. The naive version of each would have
destroyed information or churned labels on every run.
"""

from __future__ import annotations

from unifi_mapper.analysis.port_naming import (
    build_port_name_plan,
    is_cosmetic_change,
    is_placeholder_name,
    is_vendor_only_label,
    is_weak_label,
    name_quality,
    resolve_peer,
    strip_multi_suffix,
    would_lose_information,
)


def _switch(
    name: str, ports: list[dict], lldp: list[dict] | None = None, mac: str = 'sw:01'
) -> dict:
    return {
        '_id': f'id-{name}',
        'mac': mac,
        'name': name,
        'type': 'usw',
        'port_table': ports,
        'lldp_table': lldp or [],
    }


def _port(idx: int, name: str, up: bool = True) -> dict:
    return {'port_idx': idx, 'name': name, 'up': up}


def _client(
    mac: str,
    sw_mac: str,
    sw_port: int,
    name: str | None = None,
    hostname: str | None = None,
    oui: str | None = None,
) -> dict:
    return {
        'mac': mac,
        'is_wired': True,
        'sw_mac': sw_mac,
        'sw_port': sw_port,
        'name': name,
        'hostname': hostname,
        'oui': oui,
    }


def _ap(name: str, mac: str) -> dict:
    return {'_id': f'id-{name}', 'mac': mac, 'name': name, 'type': 'uap'}


# ─── LLDP peer resolution via the device registry ────────────────────────────


def test_resolves_ap_peer_from_chassis_id_not_system_name() -> None:
    """The Ultra 210W case: APs send no system_name, so chassis_id must be resolved.

    This is why seven ports kept reading 'PoE Out + Data' through earlier refreshes.
    """
    devices = [
        _switch(
            'Ultra',
            [_port(1, 'PoE Out + Data')],
            lldp=[{'local_port_idx': 1, 'chassis_id': 'ap:aa', 'port_id': '02:00:fe:02:00:08'}],
        ),
        _ap('Bravo4 U6-Pro', 'ap:aa'),
    ]

    plan = build_port_name_plan(devices, [])

    assert plan.count == 1
    assert plan.renames[0].proposed == 'Bravo4 U6-Pro'
    assert plan.renames[0].reason == 'lldp-peer'


def test_appends_remote_port_when_peer_reports_a_usable_port_id() -> None:
    devices = [
        _switch(
            'A',
            [_port(9, 'B')],
            lldp=[{'local_port_idx': 9, 'chassis_id': 'sw:02', 'port_id': 'te1'}],
        ),
        _switch('Shed XG', [], mac='sw:02'),
    ]

    plan = build_port_name_plan(devices, [])

    assert plan.renames[0].proposed == 'Shed XG te1'


def test_drops_remote_port_id_when_it_is_only_a_mac() -> None:
    entry = {'chassis_id': 'ap:aa', 'port_id': '02:00:fe:02:00:16'}
    assert resolve_peer(entry, {'ap:aa': {'name': 'Hotel3 U6 IW Kilo3'}}) == 'Hotel3 U6 IW Kilo3'


def test_corrects_a_transposed_switch_label() -> None:
    """Lounge p1/p2 had their two downstream switches swapped."""
    devices = [
        _switch(
            'Lounge Flex',
            [_port(1, 'Mike2 USW-Ultra-210W')],
            lldp=[{'local_port_idx': 1, 'chassis_id': 'sw:99', 'port_id': 'Port 16'}],
        ),
        _switch('Mike2 USW Lite 16 PoE', [], mac='sw:99'),
    ]

    plan = build_port_name_plan(devices, [])

    assert plan.renames[0].proposed == 'Mike2 USW Lite 16 PoE Port 16'


def test_unresolvable_peer_falls_through_to_clients() -> None:
    devices = [
        _switch(
            'A',
            [_port(1, 'Port 1')],
            lldp=[{'local_port_idx': 1, 'chassis_id': 'not:adopted'}],
            mac='sw:01',
        ),
    ]
    clients = [_client('aa:bb', 'sw:01', 1, hostname='MacMiniM4')]

    plan = build_port_name_plan(devices, clients)

    assert plan.renames[0].proposed == 'MacMiniM4'
    assert plan.renames[0].reason == 'wired-client'


# ─── Guard 1: never trade a readable label for an address ────────────────────


def test_does_not_overwrite_a_real_name_with_a_mac() -> None:
    """'Google Streamer 4K' must survive a poll where its client reports no hostname."""
    devices = [_switch('A', [_port(9, 'Google Streamer 4K')], mac='sw:01')]
    clients = [_client('02:00:fe:02:00:0f', 'sw:01', 9)]

    plan = build_port_name_plan(devices, clients)

    assert plan.count == 0


def test_does_replace_a_placeholder_with_a_mac() -> None:
    """An address still beats 'Port 9' — some label is better than none."""
    devices = [_switch('A', [_port(9, 'Port 9')], mac='sw:01')]
    clients = [_client('02:00:fe:02:00:0f', 'sw:01', 9)]

    plan = build_port_name_plan(devices, clients)

    assert plan.count == 1


def test_would_lose_information_predicate() -> None:
    assert would_lose_information('Google Streamer 4K', '02:00:fe:02:00:0f') is True
    assert would_lose_information('Port 9', '02:00:fe:02:00:0f') is False
    assert would_lose_information('0200fe00000a', '02:00:fe:02:00:0f') is False


# ─── Guard 1b: a vendor OUI string must not replace a curated label ──────────
# Observed 2026-08-10: a NAS reporting no hostname would have renamed both
# 'Synology NAS01 VLAN 15' and 'Synology NAS01' to 'Synology Incorporated',
# collapsing two distinguishable ports onto one manufacturer name.


def test_does_not_overwrite_a_real_name_with_a_vendor_string() -> None:
    """'Synology NAS01 VLAN 15' must survive a poll where the client has no hostname."""
    devices = [_switch('A', [_port(6, 'Synology NAS01 VLAN 15')], mac='sw:01')]
    clients = [_client('02:00:00:00:00:03', 'sw:01', 6, oui='Synology Incorporated')]

    plan = build_port_name_plan(devices, clients)

    assert plan.count == 0


def test_does_replace_a_placeholder_with_a_vendor_string() -> None:
    """A manufacturer name still beats 'Port 6' when nothing better is reported."""
    devices = [_switch('A', [_port(6, 'Port 6')], mac='sw:01')]
    clients = [_client('02:00:00:00:00:03', 'sw:01', 6, oui='Synology Incorporated')]

    plan = build_port_name_plan(devices, clients)

    assert plan.count == 1
    assert plan.renames[0].proposed == 'Synology Incorporated'


def test_is_vendor_only_label_predicate() -> None:
    """Vendor suffixes are detected regardless of case or trailing punctuation."""
    for name in (
        'Synology Incorporated',
        'Winstars Technology Ltd',
        'Ubiquiti Inc.',
        'ACME CORP',
        'Foo GmbH',
        'Bar Electronics',
    ):
        assert is_vendor_only_label(name) is True, name

    for name in ('Synology NAS01', 'Hotel3-Apple-TV', 'Google Streamer 4K', 'Port 6', ''):
        assert is_vendor_only_label(name) is False, name


def test_would_lose_information_covers_vendor_strings() -> None:
    """The guard treats a vendor string as a downgrade from a curated label."""
    assert would_lose_information('Synology NAS01', 'Synology Incorporated') is True
    assert would_lose_information('Port 6', 'Synology Incorporated') is False
    assert would_lose_information('02:00:00:00:00:03', 'Synology Incorporated') is False


# ─── Guard 2: a MAC must not represent a multi-client port ───────────────────


def test_multi_client_port_prefers_a_named_device_over_a_mac() -> None:
    """'Hotel3-Apple-TV' was nearly renamed to '02:00:fe:02:00:06 +2'."""
    devices = [_switch('A', [_port(2, 'Port 2')], mac='sw:01')]
    clients = [
        _client('02:00:fe:02:00:06', 'sw:01', 2),
        _client('02:00:fe:02:00:0c', 'sw:01', 2, name='Hotel3-Apple-TV'),
        _client('02:00:fe:02:00:07', 'sw:01', 2, hostname='jetkvm-c83ef561d14c'),
    ]

    plan = build_port_name_plan(devices, clients)

    assert plan.renames[0].proposed.startswith('Hotel3-Apple-TV')
    assert plan.renames[0].proposed.endswith('+2')


def test_name_quality_ranks_hostname_then_vendor_then_address() -> None:
    ranked = sorted(['00:11:32:4a:bd:25', 'Synology Incorporated', 'MacMiniM4'], key=name_quality)
    assert ranked == ['MacMiniM4', 'Synology Incorporated', '00:11:32:4a:bd:25']


# ─── Guard 3: no cosmetic churn ──────────────────────────────────────────────


def test_skips_punctuation_only_rename() -> None:
    devices = [_switch('A', [_port(1, 'AI-Port')], mac='sw:01')]
    clients = [_client('aa:bb', 'sw:01', 1, name='AI Port')]

    assert build_port_name_plan(devices, clients).count == 0


def test_is_cosmetic_change_predicate() -> None:
    assert is_cosmetic_change('AI-Port', 'AI Port') is True
    assert is_cosmetic_change('pi5', 'JetKVM') is False


# ─── Guard 4: the '+N' counter must not oscillate ────────────────────────────


def test_suffix_flap_is_suppressed() -> None:
    """A Synology that comes and goes flipped 'ax-… +1' <-> 'ax-…' on every run."""
    devices = [_switch('A', [_port(5, 'papa4-0200fe000009 +1')], mac='sw:01')]
    clients = [_client('02:00:fe:02:00:10', 'sw:01', 5, hostname='papa4-0200fe000009')]

    assert build_port_name_plan(devices, clients).count == 0


def test_strip_multi_suffix_predicate() -> None:
    assert strip_multi_suffix('Hotel3-Apple-TV +2') == 'Hotel3-Apple-TV'
    assert strip_multi_suffix('Hotel3-Apple-TV') == 'Hotel3-Apple-TV'
    assert strip_multi_suffix('Rack +A') == 'Rack +A'


def test_genuine_rename_still_applies_under_a_suffix() -> None:
    devices = [_switch('A', [_port(5, 'Old-Name +1')], mac='sw:01')]
    clients = [
        _client('aa:01', 'sw:01', 5, name='New-Name'),
        _client('aa:02', 'sw:01', 5, name='Other'),
    ]

    plan = build_port_name_plan(devices, clients)

    assert plan.renames[0].proposed == 'New-Name +1'


# ─── Placeholder recognition ─────────────────────────────────────────────────


def test_placeholder_covers_ultra_series_poe_defaults() -> None:
    assert is_placeholder_name('PoE Out + Data') is True
    assert is_placeholder_name('PoE In + Data') is True
    assert is_placeholder_name('Port 7', 7) is True
    assert is_placeholder_name('') is True


def test_real_labels_are_not_placeholders() -> None:
    assert is_placeholder_name('Bravo4 U6-Pro') is False
    assert is_placeholder_name('Port 7 Media Rack') is False
    assert is_placeholder_name('myHivehub') is False


def test_weak_label_detection() -> None:
    assert is_weak_label('0200fe00000a') is True
    assert is_weak_label('02:00:fe:02:00:0f') is True
    assert is_weak_label('MacMiniM4') is False


# ─── Scope: what must never be touched ───────────────────────────────────────


def test_down_ports_are_left_alone() -> None:
    """A disconnected port's label is the only record of what used to be there."""
    devices = [_switch('A', [_port(3, 'Port 3', up=False)], mac='sw:01')]
    clients = [_client('aa:bb', 'sw:01', 3, name='Something')]

    assert build_port_name_plan(devices, clients).count == 0


def test_non_switch_devices_are_skipped() -> None:
    devices = [
        {
            '_id': 'g',
            'mac': 'gw:01',
            'name': 'Gateway',
            'type': 'ugw',
            'port_table': [_port(1, 'Port 1')],
            'lldp_table': [],
        }
    ]
    clients = [_client('aa:bb', 'gw:01', 1, name='WAN')]

    assert build_port_name_plan(devices, clients).count == 0


def test_names_are_truncated_to_the_controller_limit() -> None:
    devices = [_switch('A', [_port(1, 'Port 1')], mac='sw:01')]
    clients = [_client('aa:bb', 'sw:01', 1, name='X' * 60)]

    assert len(build_port_name_plan(devices, clients).renames[0].proposed) == 32


def test_plan_groups_by_device() -> None:
    devices = [
        _switch('A', [_port(1, 'Port 1'), _port(2, 'Port 2')], mac='sw:01'),
        _switch('B', [_port(1, 'Port 1')], mac='sw:02'),
    ]
    clients = [
        _client('aa:01', 'sw:01', 1, name='One'),
        _client('aa:02', 'sw:01', 2, name='Two'),
        _client('bb:01', 'sw:02', 1, name='Three'),
    ]

    grouped = build_port_name_plan(devices, clients).by_device()

    assert sorted(grouped) == ['A', 'B']
    assert [r.port_idx for r in grouped['A']] == [1, 2]
