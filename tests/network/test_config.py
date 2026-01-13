"""Tests for NetworkConfig."""

from __future__ import annotations

import os
import pytest
from pydantic import SecretStr
from tempfile import NamedTemporaryFile
from unifi_mapper.network.config import NetworkConfig


class TestNetworkConfig:
    """Tests for NetworkConfig model."""

    def test_valid_config(self) -> None:
        """Test creating a valid config."""
        config = NetworkConfig(
            host='192.168.1.1',
            api_key=SecretStr('test-api-key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )

        assert config.host == '192.168.1.1'
        assert config.port == 443
        assert config.api_key.get_secret_value() == 'test-api-key'
        assert config.site_id == '550e8400-e29b-41d4-a716-446655440000'
        assert config.verify_ssl is False
        assert config.timeout == 30
        assert config.debug is False

    def test_host_normalization(self) -> None:
        """Test host value normalization."""
        # Strip https prefix
        config = NetworkConfig(
            host='https://192.168.1.1',
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.host == '192.168.1.1'

        # Strip http prefix
        config = NetworkConfig(
            host='http://192.168.1.1',
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.host == '192.168.1.1'

        # Strip trailing slash
        config = NetworkConfig(
            host='192.168.1.1/',
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.host == '192.168.1.1'

    def test_site_id_validation(self) -> None:
        """Test site_id format validation."""
        # Valid UUID with dashes
        config = NetworkConfig(
            host='192.168.1.1',
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.site_id == '550e8400-e29b-41d4-a716-446655440000'

        # Valid UUID without dashes
        config = NetworkConfig(
            host='192.168.1.1',
            api_key=SecretStr('key'),
            site_id='550e8400e29b41d4a716446655440000',
        )
        assert config.site_id == '550e8400e29b41d4a716446655440000'

        # Invalid UUID format
        with pytest.raises(ValueError, match='Invalid site_id format'):
            NetworkConfig(
                host='192.168.1.1',
                api_key=SecretStr('key'),
                site_id='invalid-uuid',
            )

    def test_empty_host_rejected(self) -> None:
        """Test that empty host is rejected."""
        with pytest.raises(ValueError):
            NetworkConfig(
                host='',
                api_key=SecretStr('key'),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )

    def test_empty_api_key_rejected(self) -> None:
        """Test that empty API key is rejected."""
        with pytest.raises(ValueError, match='API key is required'):
            NetworkConfig(
                host='192.168.1.1',
                api_key=SecretStr(''),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )

    def test_base_url_property(self) -> None:
        """Test base_url property."""
        config = NetworkConfig(
            host='192.168.1.1',
            port=8443,
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.base_url == 'https://192.168.1.1:8443'

    def test_api_base_url_property(self) -> None:
        """Test api_base_url property."""
        config = NetworkConfig(
            host='192.168.1.1',
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.api_base_url == 'https://192.168.1.1:443/proxy/network/integrations/v1'

    def test_get_headers(self) -> None:
        """Test HTTP headers generation."""
        config = NetworkConfig(
            host='192.168.1.1',
            api_key=SecretStr('test-api-key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        headers = config.get_headers()

        assert headers['X-API-KEY'] == 'test-api-key'
        assert headers['Accept'] == 'application/json'
        assert headers['Content-Type'] == 'application/json'

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from environment variables."""
        monkeypatch.setenv('UNIFI_NETWORK_HOST', '192.168.1.1')
        monkeypatch.setenv('UNIFI_NETWORK_API_KEY', 'env-api-key')
        monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', '550e8400-e29b-41d4-a716-446655440000')
        monkeypatch.setenv('UNIFI_NETWORK_PORT', '8443')
        monkeypatch.setenv('UNIFI_NETWORK_VERIFY_SSL', 'true')
        monkeypatch.setenv('UNIFI_NETWORK_TIMEOUT', '60')
        monkeypatch.setenv('UNIFI_NETWORK_DEBUG', 'true')

        config = NetworkConfig.from_env()

        assert config.host == '192.168.1.1'
        assert config.api_key.get_secret_value() == 'env-api-key'
        assert config.site_id == '550e8400-e29b-41d4-a716-446655440000'
        assert config.port == 8443
        assert config.verify_ssl is True
        assert config.timeout == 60
        assert config.debug is True

    def test_from_env_missing_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error when HOST is missing."""
        monkeypatch.delenv('UNIFI_NETWORK_HOST', raising=False)
        monkeypatch.setenv('UNIFI_NETWORK_API_KEY', 'key')
        monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', '550e8400-e29b-41d4-a716-446655440000')

        with pytest.raises(ValueError, match='HOST environment variable is required'):
            NetworkConfig.from_env()

    def test_from_env_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error when API_KEY is missing."""
        monkeypatch.setenv('UNIFI_NETWORK_HOST', '192.168.1.1')
        monkeypatch.delenv('UNIFI_NETWORK_API_KEY', raising=False)
        monkeypatch.setenv('UNIFI_NETWORK_SITE_ID', '550e8400-e29b-41d4-a716-446655440000')

        with pytest.raises(ValueError, match='API_KEY environment variable is required'):
            NetworkConfig.from_env()

    def test_from_env_custom_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config with custom prefix."""
        monkeypatch.setenv('CUSTOM_HOST', '10.0.0.1')
        monkeypatch.setenv('CUSTOM_API_KEY', 'custom-key')
        monkeypatch.setenv('CUSTOM_SITE_ID', '550e8400-e29b-41d4-a716-446655440000')

        config = NetworkConfig.from_env(prefix='CUSTOM_')

        assert config.host == '10.0.0.1'
        assert config.api_key.get_secret_value() == 'custom-key'

    def test_from_env_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading config from env file."""
        # Clear any existing env vars
        for var in ['UNIFI_NETWORK_HOST', 'UNIFI_NETWORK_API_KEY', 'UNIFI_NETWORK_SITE_ID']:
            monkeypatch.delenv(var, raising=False)

        with NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('UNIFI_NETWORK_HOST=file-host\n')
            f.write('UNIFI_NETWORK_API_KEY=file-key\n')
            f.write('UNIFI_NETWORK_SITE_ID=550e8400-e29b-41d4-a716-446655440000\n')
            f.write('# Comment line\n')
            f.write('UNIFI_NETWORK_PORT=9443\n')
            env_file = f.name

        try:
            config = NetworkConfig.from_env(env_file=env_file)
            assert config.host == 'file-host'
            assert config.api_key.get_secret_value() == 'file-key'
            assert config.port == 9443
        finally:
            os.unlink(env_file)

    def test_from_env_file_not_found(self) -> None:
        """Test error when env file not found."""
        with pytest.raises(FileNotFoundError, match='Environment file not found'):
            NetworkConfig.from_env(env_file='/nonexistent/path/.env')

    def test_port_bounds(self) -> None:
        """Test port value bounds."""
        # Valid port
        config = NetworkConfig(
            host='192.168.1.1',
            port=8443,
            api_key=SecretStr('key'),
            site_id='550e8400-e29b-41d4-a716-446655440000',
        )
        assert config.port == 8443

        # Port too low
        with pytest.raises(ValueError):
            NetworkConfig(
                host='192.168.1.1',
                port=0,
                api_key=SecretStr('key'),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )

        # Port too high
        with pytest.raises(ValueError):
            NetworkConfig(
                host='192.168.1.1',
                port=65536,
                api_key=SecretStr('key'),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )

    def test_timeout_bounds(self) -> None:
        """Test timeout value bounds."""
        # Timeout too low
        with pytest.raises(ValueError):
            NetworkConfig(
                host='192.168.1.1',
                timeout=4,
                api_key=SecretStr('key'),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )

        # Timeout too high
        with pytest.raises(ValueError):
            NetworkConfig(
                host='192.168.1.1',
                timeout=301,
                api_key=SecretStr('key'),
                site_id='550e8400-e29b-41d4-a716-446655440000',
            )
