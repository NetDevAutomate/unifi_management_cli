#!/usr/bin/env python3
"""
Binary pass/fail tests for TtlCache.
"""

import sys
import time
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from unifi_mapper.api_cache import TtlCache


def test_cache_stores_and_retrieves():
    """Binary test: Cache stores and retrieves values"""
    cache = TtlCache(ttl_seconds=60)

    cache.set("key1", "value1")
    result = cache.get("key1")

    assert result == "value1"

    print("✅ PASS: Cache stores and retrieves")
    return True


def test_cache_expiration():
    """Binary test: Cached values expire after TTL"""
    cache = TtlCache(ttl_seconds=1)  # 1 second TTL

    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"  # Immediately available

    # Wait for expiration
    time.sleep(1.2)
    result = cache.get("key1")

    assert result is None  # Should be expired

    print("✅ PASS: Cache expiration works")
    return True


def test_cache_hit_statistics():
    """Binary test: Cache tracks hits and misses correctly"""
    cache = TtlCache(ttl_seconds=60)

    # Miss
    result1 = cache.get("nonexistent")
    assert result1 is None

    # Set and hit
    cache.set("key1", "value1")
    result2 = cache.get("key1")
    assert result2 == "value1"

    # Another hit
    result3 = cache.get("key1")
    assert result3 == "value1"

    stats = cache.get_stats()
    assert stats['hits'] == 2
    assert stats['misses'] == 1
    assert stats['sets'] == 1
    assert stats['size'] == 1

    print("✅ PASS: Cache statistics tracked correctly")
    return True


def test_cache_invalidation():
    """Binary test: Manual invalidation removes entry"""
    cache = TtlCache(ttl_seconds=60)

    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    cache.invalidate("key1")
    result = cache.get("key1")

    assert result is None

    print("✅ PASS: Cache invalidation works")
    return True


def test_cache_clear():
    """Binary test: Clear removes all entries"""
    cache = TtlCache(ttl_seconds=60)

    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    stats_before = cache.get_stats()
    assert stats_before['size'] == 3

    cache.clear()

    stats_after = cache.get_stats()
    assert stats_after['size'] == 0
    assert cache.get("key1") is None
    assert cache.get("key2") is None

    print("✅ PASS: Cache clear works")
    return True


def test_cached_decorator():
    """Binary test: Cached decorator prevents redundant function calls"""
    cache = TtlCache(ttl_seconds=60)

    call_count = 0

    @cache.cached
    def expensive_function(x, y):
        nonlocal call_count
        call_count += 1
        return x + y

    # First call
    result1 = expensive_function(5, 3)
    assert result1 == 8
    assert call_count == 1

    # Second call with same args (should use cache)
    result2 = expensive_function(5, 3)
    assert result2 == 8
    assert call_count == 1  # Not called again

    # Different args (should execute)
    result3 = expensive_function(10, 20)
    assert result3 == 30
    assert call_count == 2

    print("✅ PASS: Cached decorator prevents redundant calls")
    return True


def test_hit_rate_calculation():
    """Binary test: Hit rate percentage calculated correctly"""
    cache = TtlCache(ttl_seconds=60)

    cache.set("key1", "value1")

    # 3 hits
    cache.get("key1")
    cache.get("key1")
    cache.get("key1")

    # 1 miss
    cache.get("nonexistent")

    stats = cache.get_stats()
    assert stats['hits'] == 3
    assert stats['misses'] == 1
    assert stats['total_requests'] == 4
    assert stats['hit_rate'] == "75.0%"

    print("✅ PASS: Hit rate calculated correctly")
    return True


if __name__ == "__main__":
    tests = [
        test_cache_stores_and_retrieves,
        test_cache_expiration,
        test_cache_hit_statistics,
        test_cache_invalidation,
        test_cache_clear,
        test_cached_decorator,
        test_hit_rate_calculation
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
