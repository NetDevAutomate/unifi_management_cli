"""Unit tests for UniFi Protect configuration module.

Tests cover:
- ProtectConfig model validation
- Environment variable loading
- Host normalization
- Client kwargs generation
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr, ValidationError

from unifi_mapper.protect.config import ProtectConfig, _load_env_file


if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class TestProtectConfig:
    """Test suite for ProtectConfig Pydantic model."""

    def test_minimal_valid_config(self) -> None:
        """Test creating config with minimal required fields."""
        config = ProtectConfig(
            host='192.168.1.1',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'
        assert config.username == 'admin'
        assert config.password.get_secret_value() == 'password123'

    def test_all_fields_config(self) -> None:
        """Test creating config with all fields specified."""
        config = ProtectConfig(
            host='192.168.1.1',
            port=8443,
            username='admin',
            password=SecretStr('password123'),
            verify_ssl=True,
            ws_timeout=60,
            cache_dir=Path('/tmp/cache'),
            store_sessions=False,
            minimum_score=50,
            ignore_unadopted=False,
            debug=True,
        )

        assert config.port == 8443
        assert config.verify_ssl is True
        assert config.ws_timeout == 60
        assert config.cache_dir == Path('/tmp/cache')
        assert config.store_sessions is False
        assert config.minimum_score == 50
        assert config.ignore_unadopted is False
        assert config.debug is True

    def test_default_values(self) -> None:
        """Test that default values are applied correctly."""
        config = ProtectConfig(
            host='192.168.1.1',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.port == 443
        assert config.verify_ssl is False
        assert config.ws_timeout == 30
        assert config.cache_dir is None
        assert config.store_sessions is True
        assert config.minimum_score == 0
        assert config.ignore_unadopted is True
        assert config.debug is False

    def test_host_normalization_strips_https(self) -> None:
        """Test that https:// prefix is stripped from host."""
        config = ProtectConfig(
            host='https://192.168.1.1',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'

    def test_host_normalization_strips_http(self) -> None:
        """Test that http:// prefix is stripped from host."""
        config = ProtectConfig(
            host='http://192.168.1.1',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'

    def test_host_normalization_strips_trailing_slash(self) -> None:
        """Test that trailing slashes are stripped from host."""
        config = ProtectConfig(
            host='192.168.1.1/',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'

    def test_host_normalization_strips_port(self) -> None:
        """Test that port is stripped from host string."""
        config = ProtectConfig(
            host='192.168.1.1:443',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'

    def test_host_normalization_full_url(self) -> None:
        """Test normalization of full URL format."""
        config = ProtectConfig(
            host='https://192.168.1.1:443/',
            username='admin',
            password=SecretStr('password123'),
        )

        assert config.host == '192.168.1.1'

    def test_empty_host_raises_error(self) -> None:
        """Test that empty host raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='',
                username='admin',
                password=SecretStr('password123'),
            )

        assert 'host' in str(exc_info.value).lower()

    def test_empty_username_raises_error(self) -> None:
        """Test that empty username raises validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                username='',
                password=SecretStr('password123'),
            )

        assert 'username' in str(exc_info.value).lower()

    def test_port_below_range_raises_error(self) -> None:
        """Test that port below valid range raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                port=0,
                username='admin',
                password=SecretStr('password123'),
            )

        assert 'port' in str(exc_info.value).lower()

    def test_port_above_range_raises_error(self) -> None:
        """Test that port above valid range raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                port=70000,
                username='admin',
                password=SecretStr('password123'),
            )

        assert 'port' in str(exc_info.value).lower()

    def test_ws_timeout_below_range_raises_error(self) -> None:
        """Test that ws_timeout below valid range raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                username='admin',
                password=SecretStr('password123'),
                ws_timeout=1,
            )

        assert 'ws_timeout' in str(exc_info.value).lower()

    def test_minimum_score_above_range_raises_error(self) -> None:
        """Test that minimum_score above valid range raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                username='admin',
                password=SecretStr('password123'),
                minimum_score=150,
            )

        assert 'minimum_score' in str(exc_info.value).lower()

    def test_extra_fields_forbidden(self) -> None:
        """Test that extra fields are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ProtectConfig(
                host='192.168.1.1',
                username='admin',
                password=SecretStr('password123'),
                unknown_field='value',  # type: ignore
            )

        assert 'extra' in str(exc_info.value).lower()

    def test_to_client_kwargs(self) -> None:
        """Test conversion to client kwargs dictionary."""
        config = ProtectConfig(
            host='192.168.1.1',
            port=8443,
            username='admin',
            password=SecretStr('password123'),
            verify_ssl=True,
            ws_timeout=60,
            minimum_score=50,
        )

        kwargs = config.to_client_kwargs()

        assert kwargs['host'] == '192.168.1.1'
        assert kwargs['port'] == 8443
        assert kwargs['username'] == 'admin'
        assert kwargs['password'] == 'password123'  # Secret value exposed
        assert kwargs['verify_ssl'] is True
        assert kwargs['ws_timeout'] == 60
        assert kwargs['minimum_score'] == 50

    def test_password_not_exposed_in_repr(self) -> None:
        """Test that password is hidden in string representation."""
        config = ProtectConfig(
            host='192.168.1.1',
            username='admin',
            password=SecretStr('supersecret'),
        )

        repr_str = repr(config)

        assert 'supersecret' not in repr_str
        assert '**********' in repr_str or "SecretStr" in repr_str


class TestProtectConfigFromEnv:
    """Test suite for ProtectConfig.from_env() method."""

    def test_from_env_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from minimal environment variables."""
        monkeypatch.setenv('PROTECT_HOST', '192.168.1.1')
        monkeypatch.setenv('PROTECT_USERNAME', 'admin')
        monkeypatch.setenv('PROTECT_PASSWORD', 'password123')

        config = ProtectConfig.from_env()

        assert config.host == '192.168.1.1'
        assert config.username == 'admin'
        assert config.password.get_secret_value() == 'password123'

    def test_from_env_all_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from all environment variables."""
        monkeypatch.setenv('PROTECT_HOST', '192.168.1.1')
        monkeypatch.setenv('PROTECT_PORT', '8443')
        monkeypatch.setenv('PROTECT_USERNAME', 'admin')
        monkeypatch.setenv('PROTECT_PASSWORD', 'password123')
        monkeypatch.setenv('PROTECT_VERIFY_SSL', 'true')
        monkeypatch.setenv('PROTECT_WS_TIMEOUT', '60')
        monkeypatch.setenv('PROTECT_STORE_SESSIONS', 'false')
        monkeypatch.setenv('PROTECT_MINIMUM_SCORE', '50')
        monkeypatch.setenv('PROTECT_IGNORE_UNADOPTED', 'false')
        monkeypatch.setenv('PROTECT_DEBUG', 'true')

        config = ProtectConfig.from_env()

        assert config.port == 8443
        assert config.verify_ssl is True
        assert config.ws_timeout == 60
        assert config.store_sessions is False
        assert config.minimum_score == 50
        assert config.ignore_unadopted is False
        assert config.debug is True

    def test_from_env_custom_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config with custom environment variable prefix."""
        monkeypatch.setenv('MYAPP_HOST', '10.0.0.1')
        monkeypatch.setenv('MYAPP_USERNAME', 'user')
        monkeypatch.setenv('MYAPP_PASSWORD', 'pass')

        config = ProtectConfig.from_env(prefix='MYAPP_')

        assert config.host == '10.0.0.1'
        assert config.username == 'user'

    def test_from_env_missing_host_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing HOST variable raises error."""
        monkeypatch.setenv('PROTECT_USERNAME', 'admin')
        monkeypatch.setenv('PROTECT_PASSWORD', 'password123')
        monkeypatch.delenv('PROTECT_HOST', raising=False)

        with pytest.raises(ValueError) as exc_info:
            ProtectConfig.from_env()

        assert 'PROTECT_HOST' in str(exc_info.value)

    def test_from_env_missing_username_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing USERNAME variable raises error."""
        monkeypatch.setenv('PROTECT_HOST', '192.168.1.1')
        monkeypatch.setenv('PROTECT_PASSWORD', 'password123')
        monkeypatch.delenv('PROTECT_USERNAME', raising=False)

        with pytest.raises(ValueError) as exc_info:
            ProtectConfig.from_env()

        assert 'PROTECT_USERNAME' in str(exc_info.value)

    def test_from_env_missing_password_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that missing PASSWORD variable raises error."""
        monkeypatch.setenv('PROTECT_HOST', '192.168.1.1')
        monkeypatch.setenv('PROTECT_USERNAME', 'admin')
        monkeypatch.delenv('PROTECT_PASSWORD', raising=False)

        with pytest.raises(ValueError) as exc_info:
            ProtectConfig.from_env()

        assert 'PROTECT_PASSWORD' in str(exc_info.value)

    def test_from_env_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from an environment file."""
        env_file = tmp_path / '.env'
        env_file.write_text(
            """
PROTECT_HOST=192.168.1.1
PROTECT_USERNAME=admin
PROTECT_PASSWORD=password123
PROTECT_PORT=8443
"""
        )

        # Clear any existing env vars
        monkeypatch.delenv('PROTECT_HOST', raising=False)
        monkeypatch.delenv('PROTECT_USERNAME', raising=False)
        monkeypatch.delenv('PROTECT_PASSWORD', raising=False)

        config = ProtectConfig.from_env(env_file=env_file)

        assert config.host == '192.168.1.1'
        assert config.port == 8443


class TestLoadEnvFile:
    """Test suite for _load_env_file helper function."""

    def test_load_basic_env_file(self, tmp_path: Path) -> None:
        """Test loading a basic environment file."""
        env_file = tmp_path / '.env'
        env_file.write_text('KEY1=value1\nKEY2=value2')

        _load_env_file(env_file)

        assert os.environ.get('KEY1') == 'value1'
        assert os.environ.get('KEY2') == 'value2'

    def test_load_env_file_with_comments(self, tmp_path: Path) -> None:
        """Test that comments are ignored."""
        env_file = tmp_path / '.env'
        env_file.write_text('# This is a comment\nKEY=value\n# Another comment')

        _load_env_file(env_file)

        assert os.environ.get('KEY') == 'value'

    def test_load_env_file_with_empty_lines(self, tmp_path: Path) -> None:
        """Test that empty lines are ignored."""
        env_file = tmp_path / '.env'
        env_file.write_text('\n\nKEY=value\n\n')

        _load_env_file(env_file)

        assert os.environ.get('KEY') == 'value'

    def test_load_env_file_strips_quotes(self, tmp_path: Path) -> None:
        """Test that quotes are stripped from values."""
        env_file = tmp_path / '.env'
        env_file.write_text('KEY1="quoted value"\nKEY2=\'single quoted\'')

        _load_env_file(env_file)

        assert os.environ.get('KEY1') == 'quoted value'
        assert os.environ.get('KEY2') == 'single quoted'

    def test_load_env_file_not_found(self, tmp_path: Path) -> None:
        """Test that missing file raises FileNotFoundError."""
        env_file = tmp_path / 'nonexistent.env'

        with pytest.raises(FileNotFoundError):
            _load_env_file(env_file)

    def test_load_env_file_with_equals_in_value(self, tmp_path: Path) -> None:
        """Test that values containing equals signs are handled correctly."""
        env_file = tmp_path / '.env'
        env_file.write_text('CONNECTION_STRING=host=localhost;port=5432')

        _load_env_file(env_file)

        assert os.environ.get('CONNECTION_STRING') == 'host=localhost;port=5432'
