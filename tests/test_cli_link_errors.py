"""`analyze link-errors`: --snapshot sets the baselines, --record appends history, a plain run only reads."""

import asyncio
import json
import pytest
from pathlib import Path
from tests.fixtures_unifi import SWITCH_ID, fake_switch
from typer.testing import CliRunner
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.analysis import link_error_tracking
from unifi_mapper.analysis.counter_history import HISTORY_FILENAME
from unifi_mapper.analysis.port_counter_baseline import state_dir
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()


class Controller:
    """An in-memory ``UniFiClient`` stand-in that counts device reads."""

    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self.devices = devices
        self.reads = 0

    def client(self) -> Any:
        controller = self

        class _Client:
            async def __aenter__(self) -> '_Client':
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def get_devices(self) -> list[dict[str, Any]]:
                controller.reads += 1
                return controller.devices

        return _Client


@pytest.fixture
def controller(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Controller:
    """Offline controller; the CWD is an empty temp dir and no config file is read."""
    fake = Controller([fake_switch()])
    monkeypatch.setattr(link_error_tracking, 'UniFiClient', fake.client())
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda _path: None)
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return fake


def _state_files() -> set[str]:
    root = state_dir()
    return {p.name for p in root.iterdir()} if root.exists() else set()


def test_snapshot_writes_both_baselines_and_no_history(controller):
    result = runner.invoke(app, ['analyze', 'link-errors', '--snapshot'])

    assert result.exit_code == 0, result.output
    assert _state_files() == {'link-error-baseline.json', 'port-counters.json'}
    baseline = json.loads((state_dir() / 'link-error-baseline.json').read_text())
    assert baseline['devices'][0]['device_id'] == SWITCH_ID
    store = json.loads((state_dir() / 'port-counters.json').read_text())
    assert store[f'{SWITCH_ID}:5']['crc_errors'] == 3
    assert not Path('reports').exists()  # nothing in the working directory any more
    assert controller.reads == 1


def test_record_writes_only_the_history(controller):
    result = runner.invoke(app, ['analyze', 'link-errors', '--record', '--retention-days', '7'])

    assert result.exit_code == 0, result.output
    assert _state_files() == {HISTORY_FILENAME, f'{HISTORY_FILENAME}.lock'}
    lines = (state_dir() / HISTORY_FILENAME).read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])['device_id'] == SWITCH_ID
    assert 'retention 7 days' in result.output


def test_snapshot_and_record_share_one_device_read(controller):
    result = runner.invoke(app, ['analyze', 'link-errors', '--snapshot', '--record'])

    assert result.exit_code == 0, result.output
    assert {'link-error-baseline.json', 'port-counters.json', HISTORY_FILENAME} <= _state_files()
    assert controller.reads == 1


def test_record_to_an_explicit_history_path(controller, tmp_path):
    target = tmp_path / 'elsewhere' / 'h.jsonl'
    result = runner.invoke(app, ['analyze', 'link-errors', '--record', '--history', str(target)])

    assert result.exit_code == 0, result.output
    assert target.exists() and _state_files() == set()


def test_plain_run_without_a_baseline_creates_no_file(controller):
    result = runner.invoke(app, ['analyze', 'link-errors'])

    assert result.exit_code == 1
    assert 'No baseline found' in result.output
    assert not state_dir().exists()
    assert list(Path.cwd().iterdir()) == []


def test_plain_run_compares_and_writes_nothing(controller):
    assert runner.invoke(app, ['analyze', 'link-errors', '--snapshot', '--record']).exit_code == 0
    before = {p.name: p.read_bytes() for p in state_dir().iterdir()}
    controller.devices = [fake_switch(port_table=[{'port_idx': 5, 'rx_errors': 500}])]

    result = runner.invoke(app, ['analyze', 'link-errors'])

    assert result.exit_code == 0, result.output
    assert {p.name: p.read_bytes() for p in state_dir().iterdir()} == before
    assert 'link-error-baseline.json' in result.output


def test_legacy_cwd_baseline_is_read_and_reported(controller):
    legacy = Path('reports') / 'link-error-baseline.json'
    legacy.parent.mkdir()
    asyncio.run(link_error_tracking.snapshot_link_errors(legacy))
    for name in ('link-error-baseline.json', 'port-counters.json'):
        (state_dir() / name).unlink(missing_ok=True)  # only the legacy file remains

    result = runner.invoke(app, ['analyze', 'link-errors'])
    report = asyncio.run(link_error_tracking.compare_link_errors())

    assert result.exit_code == 0, result.output
    assert 'legacy baseline' in result.output
    assert report['legacy_baseline'] is True
    assert report['baseline_path'] == str(Path.cwd() / 'reports' / 'link-error-baseline.json')


def test_the_xdg_baseline_wins_over_a_legacy_one(controller):
    legacy = Path('reports') / 'link-error-baseline.json'
    legacy.parent.mkdir()
    legacy.write_text('{"timestamp": "2020-01-01T00:00:00", "devices": []}')
    asyncio.run(link_error_tracking.snapshot_link_errors())

    report = asyncio.run(link_error_tracking.compare_link_errors())

    assert report['legacy_baseline'] is False
    assert report['baseline_path'] == str(state_dir() / 'link-error-baseline.json')


@pytest.mark.parametrize('days', ['0', '366'])
def test_retention_days_out_of_range_exits_2(controller, days):
    result = runner.invoke(app, ['analyze', 'link-errors', '--record', '--retention-days', days])

    assert result.exit_code == 2
    assert controller.reads == 0 and not state_dir().exists()
