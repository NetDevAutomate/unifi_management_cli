#!/usr/bin/env python3
"""
HTML parser for the UniFi Port Mapper.
Contains the UnifiHtmlParser class for parsing HTML content from the UniFi Controller.
"""

import json
import logging
from typing import Dict, List, Any, Optional

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

log = logging.getLogger(__name__)


class UnifiHtmlParser:
    """Parser for Unifi Controller HTML content."""
    
    def __init__(self, html_content: str):
        """
        Initialize the parser with HTML content.
        
        Args:
            html_content: HTML content to parse
        """
        self.html_content = html_content
        if HAS_BS4:
            self.soup = BeautifulSoup(html_content, 'lxml')
        else:
            self.soup = None
            log.warning("BeautifulSoup4 not available. HTML parsing will be limited.")
    
    def extract_client_devices(self) -> List[Dict[str, Any]]:
        """
        Extract client device information from HTML content.
        
        Returns:
            List[Dict[str, Any]]: List of client device information
        """
        if not HAS_BS4 or not self.soup:
            return []
        
        client_devices = []
        
        # Look for client device data in script tags
        for script in self.soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            if 'window.clients' in script_text:
                # Extract the client data from the script
                start_idx = script_text.find('window.clients = ') + len('window.clients = ')
                end_idx = script_text.find(';', start_idx)
                
                if start_idx >= 0 and end_idx >= 0:
                    client_json = script_text[start_idx:end_idx]
                    try:
                        client_data = json.loads(client_json)
                        if isinstance(client_data, list):
                            client_devices = client_data
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse client data: {e}")
        
        return client_devices
    
    def extract_lldp_info(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract LLDP/CDP information from HTML content.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary of port index to LLDP/CDP information
        """
        if not HAS_BS4 or not self.soup:
            return {}
        
        lldp_info = {}
        
        # Look for LLDP/CDP information in script tags
        for script in self.soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            if 'window.lldpInfo' in script_text:
                # Extract the LLDP/CDP data from the script
                start_idx = script_text.find('window.lldpInfo = ') + len('window.lldpInfo = ')
                end_idx = script_text.find(';', start_idx)
                
                if start_idx >= 0 and end_idx >= 0:
                    lldp_json = script_text[start_idx:end_idx]
                    try:
                        lldp_data = json.loads(lldp_json)
                        if isinstance(lldp_data, dict):
                            lldp_info = lldp_data
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse LLDP/CDP data: {e}")
        
        # If we couldn't find LLDP/CDP information in script tags, try to extract it from tables
        if not lldp_info:
            # Look for tables with LLDP/CDP information
            lldp_tables = self.soup.find_all('table', class_='lldp-table')
            for table in lldp_tables:
                # Extract the port index from the table header
                header = table.find('th')
                if not header:
                    continue
                
                port_idx = None
                header_text = header.get_text(strip=True)
                if 'Port' in header_text:
                    try:
                        port_idx = int(header_text.split('Port')[1].strip())
                    except (ValueError, IndexError):
                        continue
                
                if port_idx is None:
                    continue
                
                # Extract the LLDP/CDP information from the table rows
                rows = table.find_all('tr')
                if len(rows) < 2:
                    continue
                
                lldp_entry = {}
                for row in rows[1:]:
                    cells = row.find_all('td')
                    if len(cells) < 2:
                        continue
                    
                    key = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)
                    
                    if key == 'chassis name':
                        lldp_entry['chassis_name'] = value
                    elif key == 'port id':
                        lldp_entry['port_id'] = value
                    elif key == 'system description':
                        lldp_entry['system_description'] = value
                    elif key == 'capabilities':
                        lldp_entry['capabilities'] = [cap.strip() for cap in value.split(',') if cap.strip()]
                
                if lldp_entry:
                    lldp_info[str(port_idx)] = lldp_entry
        
        return lldp_info
    
    def extract_device_data(self) -> List[Dict[str, Any]]:
        """
        Extract device data from HTML content.
        
        Returns:
            List[Dict[str, Any]]: List of device data
        """
        if not HAS_BS4 or not self.soup:
            return []
        
        device_data = []
        
        # Look for device data in script tags
        for script in self.soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            if 'window.devices' in script_text:
                # Extract the device data from the script
                start_idx = script_text.find('window.devices = ') + len('window.devices = ')
                end_idx = script_text.find(';', start_idx)
                
                if start_idx >= 0 and end_idx >= 0:
                    device_json = script_text[start_idx:end_idx]
                    try:
                        device_data = json.loads(device_json)
                        if isinstance(device_data, list):
                            return device_data
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse device data: {e}")
        
        return device_data
    
    def extract_port_data(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Extract port data for a specific device from the HTML content.
        
        Args:
            device_id: ID of the device to extract port data for
        
        Returns:
            List of port data dictionaries
        """
        if not HAS_BS4 or not self.soup:
            return []
        
        port_data = []
        
        # Look for port data in script tags
        for script in self.soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            if 'window.ports' in script_text:
                # Extract the port data from the script
                start_idx = script_text.find('window.ports = ') + len('window.ports = ')
                end_idx = script_text.find(';', start_idx)
                
                if start_idx >= 0 and end_idx >= 0:
                    port_json = script_text[start_idx:end_idx]
                    try:
                        port_data = json.loads(port_json)
                        if isinstance(port_data, list):
                            # Filter ports for the specified device
                            port_data = [port for port in port_data if port.get('device_id') == device_id]
                            return port_data
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse port data: {e}")
        
        return port_data
    
    def extract_network_topology(self) -> Dict[str, Any]:
        """
        Extract network topology information from the HTML content.
        
        Returns:
            Dictionary with network topology information
        """
        if not HAS_BS4 or not self.soup:
            return {}
        
        topology_data = {}
        
        # Look for topology data in script tags
        for script in self.soup.find_all('script'):
            script_text = script.string
            if not script_text:
                continue
            
            if 'window.topology' in script_text:
                # Extract the topology data from the script
                start_idx = script_text.find('window.topology = ') + len('window.topology = ')
                end_idx = script_text.find(';', start_idx)
                
                if start_idx >= 0 and end_idx >= 0:
                    topology_json = script_text[start_idx:end_idx]
                    try:
                        topology_data = json.loads(topology_json)
                        return topology_data
                    except json.JSONDecodeError as e:
                        log.debug(f"Failed to parse topology data: {e}")
        
        return topology_data
    
    @staticmethod
    def parse_response(response) -> Any:
        """
        Parse a response from the Unifi Controller, handling both JSON and HTML responses.
        
        Args:
            response: Response from the Unifi Controller
        
        Returns:
            Parsed data as dictionary, list, or None if parsing failed
        """
        if not response or not hasattr(response, 'text'):
            return None
        
        # Try to parse as JSON first
        try:
            data = response.json()
            return data
        except json.JSONDecodeError:
            pass
        
        # If JSON parsing fails, try to parse as HTML
        if HAS_BS4 and '<html' in response.text.lower():
            parser = UnifiHtmlParser(response.text)
            
            # Try to extract different types of data
            device_data = parser.extract_device_data()
            if device_data:
                return {'data': device_data}
            
            client_data = parser.extract_client_devices()
            if client_data:
                return {'data': client_data}
            
            lldp_data = parser.extract_lldp_info()
            if lldp_data:
                return {'data': list(lldp_data.values())}
            
            topology_data = parser.extract_network_topology()
            if topology_data:
                return topology_data
        
        return None