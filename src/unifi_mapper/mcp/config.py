"""Config resolution for the MCP server, independent of the working directory.

An MCP client may launch ``unifi-mcp`` from any directory, so the server never reads a
``.env`` in the CWD. It picks at most one env file (``--config``, ``UNIFI_CONFIG``, the XDG
and home config directories, then the legacy directory) and loads it **per credential
family**, atomically, so two controllers are never mixed: a family with any key exported
by the client is the environment's, whole, and an auto-discovered file is ignored when it
describes a different controller than the one the client exported.

The functions above :func:`resolve_mcp_config` are pure; the wrapper does the I/O.
Nothing here holds or reports secret values: statuses carry key names only.
"""

import os
import sys
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


CredentialFamily = Literal['controller', 'network_api', 'protect', 'none']
ConfigSource = Literal['explicit', 'xdg', 'home', 'legacy', 'none']
FamilySource = Literal['environment', 'file', 'none']

CREDENTIAL_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    # Each inner tuple is an any-of group; every group must be satisfied.
    'controller': (('UNIFI_URL', 'UNIFI_HOST'),),  # + auth group, see controller_ready()
    'network_api': (
        ('UNIFI_NETWORK_HOST',),
        ('UNIFI_NETWORK_API_KEY',),
        ('UNIFI_NETWORK_SITE_ID',),
    ),
    'protect': (('PROTECT_HOST',), ('PROTECT_USERNAME',), ('PROTECT_PASSWORD',)),
    'none': (),
}

CONTROLLER_KEYS: frozenset[str] = frozenset(
    {
        # Identity + auth of one controller, as read by Credentials.from_env and the SSH helpers.
        'UNIFI_URL',
        'UNIFI_HOST',
        'UNIFI_PORT',
        'UNIFI_SITE',
        'UNIFI_VERIFY_SSL',
        'UNIFI_CONSOLE_API_TOKEN',
        'UNIFI_API_TOKEN',
        'UNIFI_USERNAME',
        'UNIFI_PASSWORD',
        'UNIFI_SSH_USERNAME',
        'UNIFI_SSH_PASSWORD',
    }
)
# Every key that belongs to a family. A family is loaded from a file atomically.
FAMILY_KEYS: dict[str, Callable[[str], bool]] = {
    'controller': lambda k: k in CONTROLLER_KEYS,
    'network_api': lambda k: k.startswith('UNIFI_NETWORK_'),  # NetworkConfig prefix
    'protect': lambda k: k.startswith('PROTECT_'),  # ProtectConfig prefix
}
# Never family members, never loaded from a file by the MCP resolver: UNIFI_CONFIG, UNIFI_MCP_*.
# Any other file key (UNIFI_TIMEOUT, UNIFI_OUTPUT_DIR, ...) is a "setting": per-key setdefault.
_NEVER_FROM_FILE_PREFIX = 'UNIFI_MCP_'
_NEVER_FROM_FILE = frozenset({'UNIFI_CONFIG'})

_HOST_KEYS: dict[str, tuple[str, ...]] = {
    'controller': ('UNIFI_URL', 'UNIFI_HOST'),
    'network_api': ('UNIFI_NETWORK_HOST',),
    'protect': ('PROTECT_HOST',),
}
_TOKEN_KEYS = ('UNIFI_CONSOLE_API_TOKEN', 'UNIFI_API_TOKEN')

CONFIG_DIR_NAME = 'unifi_management_cli'
LEGACY_CONFIG_DIR_NAME = 'unifi_network_mapper'
CONFIG_FILE_NAMES = ('prod.env', 'default.env')
FOREIGN_FILE_REASON = 'file describes a different controller'
FOREIGN_FILE_SUGGESTION = 'set UNIFI_CONFIG to the file for this site'


def controller_ready(env: Mapping[str, str]) -> bool:
    """Return True if ``env`` holds a usable controller identity and auth.

    Mirrors ``Credentials.from_env``: ``UNIFI_URL`` or ``UNIFI_HOST``, plus either a token
    (``UNIFI_CONSOLE_API_TOKEN``/``UNIFI_API_TOKEN``) or both username and password.
    Empty values count as absent, as they do there.

    Args:
        env: The environment to inspect.

    Returns:
        True when ``Credentials.from_env`` would succeed on ``env``.
    """
    has_host = bool(env.get('UNIFI_URL') or env.get('UNIFI_HOST'))
    has_token = any(env.get(k) for k in _TOKEN_KEYS)
    has_password = bool(env.get('UNIFI_USERNAME') and env.get('UNIFI_PASSWORD'))
    return has_host and (has_token or has_password)


