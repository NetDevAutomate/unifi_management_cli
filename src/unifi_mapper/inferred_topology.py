#!/usr/bin/env python3
"""
Inferred network topology management for the UniFi Port Mapper.
Handles generating network topology diagrams based on device types and naming conventions
when LLDP/CDP information is unavailable.
"""

import os
import json
import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple

from .models import DeviceInfo, PortInfo
from .topology import NetworkTopology

log = logging.getLogger(__name__)


class InferredNetworkTopology(NetworkTopology):
    """Class to manage inferred network topology information when LLDP/CDP data is unavailable."""
    
    def __init__(self):
        """Initialize the InferredNetworkTopology."""
        super().__init__()
    
    def determine_device_type(self, device: Dict[str, Any]) -> str:
        """
        Determine the device type based on the model and name.
        
        Args:
            device: Device information dictionary
            
        Returns:
            str: Device type (router, switch, ap, or unknown)
        """
        model = device.get('model', '').lower()
        name = device.get('name', '').lower()
        
        # Determine device type based on model
        if 'udm' in model or 'dream' in model or 'gateway' in model or 'usg' in model:
            return 'router'
        elif 'usw' in model or 'switch' in model or 'us-8' in model or 'us 8' in model:
            return 'switch'
        elif 'uap' in model or 'ap' in model or 'u6' in model or 'u7' in model or 'u8' in model:
            return 'ap'
        
        # If model doesn't give us enough information, try the name
        if 'router' in name or 'gateway' in name or 'udm' in name or 'dream' in name:
            return 'router'
        elif 'switch' in name or 'sw' in name or 'us-8' in name or 'us 8' in name:
            return 'switch'
        elif 'ap' in name or 'access point' in name or 'wifi' in name or 'u6' in name or 'u6-' in name:
            return 'ap'
        
        # Special case detection based on specific model strings
        if model in ['us 8 60w', 'us-8-60w']:
            return 'switch'
        elif model in ['u6 pro', 'u6 iw', 'u6 lr']:
            return 'ap'
        elif model == 'udm pro max':
            return 'router'
        
        # Default to unknown
        return 'unknown'
    
    def infer_connections(self) -> List[Dict[str, Any]]:
        """
        Infer connections between devices based on naming conventions and device types.
        
        Returns:
            List[Dict[str, Any]]: List of inferred connections
        """
        connections = []
        
        # Sort devices by type (routers first, then switches, then APs)
        device_types = {
            'router': [],
            'switch': [],
            'ap': [],
            'unknown': []
        }
        
        for device_id, device in self.devices.items():
            device_dict = {
                'id': device_id,
                'name': device.name,
                'model': device.model
            }
            
            device_type = self.determine_device_type(device_dict)
            device_types[device_type].append(device_dict)
        
        # Group switches by location
        location_switches = {}
        for switch in device_types['switch']:
            switch_name = switch.get('name', '').lower()
            
            # Extract location from switch name
            location = None
            for word in ['office', 'lounge', 'dining', 'kitchen', 'bedroom', 'hallway', 'shed', 'reece', 'sian']:
                if word in switch_name:
                    location = word
                    break
            
            if location:
                if location not in location_switches:
                    location_switches[location] = []
                location_switches[location].append(switch)
        
        # 1. Connect routers to switches
        routers = device_types['router']
        switches = device_types['switch']
        
        if routers and switches:
            # Assume the router is connected to all core/main switches
            main_router = routers[0] if routers else None
            
            if main_router:
                # Connect to all switches that have 'core' in their name
                core_switches = []
                for switch in switches:
                    switch_name = switch.get('name', '').lower()
                    if 'core' in switch_name or 'main' in switch_name:
                        core_switches.append(switch)
                
                # If no core switches found, connect to switches with 'usw' in model
                if not core_switches:
                    for switch in switches:
                        model = switch.get('model', '').lower()
                        if 'usw' in model and ('lite' in model or 'pro' in model or 'ultra' in model):
                            core_switches.append(switch)
                
                # If still no core switches, connect to all switches
                if not core_switches:
                    core_switches = switches
                
                # Connect router to core switches
                for switch in core_switches:
                    connections.append({
                        'source_device_id': main_router.get('id'),
                        'source_device_name': main_router.get('name'),
                        'target_device_id': switch.get('id'),
                        'target_device_name': switch.get('name'),
                        'inferred': True,
                        'source_port_name': 'WAN',
                        'target_port_name': 'LAN'
                    })
        
        # 2. Connect switches to other switches based on naming conventions and locations
        # First, identify core switches for each location
        location_core_switches = {}
        for location, loc_switches in location_switches.items():
            core_switch = None
            for switch in loc_switches:
                switch_name = switch.get('name', '').lower()
                if 'core' in switch_name:
                    core_switch = switch
                    break
            
            if core_switch:
                location_core_switches[location] = core_switch
            elif loc_switches:  # If no core switch, use the first one
                location_core_switches[location] = loc_switches[0]
        
        # Connect core switches to other switches in the same location
        for location, core_switch in location_core_switches.items():
            for switch in location_switches.get(location, []):
                if switch != core_switch:  # Don't connect to itself
                    connections.append({
                        'source_device_id': core_switch.get('id'),
                        'source_device_name': core_switch.get('name'),
                        'target_device_id': switch.get('id'),
                        'target_device_name': switch.get('name'),
                        'inferred': True,
                        'source_port_name': 'Uplink',
                        'target_port_name': 'Downlink'
                    })
        
        # 3. Connect APs to switches based on location names
        aps = device_types['ap']
        
        for ap in aps:
            ap_name = ap.get('name', '').lower()
            best_match = None
            best_match_score = 0
            
            # Extract location from AP name
            ap_location = None
            for word in ['office', 'lounge', 'dining', 'kitchen', 'bedroom', 'hallway', 'shed', 'reece', 'sian', 'bob']:
                if word in ap_name:
                    ap_location = word
                    break
            
            # If we found a location, try to match with a switch in that location
            if ap_location and ap_location in location_core_switches:
                best_match = location_core_switches[ap_location]
            else:
                # Find the switch with the most similar name
                for switch in switches:
                    switch_name = switch.get('name', '').lower()
                    
                    # Calculate a similarity score
                    score = 0
                    ap_words = ap_name.split()
                    switch_words = switch_name.split()
                    
                    for word in ap_words:
                        if word in switch_words:
                            score += 1
                    
                    if score > best_match_score:
                        best_match = switch
                        best_match_score = score
            
            # If no good match, connect to the first router or switch
            if not best_match:
                if routers:
                    best_match = routers[0]
                elif switches:
                    best_match = switches[0]
            
            if best_match:
                connections.append({
                    'source_device_id': best_match.get('id'),
                    'source_device_name': best_match.get('name'),
                    'target_device_id': ap.get('id'),
                    'target_device_name': ap.get('name'),
                    'inferred': True,
                    'source_port_name': 'PoE',
                    'target_port_name': 'LAN'
                })
        
        return connections
    
    def build_from_inference(self) -> None:
        """
        Build the topology from inferred connections when LLDP/CDP information is unavailable.
        """
        # Clear existing connections
        self.connections = []
        
        # Infer connections based on device types and naming conventions
        inferred_connections = self.infer_connections()
        
        # Add the inferred connections to the topology
        for connection in inferred_connections:
            # Create a connection dictionary in the format expected by NetworkTopology
            conn = {
                'source_device_id': connection['source_device_id'],
                'source_device_name': connection['source_device_name'],
                'target_device_id': connection['target_device_id'],
                'target_device_name': connection['target_device_name'],
                'source_port_name': connection.get('source_port_name', 'Inferred'),
                'target_port_name': connection.get('target_port_name', 'Inferred'),
                'inferred': True
            }
            
            # Add source_port_idx and target_port_id if available
            source_device = self.devices.get(connection['source_device_id'])
            target_device = self.devices.get(connection['target_device_id'])
            
            if source_device and source_device.ports:
                # Use the first available port as a fallback
                conn['source_port_idx'] = source_device.ports[0].port_idx
            
            if target_device and target_device.ports:
                # Use the first available port as a fallback
                conn['target_port_id'] = target_device.ports[0].id
            
            self.connections.append(conn)
    
    def generate_report(self, filename: str) -> bool:
        """
        Generate a network topology report.
        
        Args:
            filename: Path to save the report to
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(filename, 'w') as f:
                f.write("# UniFi Network Topology Report\n\n")
                f.write(f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # Device information
                f.write("## Device Information\n\n")
                f.write("| Device | Model | Type | MAC |\n")
                f.write("| ------ | ----- | ---- | --- |\n")
                
                for device_id, device in self.devices.items():
                    device_dict = {
                        'name': device.name,
                        'model': device.model
                    }
                    device_type = self.determine_device_type(device_dict)
                    
                    f.write(f"| {device.name} | {device.model} | {device_type} | {device.mac} |\n")
                
                # Network topology
                f.write("\n## Network Topology\n\n")
                f.write("```mermaid\n")
                f.write(self.generate_mermaid_diagram())
                f.write("\n```\n")
                
                # Notes
                f.write("\n## Notes\n\n")
                f.write("* This network topology is inferred based on device types and naming conventions.\n")
                f.write("* Actual connections may differ from the inferred connections shown in the diagram.\n")
                f.write("* Device types are determined based on model names and device names.\n")
                f.write("* Connections are color-coded by device type: routers (blue), switches (green), access points (red).\n")
                f.write("* The Dream Machine Pro Max is shown as the central node in the network.\n")
            
            log.info(f"Report saved to {filename}")
            return True
        except Exception as e:
            log.error(f"Error generating report: {e}")
            return False
    
    def generate_mermaid_diagram(self) -> str:
        """
        Generate a Mermaid diagram of the network topology with inferred connections.
        
        Returns:
            str: Mermaid diagram as a string
        """
        # If no connections, build them from inference
        if not self.connections:
            self.build_from_inference()
        
        # Find the router (Dream Machine Pro Max or any router)
        router = None
        for device_id, device in self.devices.items():
            device_dict = {
                'name': device.name,
                'model': device.model
            }
            if device.name == 'Dream Machine Pro Max' or self.determine_device_type(device_dict) == 'router':
                router = device
                router_id = device_id
                break
        
        mermaid = ["graph TD"]
        
        # Add nodes
        for device_id, device in self.devices.items():
            device_dict = {
                'name': device.name,
                'model': device.model
            }
            device_type = self.determine_device_type(device_dict)
            
            # Special case for Dream Machine Pro Max
            if device.name == 'Dream Machine Pro Max':
                device_id = 'dream_machine_pro_max'
            
            # Create a node for the device
            mermaid.append(f"    {device_id}[\"{device.name}\"] --> |{device.model}| {device_id}_type[{device_type}]")
            
            # Add style based on device type
            if device_type == 'router':
                mermaid.append(f"    style {device_id} fill:#3498db")
            elif device_type == 'switch':
                mermaid.append(f"    style {device_id} fill:#2ecc71")
            elif device_type == 'ap':
                mermaid.append(f"    style {device_id} fill:#e74c3c")
            else:
                mermaid.append(f"    style {device_id} fill:#95a5a6")
        
        # If we have a router, make sure it's connected to all core switches
        if router:
            router_id = 'dream_machine_pro_max' if router.name == 'Dream Machine Pro Max' else router_id
            
            # Find all core switches
            core_switches = []
            for device_id, device in self.devices.items():
                device_dict = {
                    'name': device.name,
                    'model': device.model
                }
                if self.determine_device_type(device_dict) == 'switch':
                    device_name = device.name.lower()
                    if 'core' in device_name:
                        core_switches.append((device_id, device))
            
            # If no core switches found, use all switches with 'usw' in model
            if not core_switches:
                for device_id, device in self.devices.items():
                    device_dict = {
                        'name': device.name,
                        'model': device.model
                    }
                    if self.determine_device_type(device_dict) == 'switch':
                        model = device.model.lower()
                        if 'usw' in model and ('lite' in model or 'pro' in model or 'ultra' in model):
                            core_switches.append((device_id, device))
            
            # Connect router to all core switches
            for switch_id, switch in core_switches:
                mermaid.append(f"    {router_id} -- \"WAN\" --> {switch_id}")
        
        # Add connections
        for connection in self.connections:
            source_id = connection.get('source_device_id')
            target_id = connection.get('target_device_id')
            source_name = connection.get('source_device_name', '')
            target_name = connection.get('target_device_name', '')
            source_port = connection.get('source_port_name', 'Inferred')
            target_port = connection.get('target_port_name', 'Inferred')
            
            # Special case for Dream Machine Pro Max
            if source_name == 'Dream Machine Pro Max':
                source_id = 'dream_machine_pro_max'
            if target_name == 'Dream Machine Pro Max':
                target_id = 'dream_machine_pro_max'
            
            # Skip router-to-switch connections (we already added them)
            if router and (source_id == router_id or target_id == router_id):
                continue
            
            # Add the connection
            if connection.get('inferred', False):
                mermaid.append(f"    {source_id} -- \"Inferred Connection\" --> {target_id}")
            else:
                mermaid.append(f"    {source_id} -- \"{source_port} -> {target_port}\" --> {target_id}")
        
        return "\n".join(mermaid)


def create_inferred_topology_from_env():
    """
    Create an InferredNetworkTopology instance using environment variables.
    
    Returns:
        InferredNetworkTopology: The created InferredNetworkTopology instance
    """
    import os
    from dotenv import load_dotenv
    from .api_client import UnifiApiClient
    
    # Load environment variables
    load_dotenv()
    
    # Get configuration values
    url = os.getenv('UNIFI_URL')
    site = os.getenv('UNIFI_SITE', 'default')
    token = os.getenv('UNIFI_CONSOLE_API_TOKEN')
    username = os.getenv('UNIFI_USERNAME')
    password = os.getenv('UNIFI_PASSWORD')
    
    if not url:
        log.error("UNIFI_URL environment variable is not set")
        return None
    
    if not token and not (username and password):
        log.error("Either UNIFI_CONSOLE_API_TOKEN or both UNIFI_USERNAME and UNIFI_PASSWORD must be set")
        return None
    
    # Create the API client
    api_client = UnifiApiClient(
        base_url=url,
        site=site,
        api_token=token,
        username=username,
        password=password
    )
    
    # Create the inferred network topology
    topology = InferredNetworkTopology()
    topology.api_client = api_client
    
    return topology


def generate_inferred_topology(base_url=None, site="default", api_token=None, 
                              username=None, password=None, output_path=None, 
                              diagram_path=None):
    """
    Generate inferred network topology report and diagram.
    
    Args:
        base_url: Base URL of the UniFi Controller
        site: Site name
        api_token: API token for authentication
        username: Username for authentication
        password: Password for authentication
        output_path: Path to save the report to
        diagram_path: Path to save the diagram to
        
    Returns:
        InferredNetworkTopology: The generated topology
    """
    from .api_client import UnifiApiClient
    
    # Create directories if they don't exist
    os.makedirs('diagrams', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    
    # Default output paths
    if not output_path:
        output_path = os.path.join('reports', 'inferred_topology_report.md')
    if not diagram_path:
        diagram_path = os.path.join('diagrams', 'inferred_topology_diagram.png')
    
    # Create the API client
    api_client = UnifiApiClient(
        base_url=base_url,
        site=site,
        api_token=api_token,
        username=username,
        password=password
    )
    
    # Create the inferred network topology
    topology = InferredNetworkTopology()
    topology.api_client = api_client
    
    try:
        # Load devices from API
        topology.load_devices_from_api()
        
        # Build the topology from inference
        topology.build_from_inference()
        
        # Generate the report
        if output_path:
            topology.generate_report(output_path)
            log.info(f"Inferred network topology report saved to {output_path}")
        
        # Generate the diagram
        if diagram_path:
            topology.generate_network_diagram(diagram_path)
            log.info(f"Inferred network diagram saved to {diagram_path}")
        
        return topology
    except Exception as e:
        log.error(f"Error generating inferred network topology: {e}")
        return None
