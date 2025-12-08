#!/usr/bin/env python3
"""
Port client for UniFi Controller API.
Handles port-related operations (update port names, batch updates).
"""

import logging
import time
import requests
from typing import Dict, List, Any, Optional, Callable

from .exceptions import UniFiApiError
from .endpoint_builder import UnifiEndpointBuilder

log = logging.getLogger(__name__)


class PortClient:
    """
    Manages port-related operations for UniFi Controller API.
    """

    def __init__(self, endpoint_builder: UnifiEndpointBuilder,
                 session: requests.Session,
                 device_client,  # Injected to avoid circular dependency
                 retry_func: Optional[Callable] = None):
        """
        Initialize PortClient.

        Args:
            endpoint_builder: UnifiEndpointBuilder instance
            session: Authenticated requests.Session instance
            device_client: DeviceClient instance for fetching device details
            retry_func: Optional function to retry requests with backoff
        """
        self.endpoint_builder = endpoint_builder
        self.session = session
        self.device_client = device_client
        self._retry_func = retry_func

        self.legacy_headers = {
            'User-Agent': 'UnifiPortMapper/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def update_port_name(self, site_id: str, device_id: str,
                        port_idx: int, name: str) -> bool:
        """
        Update the name of a single port.

        Args:
            site_id: Site ID
            device_id: Device ID
            port_idx: Port index
            name: New port name

        Returns:
            bool: True if update successful
        """
        # Get current device details
        device_details = self.device_client.get_device_details(site_id, device_id)

        if not device_details:
            log.error(f"Failed to get device details for {device_id}")
            return False

        # Find and update the port
        port_table = device_details.get("port_table", [])
        port_found = False

        for port in port_table:
            if port.get("port_idx") == port_idx:
                port["name"] = name
                port_found = True
                break

        if not port_found:
            log.error(f"Port {port_idx} not found in device {device_id}")
            return False

        # Apply the update
        return self.update_device_port_table(site_id, device_id, port_table)

    def batch_update_port_names(self, site_id: str, device_id: str,
                               port_updates: Dict[int, str]) -> bool:
        """
        Update multiple port names in a single API call.

        Args:
            site_id: Site ID
            device_id: Device ID
            port_updates: Dict mapping port indices to new names

        Returns:
            bool: True if all updates successful
        """
        if not port_updates:
            return True

        log.info(f"Batch updating {len(port_updates)} port names for device {device_id}")

        # Get current device details
        device_details = self.device_client.get_device_details(site_id, device_id)

        if not device_details:
            log.error(f"Failed to get device details for {device_id}")
            return False

        # Update all ports in port_table
        port_table = device_details.get("port_table", [])
        updated_count = 0

        for port in port_table:
            port_idx = port.get("port_idx")
            if port_idx in port_updates:
                old_name = port.get("name", f"Port {port_idx}")
                new_name = port_updates[port_idx]
                port["name"] = new_name
                updated_count += 1
                log.info(f"  Port {port_idx}: '{old_name}' -> '{new_name}'")

        if updated_count == 0:
            log.warning(f"No matching ports found for updates")
            return False

        # Apply updates
        return self.update_device_port_table(site_id, device_id, port_table)

    def update_device_port_table(self, site_id: str, device_id: str,
                                 port_table: List[Dict[str, Any]]) -> bool:
        """
        Update the entire port table for a device.

        Args:
            site_id: Site ID
            device_id: Device ID
            port_table: Complete port table with updates

        Returns:
            bool: True if update successful
        """
        try:
            endpoint = self.endpoint_builder.device_rest(site_id, device_id)
            self.session.headers.update(self.legacy_headers)

            # Get full device config for update
            device_details = self.device_client.get_device_details(site_id, device_id)

            if not device_details:
                log.error(f"Failed to get device config for update")
                return False

            # Create update payload with current config
            update_data = device_details.copy()
            update_data["port_table"] = port_table

            # Include configuration version if available (critical for persistence)
            for version_field in ["config_version", "cfgversion", "config_revision"]:
                if version_field in device_details:
                    update_data[version_field] = device_details[version_field]

            log.debug(f"Updating device port table for {device_id}")

            def _update():
                return self.session.put(endpoint, json=update_data)

            if self._retry_func:
                response = self._retry_func(_update)
            else:
                response = _update()

            if response.status_code == 200:
                log.info(f"Port table update successful for {device_id}")
                # Wait for UniFi to process
                time.sleep(2)
                return True
            else:
                log.error(f"Port table update failed: {response.status_code}")
                return False

        except Exception as e:
            log.error(f"Error updating port table: {e}")
            return False

    def verify_port_update(self, site_id: str, device_id: str,
                          port_idx: int, expected_name: str,
                          max_retries: int = 5) -> bool:
        """
        Verify that a port name update was applied.

        Args:
            site_id: Site ID
            device_id: Device ID
            port_idx: Port index to verify
            expected_name: Expected port name
            max_retries: Maximum verification attempts

        Returns:
            bool: True if port name matches expected value
        """
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    time.sleep(3 + attempt)  # Progressive delay

                device_details = self.device_client.get_device_details(site_id, device_id)

                if not device_details:
                    log.warning(f"Could not retrieve device for verification (attempt {attempt + 1})")
                    continue

                port_table = device_details.get("port_table", [])
                for port in port_table:
                    if port.get("port_idx") == port_idx:
                        current_name = port.get("name", f"Port {port_idx}")
                        if current_name == expected_name:
                            log.info(f"Port {port_idx} verified: '{current_name}'")
                            return True
                        else:
                            log.warning(f"Port {port_idx} mismatch - Expected: '{expected_name}', Found: '{current_name}'")
                            break

            except Exception as e:
                log.warning(f"Error during verification (attempt {attempt + 1}): {e}")

        log.error(f"Port {port_idx} verification failed after {max_retries} attempts")
        return False
