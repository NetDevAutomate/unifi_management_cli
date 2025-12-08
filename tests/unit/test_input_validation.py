#!/usr/bin/env python3
"""
Binary pass/fail tests for input validation and injection prevention.
Tests SQL injection, XSS, command injection, and path traversal patterns.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.api_client import UnifiApiClient


def test_site_id_sql_injection_prevention():
    """Binary test: SQL injection patterns in site_id are sanitized"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    # Test various SQL injection patterns
    test_cases = [
        ("default'; DROP TABLE devices; --", "default--"),  # Allows alphanumeric, _, -
        ("default' OR '1'='1", "defaultOR11"),
        ("default; DELETE FROM users WHERE 1=1; --", "defaultDELETEFROMusersWHERE11--"),
    ]

    for dangerous_input, expected_pattern in test_cases:
        sanitized = client._validate_site_id(dangerous_input)

        # Should remove dangerous SQL characters: ', ;, spaces
        assert "'" not in sanitized, f"Single quote not removed: {sanitized}"
        assert ";" not in sanitized, f"Semicolon not removed: {sanitized}"
        assert " " not in sanitized, f"Spaces not removed: {sanitized}"
        # Note: -- (hyphen-hyphen) is allowed since - is valid in site names

    print("✅ PASS: SQL injection dangerous chars sanitized")
    return True


def test_site_id_xss_prevention():
    """Binary test: XSS patterns in site_id are sanitized"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    dangerous_inputs = [
        "<script>alert('xss')</script>",
        "default<img src=x onerror=alert(1)>",
        "default';alert(String.fromCharCode(88,83,83))//",
    ]

    for dangerous_input in dangerous_inputs:
        sanitized = client._validate_site_id(dangerous_input)

        assert "<" not in sanitized
        assert ">" not in sanitized
        assert "(" not in sanitized
        assert ")" not in sanitized

    print("✅ PASS: XSS patterns sanitized")
    return True


def test_device_id_hex_validation():
    """Binary test: Device IDs sanitized to hexadecimal only"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    # Valid hex device IDs (should pass through unchanged, preserves case)
    valid_ids = [
        ("67e933aa6816c65fc5dfe6a9", "67e933aa6816c65fc5dfe6a9"),  # Lowercase preserved
        ("67E933AA6816C65FC5DFE6A9", "67E933AA6816C65FC5DFE6A9"),  # Uppercase preserved
    ]

    for valid_id, expected in valid_ids:
        result = client._validate_device_id(valid_id)
        assert result == expected, f"Expected {expected}, got {result}"

    # Invalid IDs (should be cleaned to only hex)
    invalid_test_cases = [
        ("device-with-dashes", "dececeddaec"),  # Only letters that are hex
        ("device_with_underscores", "dececed"),
        ("device with spaces", "dececed"),
        ("abc123xyz789", "abc123"),  # xyz removed, only hex
    ]

    for invalid_id, expected_result in invalid_test_cases:
        result = client._validate_device_id(invalid_id)
        # Should only contain hex characters (0-9, a-f)
        assert all(c in '0123456789abcdef' for c in result), f"Non-hex in result: {result}"

    print("✅ PASS: Device ID hex sanitization works")
    return True


def test_port_name_dangerous_char_removal():
    """Binary test: Dangerous characters removed from port names"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    dangerous_names = [
        "Port<script>alert('xss')</script>",
        'Port"; rm -rf /',
        "Port\x00\x01\x02",  # Null bytes and control chars
        "Port'\"\\<>",
    ]

    for dangerous_name in dangerous_names:
        sanitized = client._validate_port_name(dangerous_name)

        assert "<" not in sanitized
        assert ">" not in sanitized
        assert '"' not in sanitized
        assert "'" not in sanitized
        assert "\\" not in sanitized
        assert "\x00" not in sanitized

    print("✅ PASS: Dangerous characters removed from port names")
    return True


def test_port_name_length_limit():
    """Binary test: Port names limited to 100 characters"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    long_name = "A" * 200  # 200 characters

    try:
        sanitized = client._validate_port_name(long_name)
        print(f"❌ FAIL: Should reject name longer than 100 chars (got {len(sanitized)})")
        return False
    except ValueError as e:
        assert "too long" in str(e).lower()
        print("✅ PASS: Long port names rejected")
        return True


def test_empty_input_validation():
    """Binary test: Empty inputs raise ValueError"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    # Test empty site_id
    try:
        client._validate_site_id("")
        print("❌ FAIL: Empty site_id should raise ValueError")
        return False
    except ValueError:
        pass

    # Test empty device_id
    try:
        client._validate_device_id("")
        print("❌ FAIL: Empty device_id should raise ValueError")
        return False
    except ValueError:
        pass

    # Test empty port_name
    try:
        client._validate_port_name("")
        print("❌ FAIL: Empty port_name should raise ValueError")
        return False
    except ValueError:
        pass

    print("✅ PASS: Empty inputs rejected")
    return True


def test_path_traversal_prevention():
    """Binary test: Path traversal patterns in site_id removed"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        verify_ssl=False
    )

    dangerous_inputs = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "default/../../",
    ]

    for dangerous_input in dangerous_inputs:
        sanitized = client._validate_site_id(dangerous_input)

        assert "/" not in sanitized
        assert "\\" not in sanitized
        assert "." not in sanitized

    print("✅ PASS: Path traversal patterns removed")
    return True


if __name__ == "__main__":
    tests = [
        test_site_id_sql_injection_prevention,
        test_site_id_xss_prevention,
        test_device_id_hex_validation,
        test_port_name_dangerous_char_removal,
        test_port_name_length_limit,
        test_empty_input_validation,
        test_path_traversal_prevention
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

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("✅ ALL TESTS PASS")
        sys.exit(0)
    else:
        print(f"❌ {failed} TEST(S) FAILED")
        sys.exit(1)
