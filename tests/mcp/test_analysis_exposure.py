"""MCP exposure of the PoE, uplink, client-density and DHCP analyses (no live controller)."""

import importlib
import pytest
from pathlib import Path
from tests.fixtures_unifi import assert_no_secrets
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry


pytestmark = pytest.mark.usefixtures('block_network')

MANIFESTS = Path(server.__file__).parent / 'manifests'

# name -> (module, report key holding the per-item rows)
EXPOSED = {
    'check_poe_budget': ('unifi_mapper.analysis.poe_budget', 'devices'),
    'check_uplink_redundancy': ('unifi_mapper.analysis.uplink_redundancy', 'devices'),
    'analyze_client_density': ('unifi_mapper.analysis.client_density', 'access_points'),
    'check_dhcp_pool_utilization': ('unifi_mapper.analysis.dhcp_pool', 'pools'),
}

DEVICES = [
    {
        '_id': 'sw-core',
        'name': 'Core PoE',
        'mac': 'aa:bb:cc:00:00:01',
        'model': 'USW-Pro-24-PoE',
        'type': 'usw',
        'total_max_power': 100,
        'port_table': [
            {'port_idx': 1, 'up': True, 'speed': 1000, 'poe_mode': 'auto', 'poe_power': '88.0'},
            {'port_idx': 2, 'up': True, 'speed': 1000, 'poe_mode': 'auto', 'poe_power': '3.0'},
            {'port_idx': 25, 'up': True, 'speed': 10000, 'is_uplink': True, 'poe_mode': 'off'},
        ],
    },
    {
        '_id': 'sw-edge',
        'name': 'Edge',
        'mac': 'aa:bb:cc:00:00:02',
        'model': 'USW-Flex-XG',
        'type': 'usw',
        'port_table': [
            {'port_idx': 1, 'up': True, 'speed': 10000, 'is_uplink': True},
            {'port_idx': 2, 'up': False, 'speed': 0, 'is_uplink': True},
        ],
    },
    {'_id': 'ap-1', 'name': 'Office AP', 'mac': 'aa:bb:cc:00:00:03', 'type': 'uap'},
]
CLIENTS = [
    *[
        {'is_wired': False, 'ap_mac': 'AA:BB:CC:00:00:03', 'signal': -60, 'network_id': 'net-iot'}
        for _ in range(31)
    ],
    {'is_wired': True, 'network_id': 'net-lan'},
]
NETWORKS = [
    {
        '_id': 'net-iot',
        'name': 'IoT',
        'vlan': 30,
        'dhcpd_enabled': True,
        'dhcpd_start': '10.0.30.10',
        'dhcpd_stop': '10.0.30.47',
    },
    {
        '_id': 'net-lan',
        'name': 'LAN',
        'dhcpd_enabled': True,
        'dhcpd_start': '10.0.0.100',
        'dhcpd_stop': '10.0.0.199',
    },
    {'_id': 'net-off', 'name': 'Static', 'dhcpd_enabled': False},
]


def _fake_client_class(calls: list[str]):
    """An async stand-in for UniFiClient over the dict fixtures, recording each read."""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_devices(self):
            calls.append('get_devices')
            return DEVICES

        async def get_clients(self):
            calls.append('get_clients')
            return CLIENTS

        async def get_networks(self):
            calls.append('get_networks')
            return NETWORKS

    return _FakeClient


@pytest.fixture
def fake_unifi(monkeypatch) -> list[str]:
    """Patch UniFiClient in every exposed module and pass the MCP credential gate."""
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'FAKE-GATE-TOKEN')  # pragma: allowlist secret
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(MANIFESTS))
    calls: list[str] = []
    for module, _ in EXPOSED.values():
        monkeypatch.setattr(
            importlib.import_module(module), 'UniFiClient', _fake_client_class(calls)
        )
    return calls


def _without_timestamp(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != 'timestamp'}


async def test_search_tools_lists_the_four_analyses():
    found = {r['name']: r for r in await server.search_tools(category='analysis')}
    assert set(EXPOSED) <= set(found)
    poe = (await server.get_tool_info('check_poe_budget'))['description']
    assert 'audit_power_budget' in poe


@pytest.mark.parametrize('name', sorted(EXPOSED))
def test_manifest_entries_are_read_only_controller_tools_without_parameters(name):
    meta = ToolRegistry(MANIFESTS, strict=True).get_metadata(name)
    assert meta is not None
    assert meta.category == 'analysis'
    assert (meta.module, meta.handler) == (EXPOSED[name][0], name)
    assert meta.parameters == {}
    assert meta.mutates is False
    assert meta.credentials == 'controller'


@pytest.mark.parametrize('name', sorted(EXPOSED))
async def test_execute_tool_returns_the_model_dump(fake_unifi, name):
    module, rows = EXPOSED[name]
    raw = await server.execute_tool(name, {})
    out = raw.structuredContent
    assert out['ok'] is True, out
    assert raw.isError is not True
    assert out['result'][rows], out['result']
    handler = getattr(importlib.import_module(module), name)
    expected = (await handler()).model_dump(mode='json')
    assert _without_timestamp(out['result']) == _without_timestamp(expected)
    assert_no_secrets(raw.model_dump(mode='json'))
    assert set(fake_unifi) <= {'get_devices', 'get_clients', 'get_networks'}


async def test_fixture_findings_reach_the_mcp_result(fake_unifi):
    poe = (await server.execute_tool('check_poe_budget', {})).structuredContent['result']
    assert [d['status'] for d in poe['devices']] == ['CRITICAL']
    uplinks = (await server.execute_tool('check_uplink_redundancy', {})).structuredContent
    by_name = {d['device_name']: d for d in uplinks['result']['devices']}
    assert by_name['Core PoE']['redundant'] is False
    assert by_name['Edge']['redundant'] is True
    density = (await server.execute_tool('analyze_client_density', {})).structuredContent
    assert density['result']['access_points'][0]['status'] == 'WARNING'
    dhcp = (await server.execute_tool('check_dhcp_pool_utilization', {})).structuredContent
    assert {p['network_name']: p['status'] for p in dhcp['result']['pools']} == {
        'IoT': 'WARNING',
        'LAN': 'OK',
    }


async def test_unknown_parameter_is_rejected(fake_unifi):
    raw = await server.execute_tool('check_poe_budget', {'switch': 'x'})
    assert raw.isError is True
    assert raw.structuredContent['error_code'] == 'INVALID_PARAMETERS'
    assert fake_unifi == []


async def test_controller_failure_is_a_tool_error(monkeypatch, fake_unifi):
    class _Down:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_networks(self):
            raise OSError('connection refused')

    from unifi_mapper.analysis import dhcp_pool

    monkeypatch.setattr(dhcp_pool, 'UniFiClient', _Down)
    raw = await server.execute_tool('check_dhcp_pool_utilization', {})
    assert raw.isError is True
    assert raw.structuredContent['ok'] is False
    assert raw.structuredContent['error_code'] == 'CONTROLLER_UNREACHABLE'
