"""State files default to ``$XDG_STATE_HOME/unifi_mapper/`` (issue 010).

The radio snapshots, the config-drift baseline, the roaming history and the neighbour
baseline were written to ``reports/`` under the working directory. Under uvx the MCP
server's working directory is whatever the client chose, and a cron job and an interactive
run compared against different baselines. Every default now goes through ``state_dir()``;
an explicit path is unchanged; the MCP snapshot tool reports the absolute path it wrote and
the exact restore command.
"""

from __future__ import annotations

import asyncio
import json
import pytest
import shlex
from pathlib import Path
from typing import Any
from unifi_mapper.analysis import (
    config_drift,
    neighbour_trend,
    radio_config,
    rf_simulator,
    rf_strategy,
    roaming_analysis,
)
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.core.utils.errors import ToolError


AP = {
    '_id': 'ap1',
    'type': 'uap',
    'name': 'AP One',
    'mac': 'aa:bb:cc:dd:ee:01',
    'radio_table': [{'radio': 'na', 'channel': 36, 'ht': '80'}],
}


class FakeClient:
    """A controller with one AP; every analysis module reads it through ``get_devices``."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_devices(self) -> list[dict[str, Any]]:
        return [AP]

    async def get_clients(self) -> list[dict[str, Any]]:
        return []

    async def get_rogue_aps(self) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def xdg_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An XDG state home of this test's own, and a working directory with nothing in it."""
    state_home = tmp_path / 'state'
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return state_home / 'unifi_mapper'


# --- the defaults resolve under XDG state, read at call time ------------------------------


@pytest.mark.parametrize(
    ('resolve', 'filename'),
    [
        (radio_config.default_radio_snapshot_path, 'radio-snapshot.json'),
        (config_drift.default_config_baseline_path, 'config-baseline.json'),
        (roaming_analysis.default_roaming_history_path, 'client-roaming-history.json'),
        (neighbour_trend.default_neighbour_baseline_path, 'neighbour-baseline.json'),
    ],
)
def test_each_default_is_under_the_xdg_state_directory(
    xdg_state: Path, resolve: Any, filename: str
) -> None:
    path = resolve()
    assert path == xdg_state / filename == state_dir() / filename
    assert path.is_absolute()


@pytest.mark.parametrize('relative', ['state', './state', '~/state'])
def test_a_relative_xdg_state_home_is_ignored(
    xdg_state: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relative: str
) -> None:
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('XDG_STATE_HOME', relative)
    expected = tmp_path / 'home' / '.local' / 'state' / 'unifi_mapper'
    for resolve in (
        radio_config.default_radio_snapshot_path,
        config_drift.default_config_baseline_path,
        roaming_analysis.default_roaming_history_path,
        neighbour_trend.default_neighbour_baseline_path,
    ):
        assert resolve().parent == expected


def test_no_default_names_the_working_directory_reports_folder() -> None:
    import inspect

    for module in (radio_config, config_drift, roaming_analysis, neighbour_trend, rf_strategy):
        source = inspect.getsource(module)
        assert "'reports/" not in source, module.__name__


# --- the writers use the default and honour an explicit path ------------------------------


def test_config_snapshot_writes_the_xdg_default_and_an_explicit_path(
    xdg_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_drift, 'UniFiClient', FakeClient)
    asyncio.run(config_drift.snapshot_config())
    assert (xdg_state / 'config-baseline.json').is_file()
    explicit = tmp_path / 'mine' / 'drift.json'
    asyncio.run(config_drift.snapshot_config(str(explicit)))
    assert explicit.is_file()
    assert not Path('reports').exists()


