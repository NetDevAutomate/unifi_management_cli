"""CLI commands for the MCP tools that had none (issue 078, the MCP-only side).

Each command runs its tool through ``_run_analysis`` (guarded, read-only), prints JSON equal
to the tool's ``model_dump`` with ``--json`` and a Rich rendering otherwise, and forwards its
options to the handler by keyword. The handlers are faked in their modules; no controller.
"""

from __future__ import annotations

import importlib
import json
import pytest
from datetime import datetime
from typer.testing import CliRunner
from types import SimpleNamespace
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.core.models import ConflictingClient, IPConflict, IPConflictReport
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics.security_audit import SecurityAuditReport, SecurityDevice
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')
runner = CliRunner()
REGISTRY = ToolRegistry(default_manifests_dir(), strict=True)

IP_CONFLICTS = IPConflictReport(
    timestamp='2026-10-13T10:00:00',
    total_clients_scanned=42,
    conflicts_found=1,
    conflicts=[
        IPConflict(
            ip_address='192.0.2.50',
            clients=[
                ConflictingClient(
                    mac_address='02:00:00:00:00:50',
                    hostname='printer',
                    name='Printer',
                    is_wired=True,
                    is_guest=False,
                    connected_device='Rack Switch',
                    connected_port='7',
                    last_seen=datetime(2026, 10, 13, 9, 59),
                    vlan=10,
                ),
                ConflictingClient(
                    mac_address='02:00:00:00:00:51',
                    hostname='laptop',
                    name=None,
                    is_wired=False,
                    is_guest=False,
                    connected_device='Hall AP',
                    connected_port=None,
                    last_seen=None,
                    vlan=20,
                ),
            ],
            conflict_count=2,
            severity='CRITICAL',
            vlan_mismatch=True,
        )
    ],
    healthy=False,
    recommendations=['Reserve 192.0.2.50 for one client'],
)
SECURITY = SecurityAuditReport(
    timestamp='2026-10-13T10:00:00',
    total_devices=42,
    authorized_devices=40,
    unauthorized_devices=1,
    anomalous_devices=1,
    unknown_devices=0,
    critical_risks=[
        SecurityDevice(
            mac='02:00:00:00:00:99',
            name='mystery-box',
            ip='192.0.2.99',
            type='client',
            vendor=None,
            first_seen=None,
            last_seen=None,
            is_authorized=False,
            is_anomalous=True,
            security_flags=['unknown vendor', 'new device'],
            risk_level='critical',
        )
    ],
    high_risks=[],
    medium_risks=[],
    mac_anomalies=['02:00:00:00:00:99 seen on two switches'],
    new_devices=[],
    rogue_aps=[],
    guest_violations=[],
    vlan_analysis=[],
    immediate_actions=['Isolate mystery-box'],
    security_recommendations=['Enable 802.1X on access ports'],
)

# command -> (handler module, handler name, fixture, text the rendering must show, cli args
# beyond the command that exercise the options, and the kwargs the handler must receive)
COMMANDS: dict[str, tuple[str, str, Any, str, list[str], dict[str, Any]]] = {
    'analyze ip-conflicts': (
        'unifi_mapper.analysis.ip_conflicts',
        'detect_ip_conflicts',
        IP_CONFLICTS,
        'IP Conflicts',
        ['--include-offline'],
        {'include_offline': True},
    ),
    'diagnose security': (
        'unifi_mapper.diagnostics.security_audit',
        'security_audit',
        SECURITY,
        'Security Audit',
        [],
        {},
    ),
}


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SimpleNamespace:
    """Every handler returns its fixture and records the keyword arguments it was given."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    calls: list[tuple[str, dict[str, Any]]] = []
    for module_name, handler, report, *_ in COMMANDS.values():

        async def _fake(_name=handler, _report=report, **kwargs: Any) -> Any:
            calls.append((_name, kwargs))
            return _report

        monkeypatch.setattr(importlib.import_module(module_name), handler, _fake)

    def run(*args: str):
        return runner.invoke(app, list(args))

    return SimpleNamespace(run=run, calls=calls)


def _dump(report: Any) -> Any:
    return report.model_dump(mode='json') if hasattr(report, 'model_dump') else report


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_json_equals_the_tool_result(cli: SimpleNamespace, command: str) -> None:
    _, handler, report, _, _, _ = COMMANDS[command]
    result = cli.run(*command.split(), '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == _dump(report)
    assert [name for name, _ in cli.calls] == [handler]


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_rendering_names_the_report(cli: SimpleNamespace, command: str) -> None:
    _, _, _, shown, _, _ = COMMANDS[command]
    result = cli.run(*command.split())
    assert result.exit_code == 0, result.output
    assert shown in result.stdout


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_options_reach_the_handler_by_keyword(cli: SimpleNamespace, command: str) -> None:
    _, handler, _, _, args, expected = COMMANDS[command]
    result = cli.run(*command.split(), *args, '--json')
    assert result.exit_code == 0, result.output
    [(name, kwargs)] = cli.calls
    assert name == handler
    for key, value in expected.items():
        assert kwargs.get(key) == value, (key, kwargs)


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_the_manifest_names_the_command(command: str) -> None:
    _, handler, *_ = COMMANDS[command]
    named = [
        name
        for tools in REGISTRY.get_categories().values()
        for name in tools
        if (meta := REGISTRY.get_metadata(name)) is not None and meta.cli == command
    ]
    assert named, f'no manifest entry carries cli: {command}'
    assert handler in {REGISTRY.get_metadata(n).handler for n in named}  # type: ignore[union-attr]


def test_ip_conflicts_rendering_shows_each_client(cli: SimpleNamespace) -> None:
    result = cli.run('analyze', 'ip-conflicts')
    assert result.exit_code == 0, result.output
    text = ' '.join(result.stdout.split())
    assert '192.0.2.50' in text and 'CRITICAL' in text
    assert 'Printer' in text and 'Rack Switch' in text and 'Hall AP' in text
    assert 'VLAN mismatch' in text or 'mismatch' in text
    assert 'Reserve 192.0.2.50' in text


def test_security_rendering_shows_risks_and_actions(cli: SimpleNamespace) -> None:
    result = cli.run('diagnose', 'security')
    assert result.exit_code == 0, result.output
    text = ' '.join(result.stdout.split())
    assert 'mystery-box' in text and 'critical' in text.lower()
    assert 'Isolate mystery-box' in text
    assert 'Enable 802.1X' in text
    assert 'two switches' in text


def test_a_tool_error_prints_red_and_exits_1(cli: SimpleNamespace, monkeypatch) -> None:
    from unifi_mapper.analysis import ip_conflicts

    async def _down(**_kwargs: Any) -> Any:
        raise ToolError(
            message='Cannot connect to UniFi controller',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
        )

    monkeypatch.setattr(ip_conflicts, 'detect_ip_conflicts', _down)
    result = cli.run('analyze', 'ip-conflicts', '--json')
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'Cannot connect to UniFi controller' in result.stderr
