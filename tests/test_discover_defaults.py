"""`discover` and its root shortcuts preview by default; only --apply writes (issue 007)."""

import pytest
import re
from pathlib import Path
from typer.testing import CliRunner
from types import SimpleNamespace
from typing import Any
from unifi_mapper import config as config_module
from unifi_mapper import port_mapper, run_methods, smart_port_mapper, typer_cli
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
CRON_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'unifi-cron.sh'


class Recorder:
    """What the fakes saw: constructed mappers, dry_run flags and write calls."""

    def __init__(self) -> None:
        self.mappers: list[dict[str, Any]] = []
        self.run_dry_run: list[bool] = []
        self.smart_dry_run: list[bool] = []
        self.writes: list[object] = []


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Recorder:
    """Replace every collaborator `discover` touches with an offline fake."""
    recorder = Recorder()
    monkeypatch.chdir(tmp_path)  # discover creates reports/ and diagrams/ in the CWD

    fake_config = SimpleNamespace(
        base_url='https://192.0.2.1',
        site='default',
        api_token='fake-token',  # pragma: allowlist secret
        username=None,
        password=None,
        verify_ssl=False,
        timeout=10,
    )
    monkeypatch.setattr(
        config_module.UnifiConfig, 'from_env', classmethod(lambda cls, *a, **k: fake_config)
    )
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda _path: None)

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            recorder.mappers.append(kwargs)
            self.api_client = object()

        def batch_update_port_names(self, *args: object, **_kwargs: object) -> bool:
            recorder.writes.append(args)
            return True

    def fake_run_port_mapper(*, port_mapper: FakeMapper, dry_run: bool, **_: object):
        recorder.run_dry_run.append(dry_run)
        if not dry_run:  # mirrors run_methods: only a non-dry run reaches the writer
            port_mapper.batch_update_port_names({})
        return [], []

    class FakeSmartMapper:
        def __init__(self, _api_client: object) -> None:
            pass

        def smart_update_ports(self, *_args: object, dry_run: bool, **_kwargs: object):
            recorder.smart_dry_run.append(dry_run)
            if not dry_run:
                recorder.writes.append('smart')
            return {}

        def generate_smart_mapping_report(self, _results: object) -> str:
            return 'smart report'

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', fake_run_port_mapper)
    monkeypatch.setattr(run_methods, 'get_devices_and_lldp_data', lambda *_: ([], {}))
    monkeypatch.setattr(smart_port_mapper, 'SmartPortMapper', FakeSmartMapper)
    return recorder


def test_discover_previews_by_default(rec: Recorder) -> None:
    result = runner.invoke(app, ['discover'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [True]
    assert rec.writes == []
    assert 'DRY RUN' in result.output
    assert '--apply' in result.output


def test_discover_dry_run_is_still_accepted(rec: Recorder) -> None:
    result = runner.invoke(app, ['discover', '--dry-run'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_discover_apply_writes(rec: Recorder) -> None:
    result = runner.invoke(app, ['discover', '--apply'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [False]
    assert len(rec.writes) == 1
    assert 'DRY RUN' not in result.output


def test_root_connected_devices_previews(rec: Recorder) -> None:
    result = runner.invoke(app, ['--connected-devices'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_root_verify_updates_previews_with_the_smart_mapper(rec: Recorder) -> None:
    result = runner.invoke(app, ['--verify-updates', '--connected-devices'])

    assert result.exit_code == 0, result.output
    assert rec.smart_dry_run == [True]
    assert rec.run_dry_run == [True]  # the traditional report is always a dry run here
    assert rec.writes == []


def test_root_apply_connected_devices_writes(rec: Recorder) -> None:
    result = runner.invoke(app, ['--apply', '--connected-devices'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [False]
    assert len(rec.writes) == 1


def test_root_apply_verify_updates_writes_once_through_the_smart_mapper(rec: Recorder) -> None:
    result = runner.invoke(app, ['--verify-updates', '--connected-devices', '--apply'])

    assert result.exit_code == 0, result.output
    assert rec.smart_dry_run == [False]
    assert rec.run_dry_run == [True]  # no duplicate update from the traditional pass
    assert rec.writes == ['smart']


def test_root_dry_run_alone_still_runs_discover(rec: Recorder) -> None:
    result = runner.invoke(app, ['--dry-run'])

    assert result.exit_code == 0, result.output
    assert len(rec.mappers) == 1
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_root_apply_with_dry_run_is_rejected(rec: Recorder) -> None:
    result = runner.invoke(app, ['--apply', '--dry-run'])

    assert result.exit_code == 2
    assert 'choose --apply or --dry-run' in result.output
    assert rec.mappers == []
    assert rec.writes == []


@pytest.mark.parametrize(
    'args',
    [
        ['--apply', 'discover'],
        ['--apply', 'discover', '--connected-devices'],
        ['--apply', '--verify-updates', 'discover'],
        ['--apply', 'ports', 'list', 'USW Flex XG'],
    ],
)
def test_root_apply_before_a_subcommand_is_rejected(rec: Recorder, args: list[str]) -> None:
    """Code-review F11: Typer never hands a root --apply to the subcommand, so refuse it."""
    result = runner.invoke(app, args)

    assert result.exit_code == 2, result.output
    # Code-review F26: generic, so it also fits `--apply ports refresh X` and `--apply stp …`.
    assert '--apply must follow the subcommand and its arguments' in result.output
    assert 'discover --apply' in result.output
    # No controller client was built and nothing was written.
    assert rec.mappers == []
    assert rec.run_dry_run == []
    assert rec.smart_dry_run == []
    assert rec.writes == []


def test_root_dry_run_before_discover_still_previews(rec: Recorder) -> None:
    result = runner.invoke(app, ['--dry-run', 'discover'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [True]
    assert rec.writes == []
    assert 'DRY RUN' in result.output


def test_root_without_discover_flags_shows_help(rec: Recorder) -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert rec.mappers == []


def test_help_says_preview_by_default() -> None:
    result = runner.invoke(app, ['discover', '--help'])

    assert result.exit_code == 0
    text = re.sub(r'\s+', ' ', result.output.replace('│', ' '))  # unwrap Rich panels
    assert '--apply' in text
    assert 'preview only' in text


@pytest.mark.parametrize('width', [70, 80, 100, 120])
def test_root_apply_help_points_at_discover_apply_without_truncation(width: int) -> None:
    """Rich cuts a help line short (with an ellipsis) when the emoji's width trips its wrap."""
    result = runner.invoke(app, ['--help'], env={'COLUMNS': str(width)}, terminal_width=width)

    assert result.exit_code == 0
    lines = result.output.splitlines()
    start = next(i for i, line in enumerate(lines) if '--apply' in line)
    block = lines[start : start + 3]
    assert not any('…' in line for line in block), block
    assert 'discover --apply' in re.sub(r'\s+', ' ', ' '.join(block).replace('│', ' '))


def test_cron_port_naming_task_passes_apply() -> None:
    script = CRON_SCRIPT.read_text(encoding='utf-8')
    task = re.search(r'"port-naming\|\d+\|([^"]*)"', script)

    assert task is not None
    assert '--apply' in task.group(1).split()
    run_all = script.split('run_all() {')[1].split('\n}')[0]
    naming = [line for line in run_all.splitlines() if '--connected-devices' in line]
    assert naming and all('--apply' in line.split() for line in naming)
