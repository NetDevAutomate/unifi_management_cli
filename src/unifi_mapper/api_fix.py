#!/usr/bin/env python3
"""
A simplified API client for UniFi devices using the v1 integration API.
This is designed to provide a more reliable way to get device information.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class UnifiIntegrationClient:
    """Simple client for the UniFi Integration API."""

    def __init__(self, base_url: str, api_token: str = None):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the UniFi Controller
            api_token: API token for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.session = requests.Session()
        self.session.verify = False

        # Set headers once for all requests
        self.session.headers.update(
            {
                "User-Agent": "UnifiPortMapper/1.0",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-API-KEY": api_token,
            }
        )

    def get_sites(self) -> List[Dict[str, Any]]:
        """
        Get all sites.

        Returns:
            List of site objects
        """
        url = f"{self.base_url}/proxy/network/integration/v1/sites"
        response = self.session.get(url)

        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                return data["data"]

        log.error(f"Failed to get sites: {response.status_code}")
        return []

    def get_devices(self, site_id: str) -> List[Dict[str, Any]]:
        """
        Get all devices for a site.

        Args:
            site_id: Site ID

        Returns:
            List of device objects
        """
        url = f"{self.base_url}/proxy/network/integration/v1/sites/{site_id}/devices"
        response = self.session.get(url)

        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                return data["data"]

        log.error(f"Failed to get devices: {response.status_code}")
        return []

    def get_device(self, site_id: str, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get device details.

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            Device object or None if not found
        """
        url = f"{self.base_url}/proxy/network/integration/v1/sites/{site_id}/devices/{device_id}"
        response = self.session.get(url)

        if response.status_code == 200:
            return response.json()

        log.warning(f"Failed to get device {device_id}: {response.status_code}")
        return None


# Usage example
def test_client():
    from dotenv import load_dotenv

    load_dotenv()

    base_url = os.environ.get("UNIFI_URL")
    api_token = os.environ.get("UNIFI_CONSOLE_API_TOKEN")

    if not base_url or not api_token:
        log.error("Missing UNIFI_URL or UNIFI_CONSOLE_API_TOKEN environment variables")
        return

    client = UnifiIntegrationClient(base_url, api_token)

    # Get sites
    sites = client.get_sites()
    if not sites:
        log.error("No sites found")
        return

    site_id = sites[0]["id"]
    log.info(f"Using site ID: {site_id}")

    # Get devices
    devices = client.get_devices(site_id)
    if not devices:
        log.error("No devices found")
        return

    log.info(f"Found {len(devices)} devices")

    # Get first device details
    device_id = devices[0]["id"]
    device = client.get_device(site_id, device_id)
    if device:
        log.info(f"Got device: {device['name']} ({device['model']})")
        if "interfaces" in device:
            log.info(f"Device has {len(device['interfaces'].get('ports', []))} ports")
    else:
        log.error("Failed to get device details")


if __name__ == "__main__":
    test_client()
