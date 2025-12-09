#!/usr/bin/env python3
"""
Configuration management for UniFi Network Mapper.
Centralizes configuration loading and validation.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

log = logging.getLogger(__name__)


@dataclass
class UnifiConfig:
    """
    Centralized configuration with validation and output preferences.
    """
    base_url: str
    site: str = "default"
    api_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    verify_ssl: bool = False
    timeout: int = 10
    max_retries: int = 3
    retry_delay: float = 1.0

    # Output preferences (configurable defaults)
    default_format: str = "png"
    default_output_dir: Optional[str] = None
    default_diagram_dir: Optional[str] = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Validate base_url
        if not self.base_url:
            raise ValueError("base_url is required")

        if not (self.base_url.startswith('http://') or self.base_url.startswith('https://')):
            raise ValueError("base_url must start with http:// or https://")

        # Validate authentication
        if not self.api_token and not (self.username and self.password):
            raise ValueError("Either api_token or username+password required for authentication")

        # Clamp numeric values to safe ranges
        self.timeout = max(1, min(self.timeout, 300))  # 1-300 seconds
        self.max_retries = max(1, min(self.max_retries, 10))  # 1-10 retries
        self.retry_delay = max(0.1, min(self.retry_delay, 10.0))  # 0.1-10 seconds

        # Normalize base_url
        self.base_url = self.base_url.rstrip('/')

        # Normalize site
        self.site = self.site.strip() if self.site else "default"

    @classmethod
    def from_env(cls, env_file: str = ".env") -> "UnifiConfig":
        """
        Load configuration from environment file.

        Args:
            env_file: Path to environment file

        Returns:
            UnifiConfig instance

        Raises:
            ValueError: If required environment variables are missing
            FileNotFoundError: If env_file doesn't exist (when required vars missing)
        """
        env_path = Path(env_file)

        # Load .env file if it exists
        if env_path.exists():
            with env_path.open(encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    try:
                        key, val = line.split('=', 1)
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")
                    except ValueError:
                        log.warning(f"Invalid line in {env_file}:{line_num}: {line}")
                        continue

        # Check for required environment variable
        if 'UNIFI_URL' not in os.environ:
            raise ValueError(
                f"UNIFI_URL environment variable required. "
                f"{'Create ' + env_file if not env_path.exists() else 'Check ' + env_file}"
            )

        # Create config from environment
        return cls(
            base_url=os.environ['UNIFI_URL'],
            site=os.environ.get('UNIFI_SITE', 'default'),
            api_token=os.environ.get('UNIFI_CONSOLE_API_TOKEN'),
            username=os.environ.get('UNIFI_USERNAME'),
            password=os.environ.get('UNIFI_PASSWORD'),
            verify_ssl=os.environ.get('UNIFI_VERIFY_SSL', 'false').lower() == 'true',
            timeout=int(os.environ.get('UNIFI_TIMEOUT', '10')),
            max_retries=int(os.environ.get('UNIFI_MAX_RETRIES', '3')),
            retry_delay=float(os.environ.get('UNIFI_RETRY_DELAY', '1.0')),

            # Output preferences
            default_format=os.environ.get('UNIFI_DEFAULT_FORMAT', 'png'),
            default_output_dir=os.environ.get('UNIFI_OUTPUT_DIR'),
            default_diagram_dir=os.environ.get('UNIFI_DIAGRAM_DIR')
        )

    def to_dict(self) -> dict:
        """
        Export configuration as dictionary for API client initialization.

        Returns:
            Dictionary with all configuration values
        """
        return {
            'base_url': self.base_url,
            'site': self.site,
            'api_token': self.api_token,
            'username': self.username,
            'password': self.password,
            'verify_ssl': self.verify_ssl,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'default_format': self.default_format,
            'default_output_dir': self.default_output_dir,
            'default_diagram_dir': self.default_diagram_dir
        }
