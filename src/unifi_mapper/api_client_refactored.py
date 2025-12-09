#!/usr/bin/env python3
"""
Refactored UniFi API Client using specialized modules.
Delegates to AuthManager, DeviceClient, PortClient, and LldpClient.
"""

import logging
import time
from typing import Any, Dict, List

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from .auth_manager import AuthManager
from .device_client import DeviceClient
from .endpoint_builder import UnifiEndpointBuilder
from .exceptions import (
    UniFiApiError,
    UniFiAuthenticationError,
    UniFiConnectionError,
    UniFiPermissionError,
    UniFiTimeoutError,
)
from .lldp_client import LldpClient
from .port_client import PortClient

log = logging.getLogger(__name__)


class UnifiApiClient:
    """
    Refactored UniFi API Client delegating to specialized modules.
    Maintains backward compatibility with original interface.
    """

    def __init__(
        self,
        base_url: str,
        site: str = "default",
        verify_ssl: bool = False,
        username: str = None,
        password: str = None,
        api_token: str = None,
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize the UnifiApiClient.

        Args:
            base_url: Base URL of UniFi Controller
            site: Site name
            verify_ssl: Whether to verify SSL certificates
            username: Username for authentication
            password: Password for authentication
            api_token: API token for authentication
            timeout: Connection timeout in seconds
            max_retries: Maximum retry attempts
            retry_delay: Delay between retries in seconds
        """
        # Store configuration
        self.base_url = base_url.rstrip("/")
        self.site = site.strip() if site else "default"
        self.verify_ssl = verify_ssl
        self.timeout = max(1, min(timeout, 300))
        self.max_retries = max(1, min(max_retries, 10))
        self.retry_delay = max(0.1, min(retry_delay, 10.0))

        # Create session
        self.session = requests.Session()
        self.session.verify = verify_ssl

        # Create endpoint builder (is_unifi_os will be detected during login)
        self.endpoint_builder = UnifiEndpointBuilder(base_url, is_unifi_os=False)

        # Create specialized clients
        self.auth_manager = AuthManager(
            endpoint_builder=self.endpoint_builder,
            session=self.session,
            api_token=api_token,
            username=username,
            password=password,
            retry_func=self._retry_request,
        )

        self.device_client = DeviceClient(
            endpoint_builder=self.endpoint_builder,
            session=self.session,
            retry_func=self._retry_request,
        )

        self.port_client = PortClient(
            endpoint_builder=self.endpoint_builder,
            session=self.session,
            device_client=self.device_client,
            retry_func=self._retry_request,
        )

        self.lldp_client = LldpClient(device_client=self.device_client)

        # Backward compatibility properties
        self.is_authenticated = False
        self.is_unifi_os = False

    def _retry_request(self, func, *args, **kwargs):
        """
        Execute request with retry logic and exponential backoff.

        Args:
            func: Function to execute
            *args: Arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Result of function call

        Raises:
            UniFiPermanentError: For non-retryable errors
            UniFiRetryableError: When all retries exhausted
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, Timeout, HTTPError) as e:
                last_exception = e

                # Don't retry authentication errors
                if isinstance(e, HTTPError) and e.response.status_code in [401, 403]:
                    raise UniFiAuthenticationError(
                        f"Authentication failed: {e}",
                        status_code=e.response.status_code,
                    )

                # Don't retry on permanent client errors
                if isinstance(e, HTTPError) and 400 <= e.response.status_code < 500:
                    if e.response.status_code not in [401, 403, 408, 429]:
                        raise UniFiPermissionError(f"Client error: {e}")

                # Calculate exponential backoff
                delay = self.retry_delay * (2**attempt)

                if attempt < self.max_retries - 1:
                    log.warning(
                        f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}. Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    log.error(f"Request failed after {self.max_retries} attempts: {e}")

            except RequestException as e:
                last_exception = e
                if "timeout" in str(e).lower():
                    raise UniFiTimeoutError(f"Request timed out: {e}")
                elif "connection" in str(e).lower():
                    raise UniFiConnectionError(f"Connection failed: {e}")
                else:
                    raise UniFiApiError(f"Request failed: {e}")

        # All retries exhausted
        if last_exception:
            if isinstance(last_exception, (ConnectionError, Timeout)):
                raise UniFiConnectionError(
                    f"Connection failed after {self.max_retries} attempts: {last_exception}"
                )
            else:
                raise UniFiApiError(
                    f"Request failed after {self.max_retries} attempts: {last_exception}"
                )

    # Backward compatibility methods - delegate to specialized clients

    def login(self) -> bool:
        """Login to UniFi Controller."""
        result = self.auth_manager.login(self.site)
        self.is_authenticated = self.auth_manager.is_authenticated
        self.is_unifi_os = self.endpoint_builder.is_unifi_os

        # Update endpoint builder's prefix after UniFi OS detection
        self.endpoint_builder.prefix = "/proxy/network" if self.is_unifi_os else ""

        return result

    def logout(self) -> bool:
        """Logout from UniFi Controller."""
        result = self.auth_manager.logout()
        self.is_authenticated = self.auth_manager.is_authenticated
        return result

    def get_devices(self, site_id: str) -> Dict[str, Any]:
        """Get all devices."""
        return self.device_client.get_devices(site_id)

    def get_device_details(self, site_id: str, device_id: str) -> Dict[str, Any]:
        """Get device details."""
        return self.device_client.get_device_details(site_id, device_id)

    def get_clients(self, site_id: str) -> Dict[str, Any]:
        """Get all clients."""
        return self.device_client.get_clients(site_id)

    def get_device_ports(self, site_id: str, device_id: str) -> List[Dict[str, Any]]:
        """Get device ports."""
        return self.device_client.get_device_ports(site_id, device_id)

    def get_lldp_info(self, site_id: str, device_id: str) -> Dict[str, Dict[str, Any]]:
        """Get LLDP/CDP information."""
        return self.lldp_client.get_lldp_info(site_id, device_id)

    def update_port_name(
        self, site_id: str, device_id: str, port_idx: int, name: str
    ) -> bool:
        """Update single port name."""
        return self.port_client.update_port_name(site_id, device_id, port_idx, name)

    def update_device_port_table(
        self, device_id: str, port_table: List[Dict[str, Any]]
    ) -> bool:
        """Update device port table."""
        return self.port_client.update_device_port_table(
            self.site, device_id, port_table
        )

    def verify_port_update(
        self, device_id: str, port_idx: int, expected_name: str, max_retries: int = 5
    ) -> bool:
        """Verify port update."""
        return self.port_client.verify_port_update(
            self.site, device_id, port_idx, expected_name, max_retries
        )
