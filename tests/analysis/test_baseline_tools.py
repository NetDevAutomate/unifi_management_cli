"""The MCP side of the snapshot-and-compare commands (issue 078): `detect_config_drift`,
`compare_link_errors`, `analyze_client_roaming`, `scan_neighbour_aps` and
`compare_neighbour_baseline`.

Each wrapper checks its file argument the safe way (suffix before any filesystem call, then
absolute, then a regular file under the size cap) and delegates to the CLI's function, which
raises NO_DATA with the CLI hint when the file does not exist yet.
"""

import json
import pytest
from pathlib import Path
from typing import Any
from unifi_mapper.analysis import (
    config_drift,
    link_error_tracking,
    neighbour_trend,
    roaming_analysis,
)
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.local_paths import MAX_SNAPSHOT_BYTES, check_snapshot_path


# --- check_snapshot_path -----------------------------------------------------------------------


def test_the_suffix_is_checked_before_anything_touches_the_filesystem(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as excinfo:
        check_snapshot_path(str(tmp_path / 'baseline.txt'), what='baseline')
    assert excinfo.value.error_code == ErrorCodes.CONFIG_INVALID
    assert 'baseline must be a .json file' in excinfo.value.message


def test_a_relative_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match='must be absolute'):
        check_snapshot_path('reports/config-baseline.json', what='baseline')


def test_a_missing_file_passes_through_resolved_for_the_caller_to_report(tmp_path: Path) -> None:
    missing = tmp_path / 'later.json'
    assert check_snapshot_path(str(missing), what='baseline') == missing.resolve()


def test_a_symlink_to_a_non_json_target_is_refused(tmp_path: Path) -> None:
    target = tmp_path / 'secret.txt'
    target.write_text('x')
    link = tmp_path / 'looks.json'
    link.symlink_to(target)
    with pytest.raises(ToolError, match='must be a .json file'):
        check_snapshot_path(str(link), what='baseline')


def test_a_directory_and_an_oversized_file_are_refused(tmp_path: Path) -> None:
    folder = tmp_path / 'dir.json'
    folder.mkdir()
    with pytest.raises(ToolError, match='not a regular file'):
        check_snapshot_path(str(folder), what='baseline')
    big = tmp_path / 'big.json'
    with big.open('wb') as f:
        f.truncate(MAX_SNAPSHOT_BYTES + 1)
    with pytest.raises(ToolError, match='larger than'):
        check_snapshot_path(str(big), what='baseline')


def test_a_good_file_is_returned_resolved(tmp_path: Path) -> None:
    good = tmp_path / 'ok.json'
    good.write_text('{}')
    assert check_snapshot_path(str(good), what='baseline') == good.resolve()


# --- the wrappers ------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, devices: list[dict[str, Any]], rogue: list[dict[str, Any]]) -> None:
        self._devices, self._rogue = devices, rogue

    async def __aenter__(self) -> 'FakeClient':
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_devices(self) -> list[dict[str, Any]]:
        return self._devices

    async def get_rogue_aps(self) -> list[dict[str, Any]]:
        return self._rogue

    async def get_clients(self) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(*_a: object, **_k: object) -> FakeClient:
        return FakeClient(devices=[], rogue=[])

    for module in (config_drift, link_error_tracking, neighbour_trend, roaming_analysis):
        monkeypatch.setattr(module, 'UniFiClient', factory)


async def test_detect_config_drift_mcp_requires_an_absolute_json_path(clients: None) -> None:
    with pytest.raises(ToolError, match='must be absolute'):
        await config_drift.detect_drift_mcp('reports/config-baseline.json')


async def test_detect_config_drift_mcp_reports_no_data_with_the_cli_hint(
    clients: None, tmp_path: Path
) -> None:
    with pytest.raises(ToolError) as excinfo:
        await config_drift.detect_drift_mcp(str(tmp_path / 'none.json'))
    assert excinfo.value.error_code == ErrorCodes.NO_DATA
    assert 'config-drift --snapshot' in (excinfo.value.suggestion or '')


async def test_detect_config_drift_mcp_compares_against_the_baseline(
    clients: None, tmp_path: Path
) -> None:
    baseline = tmp_path / 'config-baseline.json'
    baseline.write_text(json.dumps({'timestamp': '2026-10-01T00:00:00', 'devices': []}))
    report = await config_drift.detect_drift_mcp(str(baseline))
    assert report['baseline_timestamp'] == '2026-10-01T00:00:00'
    assert report['devices_checked'] == 0


