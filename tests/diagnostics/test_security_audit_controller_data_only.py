"""`security_audit` reports only what the controller can show (issue 080).

After issue 079 a healthy home site still reported 2 high, 48 medium, 105 unknown devices and
11 MAC anomalies: its own adopted devices as "security-sensitive vendor: Unknown", every
smart plug for its chipset vendor, every phone for its randomised MAC, its own switches for
their sequential batch MACs, and every client as "unknown" because nothing sets
``is_authorized``. The audit is now controller-data-only: the risks are pending adoption,
guest-network overstay and the issue-079 rogue classes; everything else is information or
nothing, and a check that could not run is "not assessed", never a zero.
"""

import importlib
import time
from typing import Any


module = importlib.import_module('unifi_mapper.diagnostics.security_audit')

NOW = int(time.time())


def device(**overrides: Any) -> dict[str, Any]:
    """A ``stat/device`` record: an adopted UniFi switch, no ``oui`` (they never carry one)."""
    base = {
        'mac': '02:00:00:00:00:10',
        'name': 'Hall Switch',
        'type': 'usw',
        'model': 'USL8LP',
        'adopted': True,
        'ip': '192.0.2.10',
        'first_seen': NOW - 86400 * 30,
        'last_seen': NOW,
    }
    base.update(overrides)
    return base


def client(**overrides: Any) -> dict[str, Any]:
    """A ``stat/sta`` record: a smart plug on the IoT network."""
    base = {
        'mac': '02:00:00:00:00:20',
        'hostname': 'plug-kitchen',
        'oui': 'Espressif Inc.',
        'ip': '192.0.2.20',
        'network': 'IoT',
        'vlan': 20,
        'uptime': 3600,
        'tx_bytes': 1000,
        'first_seen': NOW - 86400 * 30,
        'last_seen': NOW,
    }
    base.update(overrides)
    return base


def report(devices: list[dict[str, Any]] = [], clients: list[dict[str, Any]] = [], **kwargs: Any):
    kwargs.setdefault('rogue_aps', [])
    kwargs.setdefault('networks_data', [])
    kwargs.setdefault('wlans_data', [])
    return module._perform_security_analysis(devices, clients, **kwargs)


def flags_of(rep, mac: str) -> list[str]:
    for d in [*rep.critical_risks, *rep.high_risks, *rep.medium_risks, *rep.new_devices]:
        if d.mac == mac:
            return d.security_flags
    return []


# --- dropped rules, each on the fixture that used to trigger it ---------------------------


def test_an_adopted_device_with_no_oui_is_not_a_vendor_risk() -> None:
    rep = report([device()])
    assert rep.medium_risks == [] and rep.high_risks == [] and rep.critical_risks == []
    assert rep.authorized_devices == 1 and rep.unauthorized_devices == 0
    assert not hasattr(module, '_is_suspicious_vendor')


def test_an_iot_chipset_vendor_is_not_a_risk() -> None:
    plugs = [
        client(oui=vendor, mac=f'02:00:00:00:00:2{i}')
        for i, vendor in enumerate(['Espressif Inc.', 'Realtek', 'Ralink', 'Private', 'Unknown'])
    ]
    rep = report([], plugs)
    assert rep.medium_risks == [] and rep.high_risks == []
    assert not any('vendor' in f.lower() for d in rep.new_devices for f in d.security_flags)


def test_a_randomised_mac_is_information_not_a_risk() -> None:
    phone = client(mac='da:a1:19:00:00:01', hostname='Pixel', oui='', tx_bytes=5_000_000_000)
    rep = report([], [phone])
    assert rep.medium_risks == [] and rep.high_risks == [] and rep.critical_risks == []
    rep_new = report([], [dict(phone, first_seen=NOW - 60)])
    [new] = rep_new.new_devices
    assert new.risk_level == 'low'
    assert any(
        'randomised' in f.lower() or 'locally administered' in f.lower()
        for f in new.security_flags
    )


def test_a_generic_infrastructure_name_is_not_a_risk() -> None:
    rep = report([device(name='Unknown')])
    assert rep.medium_risks == [] and rep.anomalous_devices == 0


def test_high_client_traffic_is_not_a_risk() -> None:
    rep = report([], [client(tx_bytes=50_000_000_000)])
    assert rep.medium_risks == [] and rep.anomalous_devices == 0


def test_a_mac_pattern_is_not_a_risk() -> None:
    rep = report([], [client(mac='12:34:56:78:9a:bc'), client(mac='')])
    assert rep.high_risks == [] and rep.medium_risks == []


def test_several_information_flags_do_not_add_up_to_a_risk() -> None:
    # Randomised MAC + inactive for a day + brand new: three flags used to mean "critical".
    stale_phone = client(
        mac='da:a1:19:00:00:02', hostname='Pixel', first_seen=NOW - 60, last_seen=NOW - 86400 * 2
    )
    rep = report([], [stale_phone])
    assert rep.critical_risks == [] and rep.high_risks == [] and rep.medium_risks == []
    [new] = rep.new_devices
    assert new.risk_level == 'low' and len(new.security_flags) >= 2


