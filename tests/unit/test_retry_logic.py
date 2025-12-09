#!/usr/bin/env python3
"""
Binary pass/fail tests for retry logic with exponential backoff.
"""

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch
import requests
from requests.exceptions import ConnectionError, Timeout, HTTPError

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.exceptions import (
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiTimeoutError,
    UniFiPermissionError
)


def test_successful_first_attempt():
    """Binary test: Successful request on first attempt makes only 1 call"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=3
    )

    call_count = 0

    def mock_func():
        nonlocal call_count
        call_count += 1
        return Mock(status_code=200)

    result = client._retry_request(mock_func)

    assert call_count == 1  # Only one attempt needed
    assert result.status_code == 200

    print("✅ PASS: Successful first attempt makes 1 call")
    return True


def test_retry_on_connection_error():
    """Binary test: Connection errors trigger retry with exponential backoff"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=3,
        retry_delay=0.1  # Fast for testing
    )

    call_count = 0

    def mock_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Connection refused")
        return Mock(status_code=200)

    start_time = time.time()
    result = client._retry_request(mock_func)
    elapsed = time.time() - start_time

    assert call_count == 3  # Failed twice, succeeded third time
    assert result.status_code == 200
    # Verify exponential backoff: 0.1 + 0.2 = 0.3s minimum
    assert elapsed >= 0.3  # Two delays (0.1 * 2^0 + 0.1 * 2^1)

    print("✅ PASS: Retries with exponential backoff")
    return True


def test_no_retry_on_auth_error():
    """Binary test: 401/403 errors don't retry (raise immediately)"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=5
    )

    call_count = 0

    def mock_func():
        nonlocal call_count
        call_count += 1
        mock_response = Mock()
        mock_response.status_code = 401
        raise HTTPError(response=mock_response)

    try:
        client._retry_request(mock_func)
        print("❌ FAIL: Should have raised UniFiAuthenticationError")
        return False
    except UniFiAuthenticationError:
        assert call_count == 1  # No retries for auth errors
        print("✅ PASS: Auth errors don't retry")
        return True


def test_no_retry_on_client_errors():
    """Binary test: 4xx errors (except 401/403/408/429) don't retry"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=5
    )

    test_cases = [400, 404, 422]  # Client errors that shouldn't retry

    for status_code in test_cases:
        call_count = 0

        def mock_func():
            nonlocal call_count
            call_count += 1
            mock_response = Mock()
            mock_response.status_code = status_code
            raise HTTPError(response=mock_response)

        try:
            client._retry_request(mock_func)
            print(f"❌ FAIL: Should have raised exception for {status_code}")
            return False
        except UniFiPermissionError:
            assert call_count == 1  # No retries
        except Exception as e:
            print(f"❌ FAIL: Wrong exception type for {status_code}: {type(e)}")
            return False

    print("✅ PASS: Client errors (4xx) don't retry")
    return True


def test_retry_exhaustion():
    """Binary test: All retries exhausted raises UniFiConnectionError"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=3,
        retry_delay=0.05
    )

    call_count = 0

    def mock_func():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Always fails")

    try:
        client._retry_request(mock_func)
        print("❌ FAIL: Should have raised UniFiConnectionError")
        return False
    except UniFiConnectionError as e:
        assert call_count == 3  # All 3 retries attempted
        assert "after 3 attempts" in str(e)
        print("✅ PASS: Retry exhaustion handled correctly")
        return True


def test_timeout_error_classification():
    """Binary test: Timeout errors raise UniFiTimeoutError"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=1
    )

    def mock_func():
        raise Timeout("Request timed out")

    try:
        client._retry_request(mock_func)
        print("❌ FAIL: Should have raised UniFiTimeoutError")
        return False
    except UniFiTimeoutError as e:
        assert "timed out" in str(e).lower()
        print("✅ PASS: Timeout errors classified correctly")
        return True


def test_exponential_backoff_calculation():
    """Binary test: Delays follow exponential pattern (delay * 2^attempt)"""
    client = UnifiApiClient(
        base_url="https://test.local",
        api_token="test-token",
        max_retries=4,
        retry_delay=0.1
    )

    call_count = 0
    attempt_times = []

    def mock_func():
        nonlocal call_count
        call_count += 1
        attempt_times.append(time.time())
        if call_count < 4:
            raise ConnectionError("Fail")
        return Mock(status_code=200)

    result = client._retry_request(mock_func)

    # Verify delays: 0.1, 0.2, 0.4 seconds
    assert call_count == 4
    assert len(attempt_times) == 4

    # Calculate actual delays
    delay1 = attempt_times[1] - attempt_times[0]
    delay2 = attempt_times[2] - attempt_times[1]
    delay3 = attempt_times[3] - attempt_times[2]

    # Allow 10% tolerance
    assert 0.09 <= delay1 <= 0.15  # ~0.1s (2^0 * 0.1)
    assert 0.18 <= delay2 <= 0.25  # ~0.2s (2^1 * 0.1)
    assert 0.35 <= delay3 <= 0.50  # ~0.4s (2^2 * 0.1)

    print("✅ PASS: Exponential backoff calculated correctly")
    return True


if __name__ == "__main__":
    tests = [
        test_successful_first_attempt,
        test_retry_on_connection_error,
        test_no_retry_on_auth_error,
        test_no_retry_on_client_errors,
        test_retry_exhaustion,
        test_timeout_error_classification,
        test_exponential_backoff_calculation
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
