#!/usr/bin/env python3
"""
LLDP client for UniFi Controller API.
Handles LLDP/CDP neighbor discovery information extraction.
"""

import logging
from typing import Dict, Any

log = logging.getLogger(__name__)


class LldpClient:
    """
    Manages LLDP/CDP information extraction for UniFi devices.
    """

    def __init__(self, device_client):
        """
        Initialize LldpClient.

        Args:
            device_client: DeviceClient instance for fetching device details
        """
        self.device_client = device_client

    def get_lldp_info(self, site_id: str, device_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get LLDP/CDP information for a device's ports.

        This method extracts LLDP data from device_details['lldp_table']
        which is already populated by the UniFi Controller.

        Args:
            site_id: Site ID
            device_id: Device ID

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary mapping port index to LLDP information
        """
        port_lldp_info = {}

        try:
            # LLDP data is already available in device details under 'lldp_table'
            device_details = self.device_client.get_device_details(site_id, device_id)

            if device_details and "lldp_table" in device_details:
                lldp_table = device_details["lldp_table"]
                log.debug(f"Found lldp_table with {len(lldp_table)} entries for device {device_id}")

                # Process each LLDP entry
                # Note: lldp_table uses 'local_port_idx' not 'port_idx'
                for entry in lldp_table:
                    local_port_idx = entry.get("local_port_idx")
                    if local_port_idx is not None:
                        # Map LLDP fields to expected format
                        port_lldp_info[str(local_port_idx)] = {
                            "port_idx": local_port_idx,
                            "chassis_id": entry.get("chassis_id", ""),
                            "port_id": entry.get("port_id", ""),
                            "system_name": entry.get("system_name", ""),
                            "chassis_name": entry.get("chassis_name", ""),
                            "remote_device_name": entry.get("system_name", entry.get("chassis_name", "")),
                            "remote_port_name": entry.get("port_id", ""),
                            "is_wired": entry.get("is_wired", True),
                            "local_port_name": entry.get("local_port_name", "")
                        }
                        log.debug(f"Mapped LLDP info for port {local_port_idx}")
            else:
                log.debug(f"No lldp_table found in device details for device {device_id}")

        except Exception as e:
            log.error(f"Error getting LLDP/CDP information: {e}")

        log.info(f"Retrieved LLDP info for {len(port_lldp_info)} ports on device {device_id}")
        return port_lldp_info
