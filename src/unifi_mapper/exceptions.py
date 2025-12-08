#!/usr/bin/env python3
"""
Exception hierarchy for UniFi API operations.
Provides structured error handling with retry/no-retry classification.
"""


class UniFiApiError(Exception):
    """Base exception for all UniFi API errors."""
    pass


class UniFiRetryableError(UniFiApiError):
    """Errors that should trigger retry logic (5xx, timeouts, connection issues)."""
    pass


class UniFiPermanentError(UniFiApiError):
    """Errors that should not be retried (4xx client errors)."""
    pass


class UniFiAuthenticationError(UniFiPermanentError):
    """Authentication failures (401, 403)."""

    def __init__(self, message: str, auth_method: str = None, status_code: int = None):
        """
        Initialize authentication error with context.

        Args:
            message: Error message
            auth_method: Authentication method that failed (token, username_password)
            status_code: HTTP status code (401, 403)
        """
        super().__init__(message)
        self.auth_method = auth_method
        self.status_code = status_code


class UniFiConnectionError(UniFiRetryableError):
    """Network connectivity issues (connection refused, DNS failures)."""
    pass


class UniFiTimeoutError(UniFiRetryableError):
    """Request timeout errors."""
    pass


class UniFiRateLimitError(UniFiRetryableError):
    """Rate limit (429) errors."""
    pass


class UniFiValidationError(UniFiPermanentError):
    """Input validation failures (invalid site_id, device_id, etc.)."""
    pass


class UniFiPermissionError(UniFiPermanentError):
    """Permission denied errors (insufficient API privileges)."""
    pass