def normalise_host(value: str | None) -> str | None:
    """Normalise a host the way ``NetworkConfig.validate_host`` does, lower-cased.

    Args:
        value: A host, ``host:port`` or URL; ``None`` or empty means absent.

    Returns:
        The bare lower-case host, or ``None`` when nothing is left.
    """
    if not value:
        return None
    normalised = value.strip()
    for prefix in ('https://', 'http://'):
        if normalised.lower().startswith(prefix):
            normalised = normalised[len(prefix) :]
            break
    normalised = normalised.rstrip('/').split(':')[0].lower()
    return normalised or None


def family_host(family: str, values: Mapping[str, str]) -> str | None:
    """Return the normalised host a mapping names for one credential family.

    Args:
        family: ``controller``, ``network_api`` or ``protect``.
        values: An environment or the parsed values of an env file.

    Returns:
        The host from ``UNIFI_URL``/``UNIFI_HOST``, ``UNIFI_NETWORK_HOST`` or
        ``PROTECT_HOST``, normalised; ``None`` if absent.
    """
    for key in _HOST_KEYS.get(family, ()):
        host = normalise_host(values.get(key))
        if host is not None:
            return host
    return None


def is_setting(key: str) -> bool:
    """Return True for a file key that is a plain setting (not in any credential family).

    Args:
        key: An env-file key.

    Returns:
        False for family members, ``UNIFI_CONFIG`` and ``UNIFI_MCP_*``; True otherwise.
    """
    if key in _NEVER_FROM_FILE or key.startswith(_NEVER_FROM_FILE_PREFIX):
        return False
    return not any(member(key) for member in FAMILY_KEYS.values())


@dataclass(frozen=True)
class FamilyStatus:
    """Readiness of one credential family. Key names only, never values."""

    ready: bool
    source: FamilySource  # where the family's keys came from
    present: tuple[str, ...]
    missing: tuple[str, ...]
    skipped_reason: str | None = None  # why a file's keys were *not* applied, if they weren't

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict (key names and flags only)."""
        return {
            'ready': self.ready,
            'source': self.source,
            'present': list(self.present),
            'missing': list(self.missing),
            'skipped_reason': self.skipped_reason,
        }


@dataclass(frozen=True)
class ResolvedConfig:
    """Where MCP config came from. Never holds secret values."""

    source: ConfigSource  # the file, if any
    path: Path | None
    tried: tuple[Path, ...]
    families: Mapping[str, FamilyStatus]
    settings_from_file: frozenset[str]  # non-family key names applied via setdefault

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict for ``--check`` and status resources (no values)."""
        return {
            'source': self.source,
            'path': str(self.path) if self.path else None,
            'tried': [str(p) for p in self.tried],
            'families': {name: status.to_json_dict() for name, status in self.families.items()},
            'settings_from_file': sorted(self.settings_from_file),
        }


def _missing_keys(family: str, env: Mapping[str, str]) -> tuple[str, ...]:
    """Return the key names (or alternatives) a family still needs in ``env``."""
    missing = [
        ' or '.join(group)
        for group in CREDENTIAL_KEYS.get(family, ())
        if not any(env.get(k) for k in group)
    ]
    if family == 'controller' and not (
        any(env.get(k) for k in _TOKEN_KEYS)
        or (env.get('UNIFI_USERNAME') and env.get('UNIFI_PASSWORD'))
    ):
        if env.get('UNIFI_USERNAME'):
            missing.append('UNIFI_PASSWORD')
        elif env.get('UNIFI_PASSWORD'):
            missing.append('UNIFI_USERNAME')
        else:
            missing.append('UNIFI_CONSOLE_API_TOKEN or UNIFI_USERNAME+UNIFI_PASSWORD')
    return tuple(missing)


