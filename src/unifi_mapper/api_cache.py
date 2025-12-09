#!/usr/bin/env python3
"""
API response cache with TTL for UniFi Controller API.
Reduces redundant API calls through time-based caching.
"""

import logging
import time
from functools import wraps
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


class TtlCache:
    """
    Time-To-Live cache for API responses.
    Automatically expires entries after specified duration.
    """

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize TTL cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default: 300 = 5 minutes)
        """
        self.ttl = ttl_seconds
        self._cache = {}
        self._stats = {"hits": 0, "misses": 0, "sets": 0, "evictions": 0}

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value or None if expired/missing
        """
        if key in self._cache:
            data, timestamp = self._cache[key]
            age = time.time() - timestamp

            if age < self.ttl:
                self._stats["hits"] += 1
                log.debug(f"Cache hit: {key} (age: {age:.1f}s)")
                return data
            else:
                # Expired
                del self._cache[key]
                self._stats["evictions"] += 1
                log.debug(f"Cache expired: {key} (age: {age:.1f}s)")

        self._stats["misses"] += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """
        Store value in cache with current timestamp.

        Args:
            key: Cache key
            value: Value to cache
        """
        self._cache[key] = (value, time.time())
        self._stats["sets"] += 1
        log.debug(f"Cache set: {key}")

    def invalidate(self, key: str) -> None:
        """
        Remove specific key from cache.

        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]
            log.debug(f"Cache invalidated: {key}")

    def clear(self) -> None:
        """Clear all cache entries."""
        count = len(self._cache)
        self._cache.clear()
        log.debug(f"Cache cleared: {count} entries removed")

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with hits, misses, hit_rate, size
        """
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = (
            (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        )

        return {
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "sets": self._stats["sets"],
            "evictions": self._stats["evictions"],
            "size": len(self._cache),
            "hit_rate": f"{hit_rate:.1f}%",
            "total_requests": total_requests,
        }

    def cached(self, func: Callable) -> Callable:
        """
        Decorator to cache function results.

        Args:
            func: Function to cache

        Returns:
            Wrapped function with caching
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # Check cache
            cached_value = self.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Execute function
            result = func(*args, **kwargs)

            # Cache result
            self.set(cache_key, result)

            return result

        return wrapper
