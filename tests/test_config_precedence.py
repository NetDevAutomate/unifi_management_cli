"""A stray ``./.env`` in the working directory never overrides ``--config`` (sibling F8)."""

import os
import pytest
import sys
from pathlib import Path
from typer.testing import CliRunner
from typing import Any, Iterator
from unifi_mapper import cli as legacy_cli
from unifi_mapper import port_mapper, run_methods
from unifi_mapper.config import UnifiConfig
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()

CONFIG_URL = 'https://192.0.2.1'
STRAY_URL = 'https://198.51.100.9'
ENV_KEYS = (
    'UNIFI_URL',
    'UNIFI_SITE',
    'UNIFI_USERNAME',
    'UNIFI_PASSWORD',
    'UNIFI_CONSOLE_API_TOKEN',
    'UNIFI_API_TOKEN',
    'UNIFI_CONFIG',
)


class _Stop(Exception):
    """Raised by the fake mapper once it has recorded what it was built with."""


@pytest.fixture
def env_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """A CWD ``.env`` naming one controller and a ``--config`` file naming another.

    Yields the ``--config`` path. ``os.environ`` is restored afterwards, because
    ``load_env_from_config`` writes keys monkeypatch does not know about.
    """
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    saved = dict(os.environ)

    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    (cwd / '.env').write_text(
        f'UNIFI_URL={STRAY_URL}\nUNIFI_SITE=stray\n'
        'UNIFI_USERNAME=stray\nUNIFI_PASSWORD=stray-password\n',  # pragma: allowlist secret
        encoding='utf-8',
    )
    config = tmp_path / 'config' / 'prod.env'
    config.parent.mkdir()
    config.write_text(
        f'UNIFI_URL={CONFIG_URL}\nUNIFI_SITE=default\n'
        'UNIFI_USERNAME=reader\nUNIFI_PASSWORD=fake-password\n',  # pragma: allowlist secret
        encoding='utf-8',
    )
    monkeypatch.chdir(cwd)
    try:
        yield config
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``UnifiPortMapper`` with a fake that records its kwargs, then stops."""
    calls: list[dict[str, Any]] = []

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            raise _Stop

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', lambda **_: ([], []))
    return calls


def test_from_env_with_a_path_ignores_the_cwd_env(env_files: Path) -> None:
    legacy_cli.load_env_from_config(str(env_files))

    assert UnifiConfig.from_env(str(env_files)).base_url == CONFIG_URL
    # The implicit default is exactly what used to win over --config.
    assert UnifiConfig.from_env().base_url == STRAY_URL


def test_discover_dry_run_uses_the_config_controller(
    env_files: Path, built: list[dict[str, Any]]
) -> None:
    result = runner.invoke(app, ['--config', str(env_files), 'discover', '--dry-run'])

    assert result.exit_code == 1, result.output  # the fake stops the command
    assert [call['base_url'] for call in built] == [CONFIG_URL]
    assert built[0]['site'] == 'default'


def test_diagram_uses_the_config_controller(env_files: Path, built: list[dict[str, Any]]) -> None:
    result = runner.invoke(app, ['--config', str(env_files), 'diagram'])

    assert result.exit_code == 1, result.output
    assert [call['base_url'] for call in built] == [CONFIG_URL]


def test_legacy_cli_uses_the_config_controller(
    env_files: Path, built: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, 'argv', ['unifi-mapper', '--config', str(env_files), '--dry-run'])

    assert legacy_cli.main() == 1  # the fake raises; main() logs and returns 1
    assert [call['base_url'] for call in built] == [CONFIG_URL]
