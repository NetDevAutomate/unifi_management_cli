"""T3: call shapes through ToolRunner for the drifted tools, plus type validation."""

import importlib
import inspect
import pytest
import sys
from pathlib import Path
from tests.fixtures_unifi import NAS_MAC, SWITCH_MAC
from tests.mcp import fakes
from typing import Any
from unifi_mapper.mcp.config import ServerSettings
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.mcp.runner import ToolRunner


GATE_ENV = {
    'UNIFI_URL': 'https://192.0.2.1',
    'UNIFI_CONSOLE_API_TOKEN': 'FAKE-SHAPES-CONSOLE-TOKEN',  # pragma: allowlist secret
}


@pytest.fixture
def gate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in GATE_ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def shipped() -> ToolRunner:
    return ToolRunner(
        ToolRegistry(default_manifests_dir(), strict=True), settings=ServerSettings()
    )


def _record(monkeypatch: pytest.MonkeyPatch, name: str) -> list[dict[str, Any]]:
    """Replace a shipped tool's handler with a recording fake carrying its signature."""
    meta = ToolRegistry(default_manifests_dir(), strict=True).get_metadata(name)
    assert meta is not None
    module = importlib.import_module(meta.module)
    real = getattr(module, meta.handler)
    received: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        received.append(kwargs)
        return {'ok': True}

    fake.__signature__ = inspect.signature(real, eval_str=True)  # type: ignore[attr-defined]
    monkeypatch.setattr(module, meta.handler, fake)
    return received


async def _envelope(runner: ToolRunner, name: str, params: dict[str, Any]) -> dict[str, Any]:
    out = (await runner.run(name, params)).structuredContent
    assert out is not None
    return out


# ---------------------------------------------------------------------------
# The drifted tools: canonical and alias shapes
# ---------------------------------------------------------------------------

SHAPES = [
    ('find_device', {'identifier': 'USW Flex XG'}, {'query': 'USW Flex XG'}),
    ('find_ip', {'ip': '192.0.2.51'}, {'ip_address': '192.0.2.51'}),
    ('find_mac', {'mac': NAS_MAC}, {'mac_address': NAS_MAC}),
    ('client_trace', {'client': NAS_MAC}, {'client_id': NAS_MAC}),
]


@pytest.mark.usefixtures('gate_env')
@pytest.mark.parametrize(('name', 'canonical', 'alias'), SHAPES)
async def test_canonical_and_alias_shapes_reach_the_handler(
    shipped, monkeypatch, name, canonical, alias
) -> None:
    received = _record(monkeypatch, name)
    assert (await _envelope(shipped, name, canonical))['ok'] is True
    assert (await _envelope(shipped, name, alias))['ok'] is True
    assert received == [canonical, canonical]


@pytest.mark.usefixtures('gate_env')
@pytest.mark.parametrize(('name', 'canonical', 'alias'), SHAPES)
async def test_alias_and_canonical_together_are_rejected(
    shipped, monkeypatch, name, canonical, alias
) -> None:
    received = _record(monkeypatch, name)
    out = await _envelope(shipped, name, {**canonical, **alias})
    assert out['error_code'] == 'INVALID_PARAMETERS'
    assert received == []


@pytest.mark.usefixtures('gate_env')
async def test_traceroute_canonical_shape(shipped, monkeypatch) -> None:
    received = _record(monkeypatch, 'traceroute')
    params = {'source': 'gateway', 'destination': '192.0.2.51', 'verbosity': 'expert'}
    assert (await _envelope(shipped, 'traceroute', params))['ok'] is True
    assert received == [{**params, 'include_firewall': True}]


@pytest.mark.usefixtures('gate_env')
async def test_traceroute_max_hops_gets_the_hint(shipped, monkeypatch) -> None:
    received = _record(monkeypatch, 'traceroute')
    params = {'source': 'gateway', 'destination': '192.0.2.51', 'max_hops': 30}
    out = await _envelope(shipped, 'traceroute', params)
    assert out['error_code'] == 'INVALID_PARAMETERS'
    assert out['message'].startswith('unknown parameter(s): max_hops')
    assert 'max_hops is not supported' in out['message']
    assert 'properties' in out['input_schema']
    assert received == []


@pytest.mark.usefixtures('gate_env')
async def test_a_typo_is_rejected_not_run_fleet_wide(shipped, monkeypatch) -> None:
    received = _record(monkeypatch, 'inspect_switch_port')
    out = await _envelope(shipped, 'inspect_switch_port', {'swtich': 'USW Flex XG', 'port': 5})
    assert out['error_code'] == 'INVALID_PARAMETERS'
    assert 'swtich' in out['message']
    assert received == []


# ---------------------------------------------------------------------------
# path_analysis_mcp: both shapes, neither or both
# ---------------------------------------------------------------------------


@pytest.fixture
def path_module(monkeypatch: pytest.MonkeyPatch):
    """The real path_analysis module with traceroute and the analysis faked."""
    module = sys.modules['unifi_mapper.connectivity.path_analysis']
    traced: list[tuple[str, str]] = []
    analysed: list[Any] = []

    async def fake_traceroute(source: str, destination: str) -> str:
        traced.append((source, destination))
        return 'traced-path'

    async def fake_analysis(path: Any) -> dict[str, Any]:
        analysed.append(path)
        return {'analysed': True}

    monkeypatch.setattr(module, 'traceroute', fake_traceroute)
    monkeypatch.setattr(module, 'path_analysis', fake_analysis)
    return module, traced, analysed