async def test_analyze_roaming_mcp_checks_the_path_then_delegates(
    clients: None, tmp_path: Path
) -> None:
    with pytest.raises(ToolError, match='must be absolute'):
        await roaming_analysis.analyze_roaming_mcp('reports/x.json')
    with pytest.raises(ToolError) as excinfo:
        await roaming_analysis.analyze_roaming_mcp(str(tmp_path / 'none.json'))
    assert excinfo.value.error_code == ErrorCodes.NO_DATA


async def test_compare_neighbour_baseline_mcp_checks_the_path_then_delegates(
    clients: None, tmp_path: Path
) -> None:
    with pytest.raises(ToolError, match='must be absolute'):
        await neighbour_trend.detect_neighbour_trend_mcp('x.json')
    with pytest.raises(ToolError) as excinfo:
        await neighbour_trend.detect_neighbour_trend_mcp(str(tmp_path / 'none.json'))
    assert excinfo.value.error_code == ErrorCodes.NO_DATA
    baseline = tmp_path / 'neighbour-baseline.json'
    baseline.write_text(json.dumps({'timestamp': 't0', 'entries': []}))
    report = await neighbour_trend.detect_neighbour_trend_mcp(
        str(baseline), signal_delta_threshold=5
    )
    assert report['new_count'] == 0 and report['disappeared_count'] == 0


async def test_compare_link_errors_mcp_defaults_to_the_xdg_baseline(
    clients: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('XDG_STATE_HOME', str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no legacy ./reports baseline either
    with pytest.raises(ToolError) as excinfo:
        await link_error_tracking.compare_link_errors_mcp()
    assert excinfo.value.error_code == ErrorCodes.NO_DATA
    with pytest.raises(ToolError, match='must be absolute'):
        await link_error_tracking.compare_link_errors_mcp('reports/link-error-baseline.json')


async def test_compare_link_errors_mcp_bounds_the_threshold(clients: None, tmp_path: Path) -> None:
    with pytest.raises(ToolError, match='threshold'):
        await link_error_tracking.compare_link_errors_mcp(
            str(tmp_path / 'b.json'), threshold_errors_per_min=0
        )


def test_the_manifest_entries_and_schemas() -> None:
    from unifi_mapper.analysis.neighbour_scan import scan_neighbours
    from unifi_mapper.mcp.catalog import build_tool
    from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir

    registry = ToolRegistry(default_manifests_dir(), strict=True)
    expected = {
        'detect_config_drift': ('analyze config-drift', config_drift.detect_drift_mcp),
        'compare_link_errors': (
            'analyze link-errors',
            link_error_tracking.compare_link_errors_mcp,
        ),
        'analyze_client_roaming': ('analyze roaming', roaming_analysis.analyze_roaming_mcp),
        'scan_neighbour_aps': ('analyze neighbours', scan_neighbours),
        'compare_neighbour_baseline': (
            'analyze neighbours',
            neighbour_trend.detect_neighbour_trend_mcp,
        ),
    }
    for name, (cli, handler) in expected.items():
        meta = registry.get_metadata(name)
        assert meta is not None, name
        assert meta.cli == cli, name
        assert meta.credentials == 'controller' and meta.mutates is False
        tool = build_tool(handler, meta)
        assert tool.output_schema is not None, name
        assert set(tool.parameters.get('properties', {})) == set(meta.parameters), name


def test_the_wrappers_never_write(tmp_path: Path) -> None:
    """The MCP wrappers are compare-only: the snapshot writers stay on the CLI."""
    import inspect

    writers = (
        'write_text',
        'snapshot_config(',
        'snapshot_client_associations(',
        'snapshot_neighbours(',
        'snapshot_link_errors(',
        'append_history(',
    )
    for fn in (
        config_drift.detect_drift_mcp,
        link_error_tracking.compare_link_errors_mcp,
        roaming_analysis.analyze_roaming_mcp,
        neighbour_trend.detect_neighbour_trend_mcp,
    ):
        source = inspect.getsource(fn)
        assert not any(w in source for w in writers), fn.__name__
