"""The STP priority audit over an anonymised 17-switch fleet (16 switches and a gateway).

The fixture keeps the shape of a real 17-device capture from the prototype (a local archive,
not in the repo): its models, STP priorities, port STP state and LLDP links. Every
identifier is a documentation value (IDs, ``02:00:00:…`` MACs, ``Switch NN`` and ``Port N``
names), and it holds no address, client or counter. The shape guard below keeps it that way.
"""

import json
import pytest
import re
from pathlib import Path
from tests.fake_controller import API, FakeController, legacy, serving
from typing import Any
from unifi_mapper.analysis.stp_audit import audit_stp_priorities


FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'fleet_17_switch_anonymised.json'
DEVICE_KEYS = {'_id', 'mac', 'name', 'model', 'type', 'stp_priority', 'port_table', 'lldp_table'}
PORT_KEYS = {
    'port_idx',
    'name',
    'stp_state',
    'stp_role',
    'stp_pathcost',
    'up',
    'enabled',
    'speed',
    'full_duplex',
}
LLDP_KEYS = {'local_port_idx', 'chassis_id', 'local_port_name', 'port_id'}
LOCAL_MAC = re.compile(r'02:00:00:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}')
ANY_MAC = re.compile(r'[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}')
IPV4 = re.compile(r'(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])')


def _fleet() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def _devices() -> list[dict[str, Any]]:
    return _fleet()['devices']


# --- the shape guard ----------------------------------------------------------------------


def test_the_fixture_holds_only_documentation_values() -> None:
    fleet = _fleet()
    text = FIXTURE.read_text(encoding='utf-8')
    assert set(fleet) == {'devices', 'generated', 'source'}
    assert fleet['source'].startswith("anonymised: a real fleet's shape")
    assert IPV4.findall(text) == []
    assert all(LOCAL_MAC.fullmatch(mac) for mac in ANY_MAC.findall(text))
    devices = fleet['devices']
    assert len(devices) == 17
    for i, device in enumerate(devices):
        assert set(device) <= DEVICE_KEYS
        assert device['_id'] == f'{i:024x}' and device['mac'] == f'02:00:00:00:00:{i:02x}'
        assert re.fullmatch(r'Gateway|Switch \d\d', device['name'])
        for port in device['port_table']:
            assert set(port) <= PORT_KEYS
            assert port['name'] == f'Port {port["port_idx"]}'
        for entry in device['lldp_table']:
            assert set(entry) <= LLDP_KEYS
            assert LOCAL_MAC.fullmatch(entry['chassis_id'])
            assert re.fullmatch(r'Port \d+', entry['local_port_name'])
            assert re.fullmatch(r'Port \d+', entry['port_id'])
    assert [d['type'] for d in devices].count('udm') == 1
    assert {d['name'] for d in devices if d['type'] == 'udm'} == {'Gateway'}


# --- the audit over the fleet -------------------------------------------------------------


async def _audit(device: str | None = None) -> tuple[dict[str, Any], FakeController]:
    controller = FakeController({f'{API}/stat/device': legacy(_devices())})
    async with serving(controller):
        return await audit_stp_priorities(device), controller


async def test_the_fleet_audit_has_one_preferred_root_and_skips_only_the_gateway() -> None:
    report, controller = await _audit()
    gateway_id = next(d['_id'] for d in _devices() if d['type'] == 'udm')
    assert len(report['switches']) == 16
    assert [s['name'] for s in report['switches'] if s['optimal_priority'] == 4096] == [
        'Switch 06'
    ]
    assert [s['device_id'] for s in report['skipped']] == [gateway_id]
    assert all(c['device_id'] != gateway_id for c in report['remediation']['changes'])
    assert all(row['device_id'] != gateway_id for row in report['switches'])
    assert len({row['tier'] for row in report['switches']}) > 1  # a hierarchy, not flat
    assert controller.methods == {'GET'}


async def test_every_scoped_row_equals_its_fleet_row() -> None:
    fleet, _ = await _audit()
    for row in fleet['switches']:
        scoped, _ = await _audit(row['device_id'])
        assert scoped['switches'] == [row], row['name']
        assert scoped['current_root'] == fleet['current_root']
        assert scoped['remediation']['changes'] == [
            c for c in fleet['remediation']['changes'] if c['device_id'] == row['device_id']
        ]


@pytest.mark.parametrize('query', ['Switch 06', '02-00-00-00-00-06', '02:00:00:00:00:06'])
async def test_the_preferred_root_resolves_by_name_and_by_mac(query: str) -> None:
    scoped, _ = await _audit(query)
    assert [row['name'] for row in scoped['switches']] == ['Switch 06']