# --- authorised / unauthorised only where the controller has a source of truth -------------


def test_the_unknown_count_is_gone_and_a_plain_client_is_not_assessed() -> None:
    rep = report([device()], [client(first_seen=NOW - 60)])
    assert 'unknown_devices' not in type(rep).model_fields
    [plain] = rep.new_devices
    assert plain.is_authorized is None  # nothing in the controller says either way
    assert rep.authorized_devices == 1  # the adopted device, not the client
    assert rep.unauthorized_devices == 0


def test_blocked_and_noted_clients_are_the_controller_s_verdicts() -> None:
    blocked = client(mac='02:00:00:00:00:31', blocked=True)
    noted = client(mac='02:00:00:00:00:32', noted=True)
    plain = client(mac='02:00:00:00:00:33')
    rep = report([], [blocked, noted, plain])
    assert rep.authorized_devices == 1 and rep.unauthorized_devices == 1
    # A blocked client is the controller doing its job, not a risk to act on.
    assert rep.high_risks == [] and rep.medium_risks == []


# --- the risks that remain ------------------------------------------------------------------


def test_pending_adoption_is_high_and_read_from_the_record_not_the_oui() -> None:
    rep = report([device(adopted=False, mac='02:00:00:00:00:11', name='New AP')])
    [pending] = rep.high_risks
    assert pending.mac == '02:00:00:00:00:11' and pending.is_authorized is False
    assert any('adopt' in f.lower() for f in pending.security_flags)
    assert rep.unauthorized_devices == 1


def test_guest_overstay_is_a_medium_risk() -> None:
    guest = client(mac='02:00:00:00:00:40', is_guest=True, network='Guest', uptime=90000)
    fresh = client(mac='02:00:00:00:00:41', is_guest=True, network='Guest', uptime=600)
    rep = report([], [guest, fresh])
    assert [g.mac for g in rep.guest_violations] == ['02:00:00:00:00:40']
    [medium] = rep.medium_risks
    assert medium.mac == '02:00:00:00:00:40' and medium.is_anomalous is True
    assert any('guest' in f.lower() for f in medium.security_flags)


# --- MAC similarity within the client population only ---------------------------------------


def test_mac_similarity_is_computed_within_clients_only() -> None:
    switches = [
        device(mac='02:00:00:00:00:10', name='Switch A'),
        device(mac='02:00:00:00:00:11', name='Switch B'),  # a sequential batch MAC
    ]
    clients = [
        client(mac='02:00:00:00:00:20'),
        client(mac='02:00:00:00:00:21', hostname='plug-hall'),
    ]
    rep = report(switches, clients)
    assert len(rep.mac_anomalies) == 1
    assert (
        '02:00:00:00:00:20' in rep.mac_anomalies[0] and '02:00:00:00:00:21' in rep.mac_anomalies[0]
    )
    assert not any('02:00:00:00:00:1' in a for a in rep.mac_anomalies)


# --- limitations and "not assessed" ---------------------------------------------------------


def test_the_report_states_its_limitations() -> None:
    rep = report([device()], [client()])
    text = ' '.join(rep.limitations).lower()
    assert 'controller' in text
    assert 'not proof' in text and 'authoris' in text and 'compromise' in text
    assert 'not assessed' in text


class FakeClient:
    def __init__(self, *, rogue_error: Exception | None = None) -> None:
        self.rogue_error = rogue_error

    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def build_path(self, endpoint: str) -> str:
        return f'/proxy/network/api/s/default/{endpoint}'

    async def get(self, path: str) -> list[dict[str, Any]]:
        if path.endswith('stat/device'):
            return [device()]
        if path.endswith('rest/wlanconf'):
            raise RuntimeError('HTTP 403: api.err.NoPermission')
        return []

    async def get_rogue_aps(self) -> list[dict[str, Any]]:
        if self.rogue_error:
            raise self.rogue_error
        return []


async def test_a_check_that_could_not_run_is_not_assessed_never_zero(monkeypatch) -> None:
    fake = FakeClient(rogue_error=RuntimeError('HTTP 500: api.err.ServerBusy'))
    monkeypatch.setattr(module, 'UniFiClient', lambda: fake)
    rep = await module.security_audit()
    assert rep.rogue_aps == [] and rep.neighbour_aps == 0
    not_assessed = [line for line in rep.limitations if 'not assessed' in line.lower()]
    assert any('stat/rogueap' in line and 'ServerBusy' in line for line in not_assessed)
    assert any('rest/wlanconf' in line for line in not_assessed)
    assert not any('rogue' in a.lower() for a in rep.immediate_actions)
    assert rep.total_devices == 1  # the audit still ran on what it could read
