"""Issue 043: `unifi-mapper inventory …` honours the root `--config` and `UNIFI_CONFIG`.

The inventory commands come from `inventory_cli.inventory_app` and took only their own
`--config`; without it they fell back to the default search, so
`unifi-mapper --config site-b.env inventory list` read the default config and acted on that
controller. The sub-app's commands now take the root value when their own option is unset.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typer.testing import CliRunner
from unifi_mapper import inventory_cli
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')
runner = CliRunner()


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    calls: list[str | None] = []

    def fake_get_api_client(config_path=None):
        calls.append(config_path)
        raise SystemExit(0)  # stop before any controller work

    monkeypatch.setattr(inventory_cli, 'get_api_client', fake_get_api_client)
    monkeypatch.delenv('UNIFI_CONFIG', raising=False)
    return calls


@pytest.mark.parametrize('command', ['list', 'check-updates', 'firmware-skew'])
def test_root_config_reaches_the_inventory_commands(seen, tmp_path: Path, command: str) -> None:
    site_b = tmp_path / 'site-b.env'
    site_b.write_text('UNIFI_URL=https://203.0.113.2\n')
    runner.invoke(app, ['--config', str(site_b), 'inventory', command])
    assert seen == [str(site_b)]


def test_unifi_config_env_reaches_the_inventory_commands(
    seen, tmp_path: Path, monkeypatch
) -> None:
    site_b = tmp_path / 'site-b.env'
    site_b.write_text('UNIFI_URL=https://203.0.113.2\n')
    monkeypatch.setenv('UNIFI_CONFIG', str(site_b))
    runner.invoke(app, ['inventory', 'list'])
    assert seen == [str(site_b)]


def test_the_sub_apps_own_config_still_wins(seen, tmp_path: Path) -> None:
    root, own = tmp_path / 'root.env', tmp_path / 'own.env'
    root.write_text('UNIFI_URL=https://203.0.113.2\n')
    own.write_text('UNIFI_URL=https://203.0.113.3\n')
    runner.invoke(app, ['--config', str(root), 'inventory', 'list', '--config', str(own)])
    assert seen == [str(own)]


def test_without_any_config_the_default_search_is_used(seen) -> None:
    runner.invoke(app, ['inventory', 'list'])
    assert seen == [None]
