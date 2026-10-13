"""Configuration models for UniFi Network API integration.

This module provides Pydantic models for configuring the UniFi Network
API client connection, including environment variable loading and validation.

The ``network_api`` family can stand on the controller's own config (issue 037):

* ``UNIFI_NETWORK_HOST`` unset: the host, port and scheme come from ``UNIFI_URL`` (or
  ``UNIFI_HOST``/``UNIFI_PORT``), normalised.
* ``UNIFI_NETWORK_SITE_ID`` unset: the config carries ``site_name`` (``UNIFI_SITE``, default
  ``default``) and the client resolves the id at first call from one ``GET /v1/sites``
  matched on ``internalReference``, cached for the process.
* ``UNIFI_NETWORK_API_KEY`` unset: ``UNIFI_CONSOLE_API_TOKEN`` stands in **only** when the
  network host's origin (scheme, host, port) equals ``UNIFI_URL``'s; the console token is
  never sent to another origin. Explicit keys always win.

:func:`resolve_network_env` is the offline view of that derivation; the MCP readiness report
uses it so ``--check`` never contacts the controller.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from typing import Annotated, Literal
from urllib.parse import urlsplit


# Ubiquiti's Network API spec gives the server as .../proxy/network/integration; Network 10.6
# also answers on the undocumented plural. The client probes ``{base}/v1/info`` in this order
# and uses the first base that does not 404, as port_diagnostics does (issue 003).
INTEGRATION_BASES: tuple[str, ...] = ('/proxy/network/integration', '/proxy/network/integrations')

NETWORK_PREFIX = 'UNIFI_NETWORK_'
CONSOLE_TOKEN_VAR = 'UNIFI_CONSOLE_API_TOKEN'
DEFAULT_SITE_NAME = 'default'  # the controller family's default too (Credentials.from_env)
_DEFAULT_PORTS = {'https': 443, 'http': 80}

# The deferred-resolution notes --check and the readiness report show, word for word.
HOST_DERIVED_NOTE = 'host: derived from UNIFI_URL'
SITE_DEFERRED_NOTE = 'site id: resolved at first call'
KEY_CONSOLE_NOTE = 'key: console token (same origin)'


@dataclass(frozen=True)
class Origin:
    """A normalised ``(scheme, host, port)``; two configs with equal origins name one server."""

    scheme: str
    host: str
    port: int


def _split_origin(value: str, default_scheme: str = 'https') -> tuple[str, str, int | None] | None:
    """Split a URL, ``host``, ``host:port`` or ``scheme://host[:port]`` into its parts.

    Returns ``(scheme, host, explicit port or None)``, lower-cased, or ``None`` when there is
    no usable host or the scheme is not http(s).
    """
    text = value.strip()
    if not text:
        return None
    if '://' not in text:
        text = f'{default_scheme}://{text}'
    parts = urlsplit(text)
    scheme = (parts.scheme or default_scheme).lower()
    host = (parts.hostname or '').strip().lower()
    if not host or scheme not in _DEFAULT_PORTS:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    return scheme, host, port


def _origin(value: str, port_var: str | None) -> Origin | None:
    """Build an origin from ``value``.

    A port in the value wins, then ``port_var`` when it is digits, then the scheme's default.
    """
    split = _split_origin(value)
    if split is None:
        return None
    scheme, host, port = split
    if port is None and port_var and port_var.strip().isdigit():
        port = int(port_var.strip())
    return Origin(scheme, host, port or _DEFAULT_PORTS[scheme])


def controller_origin(env: Mapping[str, str]) -> Origin | None:
    """Return the controller's origin from ``UNIFI_URL``, else ``UNIFI_HOST``/``UNIFI_PORT``.

    Args:
        env: The environment to read.

    Returns:
        The origin, or ``None`` when neither variable names a host.
    """
    url = env.get('UNIFI_URL')
    if url and url.strip():
        return _origin(url, None)
    host = env.get('UNIFI_HOST')
    if host and host.strip():
        return _origin(host, env.get('UNIFI_PORT'))
    return None


def network_origin(env: Mapping[str, str], prefix: str = NETWORK_PREFIX) -> Origin | None:
    """Return the Integration API's origin: ``UNIFI_NETWORK_HOST``/``PORT``, else the controller's.

    Args:
        env: The environment to read.
        prefix: The family's variable prefix.

    Returns:
        The origin the network client would connect to, or ``None`` when no host is known.
    """

    def get_env(key: str) -> str | None:
        return env.get(f'{prefix}{key}')

    host = get_env('HOST')
    if host and host.strip():
        return _origin(host, get_env('PORT'))
    return controller_origin(env)


@dataclass(frozen=True)
class NetworkEnvResolution:
    """What the ``network_api`` family resolves to from an environment, offline.

    ``missing`` names what no variable supplies; ``derived`` carries the deferred-resolution
    notes for ``--check``. The key value is kept out of ``repr``.
    """

    origin: Origin | None
    host_derived: bool
    site_id: str | None
    site_name: str | None
    api_key: str | None = field(repr=False)
    api_key_source: Literal['network', 'console'] | None
    missing: tuple[str, ...]
    derived: tuple[str, ...]


def resolve_network_env(
    env: Mapping[str, str], prefix: str = NETWORK_PREFIX
) -> NetworkEnvResolution:
    """Resolve the ``network_api`` family from ``env`` without any I/O.

    Args:
        env: The environment to read.
        prefix: The family's variable prefix.

    Returns:
        The resolution; ``missing == ()`` means :meth:`NetworkConfig.from_env` would succeed.
    """
    missing: list[str] = []

    def get_env(key: str) -> str | None:
        return env.get(f'{prefix}{key}')

    explicit_host = bool((get_env('HOST') or '').strip())
    origin = network_origin(env, prefix)
    host_derived = origin is not None and not explicit_host
    if origin is None:
        missing.append(f'{prefix}HOST or UNIFI_URL')

    api_key = (get_env('API_KEY') or '').strip() or None
    api_key_source: Literal['network', 'console'] | None = 'network' if api_key else None
    if api_key is None:
        token = (env.get(CONSOLE_TOKEN_VAR) or '').strip()
        console = controller_origin(env)
        if token and origin is not None and console is not None and origin == console:
            api_key, api_key_source = token, 'console'
        elif token and origin is not None:
            missing.append(f'{prefix}API_KEY ({CONSOLE_TOKEN_VAR} is not for this origin)')
        else:
            missing.append(f'{prefix}API_KEY or {CONSOLE_TOKEN_VAR} (same origin)')

    site_id = (get_env('SITE_ID') or '').strip() or None
    site_name: str | None = None
    if site_id is None:
        if origin is None:
            missing.append(f'{prefix}SITE_ID or UNIFI_SITE')
        else:
            site_name = (env.get('UNIFI_SITE') or '').strip() or DEFAULT_SITE_NAME

    derived = tuple(
        note
        for note, applies in (
            (HOST_DERIVED_NOTE, host_derived),
            (SITE_DEFERRED_NOTE, site_name is not None),
            (KEY_CONSOLE_NOTE, api_key_source == 'console'),  # pragma: allowlist secret
        )
        if applies
    )

    return NetworkEnvResolution(
        origin=origin,
        host_derived=host_derived,
        site_id=site_id,
        site_name=site_name,
        api_key=api_key,
        api_key_source=api_key_source,
        missing=tuple(missing),
        derived=derived,
    )


class NetworkConfig(BaseModel):
    """Configuration for connecting to a UniFi Network controller.

    This model validates all configuration parameters required for establishing
    a connection to a UniFi Network controller via the official API.

    Attributes:
        host: The hostname or IP address of the UniFi Network controller.
        port: The HTTPS port for the Network API (default: 443).
        scheme: ``https`` (default) or ``http``, as ``UNIFI_URL`` has it when derived.
        api_key: API key for authentication (generated in UniFi Integrations), or the
            console token when ``api_key_source`` is ``console`` (same origin only).
        api_key_source: Where the key came from: the family's own variable or the
            controller's console token.
        site_id: The site UUID to operate on, or ``None`` to resolve it at first call from
            ``site_name`` (one ``GET /v1/sites``, cached for the process).
        site_name: The legacy site name (``UNIFI_SITE``) to match on ``internalReference``
            when ``site_id`` is ``None``.
        verify_ssl: Whether to verify SSL certificates (default: False).
        timeout: HTTP request timeout in seconds (default: 30).
        debug: Enable debug logging for the API client (default: False).

    Example:
        >>> config = NetworkConfig(
        ...     host='192.0.2.1',
        ...     api_key=SecretStr('your-api-key'),
        ...     site_id='550e8400-e29b-41d4-a716-446655440000',
        ... )
    """

    host: Annotated[str, Field(min_length=1, description='UniFi Network controller host')]
    port: Annotated[int, Field(default=443, ge=1, le=65535, description='HTTPS port')]
    scheme: Annotated[Literal['https', 'http'], Field(default='https', description='URL scheme')]
    api_key: Annotated[SecretStr, Field(description='API key for authentication')]
    api_key_source: Annotated[
        Literal['network', 'console'],
        Field(default='network', description='Where the key is from'),
    ]
    site_id: Annotated[str | None, Field(default=None, description='Site UUID')]
    site_name: Annotated[
        str | None, Field(default=None, description='Site name to resolve the UUID from')
    ]
    verify_ssl: Annotated[bool, Field(default=False, description='Verify SSL certificates')]
    timeout: Annotated[
        int, Field(default=30, ge=5, le=300, description='Request timeout in seconds')
    ]
    debug: Annotated[bool, Field(default=False, description='Enable debug logging')]

    model_config = {'extra': 'forbid', 'validate_assignment': True}

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate and normalize the host value."""
        normalized = v.strip()
        for prefix in ('https://', 'http://'):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        normalized = normalized.rstrip('/').split(':')[0]
        if not normalized:
            raise ValueError('Host cannot be empty')
        return normalized

    @field_validator('site_id')
    @classmethod
    def validate_site_id(cls, v: str | None) -> str | None:
        """Validate site_id format (UUID); ``None`` defers the lookup to ``site_name``."""
        if v is None:
            return None
        v = v.strip()
        # Basic UUID format validation
        parts = v.split('-')
        if len(parts) == 5 and all(len(p) in (8, 4, 4, 4, 12) for p in parts):
            return v.lower()
        # Also accept without dashes
        if len(v) == 32 and all(c in '0123456789abcdefABCDEF' for c in v):
            return v.lower()
        raise ValueError(f'Invalid site_id format: {v}')

    @model_validator(mode='after')
    def validate_config(self) -> NetworkConfig:
        """Validate that required fields are provided."""
        if not self.api_key.get_secret_value():
            raise ValueError('API key is required')
        if self.site_id is None and not (self.site_name or '').strip():
            raise ValueError('site_id or site_name is required')
        return self

    @property
    def base_url(self) -> str:
        """Get the base URL for API requests."""
        return f'{self.scheme}://{self.host}:{self.port}'

    @property
    def origin(self) -> Origin:
        """The normalised origin this config connects to."""
        return Origin(self.scheme, self.host.lower(), self.port)

    @property
    def api_base_url(self) -> str:
        """Get the documented base URL for the Network Integration API.

        This is ``{base_url}{INTEGRATION_BASES[0]}/v1``. ``UniFiNetworkClient`` tries it
        first and falls back to the plural base on a 404 (``client.base_path_used`` says
        which one answered).
        """
        return f'{self.base_url}{INTEGRATION_BASES[0]}/v1'

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        prefix: str = 'UNIFI_NETWORK_',
    ) -> NetworkConfig:
        """Load configuration from environment variables.

        Args:
            env_file: Optional path to an environment file to load.
            prefix: Environment variable prefix (default: 'UNIFI_NETWORK_').

        Returns:
            A NetworkConfig instance populated from environment variables.

        With ``UNIFI_NETWORK_HOST``, ``UNIFI_NETWORK_API_KEY`` and ``UNIFI_NETWORK_SITE_ID`` all
        set, nothing is derived. Otherwise the controller's config stands in (issue 037): the
        host from ``UNIFI_URL``, the site id from ``UNIFI_SITE`` at first call, and the console
        token as the key only when the network host is ``UNIFI_URL``'s own origin.

        Raises:
            ValueError: If required environment variables are missing (the message names the
                family's variable and what could have stood in for it).

        Example:
            >>> # With environment variables:
            >>> # UNIFI_NETWORK_HOST=192.0.2.1
            >>> # UNIFI_NETWORK_API_KEY=your-api-key
            >>> # UNIFI_NETWORK_SITE_ID=site-uuid
            >>> config = NetworkConfig.from_env()
        """
        if env_file is not None:
            _load_env_file(Path(env_file))

        def get_env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f'{prefix}{key}', default)

        resolution = resolve_network_env(os.environ, prefix)
        if resolution.origin is None:
            raise ValueError(
                f'{prefix}HOST environment variable is required '
                '(or UNIFI_URL, which the Network API host is derived from)'
            )
        if resolution.api_key is None:
            why = (
                f'{CONSOLE_TOKEN_VAR} stands in only when {prefix}HOST is the same origin as '
                'UNIFI_URL; the console token is never sent to another origin'
            )
            raise ValueError(f'{prefix}API_KEY environment variable is required ({why})')

        return cls(
            host=resolution.origin.host,
            port=resolution.origin.port,
            scheme=resolution.origin.scheme,  # type: ignore[arg-type]  # _DEFAULT_PORTS keys
            api_key=SecretStr(resolution.api_key),
            api_key_source=resolution.api_key_source or 'network',
            site_id=resolution.site_id,
            site_name=resolution.site_name,
            verify_ssl=(get_env('VERIFY_SSL', 'false') or 'false').lower() == 'true',
            timeout=int(get_env('TIMEOUT', '30') or '30'),
            debug=(get_env('DEBUG', 'false') or 'false').lower() == 'true',
        )

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests."""
        return {
            'X-API-KEY': self.api_key.get_secret_value(),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }


def _load_env_file(env_path: Path) -> None:
    """Load environment variables from a file."""
    if not env_path.exists():
        raise FileNotFoundError(f'Environment file not found: {env_path}')

    with env_path.open(encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ[key] = value
