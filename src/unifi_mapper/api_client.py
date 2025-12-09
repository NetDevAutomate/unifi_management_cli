#!/usr/bin/env python3
"""
API client module for the UniFi Port Mapper.
Contains the UnifiApiClient class for interacting with the UniFi Controller API.
"""

import os
import json
import logging
import requests
import datetime
import getpass
import hashlib
import time
from typing import Dict, List, Any, Optional, Tuple
from requests.exceptions import RequestException, ConnectionError, Timeout, HTTPError

from .models import DeviceInfo, PortInfo
from .exceptions import (
    UniFiApiError,
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiTimeoutError,
    UniFiPermissionError,
    UniFiValidationError
)

log = logging.getLogger(__name__)


def _sanitize_for_logging(value: str, max_chars: int = 4) -> str:
    """
    Sanitize sensitive values for logging by showing only first/last few characters.
    
    Args:
        value: The sensitive value to sanitize
        max_chars: Maximum characters to show from start/end
        
    Returns:
        Sanitized string safe for logging
    """
    if not value or len(value) <= max_chars * 2:
        return "*" * len(value) if value else ""
    return f"{value[:max_chars]}...{value[-max_chars:]}"


def _hash_for_verification(value: str) -> str:
    """
    Create a hash of sensitive data for verification purposes without exposing the actual value.
    
    Args:
        value: The value to hash
        
    Returns:
        SHA256 hash of the value
    """
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _sanitize_response_for_logging(response_text: str, max_length: int = 200) -> str:
    """
    Sanitize response text for logging by removing potential sensitive information.
    
    Args:
        response_text: Raw response text
        max_length: Maximum length to return
        
    Returns:
        Sanitized response text safe for logging
    """
    if not response_text:
        return ""
    
    # Remove common sensitive patterns
    import re
    sanitized = response_text
    
    # Remove potential credentials, tokens, keys
    sanitized = re.sub(r'("(?:password|token|key|secret)[^"]*":\s*)"[^"]*"', r'\1"***"', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'("(?:auth|login)[^"]*":\s*)"[^"]*"', r'\1"***"', sanitized, flags=re.IGNORECASE)
    
    # Remove potential MAC addresses
    sanitized = re.sub(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', 'XX:XX:XX:XX:XX:XX', sanitized)
    
    # Remove potential IP addresses (partially)
    sanitized = re.sub(r'\b(\d{1,3}\.)\d{1,3}(\.\d{1,3}\.\d{1,3})\b', r'\1***\2', sanitized)
    
    # Truncate to max length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    
    return sanitized


class UnifiApiClient:
    """Class to interact with the UniFi Controller API."""
    
    def __init__(self, base_url: str, site: str = "default", verify_ssl: bool = False,
                 username: str = None, password: str = None, api_token: str = None,
                 timeout: int = 10, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Initialize the UnifiApiClient.
        
        Args:
            base_url: The base URL of the UniFi Controller (e.g., https://unifi.local:8443)
            site: The site name (default: "default")
            verify_ssl: Whether to verify SSL certificates (default: False)
            username: The username for the UniFi Controller (for username/password auth)
            password: The password for the UniFi Controller (for username/password auth)
            api_token: The API token for the UniFi Controller (for token-based auth)
            timeout: Connection timeout in seconds (default: 10)
            max_retries: Maximum number of retry attempts for failed requests (default: 3)
            retry_delay: Delay between retry attempts in seconds (default: 1.0)
        """
        # Validate and sanitize inputs
        if not base_url:
            raise ValueError("Base URL is required")
        
        self.base_url = base_url.rstrip('/').strip()
        
        # Validate URL format
        if not (self.base_url.startswith('http://') or self.base_url.startswith('https://')):
            raise ValueError("Base URL must start with http:// or https://")
        
        # Securely store credentials (avoid storing in plain text where possible)
        self._username = username.strip() if username else None
        self._password = password if password else None  # Keep password as-is for hashing
        self._api_token = api_token.strip() if api_token else None
        
        # Store credential hashes for logging/verification without exposing actual values
        self._username_hash = _hash_for_verification(self._username) if self._username else None
        self._password_hash = _hash_for_verification(self._password) if self._password else None
        self._token_hash = _hash_for_verification(self._api_token) if self._api_token else None
        
        self.site = site.strip() if site else "default"
        self.verify_ssl = verify_ssl
        self.timeout = max(1, min(timeout, 300))  # Clamp timeout between 1-300 seconds
        self.max_retries = max(1, min(max_retries, 10))  # Clamp retries between 1-10
        self.retry_delay = max(0.1, min(retry_delay, 10.0))  # Clamp delay between 0.1-10 seconds
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.is_authenticated = False
        self.auth_method = "token" if api_token else "username_password"
        self.successful_endpoint = None  # Store the successful endpoint
        self.is_unifi_os = False  # Whether this is a UniFi OS device (UDM, UDM Pro, etc.)
        self._last_error = None  # Store last error for debugging
        
        # Log initialization with sanitized values
        log.info(f"Initializing UniFi API client for {_sanitize_for_logging(self.base_url, 8)}")
        log.debug(f"Site: {self.site}, SSL verify: {self.verify_ssl}, Timeout: {self.timeout}s")
        if self._username_hash:
            log.debug(f"Username hash: {self._username_hash}")
        if self._token_hash:
            log.debug(f"Token hash: {self._token_hash}")
        if self._password_hash:
            log.debug(f"Password hash: {self._password_hash}")
        
        # API headers
        self.legacy_headers = {
            'User-Agent': 'UnifiPortMapper/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        self.integration_headers = {
            'User-Agent': 'UnifiPortMapper/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def _retry_request(self, func, *args, **kwargs):
        """
        Execute a request with retry logic and exponential backoff.
        
        Args:
            func: Function to execute
            *args: Arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            The result of the function call
            
        Raises:
            UniFiApiError: When all retry attempts are exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Timeout as e:
                # Handle timeout separately before ConnectionError
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    log.warning(f"Request timed out (attempt {attempt + 1}/{self.max_retries}). Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    raise UniFiTimeoutError(f"Request timed out after {self.max_retries} attempts: {e}")
            except HTTPError as e:
                last_exception = e

                # Don't retry on authentication errors
                if e.response.status_code in [401, 403]:
                    raise UniFiAuthenticationError(f"Authentication failed: {e}", status_code=e.response.status_code)

                # Don't retry on client errors (4xx except auth/timeout/rate-limit)
                if 400 <= e.response.status_code < 500 and e.response.status_code not in [401, 403, 408, 429]:
                    raise UniFiPermissionError(f"Client error: {e}")

                # Retry on server errors and retryable client errors
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    log.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    log.error(f"Request failed after {self.max_retries} attempts: {e}")
            except ConnectionError as e:
                last_exception = e
                delay = self.retry_delay * (2 ** attempt)

                if attempt < self.max_retries - 1:
                    log.warning(f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    raise UniFiConnectionError(f"Connection failed after {self.max_retries} attempts: {e}")
            except RequestException as e:
                # Handle other request exceptions
                last_exception = e
                if "timeout" in str(e).lower():
                    raise UniFiTimeoutError(f"Request timed out: {e}")
                elif "connection" in str(e).lower():
                    raise UniFiConnectionError(f"Connection failed: {e}")
                else:
                    raise UniFiApiError(f"Request failed: {e}")
            except Exception as e:
                # Handle unexpected errors
                last_exception = e
                log.error(f"Unexpected error during request: {e}")
                raise UniFiApiError(f"Unexpected error: {e}")

        # If we get here, all retries failed
        if last_exception:
            if isinstance(last_exception, Timeout):
                raise UniFiTimeoutError(f"Request timed out after {self.max_retries} attempts: {last_exception}")
            elif isinstance(last_exception, ConnectionError):
                raise UniFiConnectionError(f"Connection failed after {self.max_retries} attempts: {last_exception}")
            else:
                raise UniFiApiError(f"Request failed after {self.max_retries} attempts: {last_exception}")
        else:
            raise UniFiApiError(f"Request failed after {self.max_retries} attempts")

    def login(self) -> bool:
        """
        Login to the UniFi Controller.
        
        Returns:
            bool: True if login was successful, False otherwise
            
        Raises:
            UniFiAuthenticationError: When authentication fails
            UniFiConnectionError: When connection fails
            UniFiValidationError: When validation fails
        """
        # Check if we're already authenticated
        if self.is_authenticated:
            log.debug("Already authenticated, skipping login")
            return True
        
        # Validate we have credentials
        if self.auth_method == "token" and not self._api_token:
            raise UniFiValidationError("API token authentication selected but no token provided")
        elif self.auth_method == "username_password" and (not self._username or not self._password):
            raise UniFiValidationError("Username/password authentication selected but credentials missing")
        
        log.info(f"Attempting authentication using {self.auth_method} method")
        
        try:
            return self._perform_login()
        except UniFiApiError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            self._last_error = str(e)
            log.error(f"Unexpected error during login: {e}")
            raise UniFiApiError(f"Login failed: {e}")

    def _perform_login(self) -> bool:
        """
        Internal method to perform the actual login process.
        
        Returns:
            bool: True if login was successful, False otherwise
        """
        # Check if we're dealing with a UniFi OS device (UDM, UDM Pro, etc.)
        try:
            # Try to access the /api/system endpoint which is only available on UniFi OS devices
            def _check_unifi_os():
                return requests.get(
                    f"{self.base_url}/api/system", 
                    verify=self.verify_ssl, 
                    timeout=self.timeout
                )
            
            response = self._retry_request(_check_unifi_os)
            self.is_unifi_os = response.status_code == 200
            log.debug(f"UniFi OS detection: {self.is_unifi_os}")
        except UniFiApiError as e:
            # If we can't detect UniFi OS, assume it's a legacy controller
            log.debug(f"UniFi OS detection failed, assuming legacy controller: {e}")
            self.is_unifi_os = False
        except Exception as e:
            log.debug(f"UniFi OS detection failed: {e}")
            self.is_unifi_os = False
        
        # Set up the session with proper SSL handling for self-signed certificates
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        
        # For self-signed certificates, we need to disable SSL warnings if verify_ssl is False
        if not self.verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log.debug("SSL verification disabled - suitable for self-signed certificates")
        
        # Set up headers
        self.session.headers.update(self.legacy_headers)
        
        # Try to authenticate
        if self.auth_method == "token":
            # Token-based authentication
            log.debug(f"Attempting token authentication with hash: {self._token_hash}")
            
            # Try X-API-KEY header first
            self.session.headers.update({
                'X-API-KEY': self._api_token
            })
            
            try:
                def _try_api_key_auth():
                    if self.is_unifi_os:
                        # For UniFi OS devices, try the /proxy/network/api/s/{site}/self endpoint
                        return self.session.get(f"{self.base_url}/proxy/network/api/s/{self.site}/self", timeout=self.timeout)
                    else:
                        # For legacy controllers, try the /api/s/{site}/self endpoint
                        return self.session.get(f"{self.base_url}/api/s/{self.site}/self", timeout=self.timeout)
                
                response = self._retry_request(_try_api_key_auth)
                if response.status_code == 200:
                    self.is_authenticated = True
                    self.successful_endpoint = "api_token"
                    log.info(f"Successfully authenticated with API token (X-API-KEY) - hash: {self._token_hash}")
                    return True
            except UniFiApiError as e:
                log.debug(f"API token authentication failed: {e}")
            except requests.exceptions.SSLError as e:
                log.error(f"SSL error during token authentication: {e}")
                if not self.verify_ssl:
                    log.info("Hint: This may be due to self-signed certificate. SSL verification is disabled.")
                raise UniFiConnectionError(f"SSL error: {e}")
            
            # If X-API-KEY header didn't work, try Authorization header
            self.session.headers.update({
                'Authorization': f"Bearer {self._api_token}"
            })
            
            try:
                def _try_bearer_auth():
                    if self.is_unifi_os:
                        # For UniFi OS devices, try the /proxy/network/api/s/{site}/self endpoint
                        return self.session.get(f"{self.base_url}/proxy/network/api/s/{self.site}/self", timeout=self.timeout)
                    else:
                        # For legacy controllers, try the /api/s/{site}/self endpoint
                        return self.session.get(f"{self.base_url}/api/s/{self.site}/self", timeout=self.timeout)
                
                response = self._retry_request(_try_bearer_auth)
                if response.status_code == 200:
                    self.is_authenticated = True
                    self.successful_endpoint = "bearer_token"
                    log.info(f"Successfully authenticated with Bearer token - hash: {self._token_hash}")
                    return True
            except UniFiApiError as e:
                log.debug(f"Bearer token authentication failed: {e}")
            except requests.exceptions.SSLError as e:
                log.error(f"SSL error during bearer token authentication: {e}")
                raise UniFiConnectionError(f"SSL error: {e}")
        else:
            # Username/password authentication
            log.debug(f"Attempting username/password authentication - username hash: {self._username_hash}")
            
            try:
                if self.is_unifi_os:
                    # For UniFi OS devices, use the /api/auth/login endpoint
                    def _try_unifi_os_login():
                        login_url = f"{self.base_url}/api/auth/login"
                        login_data = {
                            "username": self._username,
                            "password": self._password
                        }
                        return self.session.post(login_url, json=login_data, timeout=self.timeout)
                    
                    response = self._retry_request(_try_unifi_os_login)
                    if response.status_code == 200:
                        self.is_authenticated = True
                        self.successful_endpoint = "unifi_os_login"
                        log.info(f"Successfully authenticated with username/password (UniFi OS) - user hash: {self._username_hash}")
                        return True
                else:
                    # For legacy controllers, use the /api/login endpoint
                    def _try_legacy_login():
                        login_url = f"{self.base_url}/api/login"
                        login_data = {
                            "username": self._username,
                            "password": self._password
                        }
                        return self.session.post(login_url, json=login_data, timeout=self.timeout)
                    
                    response = self._retry_request(_try_legacy_login)
                    if response.status_code == 200:
                        self.is_authenticated = True
                        self.successful_endpoint = "legacy_login"
                        log.info(f"Successfully authenticated with username/password (legacy) - user hash: {self._username_hash}")
                        return True
            except UniFiApiError as e:
                log.debug(f"Username/password authentication failed: {e}")
            except requests.exceptions.SSLError as e:
                log.error(f"SSL error during username/password authentication: {e}")
                if not self.verify_ssl:
                    log.info("Hint: This may be due to self-signed certificate. SSL verification is disabled.")
                raise UniFiConnectionError(f"SSL error: {e}")
            except Exception as e:
                log.debug(f"Username/password authentication failed: {e}")
        
        # If we got here, authentication failed
        log.error("Authentication failed - all methods exhausted")
        return False
    
    def logout(self) -> bool:
        """
        Logout from the UniFi Controller and clear session.
        
        Returns:
            bool: True if logout was successful, False otherwise
        """
        if not self.is_authenticated:
            log.debug("Not authenticated, nothing to logout")
            return True
        
        try:
            # Attempt to logout if we have an active session
            if self.successful_endpoint in ["legacy_login", "unifi_os_login"]:
                if self.is_unifi_os:
                    logout_url = f"{self.base_url}/api/auth/logout"
                else:
                    logout_url = f"{self.base_url}/api/logout"
                
                try:
                    response = self.session.post(logout_url, timeout=self.timeout)
                    if response.status_code == 200:
                        log.info("Successfully logged out from UniFi Controller")
                    else:
                        log.debug(f"Logout response: {response.status_code}")
                except Exception as e:
                    log.debug(f"Logout request failed: {e}")
            
            # Clear session and authentication state
            self.session.close()
            self.is_authenticated = False
            self.successful_endpoint = None
            
            log.debug("Session cleared and authentication state reset")
            return True
            
        except Exception as e:
            log.error(f"Error during logout: {e}")
            return False
    
    def clear_credentials(self) -> None:
        """
        Securely clear stored credentials from memory.
        This should be called when the client is no longer needed.
        """
        if self._password:
            # Overwrite password in memory
            self._password = "X" * len(self._password)
            self._password = None
        
        if self._api_token:
            # Overwrite token in memory
            self._api_token = "X" * len(self._api_token)
            self._api_token = None
        
        # Clear username (less sensitive but good practice)
        self._username = None
        
        # Clear hashes
        self._username_hash = None
        self._password_hash = None
        self._token_hash = None
        
        # Close session
        if hasattr(self, 'session'):
            self.session.close()
        
        log.debug("Credentials securely cleared from memory")
    
    def __del__(self):
        """Destructor to ensure credentials are cleared when object is destroyed."""
        try:
            self.clear_credentials()
        except:
            pass  # Ignore errors during cleanup
    
    def _validate_site_id(self, site_id: str) -> str:
        """
        Validate and sanitize site_id to prevent injection attacks.
        
        Args:
            site_id: Site ID to validate
            
        Returns:
            str: Validated and sanitized site ID
            
        Raises:
            ValueError: If site_id is invalid
        """
        if not site_id or not isinstance(site_id, str):
            raise ValueError("Site ID must be a non-empty string")
        
        # Remove any potentially dangerous characters
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', site_id.strip())
        
        if not sanitized:
            raise ValueError("Site ID contains no valid characters")
        
        if len(sanitized) > 50:  # Reasonable limit for site IDs
            raise ValueError("Site ID is too long")
        
        return sanitized
    
    def _validate_device_id(self, device_id: str) -> str:
        """
        Validate and sanitize device_id to prevent injection attacks.
        
        Args:
            device_id: Device ID to validate
            
        Returns:
            str: Validated and sanitized device ID
            
        Raises:
            ValueError: If device_id is invalid
        """
        if not device_id or not isinstance(device_id, str):
            raise ValueError("Device ID must be a non-empty string")
        
        # Remove any potentially dangerous characters - UniFi device IDs are typically hex
        import re
        sanitized = re.sub(r'[^a-fA-F0-9]', '', device_id.strip())
        
        if not sanitized:
            raise ValueError("Device ID contains no valid characters")
        
        if len(sanitized) not in [24, 32]:  # Typical UniFi device ID lengths
            log.warning(f"Device ID length unusual: {len(sanitized)} characters")
        
        return sanitized
    
    def _validate_port_name(self, port_name: str) -> str:
        """
        Validate and sanitize port name to prevent injection attacks.
        
        Args:
            port_name: Port name to validate
            
        Returns:
            str: Validated and sanitized port name
            
        Raises:
            ValueError: If port_name is invalid
        """
        if not port_name or not isinstance(port_name, str):
            raise ValueError("Port name must be a non-empty string")
        
        # Remove dangerous characters but allow reasonable port name characters
        import re
        sanitized = re.sub(r'[<>"\'\\\x00-\x1f\x7f]', '', port_name.strip())
        
        if not sanitized:
            raise ValueError("Port name contains no valid characters")
        
        if len(sanitized) > 100:  # Reasonable limit for port names
            raise ValueError("Port name is too long")
        
        return sanitized
    
    def get_devices(self, site_id: str) -> Dict[str, Any]:
        """
        Get all devices from the UniFi Controller.
        
        Args:
            site_id: Site ID
        
        Returns:
            Dict[str, Any]: Dictionary of devices
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
        except ValueError as e:
            log.error(f"Invalid site_id: {e}")
            return {}
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get devices")
            return {}
        
        try:
            # Determine the correct endpoint based on UniFi OS detection
            if self.is_unifi_os:
                devices_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/device"
            else:
                devices_endpoint = f"{self.base_url}/api/s/{site_id}/stat/device"
                
            # Use legacy headers for this request
            self.session.headers.update(self.legacy_headers)
            
            def _try_get_devices():
                return self.session.get(devices_endpoint, timeout=self.timeout)
            
            response = self._retry_request(_try_get_devices)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401 or response.status_code == 403:
                log.warning("Authentication issue with devices endpoint. Attempting to re-authenticate...")
                if self.login():
                    log.info("Re-authentication successful, retrying devices retrieval")
                    response = self._retry_request(_try_get_devices)
                    if response.status_code == 200:
                        return response.json()
            else:
                log.error(f"Failed to get devices: {response.status_code}")
        except UniFiApiError as e:
            log.error(f"API error getting devices: {e}")
        except requests.exceptions.SSLError as e:
            log.error(f"SSL error getting devices: {e}")
            if not self.verify_ssl:
                log.info("Hint: This may be due to self-signed certificate. SSL verification is disabled.")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.error(f"Error getting devices: {e}")
        
        return {}
    
    def get_clients(self, site_id: str) -> Dict[str, Any]:
        """
        Get all clients from the UniFi Controller.
        
        Args:
            site_id: Site ID
        
        Returns:
            Dict[str, Any]: Dictionary of clients
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
        except ValueError as e:
            log.error(f"Invalid site_id: {e}")
            return {}
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get clients")
            return {}
        
        try:
            # Determine the correct endpoint based on UniFi OS detection
            if self.is_unifi_os:
                clients_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/sta"
            else:
                clients_endpoint = f"{self.base_url}/api/s/{site_id}/stat/sta"
                
            # Use legacy headers for this request
            self.session.headers.update(self.legacy_headers)
            
            def _try_get_clients():
                return self.session.get(clients_endpoint, timeout=self.timeout)
            
            response = self._retry_request(_try_get_clients)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401 or response.status_code == 403:
                log.warning("Authentication issue with clients endpoint. Attempting to re-authenticate...")
                if self.login():
                    log.info("Re-authentication successful, retrying clients retrieval")
                    response = self._retry_request(_try_get_clients)
                    if response.status_code == 200:
                        return response.json()
            else:
                log.error(f"Failed to get clients: {response.status_code}")
        except UniFiApiError as e:
            log.error(f"API error getting clients: {e}")
        except requests.exceptions.SSLError as e:
            log.error(f"SSL error getting clients: {e}")
            if not self.verify_ssl:
                log.info("Hint: This may be due to self-signed certificate. SSL verification is disabled.")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.error(f"Error getting clients: {e}")
        
        return {}
    
    def get_device_details(self, site_id: str, device_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a device.
        
        Args:
            site_id: Site ID
            device_id: Device ID
        
        Returns:
            Dict[str, Any]: Device details
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
            device_id = self._validate_device_id(device_id)
        except ValueError as e:
            log.error(f"Invalid input for device details: {e}")
            return {}
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get device details")
            return {}
        
        device_details = {}
        
        try:
            # Try multiple API endpoints to get device details
            endpoints_to_try = []
            
            # Standard device endpoints
            if self.is_unifi_os:
                endpoints_to_try.append(f"{self.base_url}/proxy/network/api/s/{site_id}/stat/device/{device_id}")
                endpoints_to_try.append(f"{self.base_url}/proxy/network/api/s/{site_id}/rest/device/{device_id}")
            else:
                endpoints_to_try.append(f"{self.base_url}/api/s/{site_id}/stat/device/{device_id}")
                endpoints_to_try.append(f"{self.base_url}/api/s/{site_id}/rest/device/{device_id}")
            
            # Try each endpoint until we get a successful response
            for endpoint in endpoints_to_try:
                try:
                    # Use legacy headers for this request
                    self.session.headers.update(self.legacy_headers)
                    
                    log.debug(f"Getting device details from endpoint: {endpoint}")
                    
                    def _try_get_device_details():
                        return self.session.get(endpoint, timeout=self.timeout)
                    
                    response = self._retry_request(_try_get_device_details)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if "data" in data and len(data["data"]) > 0:
                            device_details = data["data"][0]
                            log.debug(f"Successfully got device details from {endpoint}")
                            return device_details
                    elif response.status_code == 401 or response.status_code == 403:
                        log.warning("Authentication issue with device endpoint. Attempting to re-authenticate...")
                        if self.login():
                            log.info("Re-authentication successful, retrying device details retrieval")
                            # Try again with the same endpoint after re-authentication
                            response = self._retry_request(_try_get_device_details)
                            if response.status_code == 200:
                                data = response.json()
                                if "data" in data and len(data["data"]) > 0:
                                    device_details = data["data"][0]
                                    log.debug(f"Successfully got device details after re-auth from {endpoint}")
                                    return device_details
                    else:
                        # Use debug level for 400 errors as they're expected for some device types
                        if response.status_code == 400:
                            log.debug(f"Device endpoint not supported: {endpoint} (status code 400)")
                        else:
                            log.debug(f"Failed to get device details from {endpoint}: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    log.debug(f"Request error getting device details from {endpoint}: {e}")
            
            # If we couldn't get device details from any endpoint, try to get it from the devices list
            try:
                devices_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/device" if self.is_unifi_os else f"{self.base_url}/api/s/{site_id}/stat/device"
                
                def _try_get_devices_fallback():
                    return self.session.get(devices_endpoint, timeout=self.timeout)
                
                response = self._retry_request(_try_get_devices_fallback)
                if response.status_code == 200:
                    data = response.json()
                    
                    if "data" in data:
                        # Find the device in the list
                        for device in data["data"]:
                            if device.get("_id") == device_id or device.get("mac") == device_id:
                                device_details = device
                                log.debug(f"Found device details in devices list")
                                return device_details
            except Exception as e:
                log.debug(f"Error getting device from devices list: {e}")
            
            # If we still couldn't get device details, try to create a minimal device details object
            if not device_details:
                log.debug(f"Creating minimal device details for device {device_id}")
                # Try to extract MAC address from device_id if it looks like a MAC
                mac = device_id
                if len(device_id) == 24 and ":" in device_id:  # Standard MAC format with colons
                    mac = device_id
                elif len(device_id) == 12 and ":" not in device_id:  # MAC without colons
                    mac = ":".join([device_id[i:i+2] for i in range(0, 12, 2)])
                
                # Create minimal device details
                device_details = {
                    "_id": device_id,
                    "mac": mac,
                    "name": f"Device {device_id[-6:]}",  # Use last 6 chars of ID as name
                    "model": "Unknown",
                    "type": "unknown"
                }
                return device_details
        except Exception as e:
            log.error(f"Error getting device details: {e}")
        
        return device_details
    
    def get_device_ports(self, site_id: str, device_id: str) -> List[Dict[str, Any]]:
        """
        Get all ports for a device.
        
        Args:
            site_id: Site ID
            device_id: Device ID
        
        Returns:
            List[Dict[str, Any]]: List of ports
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
            device_id = self._validate_device_id(device_id)
        except ValueError as e:
            log.error(f"Invalid input for device ports: {e}")
            return []
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get device ports")
            return []
            
        # First, try to get device details which should include port information
        device_data = self.get_device_details(site_id, device_id)
        
        # Check if we got device details and if it has a port_table
        if device_data and "port_table" in device_data:
            # Process port status information
            port_table = device_data["port_table"]
            
            # Try to enhance port status information
            try:
                # Get client information to determine port status
                clients_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/sta" if self.is_unifi_os else f"{self.base_url}/api/s/{site_id}/stat/sta"
                
                def _try_get_clients_for_ports():
                    return self.session.get(clients_endpoint, timeout=self.timeout)
                
                clients_response = self._retry_request(_try_get_clients_for_ports)
                
                if clients_response.status_code == 200:
                    clients_data = clients_response.json()
                    if "data" in clients_data:
                        # Create a map of port_idx to client info
                        port_client_map = {}
                        for client in clients_data["data"]:
                            if client.get("sw_mac") == device_data.get("mac"):
                                port_idx = client.get("sw_port")
                                if port_idx is not None:
                                    port_client_map[port_idx] = client
                        
                        # Update port status based on client information
                        for port in port_table:
                            port_idx = port.get("port_idx")
                            if port_idx in port_client_map:
                                # Port has a client connected
                                port["up"] = True
                                client = port_client_map[port_idx]
                                port["client_name"] = client.get("name", client.get("hostname", "Unknown Client"))
                                port["client_mac"] = client.get("mac", "")
            except Exception as e:
                log.debug(f"Error enhancing port status: {e}")
            
            return port_table
        
        # If we couldn't get port_table from device details, try to create a default one based on device model
        model = device_data.get("model", "")
        if model:
            # Create default ports based on model
            if "usw" in model.lower() or "switch" in model.lower() or "us-" in model.lower() or "usl" in model.lower():
                # For switches, create default ports
                port_count = 8  # Default port count
                
                # Adjust port count based on model
                if "24" in model:
                    port_count = 24
                elif "16" in model:
                    port_count = 16
                elif "8" in model:
                    port_count = 8
                elif "48" in model:
                    port_count = 48
                
                # Create default port table
                default_ports = []
                for i in range(1, port_count + 1):
                    # Check if this is an SFP port
                    is_sfp = False
                    if port_count > 8 and i > port_count - 4:
                        is_sfp = True  # Last 4 ports on larger switches are often SFP
                    
                    default_ports.append({
                        "port_idx": i,
                        "name": f"Port {i}",
                        "media": "SFP" if is_sfp else "RJ45",
                        "up": False,
                        "enable": True,
                        "speed": 1000,
                        "poe_enable": not is_sfp  # SFP ports don't have PoE
                    })
                return default_ports
            elif "udm" in model.lower() or "usg" in model.lower() or "gateway" in model.lower() or "ugw" in model.lower():
                # For routers/gateways, create default ports
                port_count = 4  # Default port count
                
                # Adjust port count based on model
                if "pro" in model.lower():
                    port_count = 8
                elif "max" in model.lower():
                    port_count = 10
                
                # Create default port table
                default_ports = []
                for i in range(1, port_count + 1):
                    # Check if this is an SFP port
                    is_sfp = False
                    if port_count > 4 and i > port_count - 2:
                        is_sfp = True  # Last 2 ports on larger routers are often SFP
                    
                    default_ports.append({
                        "port_idx": i,
                        "name": f"Port {i}",
                        "media": "SFP" if is_sfp else "RJ45",
                        "up": False,
                        "enable": True,
                        "speed": 1000,
                        "poe_enable": False  # Routers typically don't have PoE
                    })
                return default_ports
        
        # Return default port table as fallback based on device ID
        # This is a last resort when we can't determine the device model
        default_ports = []
        for i in range(1, 9):  # Default to 8 ports
            default_ports.append({
                "port_idx": i,
                "name": f"Port {i}",
                "media": "RJ45",
                "up": False,
                "enable": True,
                "speed": 1000,
                "poe_enable": False
            })
        return default_ports
        
    def get_lldp_info(self, site_id: str, device_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get LLDP/CDP information for a device's ports with MAC resolution.

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping port index to LLDP information
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
            device_id = self._validate_device_id(device_id)
        except ValueError as e:
            log.error(f"Invalid input for LLDP info: {e}")
            return {}

        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get LLDP info")
            return {}

        port_lldp_info = {}

        try:
            # Build MAC to device name cache if needed
            if not hasattr(self, '_mac_to_device_cache'):
                self._mac_to_device_cache = {}
                self._build_mac_to_device_cache(site_id)

            # FIX: LLDP data is already available in device details under 'lldp_table'
            device_details = self.get_device_details(site_id, device_id)

            if device_details and "lldp_table" in device_details:
                lldp_table = device_details["lldp_table"]
                log.debug(f"Found lldp_table with {len(lldp_table)} entries for device {device_id}")

                # Process each LLDP entry with MAC resolution
                for entry in lldp_table:
                    local_port_idx = entry.get("local_port_idx")
                    if local_port_idx is not None:
                        chassis_id = entry.get("chassis_id", "")
                        system_name = entry.get("system_name", "")
                        chassis_name = entry.get("chassis_name", "")

                        # Resolve MAC to device name if system_name not available
                        remote_device_name = system_name or chassis_name
                        if not remote_device_name and chassis_id:
                            remote_device_name = self._resolve_mac_to_device_name(chassis_id)

                        port_lldp_info[str(local_port_idx)] = {
                            "port_idx": local_port_idx,
                            "chassis_id": chassis_id,
                            "port_id": entry.get("port_id", ""),
                            "system_name": system_name,
                            "chassis_name": chassis_name,
                            "remote_device_name": remote_device_name,
                            "remote_port_name": entry.get("port_id", ""),
                            "remote_chassis_id": chassis_id,
                            "is_wired": entry.get("is_wired", True),
                            "local_port_name": entry.get("local_port_name", "")
                        }
                        log.debug(f"Mapped LLDP for port {local_port_idx}: {remote_device_name or chassis_id}")
            else:
                log.debug(f"No lldp_table found in device details for device {device_id}")

        except Exception as e:
            log.error(f"Error getting LLDP/CDP information: {e}")

        log.info(f"Retrieved LLDP info for {len(port_lldp_info)} ports on device {device_id}")
        return port_lldp_info

    def _build_mac_to_device_cache(self, site_id: str) -> None:
        """Build cache mapping MAC addresses to device names."""
        try:
            devices_response = self.get_devices(site_id)
            if not devices_response or "data" not in devices_response:
                return

            for device in devices_response["data"]:
                mac = device.get("mac", "").lower()
                name = device.get("name", "Unknown")

                if mac:
                    self._mac_to_device_cache[mac] = name
                    self._mac_to_device_cache[mac.replace(":", "")] = name
                    self._mac_to_device_cache[mac.upper()] = name
                    self._mac_to_device_cache[mac.upper().replace(":", "")] = name

            log.debug(f"Built MAC cache with {len(devices_response['data'])} devices")
        except Exception as e:
            log.error(f"Error building MAC cache: {e}")

    def _resolve_mac_to_device_name(self, chassis_id: str) -> str:
        """Resolve MAC address to device name."""
        if not chassis_id:
            return ""

        mac_formats = [chassis_id.lower(), chassis_id.upper(),
                      chassis_id.lower().replace(":", ""),
                      chassis_id.upper().replace(":", "")]

        for mac_format in mac_formats:
            if mac_format in self._mac_to_device_cache:
                return self._mac_to_device_cache[mac_format]

        return chassis_id
    
    def update_port_name(self, site_id: str, device_id: str, port_idx: int, name: str) -> bool:
        """
        Update the name of a port.
        
        Args:
            site_id: Site ID
            device_id: Device ID
            port_idx: Port index
            name: New port name
        
        Returns:
            bool: True if the update was successful, False otherwise
        """
        # Validate inputs
        try:
            site_id = self._validate_site_id(site_id)
            device_id = self._validate_device_id(device_id)
            name = self._validate_port_name(name)
        except ValueError as e:
            log.error(f"Invalid input for port name update: {e}")
            return False
        
        # Validate port index
        if not isinstance(port_idx, int) or port_idx < 1 or port_idx > 100:
            log.error(f"Invalid port index: {port_idx}")
            return False
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot update port name")
            return False
        
        try:
            # Determine the correct endpoint based on UniFi OS detection
            if self.is_unifi_os:
                port_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/rest/device/{device_id}"
            else:
                port_endpoint = f"{self.base_url}/api/s/{site_id}/rest/device/{device_id}"
                
            # Use legacy headers for this request
            self.session.headers.update(self.legacy_headers)
            
            # Get the current device details
            device_details = self.get_device_details(site_id, device_id)
            
            if not device_details:
                log.error(f"Failed to get device details for device {device_id}")
                return False
            
            # Find the port in the port_table
            port_table = device_details.get("port_table", [])
            port_found = False
            
            for port in port_table:
                if port.get("port_idx") == port_idx:
                    port_found = True
                    port["name"] = name
                    break
            
            if not port_found:
                log.error(f"Port {port_idx} not found in device {device_id}")
                return False
            
            # Update the device with the new port_table
            update_data = {
                "port_table": port_table
            }
            
            def _try_update_port():
                return self.session.put(port_endpoint, json=update_data, timeout=self.timeout)
            
            response = self._retry_request(_try_update_port)
            
            if response.status_code == 200:
                log.info(f"Successfully updated port {port_idx} name to '{name}' for device {device_id}")
                return True
            else:
                log.error(f"Failed to update port name: {response.status_code}")
                return False
        except Exception as e:
            log.error(f"Error updating port name: {e}")
            return False
    
    def update_device_port_table(self, device_id: str, port_table: List[Dict[str, Any]]) -> bool:
        """
        Update the entire port table for a device in a single API call.
        
        Args:
            device_id: Device ID
            port_table: Complete port table with updates
        
        Returns:
            bool: True if the update was successful, False otherwise
        """
        # Validate inputs
        try:
            device_id = self._validate_device_id(device_id)
        except ValueError as e:
            log.error(f"Invalid device_id for port table update: {e}")
            return False
        
        if not isinstance(port_table, list):
            log.error("Port table must be a list")
            return False
        
        # Validate port table entries
        for i, port in enumerate(port_table):
            if not isinstance(port, dict):
                log.error(f"Port table entry {i} must be a dictionary")
                return False
            
            # Validate port name if present
            if "name" in port:
                try:
                    port["name"] = self._validate_port_name(port["name"])
                except ValueError as e:
                    log.error(f"Invalid port name in port table entry {i}: {e}")
                    return False
        
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot update device port table")
            return False
        
        try:
            # Get current device configuration first
            device_details = self.get_device_details(self.site, device_id)
            if not device_details:
                log.error(f"Failed to get current device details for {device_id}")
                return False
            
            # Try multiple approaches for updating port configuration
            success = False
            
            # Approach 1: Use device configuration endpoint with complete config
            success = self._update_device_config_with_ports(device_id, device_details, port_table)
            
            if not success:
                # Approach 2: Use port-specific endpoint if available
                success = self._update_ports_via_port_endpoint(device_id, port_table)
            
            if not success:
                # Approach 3: Use legacy device update method
                success = self._update_device_legacy_method(device_id, device_details, port_table)
            
            if success:
                log.info(f"Successfully updated port table for device {device_id}")
                # Wait for UniFi to process the change
                import time
                time.sleep(5)  # Even longer wait time for better persistence
                return True
            else:
                log.error(f"All update methods failed for device {device_id}")
                return False
                
        except Exception as e:
            log.error(f"Error updating port table: {e}")
            return False
    
    def _update_device_config_with_ports(self, device_id: str, device_details: Dict[str, Any], port_table: List[Dict[str, Any]]) -> bool:
        """
        Update device configuration with complete device context (recommended approach).
        
        Args:
            device_id: Device ID
            device_details: Current device configuration
            port_table: Updated port table
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Determine the correct endpoint
            if self.is_unifi_os:
                endpoint = f"{self.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}"
            else:
                endpoint = f"{self.base_url}/api/s/{self.site}/rest/device/{device_id}"
            
            # Use legacy headers
            self.session.headers.update(self.legacy_headers)
            
            # Create comprehensive update payload with all current device config
            update_data = device_details.copy()  # Start with current config
            
            # Update the port table
            update_data["port_table"] = port_table
            
            # Ensure required fields are present
            required_fields = ["_id", "mac", "model", "version", "type"]
            for field in required_fields:
                if field not in update_data and field in device_details:
                    update_data[field] = device_details[field]
            
            # Include configuration revision if available (critical for persistence)
            if "config_version" in device_details:
                update_data["config_version"] = device_details["config_version"]
            if "cfgversion" in device_details:
                update_data["cfgversion"] = device_details["cfgversion"]
            if "config_revision" in device_details:
                update_data["config_revision"] = device_details["config_revision"]
            
            log.debug(f"Updating device config with comprehensive payload for {device_id}")
            log.debug(f"Payload keys: {list(update_data.keys())}")
            
            def _try_update_device_config():
                return self.session.put(endpoint, json=update_data, timeout=self.timeout)
            
            response = self._retry_request(_try_update_device_config)
            
            if response.status_code == 200:
                log.info(f"Device config update successful via comprehensive method for {device_id}")
                return True
            else:
                log.warning(f"Device config update failed: {response.status_code} - {_sanitize_response_for_logging(response.text, 200)}")
                return False
                
        except Exception as e:
            log.warning(f"Error in comprehensive device config update: {e}")
            return False
    
    def _update_ports_via_port_endpoint(self, device_id: str, port_table: List[Dict[str, Any]]) -> bool:
        """
        Try updating ports via port-specific API endpoint.
        
        Args:
            device_id: Device ID
            port_table: Updated port table
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try port-specific endpoints
            port_endpoints = []
            
            if self.is_unifi_os:
                port_endpoints = [
                    f"{self.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}/port",
                    f"{self.base_url}/proxy/network/api/s/{self.site}/cmd/devmgr"
                ]
            else:
                port_endpoints = [
                    f"{self.base_url}/api/s/{self.site}/rest/device/{device_id}/port",
                    f"{self.base_url}/api/s/{self.site}/cmd/devmgr"
                ]
            
            # Use legacy headers
            self.session.headers.update(self.legacy_headers)
            
            for endpoint in port_endpoints:
                try:
                    if "cmd/devmgr" in endpoint:
                        # Use device manager command format
                        update_data = {
                            "cmd": "set-port-config",
                            "mac": device_id,  # Some endpoints expect MAC instead of ID
                            "port_table": port_table
                        }
                    else:
                        # Use direct port update format
                        update_data = {
                            "port_table": port_table
                        }
                    
                    log.debug(f"Trying port-specific endpoint: {endpoint}")
                    
                    def _try_port_endpoint():
                        return self.session.put(endpoint, json=update_data, timeout=self.timeout)
                    
                    response = self._retry_request(_try_port_endpoint)
                    
                    if response.status_code == 200:
                        log.info(f"Port update successful via port endpoint {endpoint} for {device_id}")
                        return True
                    elif response.status_code == 404:
                        log.debug(f"Port endpoint not available: {endpoint}")
                        continue
                    else:
                        log.debug(f"Port endpoint failed: {response.status_code} - {_sanitize_response_for_logging(response.text, 100)}")
                        continue
                        
                except Exception as e:
                    log.debug(f"Error with port endpoint {endpoint}: {e}")
                    continue
            
            return False
            
        except Exception as e:
            log.warning(f"Error in port-specific update: {e}")
            return False
    
    def _update_device_legacy_method(self, device_id: str, device_details: Dict[str, Any], port_table: List[Dict[str, Any]]) -> bool:
        """
        Fallback to legacy device update method (original implementation).
        
        Args:
            device_id: Device ID
            device_details: Current device configuration
            port_table: Updated port table
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Determine the correct endpoint
            if self.is_unifi_os:
                endpoint = f"{self.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}"
            else:
                endpoint = f"{self.base_url}/api/s/{self.site}/rest/device/{device_id}"
            
            # Use legacy headers
            self.session.headers.update(self.legacy_headers)
            
            # Create minimal update payload (original method)
            update_data = {
                "port_table": port_table
            }
            
            # Add minimal required fields
            if "_id" in device_details:
                update_data["_id"] = device_details["_id"]
            if "mac" in device_details:
                update_data["mac"] = device_details["mac"]
            
            log.debug(f"Trying legacy update method for {device_id}")
            
            def _try_legacy_update():
                return self.session.put(endpoint, json=update_data, timeout=self.timeout)
            
            response = self._retry_request(_try_legacy_update)
            
            if response.status_code == 200:
                log.info(f"Legacy update method successful for {device_id}")
                return True
            else:
                log.warning(f"Legacy update method failed: {response.status_code} - {_sanitize_response_for_logging(response.text, 200)}")
                return False
                
        except Exception as e:
            log.warning(f"Error in legacy update method: {e}")
            return False
    
    def verify_port_update(self, device_id: str, port_idx: int, expected_name: str, max_retries: int = 5) -> bool:
        """
        Verify that a port name update was successfully applied and persisted.
        
        Args:
            device_id: Device ID
            port_idx: Port index to verify
            expected_name: Expected port name after update
            max_retries: Maximum number of verification attempts
        
        Returns:
            bool: True if the port name matches expected value, False otherwise
        """
        for attempt in range(max_retries):
            try:
                # Wait longer before checking, especially for first attempt
                import time
                if attempt == 0:
                    time.sleep(5)  # Initial longer wait
                else:
                    time.sleep(3 + attempt)  # Progressive delay with longer base
                
                # Get fresh device details
                device_details = self.get_device_details(self.site, device_id)
                if not device_details:
                    log.warning(f"Could not retrieve device details for verification attempt {attempt + 1}")
                    continue
                
                # Check port_table for the updated name
                port_table = device_details.get("port_table", [])
                for port in port_table:
                    if port.get("port_idx") == port_idx:
                        current_name = port.get("name", f"Port {port_idx}")
                        if current_name == expected_name:
                            log.info(f"Port {port_idx} name verification successful: '{current_name}'")
                            return True
                        else:
                            log.warning(f"Port {port_idx} name mismatch - Expected: '{expected_name}', Found: '{current_name}' (attempt {attempt + 1})")
                            break
                else:
                    log.warning(f"Port {port_idx} not found in port_table during verification (attempt {attempt + 1})")
            
            except Exception as e:
                log.warning(f"Error during port update verification (attempt {attempt + 1}): {e}")
        
        log.error(f"Port {port_idx} name verification failed after {max_retries} attempts")
        return False
    
    def get_device_mac_from_id(self, device_id: str) -> Optional[str]:
        """
        Get the MAC address for a device ID.
        
        Args:
            device_id: Device ID
        
        Returns:
            str: MAC address if found, None otherwise
        """
        try:
            device_details = self.get_device_details(self.site, device_id)
            if device_details:
                return device_details.get("mac")
        except Exception as e:
            log.debug(f"Error getting MAC for device {device_id}: {e}")
        return None
    
    def debug_device_config(self, device_id: str) -> Dict[str, Any]:
        """
        Get comprehensive device configuration for debugging purposes.
        
        Args:
            device_id: Device ID
        
        Returns:
            Dict[str, Any]: Device configuration with debug information
        """
        debug_info = {
            "device_id": device_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "api_endpoints_tried": [],
            "device_details": {},
            "port_table": [],
            "config_fields": {},
            "errors": []
        }
        
        try:
            # Get device details
            device_details = self.get_device_details(self.site, device_id)
            if device_details:
                debug_info["device_details"] = device_details
                debug_info["port_table"] = device_details.get("port_table", [])
                
                # Extract configuration-related fields
                config_fields = ["config_version", "cfgversion", "config_revision", "version", "_id", "mac", "model", "type"]
                for field in config_fields:
                    if field in device_details:
                        debug_info["config_fields"][field] = device_details[field]
            else:
                debug_info["errors"].append("Failed to get device details")
            
            # Test API endpoints availability
            test_endpoints = []
            if self.is_unifi_os:
                test_endpoints = [
                    f"{self.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}",
                    f"{self.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}/port",
                    f"{self.base_url}/proxy/network/api/s/{self.site}/cmd/devmgr"
                ]
            else:
                test_endpoints = [
                    f"{self.base_url}/api/s/{self.site}/rest/device/{device_id}",
                    f"{self.base_url}/api/s/{self.site}/rest/device/{device_id}/port",
                    f"{self.base_url}/api/s/{self.site}/cmd/devmgr"
                ]
            
            for endpoint in test_endpoints:
                try:
                    response = self.session.get(endpoint, timeout=5)
                    debug_info["api_endpoints_tried"].append({
                        "endpoint": endpoint,
                        "status_code": response.status_code,
                        "available": response.status_code in [200, 400]  # 400 might mean endpoint exists but wrong method
                    })
                except Exception as e:
                    debug_info["api_endpoints_tried"].append({
                        "endpoint": endpoint,
                        "status_code": "error",
                        "error": str(e),
                        "available": False
                    })
        
        except Exception as e:
            debug_info["errors"].append(f"Debug info collection error: {e}")
        
        return debug_info
    
    def list_devices_with_names(self) -> List[Dict[str, Any]]:
        """
        Get a list of all devices with their names and IDs for easy reference.
        
        Returns:
            List of device information dictionaries
        """
        devices_response = self.get_devices(self.site)
        device_list = []
        
        # Handle the response structure - could be dict with 'data' key or list
        devices_data = []
        if isinstance(devices_response, dict) and 'data' in devices_response:
            devices_data = devices_response['data']
        elif isinstance(devices_response, list):
            devices_data = devices_response
        else:
            log.warning(f"Unexpected devices response format: {type(devices_response)}")
            return device_list
        
        for device in devices_data:
            if not isinstance(device, dict):
                continue
                
            device_info = {
                "id": device.get("_id", "Unknown"),
                "name": device.get("name", "Unnamed Device"),
                "model": device.get("model", "Unknown Model"),
                "mac": device.get("mac", "Unknown MAC"),
                "ip": device.get("ip", "Unknown IP"),
                "type": device.get("type", "unknown"),
                "adopted": device.get("adopted", False),
                "state": device.get("state", "unknown")
            }
            device_list.append(device_info)
        
        return device_list