async def test_path_analysis_mcp_with_endpoints_traces_first(path_module) -> None:
    module, traced, analysed = path_module
    out = await module.path_analysis_mcp(source='gateway', destination='192.0.2.51')
    assert out == {'analysed': True}
    assert traced == [('gateway', '192.0.2.51')]
    assert analysed == ['traced-path']


async def test_path_analysis_mcp_with_a_path_skips_the_trace(path_module) -> None:
    module, traced, analysed = path_module
    sentinel = object()
    assert await module.path_analysis_mcp(path=sentinel) == {'analysed': True}
    assert traced == [] and analysed == [sentinel]


VALID_PATH = {
    'source': 'gateway',
    'source_resolved': '192.0.2.1',
    'destination': 'ugreen',
    'destination_resolved': '192.0.2.51',
}


@pytest.mark.usefixtures('gate_env')
@pytest.mark.parametrize(
    'params',
    [
        {},
        {'source': 'gateway'},
        {'destination': '192.0.2.51'},
        {'path': VALID_PATH, 'source': 'gateway'},
        {'path': VALID_PATH, 'source': 'gateway', 'destination': '192.0.2.51'},
    ],
)
async def test_path_analysis_neither_or_both_is_config_invalid(shipped, path_module, params):
    _, traced, analysed = path_module
    out = await _envelope(shipped, 'path_analysis', params)
    assert out['error_code'] == 'CONFIG_INVALID'
    assert 'source and destination' in out['message']
    assert traced == [] and analysed == []


@pytest.mark.usefixtures('gate_env')
async def test_path_analysis_path_shape_through_execute_tool(shipped, path_module) -> None:
    _, traced, analysed = path_module
    out = await _envelope(shipped, 'path_analysis', {'path': VALID_PATH})
    assert out == {'ok': True, 'result': {'analysed': True}}
    assert traced == [] and analysed[0].destination_resolved == '192.0.2.51'


@pytest.mark.usefixtures('gate_env')
async def test_path_analysis_endpoints_through_execute_tool(shipped, path_module) -> None:
    _, traced, _ = path_module
    params = {'source': 'gateway', 'destination': '192.0.2.51'}
    out = await _envelope(shipped, 'path_analysis', params)
    assert out == {'ok': True, 'result': {'analysed': True}}
    assert traced == [('gateway', '192.0.2.51')]


# ---------------------------------------------------------------------------
# find_mac end to end with a fake UniFiClient
# ---------------------------------------------------------------------------


class _FakeUniFiClient:
    """Async stand-in for UniFiClient returning dict fixtures."""

    ROUTES = {
        'stat/device': [{'mac': SWITCH_MAC, 'name': 'USW Flex XG', 'model': 'USWFLEXXG'}],
        'stat/sta': [
            {
                'mac': NAS_MAC,
                'hostname': 'ugreen-dxp4800',
                'is_wired': True,
                'sw_mac': SWITCH_MAC,
                'sw_port': 5,
                'vlan': 255,
                'ip': '192.0.2.51',
            }
        ],
        'stat/alluser': [],
    }

    async def __aenter__(self) -> '_FakeUniFiClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def build_path(self, endpoint: str) -> str:
        return endpoint

    async def get(self, path: str) -> list[dict[str, Any]]:
        return self.ROUTES[path]


@pytest.mark.usefixtures('gate_env')
@pytest.mark.parametrize('params', [{'mac': NAS_MAC.upper()}, {'mac_address': NAS_MAC}])
async def test_find_mac_end_to_end(shipped, monkeypatch, params) -> None:
    monkeypatch.setattr(
        sys.modules['unifi_mapper.discovery.find_mac'], 'UniFiClient', _FakeUniFiClient
    )
    out = await _envelope(shipped, 'find_mac', params)
    assert out['ok'] is True, out
    result = out['result']
    assert result['connected_to'] == SWITCH_MAC
    assert result['port_number'] == 5
    assert result['connection_type'] == 'wired'


# ---------------------------------------------------------------------------
# Type validation (design §2.5 step 6), on tests/mcp/fakes.py handlers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_runner(tmp_path: Path) -> ToolRunner:
    return ToolRunner(fakes.fake_registry(tmp_path), settings=ServerSettings())


async def test_int_given_numeric_string_is_coerced(fake_runner) -> None:
    out = await _envelope(fake_runner, 'int_param', {'n': '5'})
    assert out == {'ok': True, 'result': {'n': 5, 'type': 'int'}}


@pytest.mark.parametrize(
    ('name', 'params'),
    [
        ('str_param', {'s': 5}),
        ('literal_param', {'verbosity': 'Guided'}),
        ('list_param', {'items': 'eth0'}),
        ('no_params', {'anything': True}),
        ('int_param', {'n': 'five'}),
    ],
)
async def test_wrong_types_and_unknown_keys_are_invalid_parameters(
    fake_runner, name, params
) -> None:
    out = await _envelope(fake_runner, name, params)
    assert out['error_code'] == 'INVALID_PARAMETERS', out
    assert out['input_schema']['type'] == 'object'


async def test_list_given_a_list_is_accepted(fake_runner) -> None:
    out = await _envelope(fake_runner, 'list_param', {'items': ['eth0', 'eth1']})
    assert out == {'ok': True, 'result': {'items': ['eth0', 'eth1']}}
