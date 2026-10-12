"""Issue 077: `inventory update-firmware` previews by default and upgrades only with `--apply`.

It was the one writer that defaulted to a `y/N` prompt (skipped by `--force`) and offered
`--dry-run` as the opt-in preview, while every other command that writes to the controller
previews unless `--apply` is given (issues 007, 015). A firmware upgrade reboots devices, so the
default must be the preview. `--force` keeps its meaning (skip the confirmation) but only
together with `--apply`; `--dry-run` is still accepted and means the default; both flags at once
exit 2. `get_api_client`, `fetch_and_categorize_devices` and `_trigger_firmware_upgrade` are
faked at the module seams; no test here reaches a controller or sleeps.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner
from unifi_mapper import inventory_cli
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')
runner = CliRunner()

SWITCH = {
    'name': 'core-switch',
    'mac': '02:00:00:00:00:01',
    'model': 'USW-Pro-24',
    'type': 'switch',
    'version': '7.1.0',
    'upgradable': True,
    'upgrade_to_firmware': '7.2.0',
    'ip': '192.0.2.20',
    'state': 1,
    'adopted': True,
}


class FakeClient:
    def __init__(self) -> None:
        self.logged_out = 0

    def logout(self) -> None:
        self.logged_out += 1


@pytest.fixture
def upgrades(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake the controller seams; return the list of MACs an upgrade was triggered for."""
    triggered: list[str] = []
    client = FakeClient()

    monkeypatch.setattr(
        inventory_cli, 'get_api_client', lambda config_path=None: (client, 'default')
    )
    monkeypatch.setattr(
        inventory_cli, 'fetch_and_categorize_devices', lambda _c, _s: {'switch': [dict(SWITCH)]}
    )

    def fake_trigger(_client: object, _site: str, mac: str) -> bool:
        triggered.append(mac)
        return True

    monkeypatch.setattr(inventory_cli, '_trigger_firmware_upgrade', fake_trigger)
    monkeypatch.setattr(inventory_cli.time, 'sleep', lambda _s: None)
    monkeypatch.delenv('UNIFI_CONFIG', raising=False)
    return triggered


def _run(*argv: str, input: str | None = None):
    return runner.invoke(
        app, ['inventory', 'update-firmware', '--filter', 'all', *argv], input=input
    )


def test_the_default_is_a_preview_that_writes_nothing(upgrades) -> None:
    result = _run()
    assert result.exit_code == 0, result.output
    assert upgrades == []
    assert 'core-switch' in result.output  # the plan is still shown
    assert '--apply' in result.output  # and the output says how to run it


def test_explicit_dry_run_means_the_default(upgrades) -> None:
    result = _run('--dry-run')
    assert result.exit_code == 0, result.output
    assert upgrades == []


def test_force_alone_does_not_write(upgrades) -> None:
    # The old scripted form `--filter all --force` upgraded every device without a prompt.
    result = _run('--force')
    assert result.exit_code == 0, result.output
    assert upgrades == []
    assert '--apply' in result.output


def test_apply_still_asks_and_a_no_writes_nothing(upgrades) -> None:
    result = _run('--apply', input='n\n')
    assert result.exit_code == 0, result.output
    assert upgrades == []
    assert 'cancelled' in result.output.lower()


def test_apply_with_a_yes_triggers_the_upgrade(upgrades) -> None:
    result = _run('--apply', input='y\n')
    assert result.exit_code == 0, result.output
    assert upgrades == [SWITCH['mac']]


def test_apply_with_force_skips_the_prompt(upgrades) -> None:
    result = _run('--apply', '--force')
    assert result.exit_code == 0, result.output
    assert upgrades == [SWITCH['mac']]
    assert 'Are you sure' not in result.output


def test_dry_run_with_apply_exits_2_before_any_controller_call(upgrades, monkeypatch) -> None:
    def boom(config_path=None):  # pragma: no cover - must not be reached
        raise AssertionError('the controller was contacted')

    monkeypatch.setattr(inventory_cli, 'get_api_client', boom)
    result = _run('--dry-run', '--apply')
    assert result.exit_code == 2, result.output
    assert upgrades == []


def test_help_describes_the_preview_default() -> None:
    result = runner.invoke(app, ['inventory', 'update-firmware', '--help'])
    assert result.exit_code == 0
    assert '--apply' in result.output
    assert 'confirmation' in result.output.lower()