def family_status(
    family: str,
    env: Mapping[str, str],
    source: FamilySource,
    skipped_reason: str | None = None,
) -> FamilyStatus:
    """Return the readiness of one family in ``env`` (key names only).

    Args:
        family: ``controller``, ``network_api`` or ``protect``.
        env: The environment the family will be read from.
        source: Where the family's keys came from.
        skipped_reason: Why a file's keys for this family were not applied, if so.

    Returns:
        The family's status.
    """
    member = FAMILY_KEYS[family]
    present = tuple(sorted(k for k, v in env.items() if member(k) and v))
    missing = _missing_keys(family, env)
    return FamilyStatus(
        ready=not missing,
        source=source,
        present=present,
        missing=missing,
        skipped_reason=skipped_reason,
    )


def apply_file(
    env: Mapping[str, str], file_values: Mapping[str, str], explicit: bool
) -> tuple[dict[str, str], dict[str, FamilyStatus], frozenset[str]]:
    """Decide which keys of an env file to set, per family and atomically.

    * A family with any key exported in ``env`` is the environment's, whole; it is never
      topped up from the file.
    * An auto-discovered file (``explicit=False``) is not applied at all when a host the
      client exported differs from the same family's host in the file, or the file has no
      host for that family (the site can't be confirmed).
    * An explicit file is applied per family regardless of host. Exported families win.
    * Settings (non-family keys) follow the same foreign-file rule, then per-key setdefault.

    Args:
        env: The environment as the client exported it.
        file_values: Parsed ``KEY=VALUE`` pairs of the chosen file.
        explicit: True for ``--config``/``UNIFI_CONFIG``.

    Returns:
        ``(keys to set, per-family status, setting names applied)``.
    """
    foreign = not explicit and any(
        family_host(f, env) is not None and family_host(f, env) != family_host(f, file_values)
        for f in FAMILY_KEYS
    )
    to_set: dict[str, str] = {}
    status: dict[str, FamilyStatus] = {}
    for family, member in FAMILY_KEYS.items():
        exported = any(member(k) for k in env)
        from_file = {k: v for k, v in file_values.items() if member(k)}
        if exported:  # partially exported -> never topped up
            status[family] = family_status(family, env, 'environment')
        elif foreign and from_file:
            status[family] = family_status(family, env, 'none', skipped_reason=FOREIGN_FILE_REASON)
        else:
            to_set |= from_file
            merged = {**env, **to_set}
            status[family] = family_status(family, merged, 'file' if from_file else 'none')
    settings = (
        frozenset()
        if foreign
        else frozenset(k for k in file_values if is_setting(k) and k not in env)
    )
    to_set |= {k: file_values[k] for k in settings}
    return to_set, status, settings


def _expand_home(value: str, home: Path) -> Path:
    """Expand a leading ``~`` against the injected home directory."""
    if value == '~':
        return home
    if value.startswith('~/'):
        return home / value[2:]
    return Path(value)


def resolve_config_path(
    env: Mapping[str, str], home: Path, is_file: Callable[[Path], bool]
) -> tuple[ConfigSource, Path | None, tuple[Path, ...], str | None]:
    """Choose the env file for the MCP server. Never the CWD ``.env``.

    Order: ``UNIFI_CONFIG`` (no fall-through when it is missing), then
    ``$XDG_CONFIG_HOME/unifi_management_cli/{prod,default}.env``, then
    ``~/.config/unifi_management_cli/{prod,default}.env``, then the legacy
    ``~/.config/unifi_network_mapper/prod.env`` (with a deprecation warning).

    Args:
        env: The environment (only ``UNIFI_CONFIG`` and ``XDG_CONFIG_HOME`` are read).
        home: The user's home directory.
        is_file: Predicate telling whether a candidate path is a readable file.

    Returns:
        ``(source, path or None, paths tried, warning or None)``.
    """
    configured = env.get('UNIFI_CONFIG')
    if configured:
        path = _expand_home(configured, home)
        if is_file(path):
            return 'explicit', path, (path,), None
        return (
            'none',
            None,
            (path,),
            f'UNIFI_CONFIG={path} is not a readable file; no config file loaded '
            '(auto-discovery is skipped when UNIFI_CONFIG is set)',
        )

    candidates: list[tuple[ConfigSource, Path]] = []
    xdg = env.get('XDG_CONFIG_HOME')
    if xdg:
        candidates.extend(('xdg', Path(xdg) / CONFIG_DIR_NAME / n) for n in CONFIG_FILE_NAMES)
    home_dir = home / '.config' / CONFIG_DIR_NAME
    candidates.extend(('home', home_dir / n) for n in CONFIG_FILE_NAMES)
    candidates.append(('legacy', home / '.config' / LEGACY_CONFIG_DIR_NAME / 'prod.env'))

    tried: list[Path] = []
    for source, path in candidates:
        if path in tried:
            continue
        tried.append(path)
        if is_file(path):
            warning = None
            if source == 'legacy':
                warning = (
                    f'loading the legacy config {path}; move it to '
                    f'{home_dir / "prod.env"} (the legacy location is deprecated)'
                )
            return source, path, tuple(tried), warning
    return 'none', None, tuple(tried), None


