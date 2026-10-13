"""The one search for the project's env file, shared by every entry point (issues 048, 068).

The CLI programs (``unifi-mapper``, ``unifi-inventory``, ``unifi-network-toolkit``, the
scripts) and the MCP server used to look in different places once ``XDG_CONFIG_HOME`` was
set, and every search honoured a *relative* ``XDG_CONFIG_HOME``, which the XDG Base Directory
spec says must be ignored. This module is the single order, read at call time:

0. ``UNIFI_CONFIG`` when set: the only candidate (a wrong path is reported, never replaced).
1. ``$XDG_CONFIG_HOME/unifi_management_cli/prod.env``, then ``default.env`` there, when
   ``XDG_CONFIG_HOME`` is set to an **absolute** path.
2. ``~/.config/unifi_management_cli/prod.env``, then ``default.env`` there.
3. ``~/.config/unifi_network_mapper/prod.env`` (legacy; loaded with a deprecation warning).
4. Only when the caller passes its working directory: ``<cwd>/.env`` (deprecated; loaded with
   a warning naming the replacement; removed in :data:`CWD_ENV_REMOVED_IN`). The MCP server
   never passes one.

Pure functions: the environment, the home directory and the file predicate are injected, so
tests never read the real ``~/.config``. Nothing here reads a file's contents.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal


ConfigSource = Literal['explicit', 'xdg', 'home', 'legacy', 'cwd', 'none']

CONFIG_DIR_NAME = 'unifi_management_cli'
LEGACY_CONFIG_DIR_NAME = 'unifi_network_mapper'
CONFIG_FILE_NAMES = ('prod.env', 'default.env')
CWD_ENV_NAME = '.env'
CWD_ENV_REMOVED_IN = '0.4.0'


def xdg_config_home(env: Mapping[str, str]) -> Path | None:
    """Return ``XDG_CONFIG_HOME`` when it is set to an absolute path, else ``None``.

    The XDG Base Directory spec says a relative value must be ignored; ``~`` is not
    expanded, so ``~/conf`` is relative too. Ignoring it keeps every search independent of
    the working directory (issue 068).

    Args:
        env: The environment to read.

    Returns:
        The absolute directory, or ``None`` when the variable is unset, empty or relative.
    """
    value = env.get('XDG_CONFIG_HOME')
    if value and Path(value).is_absolute():
        return Path(value)
    return None


def config_dir(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """Return the directory the project's config files live in.

    Args:
        env: The environment; ``None`` means ``os.environ`` at call time.
        home: The home directory; ``None`` means ``Path.home()`` at call time.

    Returns:
        ``$XDG_CONFIG_HOME/unifi_management_cli`` when that variable is absolute, else
        ``~/.config/unifi_management_cli``.
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    xdg = xdg_config_home(env)
    base = xdg if xdg is not None else home / '.config'
    return base / CONFIG_DIR_NAME


def expand_home(value: str, home: Path) -> Path:
    """Expand a leading ``~`` against the injected home directory.

    Args:
        value: A path as typed; ``~`` or ``~/...`` names the home directory.
        home: The home directory to expand against.

    Returns:
        The path, with ``~`` replaced.
    """
    if value == '~':
        return home
    if value.startswith('~/'):
        return home / value[2:]
    return Path(value)


def config_candidates(
    env: Mapping[str, str], home: Path, cwd: Path | None = None
) -> tuple[tuple[ConfigSource, Path], ...]:
    """Return the config files to try, in order, each tagged with its source.

    Args:
        env: The environment (only ``UNIFI_CONFIG`` and ``XDG_CONFIG_HOME`` are read).
        home: The user's home directory.
        cwd: The working directory whose ``.env`` is the last resort; ``None`` leaves it out.

    Returns:
        ``(source, path)`` pairs, deduplicated (``XDG_CONFIG_HOME=~/.config`` is tried once).
        With ``UNIFI_CONFIG`` set, exactly one pair.
    """
    configured = env.get('UNIFI_CONFIG')
    if configured:
        return (('explicit', expand_home(configured, home)),)

    ordered: list[tuple[ConfigSource, Path]] = []
    xdg = xdg_config_home(env)
    if xdg is not None:
        ordered.extend(('xdg', xdg / CONFIG_DIR_NAME / name) for name in CONFIG_FILE_NAMES)
    home_dir = home / '.config' / CONFIG_DIR_NAME
    ordered.extend(('home', home_dir / name) for name in CONFIG_FILE_NAMES)
    ordered.append(('legacy', home / '.config' / LEGACY_CONFIG_DIR_NAME / 'prod.env'))
    if cwd is not None:
        ordered.append(('cwd', cwd / CWD_ENV_NAME))

    seen: set[Path] = set()
    unique: list[tuple[ConfigSource, Path]] = []
    for source, path in ordered:
        if path in seen:
            continue
        seen.add(path)
        unique.append((source, path))
    return tuple(unique)


def legacy_warning(path: Path, home: Path) -> str:
    """Return the warning for a config loaded from the legacy directory."""
    replacement = home / '.config' / CONFIG_DIR_NAME / 'prod.env'
    return (
        f'loading the legacy config {path}; move it to {replacement} '
        '(the legacy location is deprecated)'
    )


def cwd_env_warning(path: Path) -> str:
    """Return the deprecation warning for a config loaded from the working directory."""
    return (
        f'loading {path} from the working directory because no other config file was '
        f'found; this fallback is deprecated and is removed in {CWD_ENV_REMOVED_IN}. '
        f'Name the file instead: --config ./{CWD_ENV_NAME} or UNIFI_CONFIG=./{CWD_ENV_NAME}, '
        f'or move it to {Path("~") / ".config" / CONFIG_DIR_NAME / "prod.env"}'
    )


def readable_file(path: Path) -> bool:
    """Return True if ``path`` is a file this process can read."""
    return path.is_file() and os.access(path, os.R_OK)


def find_config(
    env: Mapping[str, str],
    home: Path,
    is_file: Callable[[Path], bool] = readable_file,
    cwd: Path | None = None,
) -> tuple[ConfigSource, Path | None, tuple[Path, ...], str | None]:
    """Pick the first existing config file in the shared order.

    Args:
        env: The environment (only ``UNIFI_CONFIG`` and ``XDG_CONFIG_HOME`` are read).
        home: The user's home directory.
        is_file: Predicate telling whether a candidate is a readable file.
        cwd: The working directory whose ``.env`` is the last resort; ``None`` leaves it out.

    Returns:
        ``(source, path or None, paths tried, warning or None)``. A set ``UNIFI_CONFIG``
        never falls through: a missing file gives ``('none', None, (path,), warning)``. The
        legacy and working-directory steps carry a warning when they win.
    """
    candidates = config_candidates(env, home, cwd)
    if candidates[0][0] == 'explicit':
        path = candidates[0][1]
        if is_file(path):
            return 'explicit', path, (path,), None
        return (
            'none',
            None,
            (path,),
            f'UNIFI_CONFIG={path} is not a readable file; no config file loaded '
            '(auto-discovery is skipped when UNIFI_CONFIG is set)',
        )

    tried: list[Path] = []
    for source, path in candidates:
        tried.append(path)
        if not is_file(path):
            continue
        warning: str | None = None
        if source == 'legacy':
            warning = legacy_warning(path, home)
        elif source == 'cwd':
            warning = cwd_env_warning(path)
        return source, path, tuple(tried), warning
    return 'none', None, tuple(tried), None
