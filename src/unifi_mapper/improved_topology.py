#!/usr/bin/env python3
"""
Improved network topology module for the UniFi Port Mapper.
Contains enhanced device detection and connection inference.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from .models import DeviceInfo, PortInfo

log = logging.getLogger(__name__)

def determine_device_type(model: str, name: str = "") -> str:
    """
    Determine the device type based on the model and name.
    
    Args:
        model (str): Device model
        name (str): Device name (optional)
    
    Returns:
        str: Device type (router, switch, ap, other)
    """
    model_lower = model.lower()
    name_lower = name.lower() if name else ""
    
    # Check for routers/gateways
    if any(x in model_lower for x in ['ugw', 'usg', 'udm', 'gateway', 'router', 'dream machine']):
        return 'router'
    
    # Check for switches - expanded to catch all switch models
    if any(x in model_lower for x in ['usw', 'switch', 'flex', 'ultra', 'us-', 'us8', 'us16', 'us24', 'us48', 
                                     'usl', 'enterprise', 'lite', 'poe', '2.5g', 'aggregation']) or \
       any(x in name_lower for x in ['switch', 'flex']):
        return 'switch'
    
    # Check for access points
    if any(x in model_lower for x in ['uap', 'ap', 'u6', 'u7', 'ac', 'nanostation', 'litebeam', 'iw']):
        return 'ap'
    
    # Default to other
    return 'other'

def infer_missing_connections(devices: Dict[str, DeviceInfo], connections: List[Dict]) -> List[Dict]:
    """
    Infer missing connections between switches and routers.
    This helps ensure all switches are connected to the network.
    
    Args:
        devices: Dictionary of devices by ID
        connections: List of existing connections
    
    Returns:
        List of new inferred connections
    """
    # First, identify all switches and routers
    switches = []
    routers = []
    new_connections = []
    
    for device_id, device in devices.items():
        device_type = determine_device_type(device.model, device.name)
        
        # Check if it's a router
        if device_type == 'router':
            routers.append(device_id)
        # Check if it's a switch
        elif device_type == 'switch':
            switches.append(device_id)
    
    # Find isolated switches (not in any connection)
    connected_devices = set()
    for connection in connections:
        connected_devices.add(connection.get('source_device_id'))
        connected_devices.add(connection.get('target_device_id'))
    
    isolated_switches = [switch_id for switch_id in switches if switch_id not in connected_devices]
    
    # For each isolated switch, try to infer a connection to a router or another switch
    for isolated_switch in isolated_switches:
        # First try to connect to a router
        if routers:
            # Connect to the first router
            router_id = routers[0]
            
            # Add an inferred connection
            new_connection = {
                'source_device_id': isolated_switch,
                'target_device_id': router_id,
                'source_port_idx': 1,  # Assume port 1 for simplicity
                'target_port_idx': len(connections) + len(new_connections) + 1,  # Use a unique port number
                'source_port_name': 'Port 1 (inferred)',
                'target_port_name': f'Port {len(connections) + len(new_connections) + 1} (inferred)',
                'inferred': True
            }
            
            new_connections.append(new_connection)
            log.info(f"Inferred connection from isolated switch {devices[isolated_switch].name} to router {devices[router_id].name}")
        
        # If no routers, connect to another switch
        elif len(switches) > 1:
            # Find a non-isolated switch to connect to
            for switch_id in switches:
                if switch_id != isolated_switch and switch_id in connected_devices:
                    # Add an inferred connection
                    new_connection = {
                        'source_device_id': isolated_switch,
                        'target_device_id': switch_id,
                        'source_port_idx': 1,  # Assume port 1 for simplicity
                        'target_port_idx': len(connections) + len(new_connections) + 1,  # Use a unique port number
                        'source_port_name': 'Port 1 (inferred)',
                        'target_port_name': f'Port {len(connections) + len(new_connections) + 1} (inferred)',
                        'inferred': True
                    }
                    
                    new_connections.append(new_connection)
                    log.info(f"Inferred connection from isolated switch {devices[isolated_switch].name} to switch {devices[switch_id].name}")
                    break
    
    return new_connections

def get_device_style(device: DeviceInfo) -> Tuple[str, str]:
    """
    Get the style for a device based on its type.
    
    Args:
        device: Device information
    
    Returns:
        Tuple of (color, icon)
    """
    device_type = determine_device_type(device.model, device.name)
    
    if device_type == 'router':
        return "#3498db", "🌐"  # Blue, Router icon
    elif device_type == 'switch':
        return "#2ecc71", "🔄"  # Green, Switch icon
    elif device_type == 'ap':
        return "#e74c3c", "📶"  # Red, AP icon
    else:
        return "#95a5a6", "💻"  # Grey, Computer icon
