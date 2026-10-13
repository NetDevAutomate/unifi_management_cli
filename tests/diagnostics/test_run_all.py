"""`run_all_diagnostics`: `unifi-mapper diagnose all` and the MCP tool share one core.

The checks table names each registered tool it runs; a check that raises is a FAIL with a
redacted detail and the others still run; the CLI gets a progress callback per check.
"""

import importlib
import pytest
from typing import Any
from unifi_mapper.diagnostics import run_all
from unifi_mapper.diagnostics.run_all import (
    CHECKS,
    DiagnosticCheck,
    DiagnosticsSummary,
    extract_status,
    run_all_diagnostics,
    run_diagnostics,
)


class _Report:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


@pytest.mark.parametrize(
    ('report', 'status'),
    [
        (_Report(), 'PASS'),
        (_Report(validation_passed=False), 'FAIL'),
        (_Report(validation_passed=True, warnings=['w']), 'WARN'),
        (_Report(warnings=[]), 'PASS'),
        (_Report(overall_health='CRITICAL'), 'FAIL'),
        (_Report(overall_health='DEGRADED'), 'WARN'),
        (_Report(network_healthy=False), 'FAIL'),
        (_Report(findings_count=2), 'WARN'),
        (_Report(findings_count=0), 'PASS'),
        (_Report(recommendations=['r']), 'WARN'),
    ],
)
def test_extract_status_reads_the_common_fields(report: object, status: str) -> None:
    assert extract_status(report) == status


def test_the_checks_name_registered_tools_in_the_cli_order() -> None:
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    registry = ToolRegistry(default_manifests_dir(), strict=True)
    assert [c.name for c in CHECKS][:3] == ['Link Quality', 'Capacity Planning', 'Port Profiles']
    assert len(CHECKS) == 15
    for check in CHECKS:
        meta = registry.get_metadata(check.tool)
        assert meta is not None, check.tool
        assert (meta.module, meta.handler) == (check.module, check.handler), check.tool
        assert callable(getattr(importlib.import_module(check.module), check.handler))


async def test_run_diagnostics_runs_every_check_and_isolates_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_loader(check: run_all.Check):
        async def load() -> object:
            calls.append(check.tool)
            if check.tool == 'get_capacity_report':
                raise RuntimeError('token=SECRET-VALUE boom')
            if check.tool == 'check_poe_budget':
                return _Report(warnings=['over budget'])
            return _Report()

        return load

    monkeypatch.setattr(run_all, '_loader', fake_loader)
    seen: list[DiagnosticCheck] = []
    summary = await run_diagnostics(progress=seen.append)
    assert isinstance(summary, DiagnosticsSummary)
    assert calls == [c.tool for c in CHECKS]
    assert [c.name for c in seen] == [c.name for c in CHECKS]
    by_tool = {c.tool: c for c in summary.checks}
    assert by_tool['get_capacity_report'].status == 'FAIL'
    assert 'SECRET-VALUE' not in by_tool['get_capacity_report'].detail
    assert 'RuntimeError' in by_tool['get_capacity_report'].detail
    assert by_tool['check_poe_budget'].status == 'WARN'
    assert by_tool['analyze_link_quality'].status == 'PASS'
    assert (summary.passed, summary.warned, summary.failed) == (13, 1, 1)
    assert summary.healthy is False
    assert summary.timestamp


async def test_run_all_diagnostics_is_the_handler_without_a_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_loader(check: run_all.Check):
        async def load() -> object:
            return _Report()

        return load

    monkeypatch.setattr(run_all, '_loader', fake_loader)
    summary = await run_all_diagnostics()
    assert summary.failed == 0 and summary.healthy is True
    assert len(summary.checks) == len(CHECKS)


def test_the_manifest_entry_names_the_cli_command_and_builds_a_schema() -> None:
    from unifi_mapper.mcp.catalog import build_tool
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    registry = ToolRegistry(default_manifests_dir(), strict=True)
    meta = registry.get_metadata('run_all_diagnostics')
    assert meta is not None
    assert meta.cli == 'diagnose all'
    assert meta.idempotent is True and meta.mutates is False
    tool = build_tool(run_all_diagnostics, meta)
    assert tool.output_schema is not None
    assert tool.parameters.get('properties', {}) == {}
