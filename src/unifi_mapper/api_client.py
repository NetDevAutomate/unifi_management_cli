#!/usr/bin/env python3
"""
API client module for the UniFi Port Mapper.
Contains the UnifiApiClient class for interacting with the UniFi Controller API.
"""

import os
import json
import logging
import requests
from typing import Dict, List, Any, Optional, Tuple

from .models import DeviceInfo, PortInfo

log = logging.getLogger(__name__)


class UnifiApiClient:
    """Class to interact with the UniFi Controller API."""
    
    def __init__(self, base_url: str, site: str = "default", verify_ssl: bool = False,
                 username: str = None, password: str = None, api_token: str = None,
                 timeout: int = 10):
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
        """
        self.base_url = base_url.rstrip('/') if base_url else ""
        self.username = username
        self.password = password
        self.api_token = api_token
        self.site = site
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.is_authenticated = False
        self.auth_method = "token" if api_token else "username_password"
        self.successful_endpoint = None  # Store the successful endpoint
        self.is_unifi_os = False  # Whether this is a UniFi OS device (UDM, UDM Pro, etc.)
        
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
    
    def login(self) -> bool:
        """
        Login to the UniFi Controller.
        
        Returns:
            bool: True if login was successful, False otherwise
        """
        # Check if we're already authenticated
        if self.is_authenticated:
            return True
        
        # Check if we're dealing with a UniFi OS device (UDM, UDM Pro, etc.)
        try:
            # Try to access the /api/system endpoint which is only available on UniFi OS devices
            response = requests.get(f"{self.base_url}/api/system", verify=self.verify_ssl, timeout=self.timeout)
            self.is_unifi_os = response.status_code == 200
            log.debug(f"UniFi OS detection: {self.is_unifi_os}")
        except Exception as e:
            log.debug(f"UniFi OS detection failed: {e}")
            self.is_unifi_os = False
        
        # Set up the session
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        
        # Set up headers
        self.session.headers.update(self.legacy_headers)
        
        # Try to authenticate
        if self.auth_method == "token":
            # Token-based authentication
            # Try X-API-KEY header first
            self.session.headers.update({
                'X-API-KEY': self.api_token
            })
            
            try:
                if self.is_unifi_os:
                    # For UniFi OS devices, try the /proxy/network/api/s/{site}/self endpoint
                    response = self.session.get(f"{self.base_url}/proxy/network/api/s/{self.site}/self", timeout=self.timeout)
                else:
                    # For legacy controllers, try the /api/s/{site}/self endpoint
                    response = self.session.get(f"{self.base_url}/api/s/{self.site}/self", timeout=self.timeout)
                
                if response.status_code == 200:
                    self.is_authenticated = True
                    self.successful_endpoint = "api_token"
                    log.info("Successfully authenticated with API token")
                    return True
            except Exception as e:
                log.debug(f"API token authentication failed: {e}")
            
            # If X-API-KEY header didn't work, try Authorization header
            self.session.headers.update({
                'Authorization': f"Bearer {self.api_token}"
            })
            
            try:
                if self.is_unifi_os:
                    # For UniFi OS devices, try the /proxy/network/api/s/{site}/self endpoint
                    response = self.session.get(f"{self.base_url}/proxy/network/api/s/{self.site}/self", timeout=self.timeout)
                else:
                    # For legacy controllers, try the /api/s/{site}/self endpoint
                    response = self.session.get(f"{self.base_url}/api/s/{self.site}/self", timeout=self.timeout)
                
                if response.status_code == 200:
                    self.is_authenticated = True
                    self.successful_endpoint = "bearer_token"
                    log.info("Successfully authenticated with Bearer token")
                    return True
            except Exception as e:
                log.debug(f"Bearer token authentication failed: {e}")
        else:
            # Username/password authentication
            try:
                if self.is_unifi_os:
                    # For UniFi OS devices, use the /api/auth/login endpoint
                    login_url = f"{self.base_url}/api/auth/login"
                    login_data = {
                        "username": self.username,
                        "password": self.password
                    }
                    response = self.session.post(login_url, json=login_data, timeout=self.timeout)
                    
                    if response.status_code == 200:
                        self.is_authenticated = True
                        self.successful_endpoint = "unifi_os_login"
                        log.info("Successfully authenticated with username/password (UniFi OS)")
                        return True
                else:
                    # For legacy controllers, use the /api/login endpoint
                    login_url = f"{self.base_url}/api/login"
                    login_data = {
                        "username": self.username,
                        "password": self.password
                    }
                    response = self.session.post(login_url, json=login_data, timeout=self.timeout)
                    
                    if response.status_code == 200:
                        self.is_authenticated = True
                        self.successful_endpoint = "legacy_login"
                        log.info("Successfully authenticated with username/password (legacy)")
                        return True
            except Exception as e:
                log.debug(f"Username/password authentication failed: {e}")
        
        # If we got here, authentication failed
        log.error("Authentication failed")
        return False
    
    def get_devices(self, site_id: str) -> Dict[str, Any]:
        """
        Get all devices from the UniFi Controller.
        
        Args:
            site_id: Site ID
        
        Returns:
            Dict[str, Any]: Dictionary of devices
        """
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
            
            response = self.session.get(devices_endpoint, timeout=self.timeout)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401 or response.status_code == 403:
                log.warning("Authentication issue with devices endpoint. Attempting to re-authenticate...")
                if self.login():
                    log.info("Re-authentication successful, retrying devices retrieval")
                    return self.get_devices(site_id)
            else:
                log.error(f"Failed to get devices: {response.status_code}")
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
            
            response = self.session.get(clients_endpoint, timeout=self.timeout)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 401 or response.status_code == 403:
                log.warning("Authentication issue with clients endpoint. Attempting to re-authenticate...")
                if self.login():
                    log.info("Re-authentication successful, retrying clients retrieval")
                    return self.get_clients(site_id)
            else:
                log.error(f"Failed to get clients: {response.status_code}")
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
                    response = self.session.get(endpoint, timeout=self.timeout)
                    
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
                            response = self.session.get(endpoint, timeout=self.timeout)
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
                
                response = self.session.get(devices_endpoint, timeout=self.timeout)
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
                clients_response = self.session.get(clients_endpoint, timeout=self.timeout)
                
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
        Get LLDP/CDP information for a device's ports.
        
        Args:
            site_id: Site ID
            device_id: Device ID
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary of port index to LLDP/CDP information
        """
        if not self.is_authenticated and not self.login():
            log.error("Not authenticated, cannot get LLDP info")
            return {}
            
        port_lldp_info = {}
        
        try:
            # Switch to legacy API headers
            self.session.headers.update(self.legacy_headers)
            
            # Determine the correct endpoint based on UniFi OS detection
            if self.is_unifi_os:
                lldp_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/device/{device_id}/lldp"
                topology_endpoint = f"{self.base_url}/proxy/network/api/s/{site_id}/stat/device/{device_id}/uplink"
            else:
                lldp_endpoint = f"{self.base_url}/api/s/{site_id}/stat/device/{device_id}/lldp"
                topology_endpoint = f"{self.base_url}/api/s/{site_id}/stat/device/{device_id}/uplink"
            
            # Try to get LLDP information from the legacy API
            try:
                response = self.session.get(lldp_endpoint, timeout=self.timeout)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "data" in data and len(data["data"]) > 0:
                        lldp_data = data["data"][0]
                        
                        # Process LLDP information
                        if "lldp_table" in lldp_data:
                            lldp_table = lldp_data["lldp_table"]
                            
                            # Process each LLDP entry
                            for entry in lldp_table:
                                port_idx = entry.get("port_idx")
                                if port_idx is not None:
                                    port_lldp_info[str(port_idx)] = entry
            except Exception as e:
                log.debug(f"Error getting LLDP information: {e}")
            
            # Try to get topology information from the uplink endpoint
            try:
                response = self.session.get(topology_endpoint, timeout=self.timeout)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if "data" in data and len(data["data"]) > 0:
                        uplink_data = data["data"][0]
                        
                        # Process uplink information
                        if "uplink_table" in uplink_data:
                            uplink_table = uplink_data["uplink_table"]
                            
                            # Process each uplink entry
                            for entry in uplink_table:
                                port_idx = entry.get("port_idx")
                                if port_idx is not None:
                                    # If we already have LLDP info for this port, merge the uplink info
                                    if str(port_idx) in port_lldp_info:
                                        port_lldp_info[str(port_idx)].update(entry)
                                    else:
                                        port_lldp_info[str(port_idx)] = entry
            except Exception as e:
                log.debug(f"Error getting uplink information: {e}")
        except Exception as e:
            log.error(f"Error getting LLDP/CDP information: {e}")
        
        return port_lldp_info
    
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
            
            response = self.session.put(port_endpoint, json=update_data, timeout=self.timeout)
            
            if response.status_code == 200:
                log.info(f"Successfully updated port {port_idx} name to '{name}' for device {device_id}")
                return True
            else:
                log.error(f"Failed to update port name: {response.status_code}")
                return False
        except Exception as e:
            log.error(f"Error updating port name: {e}")
            return False
