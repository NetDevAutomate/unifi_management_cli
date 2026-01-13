"""Configuration models for UniFi Protect integration.

This module provides Pydantic models for configuring the UniFi Protect
client connection, including environment variable loading and validation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class ProtectConfig(BaseModel):
    """Configuration for connecting to a UniFi Protect controller.

    This model validates all configuration parameters required for establishing
    a connection to a UniFi Protect controller, including authentication
    credentials and connection settings.

    Attributes:
        host: The hostname or IP address of the UniFi Protect controller.
        port: The HTTPS port for the Protect API (default: 443).
        username: Username for authentication.
        password: Password for authentication (stored securely).
        verify_ssl: Whether to verify SSL certificates (default: False).
        ws_timeout: WebSocket connection timeout in seconds (default: 30).
        cache_dir: Optional directory for caching session data.
        store_sessions: Whether to persist sessions to disk (default: True).
        minimum_score: Minimum confidence score for smart detections (0-100).
        ignore_unadopted: Skip unadopted devices in responses (default: True).
        debug: Enable debug logging for the API client (default: False).

    Example:
        >>> config = ProtectConfig(
        ...     host="192.168.1.1",
        ...     username="admin",
        ...     password=SecretStr("password123")
        ... )
        >>> print(config.host)
        192.168.1.1
    """

    host: Annotated[str, Field(min_length=1, description='UniFi Protect controller host')]
    port: Annotated[int, Field(default=443, ge=1, le=65535, description='HTTPS port')]
    username: Annotated[str, Field(min_length=1, description='Authentication username')]
    password: Annotated[SecretStr, Field(description='Authentication password')]
    verify_ssl: Annotated[bool, Field(default=False, description='Verify SSL certificates')]
    ws_timeout: Annotated[
        int, Field(default=30, ge=5, le=300, description='WebSocket timeout in seconds')
    ]
    cache_dir: Annotated[
        Path | None, Field(default=None, description='Directory for caching session data')
    ]
    store_sessions: Annotated[
        bool, Field(default=True, description='Persist sessions to disk')
    ]
    minimum_score: Annotated[
        int, Field(default=0, ge=0, le=100, description='Min smart detection confidence')
    ]
    ignore_unadopted: Annotated[
        bool, Field(default=True, description='Skip unadopted devices')
    ]
    debug: Annotated[bool, Field(default=False, description='Enable debug logging')]

    model_config = {'extra': 'forbid', 'validate_assignment': True}

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate and normalize the host value.

        Args:
            v: The host string to validate.

        Returns:
            The normalized host string with protocol prefixes removed.

        Raises:
            ValueError: If the host is empty after normalization.
        """
        # Strip protocol prefixes if present
        normalized = v.strip()
        for prefix in ('https://', 'http://'):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        # Remove trailing slashes and ports
        normalized = normalized.rstrip('/').split(':')[0]
        if not normalized:
            raise ValueError('Host cannot be empty')
        return normalized

    @field_validator('cache_dir')
    @classmethod
    def validate_cache_dir(cls, v: Path | None) -> Path | None:
        """Validate that the cache directory exists or can be created.

        Args:
            v: The cache directory path to validate.

        Returns:
            The validated cache directory path, or None if not specified.

        Raises:
            ValueError: If the path exists but is not a directory.
        """
        if v is not None:
            if v.exists() and not v.is_dir():
                raise ValueError(f'Cache path exists but is not a directory: {v}')
        return v

    @model_validator(mode='after')
    def validate_authentication(self) -> ProtectConfig:
        """Validate that authentication credentials are provided.

        Returns:
            The validated configuration instance.

        Raises:
            ValueError: If username or password is missing.
        """
        if not self.username or not self.password:
            raise ValueError('Both username and password are required')
        return self

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
        prefix: str = 'PROTECT_',
    ) -> ProtectConfig:
        """Load configuration from environment variables.

        Reads configuration from environment variables with the specified prefix.
        Optionally loads variables from an env file first.

        Args:
            env_file: Optional path to an environment file to load.
            prefix: Environment variable prefix (default: 'PROTECT_').

        Returns:
            A ProtectConfig instance populated from environment variables.

        Raises:
            ValueError: If required environment variables are missing.

        Example:
            >>> # With environment variables:
            >>> # PROTECT_HOST=192.168.1.1
            >>> # PROTECT_USERNAME=admin
            >>> # PROTECT_PASSWORD=secret
            >>> config = ProtectConfig.from_env()
        """
        if env_file is not None:
            _load_env_file(Path(env_file))

        def get_env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f'{prefix}{key}', default)

        host = get_env('HOST')
        if not host:
            raise ValueError(f'{prefix}HOST environment variable is required')

        username = get_env('USERNAME')
        if not username:
            raise ValueError(f'{prefix}USERNAME environment variable is required')

        password = get_env('PASSWORD')
        if not password:
            raise ValueError(f'{prefix}PASSWORD environment variable is required')

        cache_dir_str = get_env('CACHE_DIR')
        cache_dir = Path(cache_dir_str) if cache_dir_str else None

        return cls(
            host=host,
            port=int(get_env('PORT', '443') or '443'),
            username=username,
            password=SecretStr(password),
            verify_ssl=(get_env('VERIFY_SSL', 'false') or 'false').lower() == 'true',
            ws_timeout=int(get_env('WS_TIMEOUT', '30') or '30'),
            cache_dir=cache_dir,
            store_sessions=(get_env('STORE_SESSIONS', 'true') or 'true').lower() == 'true',
            minimum_score=int(get_env('MINIMUM_SCORE', '0') or '0'),
            ignore_unadopted=(get_env('IGNORE_UNADOPTED', 'true') or 'true').lower() == 'true',
            debug=(get_env('DEBUG', 'false') or 'false').lower() == 'true',
        )

    def to_client_kwargs(self) -> dict[str, Any]:
        """Convert configuration to kwargs for ProtectApiClient.

        Returns:
            A dictionary of keyword arguments suitable for passing
            to the uiprotect ProtectApiClient constructor.

        Example:
            >>> config = ProtectConfig(...)
            >>> client = ProtectApiClient(**config.to_client_kwargs())
        """
        return {
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': self.password.get_secret_value(),
            'verify_ssl': self.verify_ssl,
            'ws_timeout': self.ws_timeout,
            'cache_dir': self.cache_dir,
            'store_sessions': self.store_sessions,
            'minimum_score': self.minimum_score,
            'ignore_unadopted': self.ignore_unadopted,
            'debug': self.debug,
        }


def _load_env_file(env_path: Path) -> None:
    """Load environment variables from a file.

    Parses a simple .env file format and sets environment variables.
    Lines starting with # are treated as comments. Empty lines are skipped.

    Args:
        env_path: Path to the environment file.

    Raises:
        FileNotFoundError: If the env file doesn't exist.
    """
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
