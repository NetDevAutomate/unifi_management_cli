"""String-valued ``system-stats`` must not crash the health, performance and connectivity tools.

Regression (live check cli-07, 2026-10-02): this controller sends ``system-stats.cpu``
and ``.mem`` as JSON strings on every device (``'7.1'``) and omits ``loadavg_1``.
``network_health_check`` compared them with ints and raised ``TypeError``, so
``diagnose health`` and MCP ``network_health_check`` failed on every run;
``performance_analysis`` and ``connectivity_analysis`` had the same defect, and
``ToolkitAdapter.network_health_check_sync`` silently never flagged a string CPU.
"""

import importlib
import json
import pytest
import re
from pathlib import Path
from tests.fixtures_unifi import assert_no_secrets, fake_devices, fake_sta
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.core.utils.coerce import float_or_none, int_or_none
from unifi_mapper.diagnostic_reads import float_or_none as reads_float_or_none
from unifi_mapper.diagnostic_reads import int_or_none as reads_int_or_none
from unifi_mapper.diagnostics.connectivity_analysis import (
    _assess_segment_congestion,
    _identify_bottlenecks,
)
from unifi_mapper.diagnostics.network_health import _analyze_network_health
from unifi_mapper.diagnostics.performance_analysis import _analyze_device_performance
from unifi_mapper.mcp import server
from unifi_mapper.mcp.registry import ToolRegistry
from unifi_mapper.toolkit_adapters import ToolkitAdapter
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

MODULES = {
    'network_health_check': 'unifi_mapper.diagnostics.network_health',
    'performance_analysis': 'unifi_mapper.diagnostics.performance_analysis',
    'connectivity_analysis': 'unifi_mapper.diagnostics.connectivity_analysis',
}
MANIFESTS = Path(server.__file__).parent / 'manifests'


def _device(name: str, mac: str, **stats: Any) -> dict[str, Any]:
    """An online, adopted switch whose ``system-stats`` holds ``stats`` verbatim."""
    return {
        'name': name,
        'mac': mac,
        'type': 'usw',
        'model': 'USFXG',
        'state': 1,
        'adopted': True,
        'version': '7.0.0',
        'system-stats': stats,
    }


LOW = _device('Quiet', '02:00:00:00:01:01', cpu='7.1', mem='41.2')
HOT = _device('Hot', '02:00:00:00:01:02', cpu='85', mem='90', loadavg_1='2.5')
CRITICAL = _device('Critical', '02:00:00:00:01:03', cpu='96.5', mem='97', loadavg_1='4.5')


# ---------------------------------------------------------------------------
# the coercer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('value', 'expected'),
    [('7.1', 7.1), (7, 7.0), (7.5, 7.5), (' 3 ', 3.0), (None, None), (True, None), ('', None)],
)
def test_float_or_none(value, expected):
    assert float_or_none(value) == expected


@pytest.mark.parametrize(('value', 'expected'), [('7.9', 7), (5, 5), ('x', None), (False, None)])
def test_int_or_none(value, expected):
    assert int_or_none(value) == expected


def test_diagnostic_reads_reexports_the_shared_coercers():
    assert reads_float_or_none is float_or_none
    assert reads_int_or_none is int_or_none


# ---------------------------------------------------------------------------
# the pure analysers, over string-valued system-stats
# ---------------------------------------------------------------------------


def test_network_health_parses_strings_and_thresholds_still_fire():
    report = _analyze_network_health([LOW, HOT, CRITICAL], [], [])
    assert report.high_cpu_devices == ['Hot (85%)', 'Critical (96.5%)']
    assert report.high_memory_devices == ['Hot (90%)', 'Critical (97%)']
    assert report.high_load_devices == ['Hot (2.5)', 'Critical (4.5)']
    assert 'Device Critical has critical CPU usage: 96.5%' in report.critical_issues
    assert 'Device Critical has critical memory usage: 97%' in report.critical_issues
    assert not any('Quiet' in issue for issue in report.critical_issues)
    assert not any('Hot' in issue for issue in report.critical_issues)


def test_network_health_on_the_controller_shape_has_no_findings():
    report = _analyze_network_health(fake_devices(), fake_sta(), [])
    assert report.total_devices == 3
    assert report.high_cpu_devices == [] and report.high_memory_devices == []
    assert report.high_load_devices == []


def test_network_health_ignores_non_numeric_and_null_stats():
    odd = _device('Odd', '02:00:00:00:01:04', cpu='n/a', mem=None, loadavg_1=True)
    nulled = {**_device('Null', '02:00:00:00:01:05'), 'system-stats': None}
    report = _analyze_network_health([odd, nulled], [], [])
    assert report.high_cpu_devices == [] and report.high_memory_devices == []