def parse_env_file(text: str) -> tuple[dict[str, str], list[int]]:
    """Parse ``KEY=VALUE`` lines the way ``cli.load_env_from_config`` does.

    Blank lines and lines starting with ``#`` are skipped; key and value are stripped and
    surrounding quotes are removed from the value. A line without ``=`` or with an empty key
    is malformed.

    Args:
        text: The file's text.

    Returns:
        ``(values, malformed line numbers)``; line numbers are 1-based. Values are never
        reported for malformed lines.
    """
    values: dict[str, str] = {}
    bad: list[int] = []
    for line_num, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or not key:
            bad.append(line_num)
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values, bad


def _stderr_warning(message: str) -> None:
    """Write one warning line to stderr (never stdout, which may carry JSON-RPC)."""
    print(f'unifi-mcp: warning: {message}', file=sys.stderr)


def _readable_file(path: Path) -> bool:
    """Return True if ``path`` is a file this process can read."""
    return path.is_file() and os.access(path, os.R_OK)


class ConfigFileError(OSError):
    """An explicitly requested config file (``--config``) is missing or unreadable."""


def resolve_mcp_config(
    explicit: Path | None = None,
    env: MutableMapping[str, str] | None = None,
    home: Path | None = None,
    warn: Callable[[str], None] | None = None,
) -> ResolvedConfig:
    """Choose an env file, apply it to ``env`` per family and report what happened.

    Never reads a ``.env`` in the working directory.

    Args:
        explicit: ``--config PATH``; it must be a readable file.
        env: The environment to update; ``None`` means ``os.environ`` at call time.
        home: The home directory; ``None`` means ``Path.home()`` at call time.
        warn: Receives warning messages (no values); defaults to a stderr line.

    Returns:
        The resolved configuration (key names only).

    Raises:
        ConfigFileError: ``explicit`` is missing or unreadable.
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    warn = warn or _stderr_warning

    if explicit is not None:
        path = _expand_home(str(explicit), home)
        if not _readable_file(path):
            raise ConfigFileError(f'config file {path} is missing or unreadable')
        source: ConfigSource = 'explicit'
        found: Path | None = path
        tried: tuple[Path, ...] = (path,)
    else:
        source, found, tried, warning = resolve_config_path(env, home, _readable_file)
        if warning:
            warn(warning)

    file_values: dict[str, str] = {}
    if found is not None:
        try:
            text = found.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            if source == 'explicit' and explicit is not None:
                raise ConfigFileError(f'config file {found} is unreadable: {e}') from None
            warn(f'could not read {found} ({type(e).__name__}); no config file loaded')
            source, found = 'none', None
        else:
            file_values, bad = parse_env_file(text)
            for line_num in bad:
                warn(f'skipping malformed line {line_num} in {found}')

    to_set, families, settings = apply_file(env, file_values, explicit=source == 'explicit')
    if any(s.skipped_reason for s in families.values()):
        warn(
            f'not loading {found}: it describes a different controller than the one '
            f'exported by the MCP client; {FOREIGN_FILE_SUGGESTION}'
        )
    env.update(to_set)
    return ResolvedConfig(
        source=source,
        path=found,
        tried=tried,
        families=families,
        settings_from_file=settings,
    )
