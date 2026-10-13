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

import asyncio
import concurrent.futures
import math
import os
import sys
import threading
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from loguru import logger
from pathlib import Path
from typing import Any, Literal
from unifi_mapper.core.utils import auth
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.envfile import parse_env_value
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.mcp.call_audit import CALL_AUDIT_ENV, CallAuditSetting, parse_call_audit


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
        values[key] = parse_env_value(value)
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


# --- server settings (design §2.12) ---------------------------------------------------


@dataclass(frozen=True)
class ServerSettings:
    """Validated ``UNIFI_MCP_*`` settings. An invalid value falls back to its default."""

    log_level: str = 'WARNING'
    credential_timeout: float = 15.0
    max_concurrency: int = 4
    # UNIFI_MCP_TOOL_TIMEOUT: the per-call deadline, 270 s by default (issue 012 D11): above
    # any fleet read and the 100 s counter-sampling window, and 30 s below the 300 s the
    # guide's client snippets allow, so a wedged controller is [TIMEOUT] before the client
    # gives up. None (programmatic only; the variable cannot unset it) means no deadline.
    tool_timeout: float | None = 270.0
    # UNIFI_MCP_CALL_AUDIT: the call log is on by default (issue 013 D5).
    call_audit: CallAuditSetting = CallAuditSetting('default')


def _bounded_number(
    env: Mapping[str, str],
    key: str,
    parse: Callable[[str], float],
    low: float,
    high: float,
    warn: Callable[[str], None],
) -> float | None:
    """Return ``env[key]`` parsed and within ``[low, high]``, or None (warned) if invalid."""
    raw = env.get(key)
    if raw is None or raw.strip() == '':
        return None
    try:
        value = parse(raw.strip())
    except ValueError:
        value = math.nan
    if math.isfinite(value) and low <= value <= high:
        return value
    warn(f'{key}={raw!r} is not a number in {low:g}-{high:g}; using the default')
    return None


def load_server_settings(
    env: Mapping[str, str] | None = None, warn: Callable[[str], None] | None = None
) -> ServerSettings:
    """Read and validate the server's ``UNIFI_MCP_*`` settings.

    Args:
        env: The environment; ``None`` means ``os.environ`` at call time.
        warn: Receives one message per invalid value; defaults to a stderr line.

    Returns:
        The settings, with defaults for unset or invalid values.
    """
    env = os.environ if env is None else env
    warn = warn or _stderr_warning
    defaults = ServerSettings()

    log_level = defaults.log_level
    raw_level = env.get('UNIFI_MCP_LOG_LEVEL')
    if raw_level and raw_level.strip():
        candidate = raw_level.strip().upper()
        try:
            logger.level(candidate)
        except ValueError:
            warn(f'UNIFI_MCP_LOG_LEVEL={raw_level!r} is not a log level; using WARNING')
        else:
            log_level = candidate

    credential_timeout = _bounded_number(env, 'UNIFI_MCP_CREDENTIAL_TIMEOUT', float, 1, 120, warn)
    tool_timeout = _bounded_number(env, 'UNIFI_MCP_TOOL_TIMEOUT', float, 5, 3600, warn)
    max_concurrency = _bounded_number(env, 'UNIFI_MCP_MAX_CONCURRENCY', int, 1, 32, warn)
    call_audit = parse_call_audit(env.get(CALL_AUDIT_ENV), warn)
    return ServerSettings(
        log_level=log_level,
        credential_timeout=(
            defaults.credential_timeout if credential_timeout is None else credential_timeout
        ),
        max_concurrency=(
            defaults.max_concurrency if max_concurrency is None else int(max_concurrency)
        ),
        tool_timeout=defaults.tool_timeout if tool_timeout is None else tool_timeout,
        call_audit=call_audit,
    )


# --- bounded controller credential lookup (design §2.8) -------------------------------

RETRY_AFTER_S = 60.0
NO_CREDENTIALS_MESSAGE = 'No credentials found from any source'
CONFIG_MISSING_SUGGESTION = (
    'set UNIFI_CONFIG=/path/prod.env or export UNIFI_URL + UNIFI_CONSOLE_API_TOKEN'
)


class CredentialsMissingError(ToolError):
    """Controller credentials are not configured, or the lookup did not finish in time."""

    def __init__(
        self,
        message: str,
        suggestion: str | None = CONFIG_MISSING_SUGGESTION,
        tried: Sequence[Path] = (),
    ) -> None:
        """Build a ``CONFIG_MISSING`` error naming the files tried (paths, never values).

        Args:
            message: What is missing.
            suggestion: How to fix it.
            tried: Config files that were looked for.
        """
        if tried:
            message = f'{message} (tried {", ".join(str(p) for p in tried)})'
        super().__init__(
            message=message, error_code=ErrorCodes.CONFIG_MISSING, suggestion=suggestion
        )


