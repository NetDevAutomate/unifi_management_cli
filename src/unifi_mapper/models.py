#!/usr/bin/env python3
"""
Models for the UniFi Port Mapper.
Contains data classes for port and device information.
"""

from typing import Dict, List, Any, Optional


class PortInfo:
    """Data class to store port information."""
    
    def __init__(self, idx: int, name: str, media: str = "RJ45", 
                 is_uplink: bool = False, up: bool = True, enabled: bool = True,
                 speed: int = 1000, full_duplex: bool = True, has_lldp_info: bool = False,
                 lldp_info: Dict[str, Any] = None, connected_device_name: Optional[str] = None,
                 connected_port_name: Optional[str] = None, poe: bool = False):
        """
        Initialize a PortInfo object.
        
        Args:
            idx: Port index
            name: Port name
            media: Port media type (e.g., RJ45, SFP+)
            is_uplink: Whether this is an uplink port
            up: Whether the port is up
            enabled: Whether the port is enabled
            speed: Port speed in Mbps
            full_duplex: Whether the port is full duplex
            has_lldp_info: Whether the port has LLDP/CDP information
            lldp_info: LLDP/CDP information
            connected_device_name: Name of the connected device
            connected_port_name: Name of the connected port
        """
        self.id = f"port_{idx}"
        self.name = name
        self.idx = idx
        self.media = media
        self.is_uplink = is_uplink
        self.up = up
        self.enabled = enabled
        self.speed = speed
        self.full_duplex = full_duplex
        self.has_lldp_info = has_lldp_info or (lldp_info is not None and len(lldp_info) > 0)
        self.lldp_info = lldp_info or {}
        self.modified = False
        self.new_name = ""
        self.connected_device_id = None
        self.connected_port_id = None
        self.proposed_name = ""
        self.connected_device_name = connected_device_name
        self.connected_port_name = connected_port_name
        self.poe = poe

    def get_display_name(self) -> str:
        """
        Get a display name for the port that includes media type and speed.
        """
        speed_str = f"{self.speed/1000}G" if self.speed >= 1000 else f"{self.speed}M"
        return f"{self.name} ({self.media} {speed_str})"

    def get_lldp_display_name(self) -> str:
        """
        Get a display name based on LLDP/CDP information.
        """
        if not self.has_lldp_info:
            return self.name
        
        chassis_name = self.lldp_info.get('chassis_name', '')
        port_id = self.lldp_info.get('port_id', '')
        
        if chassis_name and port_id:
            return f"{chassis_name} ({port_id})"
        elif chassis_name:
            return chassis_name
        elif port_id:
            return port_id
        else:
            return self.name

    def update_lldp_info(self, lldp_info: Dict[str, Any]) -> None:
        """
        Update LLDP/CDP information for the port and set proposed name.
        
        Args:
            lldp_info: LLDP/CDP information
        """
        if not lldp_info:
            return
        
        self.lldp_info = lldp_info
        self.has_lldp_info = True
        
        # Set proposed name based on LLDP/CDP information
        chassis_name = lldp_info.get('chassis_name', '')
        port_id = lldp_info.get('port_id', '')
        
        if chassis_name and port_id:
            self.proposed_name = f"{chassis_name} ({port_id})"
        elif chassis_name:
            self.proposed_name = chassis_name
        elif port_id:
            self.proposed_name = port_id


class DeviceInfo:
    """Data class to store device information."""
    
    def __init__(self, id: str, name: str, model: str, ip: str, mac: str, ports: List[PortInfo] = None, device_type: str = None, lldp_info: Dict[str, Any] = None):
        """
        Initialize a DeviceInfo object.
        
        Args:
            id: Device ID
            name: Device name
            model: Device model
            ip: Device IP address
            mac: Device MAC address
            ports: List of ports
            device_type: Device type (router, switch, ap, or unknown)
            lldp_info: LLDP/CDP information
        """
        self.id = id
        self.name = name
        self.model = model
        self.ip = ip
        self.mac = mac
        self.ports = ports or []
        self.device_type = device_type if device_type else self.get_device_type()
        self.lldp_info = lldp_info or {}

    def get_device_type(self) -> str:
        """
        Determine the device type based on the model name.
        
        Returns:
            str: Device type
        """
        model_lower = self.model.lower()
        
        if 'udm' in model_lower or 'usg' in model_lower or 'ugw' in model_lower or 'gateway' in model_lower or 'router' in model_lower:
            return "router"
        elif 'usw' in model_lower or 'switch' in model_lower:
            return "switch"
        elif 'uap' in model_lower or 'ap' in model_lower or 'access point' in model_lower or 'u6' in model_lower or 'u7' in model_lower or 'ac' in model_lower or 'nanostation' in model_lower or 'litebeam' in model_lower:
            return "ap"
        elif 'server' in model_lower or 'nas' in model_lower:
            return "server"
        else:
            return "other"

    def get_color(self) -> str:
        """
        Get a color for the device based on its type.
        
        Returns:
            str: Color in hex format
        """
        if self.device_type == "router":
            return "#3498db"  # Blue
        elif self.device_type == "switch":
            return "#2ecc71"  # Green
        elif self.device_type == "ap":
            return "#e74c3c"  # Red
        elif self.device_type == "server":
            return "#9b59b6"  # Purple
        else:
            return "#95a5a6"  # Gray
