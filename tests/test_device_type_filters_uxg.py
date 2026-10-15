"""A UXG gateway passes every device-type filter (issue 085's second half).

The topology classifier learned ``uxg`` in 0.4.0; the type filters in ``run_methods`` (what
``discover`` maps and what the smart mapper analyses) and in ``mac_analyzer`` (which switches
are read) still listed only ``ugw``, ``usg`` and ``udm``, so a UXG site had no gateway in its
diagrams and no gateway in its MAC table.
"""

from __future__ import annotations

import pytest
from tests.fake_controller import API, FakeController, legacy, serving
from tests.fixtures_unifi import FAKE_TOKEN
from types import SimpleNamespace
from typing import Any
from unifi_mapper import run_methods
from unifi_mapper.analysis.mac_analyzer import analyze_mac_table
from unifi_mapper.core.device_types import GATEWAY_TYPES, NETWORK_DEVICE_TYPES, SWITCHING_TYPES


UXG = {
    '_id': 'gw-1',
    'name': 'Gateway',
    'mac': '02:00:00:00:00:a1',
    'type': 'uxg',
    'model': 'UXGPRO',
}
SWITCH = {
    '_id': 'sw-1',
    'name': 'Switch',
    'mac': '02:00:00:00:00:b1',
    'type': 'usw',
    'model': 'USWED37',
}
AP = {'_id': 'ap-1', 'name': 'AP', 'mac': '02:00:00:00:00:c1', 'type': 'uap', 'model': 'U6LR'}


def test_the_type_sets_know_every_gateway_code() -> None:
    assert {'ugw', 'usg', 'udm', 'uxg'} <= GATEWAY_TYPES
    assert GATEWAY_TYPES < SWITCHING_TYPES < NETWORK_DEVICE_TYPES
    assert (
        'usw' in SWITCHING_TYPES and 'uap' in NETWORK_DEVICE_TYPES and 'uap' not in SWITCHING_TYPES
    )


def test_smart_analysis_keeps_a_uxg_gateway() -> None:
    calls: list[str] = []

    class FakeApi:
        def get_devices(self, site_id: str) -> dict[str, Any]:
            return {'data': [UXG, SWITCH, AP]}

        def get_lldp_info(self, site_id: str, device_id: str) -> dict[str, Any]:
            calls.append(device_id)
            return {}

    devices, _lldp = run_methods.get_devices_and_lldp_data(
        SimpleNamespace(api_client=FakeApi()), 'default'
    )

    assert [d['_id'] for d in devices] == ['gw-1', 'sw-1']
    assert calls == ['gw-1', 'sw-1']


@pytest.fixture
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', FAKE_TOKEN)


@pytest.mark.usefixtures('_env')
async def test_mac_table_analyses_a_uxg_gateway() -> None:
    gateway = {
        **UXG,
        'port_table': [{'port_idx': 1, 'name': 'Port 1', 'mac_table_count': 1}],
    }
    client = {
        'mac': '00:00:5e:00:53:01',
        'is_wired': True,
        'sw_mac': UXG['mac'],
        'sw_port': 1,
        'sw_depth': 1,
    }
    controller = FakeController(
        {
            f'{API}/stat/device': legacy([gateway]),
            f'{API}/stat/sta': legacy([client]),
            f'{API}/rest/portconf': legacy([]),
        }
    )
    async with serving(controller):
        report = await analyze_mac_table(max_macs_per_port=5)

    assert report.devices_analyzed == 1
    assert report.total_mac_entries == 1


def test_a_uxg_or_udm_pro_gateway_is_assessed_for_port_naming() -> None:
    """port_naming_capabilities kept its own device-type set (ugw, usg, udm, usw) after the
    shared one was introduced, so a UXG or UDM Pro gateway's ports were silently skipped."""
    from unifi_mapper.analysis.port_naming_capabilities import assess_port_naming

    devices = [
        {'type': 'uxg', 'model': 'UXGPRO', 'version': '4.1.0', 'name': 'gw'},
        {'type': 'udmpro', 'model': 'UDMPRO', 'version': '4.1.0', 'name': 'gw2'},
        {'type': 'uap', 'model': 'U6LR', 'version': '6.6.0', 'name': 'ap'},
    ]
    report = assess_port_naming(devices, timestamp='2026-10-15T00:00:00Z')
    assessed = {d.name for d in report.devices}
    assert assessed == {'gw', 'gw2'}, 'both gateways assessed, the AP skipped'
