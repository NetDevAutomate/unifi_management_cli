#!/usr/bin/env python3
"""
Main port mapper module for the UniFi Port Mapper.
Contains the UnifiPortMapper class for managing port names based on LLDP/CDP information.
"""

import os
import json
import logging
import requests
import datetime
from typing import Dict, List, Any, Optional, Tuple

from .models import DeviceInfo, PortInfo
from .topology import NetworkTopology
from .device_definitions import DeviceDefinition, DEVICE_DEFINITIONS, get_device_definition
from .api_client import UnifiApiClient

log = logging.getLogger(__name__)


class UnifiPortMapper:
    """Class to manage Unifi Controller port names based on LLDP/CDP neighbor information."""
    
    def __init__(self, base_url: str, site: str = "default", verify_ssl: bool = False,
                 username: str = None, password: str = None, api_token: str = None,
                 timeout: int = 10):
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
            timeout=timeout
        )
        
        # Store parameters for convenience
        self.base_url = base_url.rstrip('/') if base_url else ""
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
    
    def update_port_name(self, device_id: str, port_idx: int, new_name: str) -> bool:
        """
        Update the name of a port.
        
        Args:
            device_id: Device ID
            port_idx: Port index
            new_name: New port name
        
        Returns:
            bool: True if the update was successful, False otherwise
        """
        return self.api_client.update_port_name(self.api_client.site, device_id, port_idx, new_name)
    
    def get_clients(self) -> List[Dict[str, Any]]:
        """
        Get all clients (wired and wireless) from the UniFi Controller.
        
        Returns:
            List[Dict[str, Any]]: List of clients
        """
        return self.api_client.get_clients(self.api_client.site)
    
    def run(self, output_path: Optional[str] = None, diagram_path: Optional[str] = None,
            dry_run: bool = False, discover_all: bool = False) -> int:
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
