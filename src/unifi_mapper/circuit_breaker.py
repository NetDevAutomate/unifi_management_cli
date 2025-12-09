#!/usr/bin/env python3
"""
Circuit breaker pattern for UniFi Controller API.
Prevents cascading failures during controller outages.
"""

import time
import logging
from enum import Enum
from typing import Callable, Any

from .exceptions import UniFiConnectionError

log = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation, requests allowed
    OPEN = "open"            # Circuit tripped, blocking requests
    HALF_OPEN = "half_open"  # Testing recovery, limited requests


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    Opens circuit after threshold failures, attempts recovery after timeout.
    """

    def __init__(self, failure_threshold: int = 5,
                 recovery_timeout: int = 60,
                 expected_exception: type = Exception):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that triggers circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Result of function execution

        Raises:
            UniFiConnectionError: When circuit is OPEN
            Exception: Original exception when circuit allows execution
        """
        # Check if circuit is open
        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                log.info("Circuit breaker: Attempting recovery (HALF_OPEN)")
                self.state = CircuitState.HALF_OPEN
            else:
                time_remaining = self.recovery_timeout - (time.time() - self.last_failure_time)
                raise UniFiConnectionError(
                    f"Circuit breaker OPEN - controller unavailable. "
                    f"Retry in {time_remaining:.0f}s"
                )

        # Execute function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _should_attempt_recovery(self) -> bool:
        """Check if recovery timeout has elapsed."""
        if not self.last_failure_time:
            return True
        return time.time() - self.last_failure_time > self.recovery_timeout

    def _on_success(self) -> None:
        """Handle successful execution."""
        if self.failure_count > 0:
            log.info(f"Circuit breaker: Resetting failure count from {self.failure_count}")

        self.failure_count = 0

        if self.state == CircuitState.HALF_OPEN:
            log.info("Circuit breaker: Recovery successful (CLOSED)")
            self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        """Handle failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                log.error(
                    f"Circuit breaker: Opening circuit after {self.failure_count} failures. "
                    f"Will retry in {self.recovery_timeout}s"
                )
                self.state = CircuitState.OPEN

    def get_state(self) -> dict:
        """
        Get current circuit breaker state.

        Returns:
            Dict with state, failure_count, time_since_failure
        """
        time_since_failure = None
        if self.last_failure_time:
            time_since_failure = time.time() - self.last_failure_time

        return {
            'state': self.state.value,
            'failure_count': self.failure_count,
            'failure_threshold': self.failure_threshold,
            'time_since_last_failure': time_since_failure,
            'recovery_timeout': self.recovery_timeout
        }

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        log.info("Circuit breaker: Manually reset to CLOSED")
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
