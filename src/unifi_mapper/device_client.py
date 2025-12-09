#!/usr/bin/env python3
"""
Device client for UniFi Controller API.
Handles device-related operations (get devices, device details, clients).
"""

import logging
import requests
from typing import Dict, List, Any, Optional, Callable

from .exceptions import UniFiApiError, UniFiConnectionError
from .endpoint_builder import UnifiEndpointBuilder
from .api_cache import TtlCache

log = logging.getLogger(__name__)


class DeviceClient:
    """
    Manages device-related operations for UniFi Controller API.
    """

    def __init__(self, endpoint_builder: UnifiEndpointBuilder,
                 session: requests.Session,
                 retry_func: Optional[Callable] = None,
                 enable_cache: bool = True,
                 cache_ttl: int = 300):
        """
        Initialize DeviceClient.

        Args:
            endpoint_builder: UnifiEndpointBuilder instance
            session: Authenticated requests.Session instance
            retry_func: Optional function to retry requests with backoff
            enable_cache: Enable response caching (default: True)
            cache_ttl: Cache TTL in seconds (default: 300 = 5 minutes)
        """
        self.endpoint_builder = endpoint_builder
        self.session = session
        self._retry_func = retry_func

        # Initialize cache
        self._cache = TtlCache(ttl_seconds=cache_ttl) if enable_cache else None

        # Headers for legacy API
        self.legacy_headers = {
            'User-Agent': 'UnifiPortMapper/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def get_devices(self, site_id: str) -> Dict[str, Any]:
        """
        Get all devices from the UniFi Controller.

        Args:
            site_id: Site ID

        Returns:
            Dict with 'data' key containing list of devices
        """
        try:
            endpoint = self.endpoint_builder.devices(site_id)
            self.session.headers.update(self.legacy_headers)

            def _get():
                return self.session.get(endpoint)

            if self._retry_func:
                response = self._retry_func(_get)
            else:
                response = _get()

            if response.status_code == 200:
                return response.json()
            else:
                log.error(f"Failed to get devices: {response.status_code}")
                return {}

        except requests.exceptions.SSLError as e:
            log.error(f"SSL error getting devices: {e}")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.error(f"Error getting devices: {e}")
            return {}

    def get_device_details(self, site_id: str, device_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a device (with caching).

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            Dict with device details including port_table and lldp_table
        """
        # Check cache first
        if self._cache:
            cache_key = f"device_details:{site_id}:{device_id}"
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        try:
            # Try multiple endpoints
            endpoints = [
                self.endpoint_builder.device_details(site_id, device_id),
                self.endpoint_builder.device_rest(site_id, device_id)
            ]

            self.session.headers.update(self.legacy_headers)

            for endpoint in endpoints:
                try:
                    log.debug(f"Trying device details endpoint: {endpoint}")

                    def _get():
                        return self.session.get(endpoint)

                    if self._retry_func:
                        response = self._retry_func(_get)
                    else:
                        response = _get()

                    if response.status_code == 200:
                        data = response.json()
                        if "data" in data and len(data["data"]) > 0:
                            result = data["data"][0]
                            log.debug(f"Successfully got device details from {endpoint}")

                            # Cache the result
                            if self._cache:
                                cache_key = f"device_details:{site_id}:{device_id}"
                                self._cache.set(cache_key, result)

                            return result
                    elif response.status_code == 400:
                        log.debug(f"Endpoint not supported: {endpoint}")
                        continue
                    else:
                        log.debug(f"Failed: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    log.debug(f"Request error: {e}")
                    continue

            # Fallback: Get from devices list
            log.debug("Attempting fallback: search devices list")
            devices_response = self.get_devices(site_id)

            if devices_response and "data" in devices_response:
                for device in devices_response["data"]:
                    if device.get("_id") == device_id or device.get("mac") == device_id:
                        log.debug("Found device in devices list")
                        return device

            log.warning(f"Could not find device details for {device_id}")
            return {}

        except Exception as e:
            log.error(f"Error getting device details: {e}")
            return {}

    def get_clients(self, site_id: str) -> Dict[str, Any]:
        """
        Get all clients from the UniFi Controller.

        Args:
            site_id: Site ID

        Returns:
            Dict with 'data' key containing list of clients
        """
        try:
            endpoint = self.endpoint_builder.clients(site_id)
            self.session.headers.update(self.legacy_headers)

            def _get():
                return self.session.get(endpoint)

            if self._retry_func:
                response = self._retry_func(_get)
            else:
                response = _get()

            if response.status_code == 200:
                return response.json()
            else:
                log.error(f"Failed to get clients: {response.status_code}")
                return {}

        except requests.exceptions.SSLError as e:
            log.error(f"SSL error getting clients: {e}")
            raise UniFiConnectionError(f"SSL error: {e}")
        except Exception as e:
            log.error(f"Error getting clients: {e}")
            return {}

    def get_device_ports(self, site_id: str, device_id: str) -> List[Dict[str, Any]]:
        """
        Get all ports for a device.

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            List of port dictionaries from port_table
        """
        device_data = self.get_device_details(site_id, device_id)

        if device_data and "port_table" in device_data:
            return device_data["port_table"]

        log.warning(f"No port_table found for device {device_id}")
        return []
