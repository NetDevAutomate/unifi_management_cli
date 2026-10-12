"""First-run surface: the no-config message and the version output.

A new user who followed ``.env.example`` and put the file somewhere else saw only
``Configuration file not found: /cwd/.env`` (readiness review, 2026-10-12): the message named
the legacy fallback and none of the places the CLI had actually searched. The ``version``
command printed a hard-coded ``2.0.0 (Enterprise Edition)`` while the package was 0.2.0, and
``--version`` was not an option.
"""

from __future__ import annotations

import logging
import pytest
from importlib.metadata import version as dist_version
from pathlib import Path
from typer.testing import CliRunner
from unifi_mapper import cli
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()


@pytest.fixture
def no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty working directory, home and XDG config home: no config anywhere."""
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'xdg'))
    monkeypatch.delenv('UNIFI_CONFIG', raising=False)
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path


def test_the_default_search_falls_back_to_the_working_directory(no_config: Path) -> None:
    assert cli.get_default_config_path() == Path('.env')


def test_a_missing_default_config_names_every_searched_path(
    no_config: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """With no --config, the error lists the XDG candidates, the fallback and what to create."""
    with caplog.at_level(logging.ERROR, logger='unifi_mapper.cli'):
        with pytest.raises(SystemExit) as exit_info:
            cli.load_env_from_config(str(cli.get_default_config_path()))
    assert exit_info.value.code == 1
    text = caplog.text
    xdg = no_config / 'xdg' / 'unifi_management_cli'
    assert str(xdg / 'prod.env') in text
    assert str(xdg / 'default.env') in text
    assert str((no_config / 'cwd' / '.env').resolve()) in text
    assert 'UNIFI_URL' in text and 'UNIFI_CONSOLE_API_TOKEN' in text
    assert '--config' in text and 'UNIFI_CONFIG' in text


def test_a_missing_explicit_config_names_only_that_path(
    no_config: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A path the user gave is reported as given; the search list would only mislead."""
    given = no_config / 'elsewhere' / 'site.env'
    with caplog.at_level(logging.ERROR, logger='unifi_mapper.cli'):
        with pytest.raises(SystemExit):
            cli.load_env_from_config(str(given))
    assert str(given) in caplog.text
    assert 'prod.env' not in caplog.text


def test_version_flag_prints_the_installed_version() -> None:
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0, result.output
    assert f'unifi-mapper {dist_version("unifi-management-cli")}' in result.output


def test_version_command_matches_the_flag_and_claims_no_edition() -> None:
    result = runner.invoke(app, ['version'])
    assert result.exit_code == 0, result.output
    assert dist_version('unifi-management-cli') in result.output
    assert 'Enterprise' not in result.output
    assert '2.0.0' not in result.output


# --- an unquoted value ends at ` #` (the README once showed inline comments; a password may
# hold a bare `#`, so only a `#` after whitespace starts a comment) --------------------------


@pytest.mark.parametrize(
    ('line', 'expected'),
    [
        ('UNIFI_URL=https://192.0.2.1             # UniFi controller URL', 'https://192.0.2.1'),
        ('UNIFI_SITE=default # Site name', 'default'),
        ('UNIFI_PASSWORD=pa#ss#word', 'pa#ss#word'),  # pragma: allowlist secret
        (
            'UNIFI_PASSWORD="secret value # not a comment"',  # pragma: allowlist secret
            'secret value # not a comment',
        ),
        ("UNIFI_PASSWORD='x # y'", 'x # y'),  # pragma: allowlist secret
        ('UNIFI_TIMEOUT=10', '10'),
    ],
)
def test_env_values_follow_the_dotenv_comment_grammar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str, expected: str
) -> None:
    key = line.split('=', 1)[0]
    monkeypatch.delenv(key, raising=False)
    env = tmp_path / 'site.env'
    env.write_text(line + '\n')
    cli.load_env_from_config(str(env))
    assert __import__('os').environ[key] == expected
