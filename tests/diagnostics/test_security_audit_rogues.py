"""`security_audit` tells a rogue AP from a neighbour (issue 079).

A neighbouring access point is a rogue only when it threatens this site: it broadcasts one of
this site's SSIDs from hardware that is not ours (critical), the controller flags it as seen
on our wired network (``is_rogue``, high), or it is UniFi hardware not adopted here heard at
a signal that puts it on the premises (medium). Everything else is a neighbour: counted, the
strongest three listed for interference context, never a risk, never an action.
"""

import importlib
from typing import Any


module = importlib.import_module('unifi_mapper.diagnostics.security_audit')

OWN_BSSIDS = {'02:00:00:00:00:a1', '02:00:00:00:00:a2'}
OWN_SSIDS = {'HomeNet', 'HomeNet-IoT'}


def entry(**overrides: Any) -> dict[str, Any]:
    base = {
        'bssid': '02:00:00:00:00:b1',
        'essid': 'NextDoor',
        'channel': 6,
        'band': 'ng',
        'signal': -78,
        'security': 'WPA2-Personal (AES/CCMP)',
        'age': 12,
        'ap_name': 'Hall AP',
        'is_ubnt': False,
        'is_unifi': False,
        'is_rogue': False,
        'oui': 'Netgear',
        'model_display': '',
    }
    base.update(overrides)
    return base


def classify(entries: list[dict[str, Any]]):
    return module.classify_rogue_aps(entries, own_bssids=OWN_BSSIDS, own_ssids=OWN_SSIDS)


def test_a_plain_neighbour_is_counted_and_never_a_risk() -> None:
    rogues, neighbours = classify([entry()])
    assert rogues == []
    assert len(neighbours) == 1 and neighbours[0].essid == 'NextDoor'


def test_our_ssid_from_foreign_hardware_is_a_critical_impersonation() -> None:
    rogues, neighbours = classify([entry(essid='HomeNet', bssid='02:00:00:00:00:c1', signal=-61)])
    assert neighbours == []
    [rogue] = rogues
    assert rogue.risk_level == 'critical'
    assert rogue.type == 'rogue_ap' and rogue.mac == '02:00:00:00:00:c1'
    assert rogue.is_authorized is False and rogue.is_anomalous is True
    assert any(
        'HomeNet' in flag and 'not one of this site' in flag for flag in rogue.security_flags
    )
    assert any('Hall AP' in flag for flag in rogue.security_flags)


def test_the_controller_s_own_rogue_flag_is_high() -> None:
    rogues, neighbours = classify([entry(is_rogue=True)])
    assert neighbours == []
    [rogue] = rogues
    assert rogue.risk_level == 'high'
    assert any('wired' in flag for flag in rogue.security_flags)


def test_unifi_hardware_not_adopted_here_is_medium_only_when_heard_strongly() -> None:
    strong, weak = (
        entry(is_ubnt=True, is_unifi=True, signal=-55, model_display='U6 Pro'),
        entry(is_ubnt=True, is_unifi=True, signal=-80, bssid='02:00:00:00:00:b2'),
    )
    rogues, neighbours = classify([strong, weak])
    [rogue] = rogues
    assert rogue.mac == strong['bssid'] and rogue.risk_level == 'medium'
    assert rogue.vendor == 'U6 Pro'
    assert any('not adopted' in flag for flag in rogue.security_flags)
    assert [n.bssid for n in neighbours] == ['02:00:00:00:00:b2']


def test_our_own_radios_and_stale_entries_are_ignored() -> None:
    own = entry(bssid='02:00:00:00:00:A1', essid='HomeNet')  # case differs on purpose
    stale = entry(bssid='02:00:00:00:00:b3', age=module.MAX_ROGUE_AGE_SECONDS + 1)
    rogues, neighbours = classify([own, stale])
    assert rogues == [] and neighbours == []


def test_impersonation_outranks_the_other_rules() -> None:
    rogues, _ = classify([entry(essid='HomeNet-IoT', is_rogue=True, is_ubnt=True, signal=-40)])
    [rogue] = rogues
    assert rogue.risk_level == 'critical'
    assert (
        sum('wired' in f for f in rogue.security_flags) == 1
    )  # the other evidence is still listed


def test_strongest_neighbours_are_the_three_loudest_in_order() -> None:
    entries = [
        entry(bssid=f'02:00:00:00:00:{i:02x}', essid=f'N{i}', signal=-90 + i) for i in range(10)
    ]
    report = module._perform_security_analysis([], [], entries, [], wlans_data=[])
    assert report.neighbour_aps == 10
    assert [n.essid for n in report.strongest_neighbours] == ['N9', 'N8', 'N7']
    assert report.strongest_neighbours[0].signal == -81
    assert (
        report.rogue_aps == [] and report.critical_risks == [] and report.unauthorized_devices == 0
    )
    assert not any('rogue' in action.lower() for action in report.immediate_actions)
    assert any('10 neighbouring' in r for r in report.security_recommendations)


def test_the_report_wires_own_ssids_from_wlanconf_and_vap_table() -> None:
    devices = [
        {
            'mac': '02:00:00:00:00:10',
            'name': 'Hall AP',
            'type': 'uap',
            'adopted': True,
            'vap_table': [{'bssid': '02:00:00:00:00:A1', 'essid': 'HomeNet'}],
        }
    ]
    wlans = [{'name': 'HomeNet'}, {'name': 'Guest-Legacy'}]
    rogues = [
        entry(
            essid='Guest-Legacy', bssid='02:00:00:00:00:c9', signal=-70
        ),  # a disabled WLAN's name
        entry(essid='HomeNet', bssid='02:00:00:00:00:a1'),  # our own radio heard by another AP
        entry(),
    ]
    report = module._perform_security_analysis(devices, [], rogues, [], wlans_data=wlans)
    assert [r.mac for r in report.rogue_aps] == ['02:00:00:00:00:c9']
    assert report.rogue_aps[0].risk_level == 'critical'
    assert report.neighbour_aps == 1
    assert report.unauthorized_devices == 1  # the impersonator, not the neighbour
    assert any('Guest-Legacy' in a for a in report.immediate_actions)
    # The neighbour's BSSID no longer feeds the MAC-anomaly pass.
    assert not any('02:00:00:00:00:b1' in a for a in report.mac_anomalies)


class FakeClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def build_path(self, endpoint: str) -> str:
        return f'/proxy/network/api/s/default/{endpoint}'

    async def get(self, path: str) -> list[dict[str, Any]]:
        self.paths.append(path)
        if path.endswith('rest/wlanconf'):
            return [{'name': 'HomeNet'}]
        return []

    async def get_rogue_aps(self) -> list[dict[str, Any]]:
        return [entry(essid='HomeNet', bssid='02:00:00:00:00:c1')]


async def test_security_audit_reads_the_wlan_list_and_classifies(monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(module, 'UniFiClient', lambda: fake)
    report = await module.security_audit()
    assert any(p.endswith('rest/wlanconf') for p in fake.paths)
    assert [r.risk_level for r in report.rogue_aps] == ['critical']
    assert report.neighbour_aps == 0