def test_device_performance_parses_strings_and_thresholds_still_fire():
    low = _analyze_device_performance(LOW)
    assert low is not None
    assert (low.cpu_percent, low.memory_percent, low.load_average) == (7.1, 41.2, None)
    assert low.bottleneck_indicators == []

    hot = _analyze_device_performance(HOT)
    assert hot is not None
    assert hot.bottleneck_indicators == [
        'High CPU usage: 85%',
        'High memory usage: 90%',
        'High load average: 2.5',
    ]

    critical = _analyze_device_performance(CRITICAL)
    assert critical is not None
    assert critical.bottleneck_indicators == [
        'Critical CPU usage: 96.5%',
        'Critical memory usage: 97%',
        'Very high load average: 4.5',
    ]
    assert critical.performance_score < hot.performance_score < low.performance_score


def test_identify_bottlenecks_parses_strings_and_the_threshold_still_fires():
    _, latency = _identify_bottlenecks([LOW, HOT, CRITICAL], [])
    assert latency == ['Critical - high CPU usage may cause latency']


def test_segment_congestion_parses_strings_and_the_threshold_still_fires():
    assert _assess_segment_congestion([LOW], []) == 'low'
    assert _assess_segment_congestion([LOW, LOW, LOW, LOW, LOW, HOT], []) == 'medium'
    assert _assess_segment_congestion([LOW, HOT, CRITICAL], []) == 'critical'


class _SyncApi:
    site = 'default'

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.devices = devices

    def get_devices(self, site: str) -> dict[str, Any]:
        return {'data': self.devices}


def test_toolkit_adapter_flags_a_string_cpu():
    report = ToolkitAdapter(_SyncApi([LOW, HOT])).network_health_check_sync()
    assert report['devices_with_issues'] == 1
    assert report['issues'] == [
        {'device': 'Hot', 'issue': 'High CPU usage: 85%', 'severity': 'medium'}
    ]


# ---------------------------------------------------------------------------
# end to end: the CLI command and execute_tool over a fake async client
# ---------------------------------------------------------------------------


def _fake_client_class(calls: list[str]):
    """An async stand-in for UniFiClient answering ``get`` from the shared fixtures."""
    routes = {
        'stat/device': fake_devices,
        'stat/sta': fake_sta,
        'stat/health': lambda: [{'subsystem': 'lan', 'status': 'ok'}],
    }

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def build_path(self, endpoint: str) -> str:
            return f'/proxy/network/api/s/default/{endpoint}'

        async def get(self, path: str, **params: Any) -> Any:
            endpoint = path.split('/api/s/default/', 1)[1]
            calls.append(endpoint)
            if endpoint in routes:
                return routes[endpoint]()
            match = re.fullmatch(r'stat/device/(\w+)', endpoint)
            if match:
                return [d for d in fake_devices() if d.get('_id') == match.group(1)]
            raise AssertionError(f'unexpected read {endpoint}')

    return _FakeClient


@pytest.fixture
def fake_unifi(monkeypatch, tmp_path) -> list[str]:
    """Patch UniFiClient in the three tools and pass the CLI env load and MCP credential gate."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda *_: None)
    monkeypatch.setenv('UNIFI_URL', 'https://192.0.2.1')
    monkeypatch.setenv('UNIFI_CONSOLE_API_TOKEN', 'FAKE-GATE-TOKEN')  # pragma: allowlist secret
    monkeypatch.setattr(server, 'get_registry', lambda: ToolRegistry(MANIFESTS))
    calls: list[str] = []
    for module in MODULES.values():
        monkeypatch.setattr(
            importlib.import_module(module), 'UniFiClient', _fake_client_class(calls)
        )
    return calls


def test_diagnose_health_json_runs_the_real_analysis(fake_unifi):
    result = CliRunner().invoke(app, ['diagnose', 'health', '--json'])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report['total_devices'] == 3
    assert report['clients_connected'] == 2
    assert report['high_cpu_devices'] == []
    assert_no_secrets(result.stdout)
    assert fake_unifi == ['stat/device', 'stat/sta', 'stat/health']


@pytest.mark.parametrize('name', sorted(MODULES))
async def test_execute_tool_succeeds_on_string_system_stats(fake_unifi, name):
    raw = await server.execute_tool(name, {})
    out = raw.structuredContent
    assert raw.isError is not True, out
    assert out['ok'] is True, out
    assert_no_secrets(raw.model_dump(mode='json'))
    assert fake_unifi and set(fake_unifi) <= {
        'stat/device',
        'stat/sta',
        'stat/health',
        *(f'stat/device/{d["_id"]}' for d in fake_devices()),
    }


async def test_execute_tool_performance_analysis_reports_the_parsed_cpu(fake_unifi):
    out = (await server.execute_tool('performance_analysis', {})).structuredContent
    switch = next(
        p
        for bucket in ('high_performers', 'average_performers', 'poor_performers')
        for p in out['result'][bucket]
        if p['name'] == 'USW Flex XG'
    )
    assert (switch['cpu_percent'], switch['memory_percent']) == (7.1, 41.2)
