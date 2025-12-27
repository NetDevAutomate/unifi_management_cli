#!/usr/bin/env python3
"""
VLAN Configuration Automation for UniFi networks.
Automates the creation and configuration of VLANs and routing.
"""

import logging
from typing import Dict, List, Any, Optional
from .api_client import UnifiApiClient

logger = logging.getLogger(__name__)

class VLANConfigurator:
    """Automate VLAN configuration tasks."""
    
    def __init__(self, api_client: UnifiApiClient, site: str = "default"):
        self.api_client = api_client
        self.site = site
    
    def create_network(self, name: str, vlan_id: Optional[int], subnet: str, gateway: str, 
                      dhcp_start: str = None, dhcp_stop: str = None) -> bool:
        """Create a new network/VLAN."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"
            
            network_config = {
                "name": name,
                "purpose": "corporate",
                "ip_subnet": subnet,
                "gateway_ip": gateway,
                "enabled": True
            }
            
            # Only add VLAN config if vlan_id is provided (not for default network)
            if vlan_id is not None:
                network_config.update({
                    "vlan_enabled": True,
                    "vlan": vlan_id
                })
            
            if dhcp_start and dhcp_stop:
                network_config.update({
                    "dhcpd_enabled": True,
                    "dhcpd_start": dhcp_start,
                    "dhcpd_stop": dhcp_stop
                })
            
            def _try_create():
                return self.api_client.session.post(
                    endpoint, 
                    json=network_config,
                    timeout=self.api_client.timeout
                )
            
            response = self.api_client._retry_request(_try_create)
            
            if response.status_code in [200, 201]:
                vlan_desc = f"VLAN {vlan_id}" if vlan_id else "Default"
                logger.info(f"Successfully created network '{name}' ({vlan_desc})")
                return True
            else:
                logger.error(f"Failed to create network: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating network: {e}")
            return False
    
    def update_network_gateway(self, network_id: str, gateway_ip: str, subnet: str = None) -> bool:
        """Update gateway configuration for existing network."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf/{network_id}"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf/{network_id}"
            
            update_config = {"gateway_ip": gateway_ip}
            # Only update subnet if it's provided and different
            if subnet:
                update_config["ip_subnet"] = subnet
            
            def _try_update():
                return self.api_client.session.put(
                    endpoint,
                    json=update_config,
                    timeout=self.api_client.timeout
                )
            
            response = self.api_client._retry_request(_try_update)
            
            if response.status_code == 200:
                logger.info(f"Successfully updated network gateway to {gateway_ip}")
                return True
            else:
                logger.error(f"Failed to update network: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating network: {e}")
            return False
    
    def create_trunk_port_profile(self, name: str, native_vlan_id: int, tagged_vlan_ids: List[int]) -> bool:
        """Create a trunk port profile with specified VLANs."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/portconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/portconf"
            
            # Get network IDs for VLANs
            networks = self.get_networks()
            vlan_to_network = {net.get('vlan', 1): net['_id'] for net in networks}
            
            native_network_id = vlan_to_network.get(native_vlan_id)
            tagged_network_ids = [vlan_to_network.get(vid) for vid in tagged_vlan_ids if vid in vlan_to_network]
            
            if not native_network_id:
                logger.error(f"Native VLAN {native_vlan_id} not found")
                return False
            
            profile_config = {
                "name": name,
                "forward": "customize",
                "native_networkconf_id": native_network_id,
                "tagged_networkconf_ids": tagged_network_ids
            }
            
            def _try_create_profile():
                return self.api_client.session.post(
                    endpoint,
                    json=profile_config,
                    timeout=self.api_client.timeout
                )
            
            response = self.api_client._retry_request(_try_create_profile)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully created port profile '{name}'")
                return True
            else:
                logger.error(f"Failed to create port profile: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating port profile: {e}")
            return False
    
    def get_networks(self) -> List[Dict[str, Any]]:
        """Get all configured networks."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"
            
            def _try_get():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            
            response = self.api_client._retry_request(_try_get)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('data', [])
            return []
            
        except Exception as e:
            logger.error(f"Error getting networks: {e}")
            return []
    
    def find_network_by_vlan(self, vlan_id: int) -> Optional[Dict[str, Any]]:
        """Find network configuration by VLAN ID."""
        networks = self.get_networks()
        for network in networks:
            if network.get('vlan') == vlan_id:
                return network
        return None
    
    def auto_fix_vlan_connectivity(self, source_vlan: int, dest_vlan: int, 
                                  source_subnet: str, dest_subnet: str,
                                  source_gateway: str, dest_gateway: str) -> Dict[str, bool]:
        """Automatically fix VLAN connectivity issues."""
        results = {
            'source_vlan_handled': False,
            'dest_vlan_gateway_fixed': False,
            'trunk_profile_created': False
        }
        
        # 1. Handle source VLAN (VLAN 1 is special - it's the default network)
        if source_vlan == 1:
            logger.info("VLAN 1 is the default network - checking if default network exists")
            networks = self.get_networks()
            default_network = None
            for net in networks:
                if net.get('purpose') == 'corporate' and not net.get('vlan_enabled'):
                    default_network = net
                    break
            
            if default_network:
                logger.info("Default network exists - ensuring proper configuration")
                # Update default network to have proper gateway if needed
                if not default_network.get('gateway_ip') or default_network.get('gateway_ip') != source_gateway:
                    results['source_vlan_handled'] = self.update_network_gateway(
                        default_network['_id'], source_gateway  # Don't pass subnet for default network
                    )
                else:
                    results['source_vlan_handled'] = True
            else:
                logger.info("Creating default corporate network")
                results['source_vlan_handled'] = self.create_network(
                    name="Default",
                    vlan_id=None,  # No VLAN ID for default network
                    subnet=source_subnet,
                    gateway=source_gateway,
                    dhcp_start=source_gateway.rsplit('.', 1)[0] + '.100',
                    dhcp_stop=source_gateway.rsplit('.', 1)[0] + '.200'
                )
        else:
            # Handle non-default VLANs normally
            source_network = self.find_network_by_vlan(source_vlan)
            if not source_network:
                logger.info(f"Creating missing VLAN {source_vlan}")
                results['source_vlan_handled'] = self.create_network(
                    name=f"VLAN {source_vlan}",
                    vlan_id=source_vlan,
                    subnet=source_subnet,
                    gateway=source_gateway,
                    dhcp_start=source_gateway.rsplit('.', 1)[0] + '.100',
                    dhcp_stop=source_gateway.rsplit('.', 1)[0] + '.200'
                )
            else:
                results['source_vlan_handled'] = True
        
        # 2. Fix destination VLAN gateway
        dest_network = self.find_network_by_vlan(dest_vlan)
        if dest_network:
            current_gateway = dest_network.get('gateway_ip')
            if not current_gateway or current_gateway != dest_gateway:
                logger.info(f"Fixing gateway for VLAN {dest_vlan}: {current_gateway} → {dest_gateway}")
                results['dest_vlan_gateway_fixed'] = self.update_network_gateway(
                    dest_network['_id'], dest_gateway
                )
            else:
                logger.info(f"VLAN {dest_vlan} gateway already correct: {current_gateway}")
                results['dest_vlan_gateway_fixed'] = True
        else:
            logger.warning(f"VLAN {dest_vlan} network not found - cannot fix gateway")
        
        # 3. Create trunk profile (skip if source is VLAN 1 since it's handled differently)
        if source_vlan != 1:
            trunk_name = f"Trunk VLAN {source_vlan}+{dest_vlan}"
            results['trunk_profile_created'] = self.create_trunk_port_profile(
                name=trunk_name,
                native_vlan_id=source_vlan,
                tagged_vlan_ids=[source_vlan, dest_vlan]
            )
        else:
            # For VLAN 1, create a profile that includes VLAN 10 as tagged
            trunk_name = f"Trunk Default+VLAN{dest_vlan}"
            # Get the default network ID
            networks = self.get_networks()
            default_net_id = None
            for net in networks:
                if not net.get('vlan_enabled') or net.get('vlan') == 1:
                    default_net_id = net['_id']
                    break
            
            if default_net_id:
                results['trunk_profile_created'] = self.create_trunk_port_profile_by_id(
                    name=trunk_name,
                    native_network_id=default_net_id,
                    tagged_vlan_ids=[dest_vlan]
                )
            else:
                logger.error("Could not find default network for trunk profile")
        
        return results
    
    def create_trunk_port_profile_by_id(self, name: str, native_network_id: str, tagged_vlan_ids: List[int]) -> bool:
        """Create a trunk port profile using network ID for native and VLAN IDs for tagged."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/portconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/portconf"
            
            # Get network IDs for tagged VLANs
            networks = self.get_networks()
            vlan_to_network = {net.get('vlan'): net['_id'] for net in networks if net.get('vlan')}
            
            tagged_network_ids = [vlan_to_network.get(vid) for vid in tagged_vlan_ids if vid in vlan_to_network]
            
            profile_config = {
                "name": name,
                "forward": "customize",
                "native_networkconf_id": native_network_id,
                "tagged_networkconf_ids": tagged_network_ids
            }
            
            def _try_create_profile():
                return self.api_client.session.post(
                    endpoint,
                    json=profile_config,
                    timeout=self.api_client.timeout
                )
            
            response = self.api_client._retry_request(_try_create_profile)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully created port profile '{name}'")
                return True
            else:
                logger.error(f"Failed to create port profile: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error creating port profile: {e}")
            return False
