"""Credential chain authentication utilities."""

import asyncio
import json
import os
from pydantic import BaseModel, Field
from typing import Any
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from urllib.parse import urlparse


class Credentials(BaseModel):
    """UniFi controller credentials.

    Supports both token-based and username/password authentication.
    Token auth is preferred for UniFi OS controllers (UDM/UDR).
    """

    host: str = Field(description='Controller hostname or IP')
    port: int = Field(default=443, description='Controller port')
    username: str | None = Field(default=None, description='Admin username')
    password: str | None = Field(default=None, description='Admin password', repr=False)
    api_token: str | None = Field(
        default=None, description='API token for token-based auth', repr=False
    )
    site: str = Field(default='default', description='Site name')
    verify_ssl: bool = Field(default=False, description='Verify SSL certificate')

    @classmethod
    def from_env(cls) -> 'Credentials':
        """Load credentials from environment variables.

        Supports:
        - UNIFI_URL or UNIFI_HOST for controller address
        - UNIFI_CONSOLE_API_TOKEN or UNIFI_API_TOKEN for token auth
        - UNIFI_USERNAME and UNIFI_PASSWORD for password auth

        Token auth is preferred if token is provided.
        """
        # Support both UNIFI_URL (preferred) and UNIFI_HOST (legacy)
        url_or_host = os.environ.get('UNIFI_URL') or os.environ.get('UNIFI_HOST')

        if not url_or_host:
            raise ToolError(
                message='Missing UNIFI_URL or UNIFI_HOST environment variable',
                error_code=ErrorCodes.AUTHENTICATION_FAILED,
                suggestion='Set UNIFI_URL=https://your-controller-ip or UNIFI_HOST=your-controller-ip',
            )

        # Parse URL to extract host and port
        if url_or_host.startswith(('http://', 'https://')):
            parsed = urlparse(url_or_host)
            host = parsed.hostname or url_or_host
            port = parsed.port or 443
        else:
            host = url_or_host
            port = int(os.environ.get('UNIFI_PORT', '443'))

        # Get API token (supports multiple env var names)
        api_token = os.environ.get('UNIFI_CONSOLE_API_TOKEN') or os.environ.get('UNIFI_API_TOKEN')

        # Get username/password
        username = os.environ.get('UNIFI_USERNAME')
        password = os.environ.get('UNIFI_PASSWORD')

        # Validate: need either token OR (username AND password)
        if not api_token and not (username and password):
            raise ToolError(
                message='Must provide either API token or username/password',
                error_code=ErrorCodes.AUTHENTICATION_FAILED,
                suggestion='Set UNIFI_CONSOLE_API_TOKEN or both UNIFI_USERNAME and UNIFI_PASSWORD',
            )

        # Parse verify_ssl
        verify_ssl = os.environ.get('UNIFI_VERIFY_SSL', 'false').lower() == 'true'

        return cls(
            host=host,
            port=port,
            username=username,
            password=password,
            api_token=api_token,
            site=os.environ.get('UNIFI_SITE', 'default'),
            verify_ssl=verify_ssl,
        )

    @property
    def has_token(self) -> bool:
        """Check if token authentication is available."""
        return bool(self.api_token)

    @property
    def has_password(self) -> bool:
        """Check if password authentication is available."""
        return bool(self.username and self.password)

    @classmethod
    def from_keychain(cls, keychain_data: str) -> 'Credentials':
        """Load credentials from macOS Keychain JSON data."""
        try:
            data = json.loads(keychain_data)
            return cls(**data)
        except (json.JSONDecodeError, KeyError) as e:
            raise ToolError(
                message=f'Invalid keychain data: {e}',
                error_code=ErrorCodes.AUTHENTICATION_FAILED,
                suggestion='Verify keychain entry format: {"host": "...", "username": "...", "password": "..."}',
            )

    @classmethod
    def from_onepassword(cls, op_data: dict[str, Any]) -> 'Credentials':
        """Load credentials from 1Password CLI JSON data."""
        try:
            # 1Password CLI returns fields in different format
            fields = op_data.get('fields', [])
            field_map = {field['label'].lower(): field['value'] for field in fields}

            return cls(
                host=field_map['host'],
                username=field_map['username'],
                password=field_map['password'],
                site=field_map.get('site', 'default'),
                port=int(field_map.get('port', '443')),
            )
        except (KeyError, ValueError) as e:
            raise ToolError(
                message=f'Invalid 1Password data: {e}',
                error_code=ErrorCodes.AUTHENTICATION_FAILED,
                suggestion='Ensure 1Password item has fields: host, username, password',
            )


async def get_credentials() -> Credentials:
    """Get UniFi credentials using fallback chain: Environment → Keychain → 1Password CLI.

    Returns:
        Credentials object with connection details

    Raises:
        ToolError: If no credentials can be found from any source
    """
    methods_tried = []

    # 1. Environment variables (highest priority)
    try:
        return Credentials.from_env()
    except ToolError:
        methods_tried.append('Environment variables (UNIFI_*)')

    # 2. macOS Keychain via keyring
    try:
        import keyring

        keychain_data = keyring.get_password('unifi-mcp', 'controller')
        if keychain_data:
            return Credentials.from_keychain(keychain_data)
        else:
            methods_tried.append('macOS Keychain (unifi-mcp service)')
    except ImportError:
        methods_tried.append('macOS Keychain (keyring not available)')
    except ToolError:
        methods_tried.append('macOS Keychain (invalid data)')

    # 3. 1Password CLI
    try:
        process = await asyncio.create_subprocess_exec(
            'op',
            'item',
            'get',
            'UniFi Controller',
            '--format',
            'json',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            op_data = json.loads(stdout.decode())
            return Credentials.from_onepassword(op_data)
        else:
            methods_tried.append(f'1Password CLI (exit code {process.returncode})')

    except (json.JSONDecodeError, FileNotFoundError, ToolError):
        methods_tried.append('1Password CLI (not available or invalid data)')

    # All methods failed
    raise ToolError(
        message='No credentials found from any source',
        error_code=ErrorCodes.AUTHENTICATION_FAILED,
        suggestion=(
            'Set credentials using one of these methods:\n'
            '1. Environment: UNIFI_HOST, UNIFI_USERNAME, UNIFI_PASSWORD\n'
            '2. Keychain: Use keyring.set_password("unifi-mcp", "controller", json_data)\n'
            '3. 1Password: Create item named "UniFi Controller" with host, username, password fields'
        ),
        related_tools=['find_device', 'get_network_topology'],
    )


async def clear_credentials_cache() -> None:
    """Clear any cached credentials (placeholder for future session management)."""
    # Future: Clear session tokens, reset authentication state
    pass
