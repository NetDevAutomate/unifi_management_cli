"""`discover` and its root shortcuts preview by default; only --apply writes (issue 007).

Issue 027: a root shortcut given before a subcommand is passed on to `discover`, or exits 2
before any other subcommand, so no typed flag is ever dropped silently.
"""

import pytest
import re
from pathlib import Path
from typer.testing import CliRunner
from types import SimpleNamespace
from typing import Any, NoReturn
from unifi_mapper import cli as cli_module
from unifi_mapper import config as config_module
from unifi_mapper import port_mapper, run_methods, smart_port_mapper, typer_cli
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()
CRON_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'unifi-cron.sh'


class Recorder:
    """What the fakes saw: constructed mappers, dry_run flags, write calls and config reads."""

    def __init__(self) -> None:
        self.mappers: list[dict[str, Any]] = []
        self.run_dry_run: list[bool] = []
        self.smart_dry_run: list[bool] = []
        self.writes: list[object] = []
        self.connected: list[bool] = []
        self.config_loads: list[str] = []


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
    # Every subcommand reads its config first, so a recorded read means a subcommand started.
    monkeypatch.setattr(typer_cli, 'load_env_from_config', recorder.config_loads.append)
    monkeypatch.setattr(cli_module, 'load_env_from_config', recorder.config_loads.append)

    def no_credential_chain(*_args: object, **_kwargs: object) -> NoReturn:
        # The async client's chain reads the Keychain and runs `op`: never in a unit test.
        raise AssertionError('get_credentials() ran: a subcommand reached the controller client')

    for target in (
        'unifi_mapper.core.utils.auth.get_credentials',
        'unifi_mapper.core.utils.client.get_credentials',
        'unifi_mapper.core.get_credentials',
    ):
        monkeypatch.setattr(target, no_credential_chain)

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            recorder.mappers.append(kwargs)
            self.api_client = object()

        def batch_update_port_names(self, *args: object, **_kwargs: object) -> bool:
            recorder.writes.append(args)
            return True

    def fake_run_port_mapper(
        *, port_mapper: FakeMapper, dry_run: bool, show_connected_devices: bool, **_: object
    ):
        recorder.run_dry_run.append(dry_run)
        recorder.connected.append(show_connected_devices)
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
        ['--apply', 'ports', 'refresh'],
        ['--apply', 'stp', 'optimize'],
        ['--apply', 'stp', 'apply', '--plan', 'plan.json'],
    ],
)
def test_root_apply_before_a_subcommand_is_rejected(rec: Recorder, args: list[str]) -> None:
    """Code-review F11: Typer never hands a root --apply to the subcommand, so refuse it."""
    result = runner.invoke(app, args)

    assert result.exit_code == 2, result.output
    # Code-review F26 and issue 027: generic, naming the subcommands' own --apply.
    assert '--apply must follow the subcommand and its arguments' in result.output
    assert 'discover --apply' in result.output
    assert 'ports refresh --apply' in result.output
    # No subcommand started, no controller client was built and nothing was written.
    assert rec.config_loads == []
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


# --- issue 027: root shortcuts before a subcommand ------------------------------------------

# Subcommands other than discover, including every one with its own --apply or --dry-run.
OTHER_SUBCOMMANDS = [
    ['ports', 'list', 'switch-a'],
    ['ports', 'refresh'],
    ['ports', 'refresh', '--apply'],
    ['stp', 'optimize'],
    ['stp', 'optimize', '--apply'],
    ['stp', 'apply', '--plan', 'plan.json', '--no-dry-run'],
    ['radio', 'optimize', '--apply'],
    ['analyze', 'link-errors'],
]
SHORTCUT_HINTS = {
    '--dry-run': (
        'read-only subcommands need no flag, '
        'and those with their own --dry-run take it after their arguments'
    ),
    '--connected-devices': 'unifi-mapper discover --connected-devices',
    '--verify-updates': 'unifi-mapper discover --verify-updates',
}
# Code-review F33: subcommands with no --dry-run of their own.
READ_ONLY_SUBCOMMANDS = [['ports', 'list', 'X'], ['analyze', 'link-errors']]


def _assert_nothing_ran(rec: Recorder) -> None:
    """No subcommand started (no config read), no client was built and nothing was written."""
    assert rec.config_loads == []
    assert rec.mappers == []
    assert rec.run_dry_run == []
    assert rec.smart_dry_run == []
    assert rec.writes == []


@pytest.mark.parametrize('subcommand', OTHER_SUBCOMMANDS, ids=' '.join)
@pytest.mark.parametrize('flag', sorted(SHORTCUT_HINTS))
def test_root_shortcut_before_another_subcommand_is_rejected(
    rec: Recorder, flag: str, subcommand: list[str]
) -> None:
    """Typer drops a root flag before a subcommand, so a typed --dry-run could write (027)."""
    result = runner.invoke(app, [flag, *subcommand])

    assert result.exit_code == 2, result.output
    text = re.sub(r'\s+', ' ', result.output)
    assert f'{flag} ' in text and 'only' in text and 'discover' in text, text
    assert SHORTCUT_HINTS[flag] in text, text
    _assert_nothing_ran(rec)


