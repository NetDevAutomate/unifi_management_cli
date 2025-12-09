#!/usr/bin/env python3
"""
Binary pass/fail tests for AuthManager.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import requests

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.auth_manager import AuthManager
from unifi_mapper.endpoint_builder import UnifiEndpointBuilder
from unifi_mapper.exceptions import UniFiAuthenticationError, UniFiValidationError


def test_token_authentication_success():
    """Binary test: Token auth succeeds with X-API-KEY header"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    session.get = Mock(return_value=mock_response)

    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder, session=session, api_token="test-token-123"
    )

    result = auth_mgr.login("default")

    assert result is True
    assert auth_mgr.is_authenticated is True
    assert "token" in auth_mgr.successful_endpoint
    assert "X-API-KEY" in session.headers
    assert session.headers["X-API-KEY"] == "test-token-123"

    print("✅ PASS: Token authentication succeeds")
    return True


def test_password_authentication_success():
    """Binary test: Password auth succeeds with correct credentials"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock successful response
    mock_response = Mock()
    mock_response.status_code = 200
    session.post = Mock(return_value=mock_response)
    session.get = Mock(return_value=Mock(status_code=404))  # UniFi OS detection fails

    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder,
        session=session,
        username="admin",
        password="password123",
    )

    result = auth_mgr.login("default")

    assert result is True
    assert auth_mgr.is_authenticated is True
    assert "password" in auth_mgr.successful_endpoint

    # Verify login was called with correct data
    call_args = session.post.call_args
    assert call_args[1]["json"]["username"] == "admin"
    assert call_args[1]["json"]["password"] == "password123"

    print("✅ PASS: Password authentication succeeds")
    return True


def test_missing_credentials_validation():
    """Binary test: Missing credentials raises UniFiValidationError"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Test missing token
    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder,
        session=session,
        api_token=None,
        username=None,
        password=None,
    )

    try:
        auth_mgr.login("default")
        print("❌ FAIL: Should raise UniFiValidationError for missing credentials")
        return False
    except UniFiValidationError as e:
        assert "credentials missing" in str(e).lower()
        print("✅ PASS: Missing credentials rejected")
        return True


def test_already_authenticated_skip():
    """Binary test: Already authenticated sessions skip re-auth"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()
    session.get = Mock()

    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder, session=session, api_token="test-token"
    )

    # Manually mark as authenticated
    auth_mgr.is_authenticated = True

    result = auth_mgr.login("default")

    assert result is True
    assert session.get.call_count == 0  # No API calls made

    print("✅ PASS: Already authenticated sessions skip re-auth")
    return True


def test_unifi_os_detection():
    """Binary test: UniFi OS detection updates endpoint_builder"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    # Mock UniFi OS system check success
    with patch("requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200)

        auth_mgr = AuthManager(
            endpoint_builder=endpoint_builder, session=session, api_token="test-token"
        )

        # Trigger detection
        auth_mgr._detect_unifi_os()

        assert endpoint_builder.is_unifi_os is True

    print("✅ PASS: UniFi OS detection works")
    return True


def test_logout_clears_state():
    """Binary test: Logout clears authentication state"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = Mock(spec=requests.Session)
    session.verify = False  # Add missing attribute
    session.close = Mock()
    session.post = Mock(return_value=Mock(status_code=200))

    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder, session=session, api_token="test-token"
    )

    # Set authenticated state
    auth_mgr.is_authenticated = True
    auth_mgr.successful_endpoint = "password_login"

    result = auth_mgr.logout()

    assert result is True
    assert auth_mgr.is_authenticated is False
    assert auth_mgr.successful_endpoint is None
    assert session.close.called

    print("✅ PASS: Logout clears authentication state")
    return True


def test_credential_clearing():
    """Binary test: Credentials are securely cleared from memory"""
    endpoint_builder = UnifiEndpointBuilder("https://test.local", is_unifi_os=False)
    session = requests.Session()

    auth_mgr = AuthManager(
        endpoint_builder=endpoint_builder,
        session=session,
        api_token="sensitive-token",
        username="admin",
        password="password123",
    )

    # Verify credentials are set
    assert auth_mgr._api_token == "sensitive-token"
    assert auth_mgr._username == "admin"
    assert auth_mgr._password == "password123"

    # Clear credentials
    auth_mgr.clear_credentials()

    # Verify credentials are cleared
    assert auth_mgr._api_token is None
    assert auth_mgr._username is None
    assert auth_mgr._password is None
    assert auth_mgr._token_hash is None
    assert auth_mgr._username_hash is None
    assert auth_mgr._password_hash is None

    print("✅ PASS: Credentials securely cleared")
    return True


if __name__ == "__main__":
    tests = [
        test_token_authentication_success,
        test_password_authentication_success,
        test_missing_credentials_validation,
        test_already_authenticated_skip,
        test_unifi_os_detection,
        test_logout_clears_state,
        test_credential_clearing,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            print(f"❌ ERROR: {test.__name__} - {e}")
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
