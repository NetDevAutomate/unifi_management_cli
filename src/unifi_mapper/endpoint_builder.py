#!/usr/bin/env python3
"""
Endpoint builder for UniFi Controller API.
Centralizes URL construction logic for both UniFi OS and legacy controllers.
"""


class UnifiEndpointBuilder:
    """
    Centralized endpoint construction for UniFi Controller API.
    Handles differences between UniFi OS (UDM) and legacy controllers.
    """

    def __init__(self, base_url: str, is_unifi_os: bool):
        """
        Initialize endpoint builder.

        Args:
            base_url: Base URL of UniFi Controller (e.g., https://unifi.local:8443)
            is_unifi_os: Whether this is a UniFi OS device (UDM, UDM Pro, etc.)
        """
        self.base_url = base_url.rstrip("/")
        self.is_unifi_os = is_unifi_os
        self.prefix = "/proxy/network" if is_unifi_os else ""

    def devices(self, site_id: str) -> str:
        """Get devices list endpoint."""
        return f"{self.base_url}{self.prefix}/api/s/{site_id}/stat/device"

    def device_details(self, site_id: str, device_id: str) -> str:
        """Get device details endpoint."""
        return f"{self.base_url}{self.prefix}/api/s/{site_id}/stat/device/{device_id}"

    def device_rest(self, site_id: str, device_id: str) -> str:
        """Get device REST endpoint (for updates)."""
        return f"{self.base_url}{self.prefix}/api/s/{site_id}/rest/device/{device_id}"

    def clients(self, site_id: str) -> str:
        """Get clients list endpoint."""
        return f"{self.base_url}{self.prefix}/api/s/{site_id}/stat/sta"

    def login(self) -> str:
        """Get login endpoint."""
        if self.is_unifi_os:
            return f"{self.base_url}/api/auth/login"
        else:
            return f"{self.base_url}/api/login"

    def logout(self) -> str:
        """Get logout endpoint."""
        if self.is_unifi_os:
            return f"{self.base_url}/api/auth/logout"
        else:
            return f"{self.base_url}/api/logout"

    def self_check(self, site_id: str) -> str:
        """Get self-check endpoint (for authentication verification)."""
        if self.is_unifi_os:
            return f"{self.base_url}/proxy/network/api/s/{site_id}/self"
        return f"{self.base_url}/api/s/{site_id}/self"

    def system_check(self) -> str:
        """Get system endpoint (for UniFi OS detection)."""
        return f"{self.base_url}/api/system"
