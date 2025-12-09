#!/usr/bin/env python3
"""
Binary pass/fail tests for CircuitBreaker.
"""

import sys
import time
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.circuit_breaker import CircuitBreaker, CircuitState
from unifi_mapper.exceptions import UniFiConnectionError


def test_circuit_starts_closed():
    """Binary test: Circuit breaker starts in CLOSED state"""
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=5)

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    print("✅ PASS: Circuit starts CLOSED")
    return True


def test_successful_calls_dont_trip_circuit():
    """Binary test: Successful calls keep circuit CLOSED"""
    breaker = CircuitBreaker(failure_threshold=3)

    def successful_func():
        return "success"

    # Multiple successful calls
    for _ in range(10):
        result = breaker.call(successful_func)
        assert result == "success"

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    print("✅ PASS: Successful calls don't trip circuit")
    return True


def test_circuit_opens_after_threshold():
    """Binary test: Circuit opens after failure threshold reached"""
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1)

    call_count = 0

    def failing_func():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Always fails")

    # Fail 3 times
    for i in range(3):
        try:
            breaker.call(failing_func)
        except ConnectionError:
            pass

    assert breaker.state == CircuitState.OPEN
    assert breaker.failure_count == 3

    print("✅ PASS: Circuit opens after threshold")
    return True


def test_open_circuit_blocks_calls():
    """Binary test: OPEN circuit blocks calls and raises UniFiConnectionError"""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=10)

    def failing_func():
        raise ConnectionError("Fail")

    # Trip the circuit
    for _ in range(2):
        try:
            breaker.call(failing_func)
        except ConnectionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # Next call should be blocked
    try:
        breaker.call(failing_func)
        print("❌ FAIL: OPEN circuit should block calls")
        return False
    except UniFiConnectionError as e:
        assert "Circuit breaker OPEN" in str(e)
        print("✅ PASS: OPEN circuit blocks calls")
        return True


def test_circuit_attempts_recovery():
    """Binary test: Circuit attempts recovery after timeout"""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)

    def initially_failing_func():
        if breaker.state == CircuitState.HALF_OPEN:
            return "recovered"
        raise ConnectionError("Fail")

    # Trip circuit
    for _ in range(2):
        try:
            breaker.call(initially_failing_func)
        except ConnectionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # Wait for recovery timeout
    time.sleep(1.2)

    # Should attempt recovery
    result = breaker.call(initially_failing_func)
    assert result == "recovered"
    assert breaker.state == CircuitState.CLOSED

    print("✅ PASS: Circuit attempts recovery")
    return True


def test_half_open_success_closes_circuit():
    """Binary test: Successful call in HALF_OPEN closes circuit"""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=1)

    # Trip circuit
    for _ in range(2):
        try:
            breaker.call(lambda: (_ for _ in ()).throw(ConnectionError("Fail")))
        except ConnectionError:
            pass

    breaker.state = CircuitState.HALF_OPEN

    # Successful call should close circuit
    def success_func():
        return "ok"

    result = breaker.call(success_func)

    assert result == "ok"
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    print("✅ PASS: HALF_OPEN success closes circuit")
    return True


def test_manual_reset():
    """Binary test: Manual reset returns circuit to CLOSED"""
    breaker = CircuitBreaker(failure_threshold=2)

    # Trip circuit
    for _ in range(2):
        try:
            breaker.call(lambda: (_ for _ in ()).throw(ConnectionError()))
        except ConnectionError:
            pass

    assert breaker.state == CircuitState.OPEN

    # Manual reset
    breaker.reset()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0

    print("✅ PASS: Manual reset works")
    return True


if __name__ == "__main__":
    tests = [
        test_circuit_starts_closed,
        test_successful_calls_dont_trip_circuit,
        test_circuit_opens_after_threshold,
        test_open_circuit_blocks_calls,
        test_circuit_attempts_recovery,
        test_half_open_success_closes_circuit,
        test_manual_reset,
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