class _Lookup(concurrent.futures.Future[Credentials]):
    """A future that records when its lookup finished (for the retry interval)."""

    finished_at: float | None = None


_pending: concurrent.futures.Future[Credentials] | None = None


def _now() -> float:
    """Return a monotonic clock reading (a seam for tests)."""
    return time.monotonic()


def _submit_daemon(fn: Callable[[], Credentials]) -> concurrent.futures.Future[Credentials]:
    """Run fn on a daemon thread so a pending Keychain prompt never blocks process exit.

    Args:
        fn: The blocking lookup.

    Returns:
        A future that receives fn's result or exception.
    """
    fut = _Lookup()

    def _run() -> None:
        if not fut.set_running_or_notify_cancel():
            return
        try:
            result = fn()
        except BaseException as e:  # noqa: BLE001 - delivered to the awaiting caller
            fut.finished_at = _now()
            fut.set_exception(e)
        else:
            fut.finished_at = _now()
            fut.set_result(result)

    threading.Thread(target=_run, name='unifi-cred', daemon=True).start()
    return fut


def _resolve_blocking() -> Credentials:
    """Run the credential chain on its own event loop (called on the daemon thread)."""
    # Module-attribute call (auth.get_credentials), so the test guard patches one name.
    return asyncio.run(auth.get_credentials())


def _should_retry(fut: concurrent.futures.Future[Credentials]) -> bool:
    """Return True if a finished, failed lookup is old enough to be re-submitted."""
    if fut.cancelled():
        return True
    if not fut.done() or fut.exception() is None:
        return False
    finished = getattr(fut, 'finished_at', None)
    return finished is None or _now() - finished >= RETRY_AFTER_S


async def ensure_controller_credentials(timeout: float, tried: Sequence[Path] = ()) -> None:
    """Raise CredentialsMissingError unless controller credentials resolve within timeout.

    Returns at once when the environment already holds controller credentials. Otherwise
    the credential chain (Keychain, then 1Password) runs on a daemon thread, at most one
    at a time; the event loop stays responsive while it waits. A lookup that times out
    keeps running, so a later call can use its result. On success the credentials are
    written to ``os.environ`` (:func:`apply_credentials_to_env`).

    Args:
        timeout: Seconds to wait for the lookup.
        tried: Config files that were looked for, named in the error.

    Raises:
        CredentialsMissingError: Nothing found, the lookup is still running, or the
            credentials found are for a different controller than the one exported.
        ToolError: Any other domain error from the credential chain, unchanged.
    """
    global _pending
    if controller_ready(os.environ):
        return
    if _pending is None or _should_retry(_pending):
        _pending = _submit_daemon(_resolve_blocking)
    try:
        creds = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(_pending)), timeout)
    except TimeoutError:
        raise CredentialsMissingError(
            f'credential lookup still running after {timeout:g}s '
            '(Keychain/1Password may be waiting for approval); retry shortly',
            suggestion=None,
        ) from None
    except ToolError as e:
        if e.message == NO_CREDENTIALS_MESSAGE:
            raise CredentialsMissingError(
                'no controller credentials in the environment, the config file, the '
                'Keychain or 1Password',
                tried=tried,
            ) from None
        raise
    apply_credentials_to_env(creds)  # controller family, atomically


def apply_credentials_to_env(
    creds: Credentials, env: MutableMapping[str, str] | None = None
) -> None:
    """Write resolved controller credentials under the keys ``Credentials.from_env`` reads.

    Never mixes controllers: with no controller key exported, every resolved key is
    written. With some exported, the credentials are applied only when their host
    equals the exported host (normalised); missing keys are then filled and exported
    ones kept. Otherwise nothing is written.

    Args:
        creds: Credentials from the Keychain or 1Password.
        env: The environment to update; ``None`` means ``os.environ`` at call time.

    Raises:
        CredentialsMissingError: The credentials are for a different controller.
    """
    env = os.environ if env is None else env
    resolved = {
        'UNIFI_HOST': creds.host,
        'UNIFI_PORT': str(creds.port),
        'UNIFI_SITE': creds.site,
        'UNIFI_VERIFY_SSL': 'true' if creds.verify_ssl else 'false',
    }
    if creds.api_token:
        resolved['UNIFI_CONSOLE_API_TOKEN'] = creds.api_token
    if creds.username:
        resolved['UNIFI_USERNAME'] = creds.username
    if creds.password:
        resolved['UNIFI_PASSWORD'] = creds.password

    if not any(k in CONTROLLER_KEYS for k in env):
        env.update(resolved)
        return
    if family_host('controller', env) != normalise_host(creds.host):
        raise CredentialsMissingError(
            'Keychain/1Password credentials are for a different controller than UNIFI_URL',
            suggestion='set UNIFI_CONFIG or export a token',
        )
    for key, value in resolved.items():
        if not env.get(key):
            env[key] = value
