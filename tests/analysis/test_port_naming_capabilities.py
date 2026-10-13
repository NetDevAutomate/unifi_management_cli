"""`get_port_naming_capabilities`: `unifi-mapper capabilities` and the MCP tool share one core.

The assessment is the detector's verdict per network device (gateways and switches, as the
port-naming workflow targets them), structured; the CLI prints the text rendering.
"""

import json
import pytest
from typer.testing import CliRunner
from typing import Any
from unifi_mapper.analysis import port_naming_capabilities as pnc
from unifi_mapper.analysis.port_naming_capabilities import (
    PortNamingCapabilityReport,
    assess_port_naming,
    get_port_naming_capabilities,
    render_text,
)


DEVICES: list[dict[str, Any]] = [
    {'name': 'Rack Switch', 'model': 'USW-Pro-24-PoE', 'type': 'usw', 'version': '7.1.26'},
    {'name': 'Garage Switch', 'model': 'US8P60', 'type': 'usw', 'version': '7.2.123'},
    {'name': 'Flex', 'model': 'USL8LP', 'type': 'usw', 'version': '6.6.65'},
    {'name': 'Gateway', 'model': 'UDM-Pro', 'type': 'udm', 'version': '4.0.6'},
    {'name': 'Hall AP', 'model': 'U6-Pro', 'type': 'uap', 'version': '6.6.65'},
]


def test_assess_port_naming_keeps_network_devices_and_classifies_each() -> None:
    report = assess_port_naming(DEVICES, timestamp='t')
    assert isinstance(report, PortNamingCapabilityReport)
    assert [d.name for d in report.devices] == ['Flex', 'Garage Switch', 'Gateway', 'Rack Switch']
    by_name = {d.name: d for d in report.devices}
    assert by_name['Rack Switch'].support == 'full'
    assert by_name['Garage Switch'].support == 'resets'
    assert by_name['Garage Switch'].known_issues
    assert by_name['Flex'].support == 'limited'
    assert (
        report.devices_analyzed,
        report.compatible,
        report.problematic,
        report.unsupported,
    ) == (
        4,
        2,
        2,
        0,
    )
    assert report.automated_naming_recommended is False
    assert any('Garage Switch' in r for r in report.recommendations)


def test_assess_port_naming_recommends_automation_when_every_device_is_compatible() -> None:
    report = assess_port_naming(DEVICES[:1] + DEVICES[3:], timestamp='t')
    assert report.problematic == 0 and report.unsupported == 0
    assert report.automated_naming_recommended is True
    assert report.recommendations == []


def test_render_text_mirrors_the_compatibility_report() -> None:
    text = render_text(assess_port_naming(DEVICES, timestamp='t'))
    assert 'UNIFI DEVICE PORT NAMING COMPATIBILITY REPORT' in text
    assert 'Garage Switch (US8P60) - Firmware 7.2.123' in text
    assert 'AUTO-RESETS' in text and 'FULL SUPPORT' in text and 'LIMITED' in text
    assert 'Total devices analyzed: 4' in text
    assert 'Automated port naming not recommended' in text


class FakeClient:
    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_devices(self) -> list[dict[str, Any]]:
        return DEVICES


async def test_the_handler_reads_devices_through_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pnc, 'UniFiClient', FakeClient)
    report = await get_port_naming_capabilities()
    assert report.devices_analyzed == 4 and report.problematic == 2


def test_the_manifest_entry_and_schema() -> None:
    from unifi_mapper.mcp.catalog import build_tool
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    meta = ToolRegistry(default_manifests_dir(), strict=True).get_metadata(
        'get_port_naming_capabilities'
    )
    assert meta is not None and meta.cli == 'capabilities'
    assert build_tool(get_port_naming_capabilities, meta).output_schema is not None


def test_the_cli_command_uses_the_core_and_honours_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.fake_controller import FakeController, route_cli
    from unifi_mapper import typer_cli

    monkeypatch.setattr(pnc, 'UniFiClient', FakeClient)
    route_cli(monkeypatch, FakeController({}))  # the handler's client is faked; no route is hit
    runner = CliRunner()
    result = runner.invoke(typer_cli.app, ['capabilities', '--json'])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['devices_analyzed'] == 4
    text = runner.invoke(typer_cli.app, ['capabilities'])
    assert text.exit_code == 0, text.output
    assert 'COMPATIBILITY SUMMARY' in text.stdout
