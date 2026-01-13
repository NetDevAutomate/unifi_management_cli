"""Configuration models for UniFi Network API integration.

This module provides Pydantic models for configuring the UniFi Network
API client connection, including environment variable loading and validation.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from typing import Annotated


class NetworkConfig(BaseModel):
    """Configuration for connecting to a UniFi Network controller.

    This model validates all configuration parameters required for establishing
    a connection to a UniFi Network controller via the official API.

    Attributes:
        host: The hostname or IP address of the UniFi Network controller.
        port: The HTTPS port for the Network API (default: 443).
        api_key: API key for authentication (generated in UniFi Integrations).
        site_id: The site UUID to operate on.
        verify_ssl: Whether to verify SSL certificates (default: False).
        timeout: HTTP request timeout in seconds (default: 30).
        debug: Enable debug logging for the API client (default: False).

    Example:
        >>> config = NetworkConfig(
        ...     host="192.168.1.1",
        ...     api_key=SecretStr("your-api-key"),
        ...     site_id="550e8400-e29b-41d4-a716-446655440000"
        ... )
    """

    host: Annotated[str, Field(min_length=1, description='UniFi Network controller host')]
    port: Annotated[int, Field(default=443, ge=1, le=65535, description='HTTPS port')]
    api_key: Annotated[SecretStr, Field(description='API key for authentication')]
    site_id: Annotated[str, Field(min_length=1, description='Site UUID')]
    verify_ssl: Annotated[bool, Field(default=False, description='Verify SSL certificates')]
    timeout: Annotated[int, Field(default=30, ge=5, le=300, description='Request timeout in seconds')]
    debug: Annotated[bool, Field(default=False, description='Enable debug logging')]

    model_config = {'extra': 'forbid', 'validate_assignment': True}

    @field_validator('host')
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Validate and normalize the host value."""
        normalized = v.strip()
        for prefix in ('https://', 'http://'):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix):]
                break
        normalized = normalized.rstrip('/').split(':')[0]
        if not normalized:
            raise ValueError('Host cannot be empty')
        return normalized

    @field_validator('site_id')
    @classmethod
    def validate_site_id(cls, v: str) -> str:
        """Validate site_id format (UUID)."""
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
        return self

    @property
    def base_url(self) -> str:
        """Get the base URL for API requests."""
        return f"https://{self.host}:{self.port}"

    @property
    def api_base_url(self) -> str:
        """Get the base URL for the Network API."""
        return f"{self.base_url}/proxy/network/integrations/v1"

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

        Raises:
            ValueError: If required environment variables are missing.

        Example:
            >>> # With environment variables:
            >>> # UNIFI_NETWORK_HOST=192.168.1.1
            >>> # UNIFI_NETWORK_API_KEY=your-api-key
            >>> # UNIFI_NETWORK_SITE_ID=site-uuid
            >>> config = NetworkConfig.from_env()
        """
        if env_file is not None:
            _load_env_file(Path(env_file))

        def get_env(key: str, default: str | None = None) -> str | None:
            return os.environ.get(f'{prefix}{key}', default)

        host = get_env('HOST')
        if not host:
            raise ValueError(f'{prefix}HOST environment variable is required')

        api_key = get_env('API_KEY')
        if not api_key:
            raise ValueError(f'{prefix}API_KEY environment variable is required')

        site_id = get_env('SITE_ID')
        if not site_id:
            raise ValueError(f'{prefix}SITE_ID environment variable is required')

        return cls(
            host=host,
            port=int(get_env('PORT', '443') or '443'),
            api_key=SecretStr(api_key),
            site_id=site_id,
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
