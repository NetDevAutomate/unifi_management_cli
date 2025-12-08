#!/usr/bin/env python3
"""
Authentication manager for UniFi Controller API.
Handles login, logout, session management, and UniFi OS detection.
"""

import logging
import requests
import urllib3
import hashlib
from typing import Optional, Callable

from .exceptions import (
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiValidationError,
    UniFiApiError
)
from .endpoint_builder import UnifiEndpointBuilder

log = logging.getLogger(__name__)


def _hash_for_verification(value: str) -> str:
    """Create a hash of sensitive data for verification without exposing actual value."""
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


class AuthManager:
    """
    Manages authentication and session for UniFi Controller API.
    Handles both token-based and username/password authentication.
    """

    def __init__(self, endpoint_builder: UnifiEndpointBuilder,
                 session: requests.Session,
                 api_token: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 retry_func: Optional[Callable] = None):
        """
        Initialize AuthManager.

        Args:
            endpoint_builder: UnifiEndpointBuilder instance
            session: requests.Session instance
            api_token: API token for token-based authentication
            username: Username for username/password authentication
            password: Password for username/password authentication
            retry_func: Function to retry requests with backoff
        """
        self.endpoint_builder = endpoint_builder
        self.session = session
        self._api_token = api_token.strip() if api_token else None
        self._username = username.strip() if username else None
        self._password = password if password else None
        self._retry_func = retry_func

        # Store credential hashes for logging
        self._token_hash = _hash_for_verification(self._api_token) if self._api_token else None
        self._username_hash = _hash_for_verification(self._username) if self._username else None
        self._password_hash = _hash_for_verification(self._password) if self._password else None

        # Authentication state
        self.is_authenticated = False
        self.auth_method = "token" if api_token else "username_password"
        self.successful_endpoint = None
        self._last_error = None

        # Disable SSL warnings if needed
        if not session.verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def login(self, site_id: str = "default") -> bool:
        """
        Login to the UniFi Controller.

        Args:
            site_id: Site ID for authentication verification

        Returns:
            bool: True if login successful, False otherwise

        Raises:
            UniFiAuthenticationError: When authentication fails
            UniFiConnectionError: When connection fails
            UniFiValidationError: When credentials are missing
        """
        # Check if already authenticated
        if self.is_authenticated:
            log.debug("Already authenticated, skipping login")
            return True

        # Validate credentials
        if self.auth_method == "token" and not self._api_token:
            raise UniFiValidationError("API token authentication selected but no token provided")
        elif self.auth_method == "username_password" and (not self._username or not self._password):
            raise UniFiValidationError("Username/password authentication selected but credentials missing")

        log.info(f"Attempting authentication using {self.auth_method} method")

        try:
            return self._perform_login(site_id)
        except UniFiApiError:
            raise
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Unexpected error during login: {e}")
            raise UniFiApiError(f"Login failed: {e}")

    def _perform_login(self, site_id: str) -> bool:
        """
        Perform the actual login process.

        Args:
            site_id: Site ID for verification

        Returns:
            bool: True if successful
        """
        # Detect UniFi OS
        self._detect_unifi_os()

        if self.auth_method == "token":
            return self._token_login(site_id)
        else:
            return self._password_login(site_id)

    def _detect_unifi_os(self) -> None:
        """Detect if controller is UniFi OS device."""
        try:
            endpoint = self.endpoint_builder.system_check()

            def _check():
                return requests.get(endpoint, verify=self.session.verify,
                                  timeout=self.session.timeout if hasattr(self.session, 'timeout') else 10)

            if self._retry_func:
                response = self._retry_func(_check)
            else:
                response = _check()

            self.endpoint_builder.is_unifi_os = response.status_code == 200
            log.debug(f"UniFi OS detection: {self.endpoint_builder.is_unifi_os}")
        except Exception as e:
            log.debug(f"UniFi OS detection failed, assuming legacy: {e}")
            self.endpoint_builder.is_unifi_os = False

    def _token_login(self, site_id: str) -> bool:
        """
        Authenticate using API token.

        Args:
            site_id: Site ID for verification

        Returns:
            bool: True if successful
        """
        log.debug(f"Attempting token authentication - hash: {self._token_hash}")

        # Try X-API-KEY header first
        self.session.headers.update({'X-API-KEY': self._api_token})

        if self._try_token_auth(site_id, "X-API-KEY"):
            return True

        # Try Bearer token as fallback
        self.session.headers.update({'Authorization': f"Bearer {self._api_token}"})
        del self.session.headers['X-API-KEY']

        if self._try_token_auth(site_id, "Bearer"):
            return True

        log.error("Token authentication failed - all methods exhausted")
        return False

    def _try_token_auth(self, site_id: str, method: str) -> bool:
        """Try token authentication with specific method."""
        try:
            endpoint = self.endpoint_builder.self_check(site_id)

            def _check():
                return self.session.get(endpoint)

            if self._retry_func:
                response = self._retry_func(_check)
            else:
                response = _check()

            if response.status_code == 200:
                self.is_authenticated = True
                self.successful_endpoint = f"token_{method.lower()}"
                log.info(f"Successfully authenticated with {method} token - hash: {self._token_hash}")
                return True
        except requests.exceptions.SSLError as e:
            log.error(f"SSL error during token authentication: {e}")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.debug(f"{method} token authentication failed: {e}")

        return False

    def _password_login(self, site_id: str) -> bool:
        """
        Authenticate using username/password.

        Args:
            site_id: Site ID

        Returns:
            bool: True if successful
        """
        log.debug(f"Attempting password authentication - username hash: {self._username_hash}")

        try:
            endpoint = self.endpoint_builder.login()
            login_data = {
                "username": self._username,
                "password": self._password
            }

            def _login():
                return self.session.post(endpoint, json=login_data)

            if self._retry_func:
                response = self._retry_func(_login)
            else:
                response = _login()

            if response.status_code == 200:
                self.is_authenticated = True
                self.successful_endpoint = "password_login"
                log.info(f"Successfully authenticated with username/password - user hash: {self._username_hash}")
                return True
            else:
                log.error(f"Password authentication failed: {response.status_code}")
                return False

        except requests.exceptions.SSLError as e:
            log.error(f"SSL error during password authentication: {e}")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.error(f"Password authentication failed: {e}")
            return False

    def logout(self) -> bool:
        """
        Logout from UniFi Controller and clear session.

        Returns:
            bool: True if logout successful
        """
        if not self.is_authenticated:
            log.debug("Not authenticated, nothing to logout")
            return True

        try:
            # Only logout for password-based auth
            if self.successful_endpoint and "password" in self.successful_endpoint:
                endpoint = self.endpoint_builder.logout()

                try:
                    response = self.session.post(endpoint)
                    if response.status_code == 200:
                        log.info("Successfully logged out")
                    else:
                        log.debug(f"Logout response: {response.status_code}")
                except Exception as e:
                    log.debug(f"Logout request failed: {e}")

            # Clear authentication state
            self.session.close()
            self.is_authenticated = False
            self.successful_endpoint = None
            log.debug("Session cleared and authentication state reset")
            return True

        except Exception as e:
            log.error(f"Error during logout: {e}")
            return False

    def clear_credentials(self) -> None:
        """Securely clear stored credentials from memory."""
        if self._password:
            self._password = "X" * len(self._password)
            self._password = None

        if self._api_token:
            self._api_token = "X" * len(self._api_token)
            self._api_token = None

        self._username = None
        self._username_hash = None
        self._password_hash = None
        self._token_hash = None

        log.debug("Credentials securely cleared from memory")

    def __del__(self):
        """Destructor to ensure credentials are cleared."""
        try:
            self.clear_credentials()
        except:
            pass
