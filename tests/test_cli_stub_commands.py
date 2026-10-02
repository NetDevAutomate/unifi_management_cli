"""CLI tests for `find device`, `analyze link-quality` and `diagnose health` (issue 001)."""

import importlib
import json
import pytest
from typer.testing import CliRunner
from types import SimpleNamespace
from unifi_mapper import typer_cli
from unifi_mapper.core.models import Device, LinkQualityReport, PortLinkQuality
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics.network_health import NetworkHealthReport
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

# Imported as modules: the packages re-export same-named functions.
find_device = importlib.import_module('unifi_mapper.discovery.find_device')
link_quality = importlib.import_module('unifi_mapper.analysis.link_quality')
network_health = importlib.import_module('unifi_mapper.diagnostics.network_health')

runner = CliRunner()

DEVICE = Device(
    mac='aa:bb:cc:00:00:51',
    name='UGREEN DXP4800',
    model='DXP4800 GT',
    ip='192.0.2.51',
    type='client',
    connected_to='aa:bb:cc:00:00:02',
    port_idx=5,
)
LINK_REPORT = LinkQualityReport(
    timestamp='2026-10-02T12:00:00',
    devices_analyzed=1,
    ports_analyzed=8,
    healthy_ports=7,
    degraded_ports=1,
    critical_ports=0,
    port_metrics=[
        PortLinkQuality(
            device_id='sw-edge',
            device_name='Edge',
            port_idx=3,
            port_name='Port 3',
            link_speed='1000 Mbps',
            full_duplex=True,
            stp_state='forwarding',
            poe_power=None,
            rx_errors=120,
            health_score=75,
            issues=['CRC errors'],
        )
    ],
    overall_health='DEGRADED',
    top_issues=['CRC errors (1 ports)'],
)
HEALTH_REPORT = NetworkHealthReport(
    timestamp='2026-10-02T12:00:00',
    overall_score=85,
    status='warning',
    total_devices=3,
    devices_online=3,
    devices_offline=0,
    devices_adopted=2,
    high_cpu_devices=['Gateway (91%)'],
    high_memory_devices=[],
    high_load_devices=[],
    clients_connected=40,
    uplink_issues=[],
    firmware_outdated=['Old AP (v4.3.1)'],
    critical_issues=[],
    warnings=['Device Spare is not adopted'],
    recommendations=['Monitor high CPU devices and consider load balancing'],
)


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Run the CLI with each implementation coroutine replaced by a recording fake."""
    monkeypatch.chdir(tmp_path)
    loaded: list[str] = []
    monkeypatch.setattr(typer_cli, 'load_env_from_config', loaded.append)
    calls: list[tuple[str, dict]] = []

    async def fake_find_device(identifier):
        calls.append(('find_device', {'identifier': identifier}))
        if identifier == 'missing':
            raise ToolError(
                message=f'Device with identifier "{identifier}" not found on network',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
            )
        return DEVICE

    async def fake_link_quality(device_id=None, include_healthy=False):
        calls.append(
            ('analyze_link_quality', {'device_id': device_id, 'include_healthy': include_healthy})
        )
        if device_id == 'missing':
            raise ToolError(
                message=f'Device with ID {device_id} not found',
                error_code=ErrorCodes.DEVICE_NOT_FOUND,
            )
        return LINK_REPORT

    async def fake_health_check():
        calls.append(('network_health_check', {}))
        return HEALTH_REPORT

    monkeypatch.setattr(find_device, 'find_device', fake_find_device)
    monkeypatch.setattr(link_quality, 'analyze_link_quality', fake_link_quality)
    monkeypatch.setattr(network_health, 'network_health_check', fake_health_check)

    def run(*args: str):
        return runner.invoke(app, list(args))

    return SimpleNamespace(run=run, calls=calls, loaded=loaded)


# ---------------------------------------------------------------------------
# find device
# ---------------------------------------------------------------------------


def test_find_device_json_equals_the_model_dump(cli):
    result = cli.run('find', 'device', 'UGREEN', '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == DEVICE.model_dump(mode='json')
    assert cli.calls == [('find_device', {'identifier': 'UGREEN'})]
    assert len(cli.loaded) == 1


def test_find_device_table_output(cli):
    result = cli.run('find', 'device', 'aa:bb:cc:00:00:51')
    assert result.exit_code == 0, result.output
    assert 'UGREEN DXP4800' in result.stdout and '192.0.2.51' in result.stdout
    assert 'Integration with enhanced device discovery' not in result.stdout


def test_find_device_not_found_exits_1_with_the_message(cli):
    result = cli.run('find', 'device', 'missing', '--json')
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'Device with identifier "missing" not found on network' in result.stderr


def test_find_device_query_is_still_required(cli):
    result = cli.run('find', 'device')
    assert result.exit_code == 2
    assert cli.calls == [] and cli.loaded == []


# ---------------------------------------------------------------------------
# analyze link-quality
# ---------------------------------------------------------------------------


def test_link_quality_json_equals_the_model_dump(cli):
    result = cli.run('analyze', 'link-quality', '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == LINK_REPORT.model_dump(mode='json')
    assert cli.calls == [('analyze_link_quality', {'device_id': None, 'include_healthy': False})]


def test_link_quality_passes_device_and_include_healthy(cli):
    result = cli.run('analyze', 'link-quality', '--device', 'sw-edge', '--include-healthy')
    assert result.exit_code == 0, result.output
    assert cli.calls == [
        ('analyze_link_quality', {'device_id': 'sw-edge', 'include_healthy': True})
    ]
    assert 'Port Link Quality' in result.stdout and 'DEGRADED' in result.stdout
    assert 'unifi-network-toolkit' not in result.stdout


def test_link_quality_unknown_device_exits_1_with_the_message(cli):
    result = cli.run('analyze', 'link-quality', '--device', 'missing')
    assert result.exit_code == 1
    assert 'Device with ID missing not found' in result.stderr


# ---------------------------------------------------------------------------
# diagnose health
# ---------------------------------------------------------------------------


def test_diagnose_health_json_equals_the_model_dump(cli):
    result = cli.run('diagnose', 'health', '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == HEALTH_REPORT.model_dump(mode='json')
    assert cli.calls == [('network_health_check', {})]


def test_diagnose_health_table_and_detailed_section(cli):
    plain = cli.run('diagnose', 'health')
    assert plain.exit_code == 0, plain.output
    assert '85/100' in plain.stdout and 'Device Spare is not adopted' in plain.stdout
    assert 'Gateway (91%)' not in plain.stdout
    assert 'unifi-network-toolkit' not in plain.stdout

    detailed = cli.run('diagnose', 'health', '--detailed')
    assert detailed.exit_code == 0, detailed.output
    assert 'Gateway (91%)' in detailed.stdout and 'Old AP (v4.3.1)' in detailed.stdout


def test_diagnose_health_controller_error_exits_1(monkeypatch, cli):
    async def _down():
        raise ToolError(
            message='Cannot connect to UniFi controller for health check',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
        )

    monkeypatch.setattr(network_health, 'network_health_check', _down)
    result = cli.run('diagnose', 'health', '--json')
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'Cannot connect to UniFi controller for health check' in result.stderr
