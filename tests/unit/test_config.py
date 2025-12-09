#!/usr/bin/env python3
"""
Binary pass/fail tests for UnifiConfig.
"""

import os
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.config import UnifiConfig


def test_valid_token_config():
    """Binary test: Valid token-based config passes validation"""
    config = UnifiConfig(
        base_url="https://unifi.local:8443",
        site="default",
        api_token="test-token-12345",
    )

    assert config.base_url == "https://unifi.local:8443"
    assert config.site == "default"
    assert config.api_token == "test-token-12345"
    assert config.timeout == 10  # default
    assert config.max_retries == 3  # default

    print("✅ PASS: Valid token config accepted")
    return True


def test_valid_password_config():
    """Binary test: Valid username/password config passes validation"""
    config = UnifiConfig(
        base_url="https://unifi.local:8443",
        site="custom-site",
        username="admin",
        password="password123",
    )

    assert config.base_url == "https://unifi.local:8443"
    assert config.site == "custom-site"
    assert config.username == "admin"
    assert config.password == "password123"

    print("✅ PASS: Valid password config accepted")
    return True


def test_missing_base_url():
    """Binary test: Missing base_url raises ValueError"""
    try:
        config = UnifiConfig(base_url="", api_token="test-token")
        print("❌ FAIL: Should have raised ValueError for missing base_url")
        return False
    except ValueError as e:
        assert "base_url is required" in str(e)
        print("✅ PASS: Missing base_url rejected")
        return True


def test_invalid_url_format():
    """Binary test: URL without http(s):// raises ValueError"""
    try:
        config = UnifiConfig(base_url="unifi.local:8443", api_token="test-token")
        print("❌ FAIL: Should have raised ValueError for invalid URL format")
        return False
    except ValueError as e:
        assert "must start with http" in str(e)
        print("✅ PASS: Invalid URL format rejected")
        return True


def test_missing_auth_credentials():
    """Binary test: No auth credentials raises ValueError"""
    try:
        config = UnifiConfig(base_url="https://unifi.local:8443")
        print("❌ FAIL: Should have raised ValueError for missing auth")
        return False
    except ValueError as e:
        assert "api_token or username+password required" in str(e)
        print("✅ PASS: Missing auth credentials rejected")
        return True


def test_numeric_value_clamping():
    """Binary test: Out-of-range numeric values are clamped"""
    config = UnifiConfig(
        base_url="https://unifi.local",
        api_token="test",
        timeout=500,  # Above max (300)
        max_retries=20,  # Above max (10)
        retry_delay=15.0,  # Above max (10.0)
    )

    assert config.timeout == 300  # Clamped to max
    assert config.max_retries == 10  # Clamped to max
    assert config.retry_delay == 10.0  # Clamped to max

    config2 = UnifiConfig(
        base_url="https://unifi.local",
        api_token="test",
        timeout=0,  # Below min (1)
        max_retries=0,  # Below min (1)
        retry_delay=0.0,  # Below min (0.1)
    )

    assert config2.timeout == 1  # Clamped to min
    assert config2.max_retries == 1  # Clamped to min
    assert config2.retry_delay == 0.1  # Clamped to min

    print("✅ PASS: Numeric value clamping works")
    return True


def test_url_normalization():
    """Binary test: Trailing slashes removed from base_url"""
    config = UnifiConfig(base_url="https://unifi.local:8443///", api_token="test")

    assert config.base_url == "https://unifi.local:8443"
    assert not config.base_url.endswith("/")

    print("✅ PASS: URL normalization works")
    return True


def test_to_dict_export():
    """Binary test: to_dict() returns all configuration values"""
    config = UnifiConfig(
        base_url="https://unifi.local", site="office", api_token="token123", timeout=15
    )

    config_dict = config.to_dict()

    assert config_dict["base_url"] == "https://unifi.local"
    assert config_dict["site"] == "office"
    assert config_dict["api_token"] == "token123"
    assert config_dict["timeout"] == 15
    assert "password" in config_dict  # Key exists even if None

    print("✅ PASS: to_dict() export works")
    return True


if __name__ == "__main__":
    tests = [
        test_valid_token_config,
        test_valid_password_config,
        test_missing_base_url,
        test_invalid_url_format,
        test_missing_auth_credentials,
        test_numeric_value_clamping,
        test_url_normalization,
        test_to_dict_export,
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

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
