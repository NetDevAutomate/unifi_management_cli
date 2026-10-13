"""One config search for the CLI and the MCP server (issues 048 and 068).

With ``XDG_CONFIG_HOME`` set the two entry points used to search different files, and every
search honoured a relative ``XDG_CONFIG_HOME``, reading a file under the working directory.
Now one function orders the candidates; the CLI adds only the deprecated ``./.env`` as its
last resort, with a warning before anything contacts the controller.
"""

from __future__ import annotations

import os
import pytest
import sys
from pathlib import Path
from typer.testing import CliRunner
from typing import Any, Iterator
from unifi_mapper import cli, port_mapper, run_methods
from unifi_mapper.core.utils.config_search import (
    config_candidates,
    config_dir,
    find_config,
    xdg_config_home,
)
from unifi_mapper.mcp.config import resolve_config_path
from unifi_mapper.typer_cli import app


pytestmark = pytest.mark.usefixtures('block_network')

runner = CliRunner()

URL = 'https://192.0.2.1'
RELATIVE_XDG = ('conf', './conf', '~/conf')


def _write_env(path: Path, url: str = URL) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'UNIFI_URL={url}\nUNIFI_SITE=default\n'
        'UNIFI_USERNAME=reader\nUNIFI_PASSWORD=fake-password\n',  # pragma: allowlist secret
        encoding='utf-8',
    )
    return path


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A home, an XDG config home and a working directory with nothing in them.

    ``os.environ`` is restored afterwards: ``load_env_from_config`` writes keys monkeypatch
    does not know about.
    """
    home = tmp_path / 'home'
    xdg = tmp_path / 'xdg'
    cwd = tmp_path / 'cwd'
    for directory in (home, xdg, cwd):
        directory.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(xdg))
    for key in ('UNIFI_CONFIG', 'UNIFI_URL', 'UNIFI_SITE'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(cwd)
    return {'home': home, 'xdg': xdg, 'cwd': cwd}


@pytest.fixture
def restore_environ() -> Iterator[None]:
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


# --- the shared order, one test per step ------------------------------------------------


def _paths(isolated: dict[str, Path]) -> dict[str, Path]:
    home, xdg = isolated['home'], isolated['xdg']
    return {
        'xdg_prod': xdg / 'unifi_management_cli' / 'prod.env',
        'xdg_default': xdg / 'unifi_management_cli' / 'default.env',
        'home_prod': home / '.config' / 'unifi_management_cli' / 'prod.env',
        'home_default': home / '.config' / 'unifi_management_cli' / 'default.env',
        'legacy': home / '.config' / 'unifi_network_mapper' / 'prod.env',
        'cwd': isolated['cwd'] / '.env',
    }


def test_unifi_config_is_the_only_candidate_even_when_missing(isolated: dict[str, Path]) -> None:
    for path in _paths(isolated).values():
        _write_env(path)
    explicit = isolated['home'] / 'elsewhere.env'
    env = {'UNIFI_CONFIG': str(explicit), 'XDG_CONFIG_HOME': str(isolated['xdg'])}
    assert config_candidates(env, isolated['home'], isolated['cwd']) == (('explicit', explicit),)
    source, path, tried, warning = find_config(env, isolated['home'], cwd=isolated['cwd'])
    assert (source, path, tried) == ('none', None, (explicit,))
    assert warning and str(explicit) in warning


@pytest.mark.parametrize(
    ('step', 'source'),
    [
        ('xdg_prod', 'xdg'),
        ('xdg_default', 'xdg'),
        ('home_prod', 'home'),
        ('home_default', 'home'),
        ('legacy', 'legacy'),
        ('cwd', 'cwd'),
    ],
)
def test_each_step_wins_over_every_later_one(
    isolated: dict[str, Path], step: str, source: str
) -> None:
    paths = _paths(isolated)
    order = list(paths)
    for later in order[order.index(step) :]:
        _write_env(paths[later])
    got_source, path, tried, warning = find_config(
        dict(os.environ), isolated['home'], cwd=isolated['cwd']
    )
    assert (got_source, path) == (source, paths[step])
    assert tried == tuple(paths[s] for s in order[: order.index(step) + 1])
    assert (warning is not None) == (source in ('legacy', 'cwd'))


def test_the_cwd_env_is_the_lowest_step_and_only_when_asked(isolated: dict[str, Path]) -> None:
    _write_env(_paths(isolated)['cwd'])
    env = dict(os.environ)
    with_cwd = config_candidates(env, isolated['home'], isolated['cwd'])
    assert with_cwd[-1] == ('cwd', isolated['cwd'] / '.env')
    assert config_candidates(env, isolated['home']) == with_cwd[:-1]
    assert find_config(env, isolated['home'])[:2] == ('none', None)


def test_legacy_and_cwd_warnings_name_the_replacement(isolated: dict[str, Path]) -> None:
    paths = _paths(isolated)
    _write_env(paths['legacy'])
    _, _, _, legacy = find_config(dict(os.environ), isolated['home'], cwd=isolated['cwd'])
    assert legacy and 'deprecated' in legacy and str(paths['home_prod']) in legacy

    paths['legacy'].unlink()
    _write_env(paths['cwd'])
    _, _, _, cwd = find_config(dict(os.environ), isolated['home'], cwd=isolated['cwd'])
    assert cwd and str(paths['cwd']) in cwd
    assert '--config ./.env' in cwd and 'UNIFI_CONFIG' in cwd and '0.4.0' in cwd


# --- a relative XDG_CONFIG_HOME is ignored (issue 068) ---------------------------------


@pytest.mark.parametrize('relative', RELATIVE_XDG)
def test_a_relative_xdg_config_home_is_unset_for_the_shared_search(
    isolated: dict[str, Path], relative: str
) -> None:
    stray = _write_env(isolated['cwd'] / 'conf' / 'unifi_management_cli' / 'prod.env')
    env = {'XDG_CONFIG_HOME': relative}
    assert xdg_config_home(env) is None
    assert (
        config_dir(env, isolated['home']) == isolated['home'] / '.config' / 'unifi_management_cli'
    )
    assert config_candidates(env, isolated['home']) == config_candidates({}, isolated['home'])
    source, path, tried, _ = find_config(env, isolated['home'], cwd=isolated['cwd'])
    assert (source, path) == ('none', None)
    assert stray not in tried and all(p.is_absolute() for p in tried)


@pytest.mark.parametrize('relative', RELATIVE_XDG)
def test_a_relative_xdg_config_home_is_unset_for_the_cli(
    isolated: dict[str, Path], monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    stray = _write_env(isolated['cwd'] / 'conf' / 'unifi_management_cli' / 'prod.env')
    monkeypatch.setenv('XDG_CONFIG_HOME', relative)
    candidates = cli.default_config_candidates()
    assert stray not in candidates and all(p.is_absolute() for p in candidates)
    assert cli.get_default_config_path() == isolated['cwd'] / '.env'  # nothing found


@pytest.mark.parametrize('relative', RELATIVE_XDG)
def test_a_relative_xdg_config_home_is_unset_for_the_mcp_server(
    isolated: dict[str, Path], relative: str
) -> None:
    stray = _write_env(isolated['cwd'] / 'conf' / 'unifi_management_cli' / 'prod.env')
    source, path, tried, _ = resolve_config_path(
        {'XDG_CONFIG_HOME': relative}, isolated['home'], Path.is_file
    )
    assert (source, path) == ('none', None)
    assert stray not in tried and all(p.is_absolute() for p in tried)


# --- the CLI and the MCP server agree (issue 048) ------------------------------------


@pytest.mark.parametrize(
    'present',
    [
        (),
        ('xdg_prod',),
        ('xdg_default',),
        ('home_prod', 'xdg_default'),
        ('home_default',),
        ('legacy',),
        ('legacy', 'home_default', 'xdg_prod'),
    ],
)
def test_cli_and_mcp_server_pick_the_same_file(
    isolated: dict[str, Path], present: tuple[str, ...]
) -> None:
    paths = _paths(isolated)
    for step in present:
        _write_env(paths[step])
    env = dict(os.environ)
    mcp_path = resolve_config_path(env, isolated['home'], Path.is_file)[1]
    cli_path = cli.get_default_config_path(warn=lambda _m: None)
    if present:
        assert cli_path == mcp_path
    else:
        assert mcp_path is None and cli_path == isolated['cwd'] / '.env'


def test_the_cli_search_lists_the_shared_paths_then_the_cwd_env(
    isolated: dict[str, Path],
) -> None:
    paths = _paths(isolated)
    assert cli.default_config_candidates() == [
        paths['xdg_prod'],
        paths['xdg_default'],
        paths['home_prod'],
        paths['home_default'],
        paths['legacy'],
        paths['cwd'],
    ]


def test_cli_legacy_file_warns_like_the_server(
    isolated: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = _write_env(_paths(isolated)['legacy'])
    assert cli.get_default_config_path() == legacy
    err = capsys.readouterr().err
    assert str(legacy) in err and 'deprecated' in err


# --- the ./.env fallback warns before any controller connection ----------------------


def test_cwd_env_fallback_warns_on_stderr(
    isolated: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    stray = _write_env(_paths(isolated)['cwd'])
    assert cli.get_default_config_path() == stray
    out, err = capsys.readouterr()
    assert out == ''
    assert str(stray) in err and '0.4.0' in err
    assert '--config ./.env' in err and 'UNIFI_CONFIG' in err


def test_an_explicit_cwd_env_does_not_warn(
    isolated: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stray = _write_env(_paths(isolated)['cwd'])
    monkeypatch.setenv('UNIFI_CONFIG', './.env')
    assert cli.get_default_config_path() == Path('./.env')
    assert capsys.readouterr().err == ''
    assert stray.exists()


class _Stop(Exception):
    """Raised by the fake mapper once it has recorded that it was built."""


def test_cwd_env_warning_precedes_the_client(
    isolated: dict[str, Path], monkeypatch: pytest.MonkeyPatch, restore_environ: None
) -> None:
    """``discover --dry-run`` with only ``./.env``: the warning, then the client, then stop."""
    _write_env(_paths(isolated)['cwd'])
    events: list[str] = []

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            events.append(f'client:{kwargs["base_url"]}')
            raise _Stop

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', lambda **_: ([], []))
    monkeypatch.setattr(cli, '_stderr_warning', lambda message: events.append('warning'))

    result = runner.invoke(app, ['discover', '--dry-run'])

    assert result.exit_code == 1, result.output  # the fake stops the command
    assert events == ['warning', f'client:{URL}']


def test_legacy_argparse_entry_warns_before_the_client(
    isolated: dict[str, Path], monkeypatch: pytest.MonkeyPatch, restore_environ: None
) -> None:
    _write_env(_paths(isolated)['cwd'])
    events: list[str] = []

    class FakeMapper:
        def __init__(self, **kwargs: Any) -> None:
            events.append('client')
            raise _Stop

    monkeypatch.setattr(port_mapper, 'UnifiPortMapper', FakeMapper)
    monkeypatch.setattr(run_methods, 'run_port_mapper', lambda **_: ([], []))
    monkeypatch.setattr(cli, '_stderr_warning', lambda message: events.append('warning'))
    monkeypatch.setattr(sys, 'argv', ['unifi-mapper', '--dry-run'])

    assert cli.main() == 1
    assert events == ['warning', 'client']


def test_help_does_not_run_the_search(
    isolated: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--help`` on the argparse entry point must not warn about a ``./.env`` it never loads."""
    _write_env(_paths(isolated)['cwd'])
    monkeypatch.setattr(sys, 'argv', ['unifi-mapper', '--help'])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
    assert '0.4.0' not in capsys.readouterr().err


def test_mcp_config_delegates_to_the_shared_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """One search, not two that drift: the server's resolver calls the shared function."""
    from unifi_mapper.mcp import config as mcp_config

    seen: list[tuple[object, ...]] = []

    def _fake(env: Any, home: Path, is_file: Any = None, cwd: Path | None = None) -> tuple:
        seen.append((home, cwd))
        return ('none', None, (), None)

    monkeypatch.setattr(mcp_config, 'find_config', _fake)
    assert mcp_config.resolve_config_path({}, Path('/h'), Path.is_file) == ('none', None, (), None)
    assert seen == [(Path('/h'), None)]  # never the working directory