def test_the_dry_run_hint_names_a_subcommand_dry_run(rec: Recorder) -> None:
    result = runner.invoke(app, ['--dry-run', 'ports', 'refresh', '--apply'])

    assert result.exit_code == 2
    assert 'unifi-mapper ports refresh --dry-run' in re.sub(r'\s+', ' ', result.output)
    _assert_nothing_ran(rec)


@pytest.mark.parametrize('read_only', READ_ONLY_SUBCOMMANDS, ids=' '.join)
def test_the_dry_run_hint_suggests_no_flag_a_read_only_subcommand_lacks(
    rec: Recorder, read_only: list[str]
) -> None:
    """Code-review F33: following the hint must never give 'No such option: --dry-run'."""
    result = runner.invoke(app, ['--dry-run', *read_only])

    assert result.exit_code == 2, result.output
    hint = re.sub(r'\s+', ' ', result.output)
    assert 'read-only subcommands need no flag' in hint, hint
    # The premise: the subcommand has no --dry-run (the parse fails before --help runs).
    lacks = runner.invoke(app, [*read_only, '--dry-run', '--help'])
    assert lacks.exit_code == 2, lacks.output
    assert 'No such option: --dry-run' in lacks.output, lacks.output
    # The one --dry-run the hint suggests is a real option of the subcommand it names.
    [example] = re.findall(r'\(e\.g\. unifi-mapper ([^)]+)\)', hint)
    named = runner.invoke(app, [*example.split(), '--help'])
    assert named.exit_code == 0, named.output
    _assert_nothing_ran(rec)


@pytest.mark.parametrize(
    'args',
    [
        ['--dry-run', 'discover', '--apply'],
        ['--dry-run', '--connected-devices', 'discover', '--apply'],
        ['--dry-run', '--verify-updates', 'discover', '--apply'],
    ],
)
def test_root_dry_run_with_discover_apply_is_a_conflict(rec: Recorder, args: list[str]) -> None:
    """The issue 027 write forms: a typed --dry-run must never write."""
    result = runner.invoke(app, args)

    assert result.exit_code == 2, result.output
    assert 'choose --apply or --dry-run' in result.output
    _assert_nothing_ran(rec)


def test_root_dry_run_with_discover_dry_run_previews(rec: Recorder) -> None:
    result = runner.invoke(app, ['--dry-run', 'discover', '--dry-run'])

    assert result.exit_code == 0, result.output
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_root_connected_devices_reaches_discover(rec: Recorder) -> None:
    result = runner.invoke(app, ['--connected-devices', 'discover'])

    assert result.exit_code == 0, result.output
    assert rec.connected == [True]
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_root_verify_updates_reaches_discover(rec: Recorder) -> None:
    result = runner.invoke(app, ['--verify-updates', 'discover'])

    assert result.exit_code == 0, result.output
    assert rec.smart_dry_run == [True]
    assert rec.run_dry_run == [True]
    assert rec.writes == []


def test_root_shortcuts_reach_discover_together(rec: Recorder) -> None:
    result = runner.invoke(
        app, ['--dry-run', '--connected-devices', '--verify-updates', 'discover']
    )

    assert result.exit_code == 0, result.output
    assert rec.connected == [True]
    assert rec.smart_dry_run == [True]
    assert rec.writes == []


def test_root_connected_devices_with_discover_apply_writes_once(rec: Recorder) -> None:
    """Forwarding never blocks a write that the subcommand's own --apply asked for."""
    result = runner.invoke(app, ['--connected-devices', 'discover', '--apply'])

    assert result.exit_code == 0, result.output
    assert rec.connected == [True]
    assert rec.run_dry_run == [False]
    assert len(rec.writes) == 1


def test_root_verify_updates_with_discover_apply_writes_through_the_smart_mapper(
    rec: Recorder,
) -> None:
    result = runner.invoke(app, ['--verify-updates', 'discover', '--apply'])

    assert result.exit_code == 0, result.output
    assert rec.smart_dry_run == [False]
    assert rec.writes == ['smart']


def test_global_options_still_precede_any_subcommand(rec: Recorder, tmp_path: Path) -> None:
    """--config and --debug are global options, not discover shortcuts."""
    config = tmp_path / 'site.env'
    config.write_text('UNIFI_URL=https://192.0.2.1\n', encoding='utf-8')

    result = runner.invoke(app, ['--debug', '--config', str(config), 'discover'])

    assert result.exit_code == 0, result.output
    assert rec.config_loads == [str(config)]
    assert rec.run_dry_run == [True]


def test_root_shortcuts_do_not_leak_into_the_next_invocation(rec: Recorder) -> None:
    """``state`` is module-wide; the shortcuts given before one discover must not stick."""
    first = runner.invoke(app, ['--dry-run', '--connected-devices', 'discover'])
    second = runner.invoke(app, ['discover', '--apply'])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert rec.connected == [True, False]
    assert rec.run_dry_run == [True, False]
    assert len(rec.writes) == 1


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
