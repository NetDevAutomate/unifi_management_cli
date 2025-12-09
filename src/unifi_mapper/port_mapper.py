#!/usr/bin/env python3
"""
Main port mapper module for the UniFi Port Mapper.
Contains the UnifiPortMapper class for managing port names based on LLDP/CDP information.
"""

import logging
from typing import Any, Dict, List, Optional

from .api_client import UnifiApiClient
from .network_topology import NetworkTopology

log = logging.getLogger(__name__)


class UnifiPortMapper:
    """Class to manage Unifi Controller port names based on LLDP/CDP neighbor information."""

    def __init__(
        self,
        base_url: str,
        site: str = "default",
        verify_ssl: bool = False,
        username: str = None,
        password: str = None,
        api_token: str = None,
        timeout: int = 10,
    ):
        """
        Initialize the UnifiPortMapper.

        Args:
            base_url: The base URL of the Unifi Controller (e.g., https://unifi.local:8443)
            site: The site name (default: "default")
            verify_ssl: Whether to verify SSL certificates (default: False)
            username: The username for the Unifi Controller (for username/password auth)
            password: The password for the Unifi Controller (for username/password auth)
            api_token: The API token for the Unifi Controller (for token-based auth)
            timeout: Connection timeout in seconds (default: 10)
        """
        # Initialize the API client
        self.api_client = UnifiApiClient(
            base_url=base_url,
            site=site,
            verify_ssl=verify_ssl,
            username=username,
            password=password,
            api_token=api_token,
            timeout=timeout,
        )

        # Store parameters for convenience
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.username = username
        self.password = password
        self.api_token = api_token
        self.site = site
        self.verify_ssl = verify_ssl
        self.timeout = timeout

        # Network topology
        self.topology = NetworkTopology()

    def login(self) -> bool:
        """
        Login to the UniFi Controller.

        Returns:
            bool: True if login was successful, False otherwise
        """
        return self.api_client.login()

    def logout(self) -> bool:
        """
        Logout from the UniFi Controller.

        Returns:
            bool: True if logout was successful, False otherwise
        """
        return self.api_client.logout()

    def get_sites(self) -> List[Dict[str, Any]]:
        """
        Get all sites from the UniFi Controller.

        Returns:
            List[Dict[str, Any]]: List of sites
        """
        return self.api_client.get_sites()

    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get all devices from the UniFi Controller.

        Returns:
            List[Dict[str, Any]]: List of devices
        """
        return self.api_client.get_devices(self.api_client.site)

    def get_device_ports(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get all ports for a device.

        Args:
            device_id: Device ID

        Returns:
            List[Dict[str, Any]]: List of ports
        """
        return self.api_client.get_device_ports(self.api_client.site, device_id)

    def get_lldp_info(self, device_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get LLDP/CDP information for a device's ports.

        Args:
            device_id: Device ID

        Returns:
            Dict[str, Dict[str, Any]]: Dictionary of port index to LLDP/CDP information
        """
        return self.api_client.get_lldp_info(self.api_client.site, device_id)

    def update_port_name(
        self, device_id: str, port_idx: int, new_name: str, verify_update: bool = True
    ) -> bool:
        """
        Update the name of a port.

        Args:
            device_id: Device ID
            port_idx: Port index
            new_name: New port name

        Returns:
            bool: True if the update was successful, False otherwise
        """
        return self.api_client.update_port_name(
            self.api_client.site, device_id, port_idx, new_name
        )

    def get_clients(self) -> List[Dict[str, Any]]:
        """
        Get all clients (wired and wireless) from the UniFi Controller.

        Returns:
            List[Dict[str, Any]]: List of clients
        """
        return self.api_client.get_clients(self.api_client.site)

    def get_client_port_mapping(
        self, device_mac: str
    ) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get mapping of ports to connected clients for a specific device.

        Args:
            device_mac: MAC address of the device

        Returns:
            Dict[int, List[Dict[str, Any]]]: Dictionary mapping port indices to lists of connected clients
        """
        clients_response = self.get_clients()
        port_clients = {}

        # Handle the response structure - could be dict with 'data' key or list
        clients_data = []
        if isinstance(clients_response, dict) and "data" in clients_response:
            clients_data = clients_response["data"]
        elif isinstance(clients_response, list):
            clients_data = clients_response
        else:
            log.warning(f"Unexpected clients response format: {type(clients_response)}")
            return port_clients

        for client in clients_data:
            # Skip if client is not a dict
            if not isinstance(client, dict):
                log.debug(f"Skipping non-dict client: {type(client)}")
                continue

            # Check if this is a client for our target device (regardless of online status)
            if (
                client.get("is_wired", False)
                and client.get("sw_mac", "").lower() == device_mac.lower()
            ):
                # Check if client is actually online/active
                is_online = client.get(
                    "is_online", True
                )  # Default to True if not present
                last_seen = client.get("last_seen", 0)
                is_active = last_seen > 0  # Has been seen recently

                if is_online and is_active:
                    port_idx = client.get("sw_port")
                    if port_idx is not None:
                        if port_idx not in port_clients:
                            port_clients[port_idx] = []

                        # Extract client information
                        client_info = {
                            "mac": client.get("mac", ""),
                            "name": client.get("name", ""),
                            "hostname": client.get("hostname", ""),
                            "ip": client.get("ip", ""),
                            "dev_cat_name": client.get("dev_cat_name", ""),
                            "dev_vendor": str(client.get("dev_vendor", "")),
                            "dev_id": str(client.get("dev_id", "")),
                            "is_online": is_online,
                            "last_seen": client.get("last_seen", 0),
                        }
                        port_clients[port_idx].append(client_info)
                        client_name = (
                            client_info["name"] or client_info["hostname"] or "Unknown"
                        )
                        log.debug(
                            f"Found ACTIVE client '{client_name}' (online={is_online}, last_seen={client.get('last_seen', 0)}) on port {port_idx}"
                        )

        if port_clients:
            log.info(
                f"Found clients on {len(port_clients)} ports for device {device_mac}"
            )

        return port_clients

    def format_client_names(
        self, clients: List[Dict[str, Any]], max_names: int = 2
    ) -> str:
        """
        Format client names for port naming.

        Args:
            clients: List of client information dictionaries
            max_names: Maximum number of client names to include

        Returns:
            str: Formatted client names
        """
        if not clients:
            return ""

        names = []
        for client in clients[:max_names]:
            # Priority: custom name > hostname > vendor+model > MAC
            name = client.get("name", "").strip()
            if not name:
                name = client.get("hostname", "").strip()
            if not name:
                vendor = client.get("dev_vendor", "").strip()
                dev_id = client.get("dev_id", "").strip()
                if vendor and dev_id:
                    name = f"{vendor}-{dev_id}"
                elif vendor:
                    name = vendor
            if not name:
                name = (
                    client.get("mac", "").replace(":", "")[-6:].upper()
                )  # Last 6 chars of MAC

            if name:
                names.append(name)

        if not names:
            return ""

        result = ", ".join(names)
        if len(clients) > max_names:
            result += f" (+{len(clients) - max_names})"

        # Sanitize the result to avoid potential UniFi controller issues
        # Replace problematic characters that might cause persistence issues
        import re

        result = re.sub(r"[,]+", "-", result)  # Replace commas with hyphens
        result = re.sub(r"[()]+", "", result)  # Remove parentheses
        result = re.sub(r"\s*\+\s*", "-", result)  # Replace + with hyphens
        result = re.sub(r"\s+", "-", result)  # Replace spaces with hyphens
        result = re.sub(r"-+", "-", result)  # Collapse multiple hyphens
        result = result.strip("-")  # Remove leading/trailing hyphens

        return result

    def batch_update_port_names(
        self, device_id: str, port_updates: Dict[int, str], verify_updates: bool = True
    ) -> bool:
        """
        Update multiple port names for a device in a single API call with verification.

        Args:
            device_id: Device ID
            port_updates: Dictionary mapping port indices to new names
            verify_updates: Whether to verify that updates were applied successfully

        Returns:
            bool: True if all updates were successful, False otherwise
        """
        if not port_updates:
            return True

        log.info(
            f"Batch updating {len(port_updates)} port names for device {device_id}"
        )

        # Get current device details once
        device_details = self.api_client.get_device_details(
            self.api_client.site, device_id
        )
        if not device_details:
            log.error(f"Failed to get device details for device {device_id}")
            return False

        # Log device information for debugging
        device_name = device_details.get("name", "Unknown")
        device_model = device_details.get("model", "Unknown")
        device_mac = device_details.get("mac", "Unknown")
        log.info(f"Updating device: {device_name} ({device_model}) - MAC: {device_mac}")

        # Find and update all ports in the port_table
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
            log.warning(f"No matching ports found for updates on device {device_id}")
            return False

        # Send the updated port_table in a single API call
        update_success = self.api_client.update_device_port_table(device_id, port_table)

        if not update_success:
            log.error(f"Failed to update port table for device {device_id}")
            return False

        # Verify updates if requested
        if verify_updates:
            log.info(f"Verifying {len(port_updates)} port name updates...")
            verification_failures = []

            for port_idx, expected_name in port_updates.items():
                if not self.api_client.verify_port_update(
                    device_id, port_idx, expected_name
                ):
                    verification_failures.append((port_idx, expected_name))

            if verification_failures:
                log.error(
                    f"Port name verification failed for {len(verification_failures)} ports on device {device_id}:"
                )
                for port_idx, expected_name in verification_failures:
                    log.error(
                        f"  Port {port_idx}: Expected '{expected_name}' but verification failed"
                    )
                return False
            else:
                log.info(
                    f"All {len(port_updates)} port name updates verified successfully for device {device_id}"
                )

        return True

    def run(
        self,
        output_path: Optional[str] = None,
        diagram_path: Optional[str] = None,
        dry_run: bool = False,
        discover_all: bool = False,
    ) -> int:
        """
        Run the port mapper with the specified options.

        Args:
            output_path: Path to the output report file
            diagram_path: Path to the output diagram file
            dry_run: Whether to run in dry run mode
            discover_all: Whether to discover all devices

        Returns:
            int: Exit code (0 for success, non-zero for failure)
        """
        from .run_methods import run_port_mapper as run_method

        return run_method(self, output_path, diagram_path, dry_run, discover_all)
