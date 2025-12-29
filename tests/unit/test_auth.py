"""Unit tests for authentication and credential chain."""

import json
import os
import pytest
from unifi_mcp.utils.auth import Credentials, get_credentials
from unifi_mcp.utils.errors import ErrorCodes, ToolError
from unittest.mock import AsyncMock, patch


class TestCredentials:
    """Test Credentials model."""

    def test_credentials_creation(self, sample_credentials):
        """Test creating credentials."""
        assert sample_credentials.host == '192.168.1.1'
        assert sample_credentials.username == 'admin'
        assert sample_credentials.password == 'password123'  # pragma: allowlist secret
        assert sample_credentials.site == 'default'
        assert sample_credentials.port == 443

    def test_credentials_from_env_success(self):
        """Test loading credentials from environment variables."""
        env_vars = {
            'UNIFI_HOST': '192.168.1.2',
            'UNIFI_USERNAME': 'testuser',
            'UNIFI_PASSWORD': 'testpass',  # pragma: allowlist secret
            'UNIFI_SITE': 'testsite',
            'UNIFI_PORT': '8443',
        }

        with patch.dict(os.environ, env_vars):
            creds = Credentials.from_env()
            assert creds.host == '192.168.1.2'
            assert creds.username == 'testuser'
            assert creds.password == 'testpass'  # pragma: allowlist secret
            assert creds.site == 'testsite'
            assert creds.port == 8443

    def test_credentials_from_env_missing_required(self):
        """Test loading credentials with missing required env vars."""
        with patch.dict(os.environ, {'UNIFI_HOST': '192.168.1.1'}, clear=True):
            with pytest.raises(ToolError) as exc_info:
                Credentials.from_env()

            assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
            assert 'UNIFI_USERNAME' in str(exc_info.value)
            assert 'UNIFI_PASSWORD' in str(exc_info.value)

    def test_credentials_from_keychain_valid(self):
        """Test loading credentials from keychain data."""
        keychain_json = json.dumps(
            {
                'host': '192.168.1.3',
                'username': 'keychain_user',
                'password': 'keychain_pass',  # pragma: allowlist secret
                'site': 'keychain_site',
            }
        )

        creds = Credentials.from_keychain(keychain_json)
        assert creds.host == '192.168.1.3'
        assert creds.username == 'keychain_user'
        assert creds.site == 'keychain_site'

    def test_credentials_from_keychain_invalid_json(self):
        """Test invalid JSON in keychain."""
        with pytest.raises(ToolError) as exc_info:
            Credentials.from_keychain('invalid json')

        assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
        assert 'Invalid keychain data' in str(exc_info.value)

    def test_credentials_from_onepassword_valid(self):
        """Test loading credentials from 1Password CLI data."""
        op_data = {
            'fields': [
                {'label': 'host', 'value': '192.168.1.4'},
                {'label': 'username', 'value': 'op_user'},
                {'label': 'password', 'value': 'op_pass'},
                {'label': 'site', 'value': 'op_site'},
            ]
        }

        creds = Credentials.from_onepassword(op_data)
        assert creds.host == '192.168.1.4'
        assert creds.username == 'op_user'
        assert creds.site == 'op_site'

    def test_credentials_from_onepassword_missing_fields(self):
        """Test 1Password data with missing required fields."""
        op_data = {
            'fields': [
                {'label': 'host', 'value': '192.168.1.4'},
                # Missing username and password
            ]
        }

        with pytest.raises(ToolError) as exc_info:
            Credentials.from_onepassword(op_data)

        assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED


class TestCredentialChain:
    """Test credential chain fallback logic."""

    @pytest.mark.asyncio
    async def test_get_credentials_from_env(self):
        """Test credential chain - environment variables."""
        env_vars = {
            'UNIFI_HOST': '192.168.1.1',
            'UNIFI_USERNAME': 'admin',
            'UNIFI_PASSWORD': 'password',  # pragma: allowlist secret
        }

        with patch.dict(os.environ, env_vars):
            creds = await get_credentials()
            assert creds.host == '192.168.1.1'
            assert creds.username == 'admin'

    @pytest.mark.asyncio
    async def test_get_credentials_from_keychain(self):
        """Test credential chain - keychain fallback."""
        # Mock keyring to return valid data
        keychain_data = json.dumps(
            {
                'host': '192.168.1.2',
                'username': 'keychain_user',
                'password': 'keychain_pass',  # pragma: allowlist secret
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            with patch('keyring.get_password', return_value=keychain_data):
                creds = await get_credentials()
                assert creds.host == '192.168.1.2'
                assert creds.username == 'keychain_user'

    @pytest.mark.asyncio
    async def test_get_credentials_from_onepassword(self):
        """Test credential chain - 1Password CLI fallback."""
        op_output = json.dumps(
            {
                'fields': [
                    {'label': 'host', 'value': '192.168.1.3'},
                    {'label': 'username', 'value': 'op_user'},
                    {'label': 'password', 'value': 'op_pass'},
                ]
            }
        )

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (op_output.encode(), b'')

        with patch.dict(os.environ, {}, clear=True):
            with patch('keyring.get_password', return_value=None):
                with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                    creds = await get_credentials()
                    assert creds.host == '192.168.1.3'
                    assert creds.username == 'op_user'

    @pytest.mark.asyncio
    async def test_get_credentials_all_methods_fail(self):
        """Test credential chain - all methods fail."""
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b'', b'error')

        with patch.dict(os.environ, {}, clear=True):
            with patch('keyring.get_password', return_value=None):
                with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                    with pytest.raises(ToolError) as exc_info:
                        await get_credentials()

                    assert exc_info.value.error_code == ErrorCodes.AUTHENTICATION_FAILED
                    assert 'No credentials found' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_credentials_keyring_not_available(self):
        """Test credential chain when keyring not available."""
        op_output = json.dumps(
            {
                'fields': [
                    {'label': 'host', 'value': '192.168.1.3'},
                    {'label': 'username', 'value': 'op_user'},
                    {'label': 'password', 'value': 'op_pass'},
                ]
            }
        )

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (op_output.encode(), b'')

        with patch.dict(os.environ, {}, clear=True):
            # Mock keyring import to fail
            with patch('builtins.__import__', side_effect=ImportError('keyring not found')):
                with patch('asyncio.create_subprocess_exec', return_value=mock_process):
                    creds = await get_credentials()
                    # Should succeed via 1Password fallback
                    assert creds.host == '192.168.1.3'