def test_roaming_snapshot_writes_the_xdg_default_and_an_explicit_path(
    xdg_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(roaming_analysis, 'UniFiClient', FakeClient)
    asyncio.run(roaming_analysis.snapshot_client_associations())
    assert (xdg_state / 'client-roaming-history.json').is_file()
    explicit = tmp_path / 'mine' / 'roaming.json'
    asyncio.run(roaming_analysis.snapshot_client_associations(str(explicit)))
    assert explicit.is_file()
    assert not Path('reports').exists()


def test_roaming_readers_default_to_the_xdg_history(xdg_state: Path) -> None:
    assert roaming_analysis.history_hours_available() == 0.0
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(roaming_analysis.analyze_roaming())
    assert str(xdg_state / 'client-roaming-history.json') in excinfo.value.message


def test_rf_strategy_plan_gates_on_the_xdg_history(xdg_state: Path) -> None:
    """With no history anywhere the plan is refused before any controller read."""
    with pytest.raises(ToolError, match='Insufficient roaming history'):
        asyncio.run(rf_strategy.generate_plan())


def test_rf_simulator_defaults_are_not_a_reports_string() -> None:
    import inspect

    for fn in (rf_simulator.simulate_disable, rf_simulator.simulate_width_change):
        default = inspect.signature(fn).parameters['history_path'].default
        assert default is None, fn.__name__


def test_neighbour_snapshot_writes_the_xdg_default_and_an_explicit_path(
    xdg_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(neighbour_trend, 'UniFiClient', FakeClient)
    asyncio.run(neighbour_trend.snapshot_neighbours())
    assert (xdg_state / 'neighbour-baseline.json').is_file()
    explicit = tmp_path / 'mine' / 'neighbours.json'
    asyncio.run(neighbour_trend.snapshot_neighbours(str(explicit)))
    assert explicit.is_file()
    assert not Path('reports').exists()


# --- the radio snapshot over MCP ----------------------------------------------------------


def test_mcp_snapshot_writes_under_xdg_state_and_returns_the_absolute_path(
    xdg_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(radio_config, 'UniFiClient', FakeClient)
    result = asyncio.run(radio_config.snapshot_radio_config_mcp())
    written = xdg_state / 'radio-snapshot.json'
    assert result['file'] == str(written)
    assert Path(result['file']).is_absolute() and written.is_file()
    assert result['aps_captured'] == 1
    assert json.loads(written.read_text())['aps'][0]['device_id'] == 'ap1'
    assert result['restore_command'] == f'unifi-mapper radio restore --snapshot {written}'
    assert not Path('reports').exists()


def test_the_restore_command_round_trips_a_path_with_a_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_home = tmp_path / 'my state'
    monkeypatch.setenv('XDG_STATE_HOME', str(state_home))
    monkeypatch.setattr(radio_config, 'UniFiClient', FakeClient)
    result = asyncio.run(radio_config.snapshot_radio_config_mcp())
    argv = shlex.split(result['restore_command'])
    assert argv[:4] == ['unifi-mapper', 'radio', 'restore', '--snapshot']
    assert argv[4] == result['file'] == str(state_home / 'unifi_mapper' / 'radio-snapshot.json')
    assert Path(argv[4]).is_file()


def test_restore_defaults_to_the_mcp_snapshot_and_previews(
    xdg_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(radio_config, 'UniFiClient', FakeClient)
    asyncio.run(radio_config.snapshot_radio_config_mcp())
    results = asyncio.run(radio_config.restore_radio_config(dry_run=True))
    assert results and all(str(r.get('status')).startswith('DRY_RUN') for r in results), results


def test_pre_optimisation_snapshot_goes_under_xdg_state(
    xdg_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(radio_config, 'UniFiClient', FakeClient)
    from unifi_mapper.core.utils import client as client_module

    monkeypatch.setattr(client_module, 'UniFiClient', FakeClient)  # the wrapper imports it late

    async def _no_apply(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(radio_config, 'apply_radio_config', _no_apply)
    asyncio.run(radio_config.apply_radio_optimization_mcp())
    assert (xdg_state / 'radio-pre-optimization.json').is_file()
    assert not Path('reports').exists()
