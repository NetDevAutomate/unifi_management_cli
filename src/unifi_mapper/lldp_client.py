#!/usr/bin/env python3
"""
LLDP client for UniFi Controller API.
Handles LLDP/CDP neighbor discovery information extraction.
"""

import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


class LldpClient:
    """
    Manages LLDP/CDP information extraction for UniFi devices.
    Resolves chassis_id (MAC addresses) to device names.
    """

    def __init__(self, device_client):
        """
        Initialize LldpClient.

        Args:
            device_client: DeviceClient instance for fetching device details
        """
        self.device_client = device_client
        self._mac_to_device_cache = {}  # Cache MAC → device name lookups

    def get_lldp_info(self, site_id: str, device_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get LLDP/CDP information for a device's ports.

        This method extracts LLDP data from device_details['lldp_table']
        and resolves chassis_id (MAC addresses) to device names.

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping port index to LLDP information
        """
        port_lldp_info = {}

        try:
            # Build MAC to device name cache if needed
            if not self._mac_to_device_cache:
                self._build_mac_to_device_cache(site_id)

            # LLDP data is already available in device details under 'lldp_table'
            device_details = self.device_client.get_device_details(site_id, device_id)

            if device_details and "lldp_table" in device_details:
                lldp_table = device_details["lldp_table"]
                log.debug(
                    f"Found lldp_table with {len(lldp_table)} entries for device {device_id}"
                )

                # Process each LLDP entry
                # Note: lldp_table uses 'local_port_idx' not 'port_idx'
                for entry in lldp_table:
                    local_port_idx = entry.get("local_port_idx")
                    if local_port_idx is not None:
                        # Get chassis_id (MAC address) and resolve to device name
                        chassis_id = entry.get("chassis_id", "")
                        system_name = entry.get("system_name", "")
                        chassis_name = entry.get("chassis_name", "")

                        # Try to resolve MAC to device name if system_name not available
                        remote_device_name = system_name or chassis_name
                        if not remote_device_name and chassis_id:
                            remote_device_name = self._resolve_mac_to_device_name(
                                chassis_id
                            )

                        # Map LLDP fields to expected format
                        port_lldp_info[str(local_port_idx)] = {
                            "port_idx": local_port_idx,
                            "chassis_id": chassis_id,
                            "port_id": entry.get("port_id", ""),
                            "system_name": system_name,
                            "chassis_name": chassis_name,
                            "remote_device_name": remote_device_name,
                            "remote_port_name": entry.get("port_id", ""),
                            "remote_chassis_id": chassis_id,  # Add for report compatibility
                            "is_wired": entry.get("is_wired", True),
                            "local_port_name": entry.get("local_port_name", ""),
                        }
                        log.debug(
                            f"Mapped LLDP for port {local_port_idx}: {remote_device_name or chassis_id}"
                        )
            else:
                log.debug(
                    f"No lldp_table found in device details for device {device_id}"
                )

        except Exception as e:
            log.error(f"Error getting LLDP/CDP information: {e}")

        log.info(
            f"Retrieved LLDP info for {len(port_lldp_info)} ports on device {device_id}"
        )
        return port_lldp_info

    def _build_mac_to_device_cache(self, site_id: str) -> None:
        """
        Build cache mapping MAC addresses to device names.

        Args:
            site_id: Site ID
        """
        try:
            devices_response = self.device_client.get_devices(site_id)
            if not devices_response or "data" not in devices_response:
                log.warning("Could not build MAC to device cache")
                return

            for device in devices_response["data"]:
                mac = device.get("mac", "").lower()
                name = device.get("name", "Unknown Device")

                if mac:
                    # Store multiple formats for matching
                    self._mac_to_device_cache[mac] = name
                    self._mac_to_device_cache[mac.replace(":", "")] = name
                    self._mac_to_device_cache[mac.upper()] = name
                    self._mac_to_device_cache[mac.upper().replace(":", "")] = name

            log.debug(f"Built MAC cache with {len(devices_response['data'])} devices")

        except Exception as e:
            log.error(f"Error building MAC to device cache: {e}")

    def _resolve_mac_to_device_name(self, chassis_id: str) -> str:
        """
        Resolve MAC address (chassis_id) to device name.

        Args:
            chassis_id: MAC address from LLDP

        Returns:
            Device name or MAC address if not found
        """
        if not chassis_id:
            return ""

        # Try various MAC formats
        mac_formats = [
            chassis_id.lower(),
            chassis_id.upper(),
            chassis_id.lower().replace(":", ""),
            chassis_id.upper().replace(":", ""),
        ]

        for mac_format in mac_formats:
            if mac_format in self._mac_to_device_cache:
                device_name = self._mac_to_device_cache[mac_format]
                log.debug(f"Resolved MAC {chassis_id} to device: {device_name}")
                return device_name

        log.debug(f"Could not resolve MAC {chassis_id} to device name")
        return chassis_id  # Return MAC if not found
