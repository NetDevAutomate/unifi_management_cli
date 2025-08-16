#!/usr/bin/env python3
"""
Fix script for UniFi port name persistence issues.

This script implements alternative approaches to fix the port name persistence
issue where API calls return HTTP 200 but changes don't persist in the UI.
"""

import os
import sys
import json
import logging
import argparse
import time
from dotenv import load_dotenv

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unifi_mapper.api_client import UnifiApiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


class UnifiPortPersistenceFixer:
    """Enhanced port update class with multiple persistence strategies."""
    
    def __init__(self, api_client: UnifiApiClient):
        self.api_client = api_client
    
    def force_device_provision(self, device_id: str) -> bool:
        """
        Force device provisioning to ensure configuration is applied.
        
        Args:
            device_id: Device ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to force device provisioning
            if self.api_client.is_unifi_os:
                provision_endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.api_client.site}/cmd/devmgr"
            else:
                provision_endpoint = f"{self.api_client.base_url}/api/s/{self.api_client.site}/cmd/devmgr"
            
            # Get device MAC for provisioning command
            device_mac = self.api_client.get_device_mac_from_id(device_id)
            if not device_mac:
                log.warning(f"Could not get MAC address for device {device_id}")
                return False
            
            provision_data = {
                "cmd": "force-provision",
                "mac": device_mac
            }
            
            self.api_client.session.headers.update(self.api_client.legacy_headers)
            response = self.api_client.session.post(provision_endpoint, json=provision_data, timeout=self.api_client.timeout)
            
            if response.status_code == 200:
                log.info(f"Successfully triggered force provisioning for device {device_id}")
                return True
            else:
                log.warning(f"Force provisioning failed: {response.status_code} - {response.text[:100]}")
                return False
                
        except Exception as e:
            log.warning(f"Error during force provisioning: {e}")
            return False
    
    def restart_device(self, device_id: str) -> bool:
        """
        Restart the device to force configuration reload.
        
        Args:
            device_id: Device ID
            
        Returns:
            bool: True if restart command was sent successfully, False otherwise
        """
        try:
            if self.api_client.is_unifi_os:
                restart_endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.api_client.site}/cmd/devmgr"
            else:
                restart_endpoint = f"{self.api_client.base_url}/api/s/{self.api_client.site}/cmd/devmgr"
            
            # Get device MAC for restart command
            device_mac = self.api_client.get_device_mac_from_id(device_id)
            if not device_mac:
                log.warning(f"Could not get MAC address for device {device_id}")
                return False
            
            restart_data = {
                "cmd": "restart",
                "mac": device_mac
            }
            
            self.api_client.session.headers.update(self.api_client.legacy_headers)
            response = self.api_client.session.post(restart_endpoint, json=restart_data, timeout=self.api_client.timeout)
            
            if response.status_code == 200:
                log.info(f"Successfully sent restart command to device {device_id}")
                log.warning("Device will restart - this may take 1-2 minutes")
                return True
            else:
                log.warning(f"Device restart failed: {response.status_code} - {response.text[:100]}")
                return False
                
        except Exception as e:
            log.warning(f"Error during device restart: {e}")
            return False
    
    def update_port_with_persistence_fixes(self, device_id: str, port_updates: dict, 
                                          force_provision: bool = True, 
                                          restart_if_needed: bool = False) -> bool:
        """
        Update port names with enhanced persistence strategies.
        
        Args:
            device_id: Device ID
            port_updates: Dictionary mapping port indices to new names
            force_provision: Whether to force device provisioning after update
            restart_if_needed: Whether to restart the device if other methods fail
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not port_updates:
            return True
        
        log.info(f"Updating ports with persistence fixes for device {device_id}")
        
        # Step 1: Standard port table update
        device_details = self.api_client.get_device_details(self.api_client.site, device_id)
        if not device_details:
            log.error(f"Failed to get device details for {device_id}")
            return False
        
        port_table = device_details.get("port_table", [])
        for port in port_table:
            port_idx = port.get("port_idx")
            if port_idx in port_updates:
                port["name"] = port_updates[port_idx]
                log.info(f"Updating port {port_idx} to '{port_updates[port_idx]}'")
        
        # Try the enhanced update method
        success = self.api_client.update_device_port_table(device_id, port_table)
        if not success:
            log.error("Standard update method failed")
            return False
        
        # Step 2: Force provisioning if enabled
        if force_provision:
            log.info("Forcing device provisioning...")
            self.force_device_provision(device_id)
            time.sleep(3)  # Wait for provisioning
        
        # Step 3: Verify the changes
        log.info("Verifying port name changes...")
        verification_failures = []
        for port_idx, expected_name in port_updates.items():
            if not self.api_client.verify_port_update(device_id, port_idx, expected_name, max_retries=5):
                verification_failures.append((port_idx, expected_name))
        
        if not verification_failures:
            log.info("✓ All port name updates verified successfully!")
            return True
        
        # Step 4: If verification failed and restart is allowed, try restarting the device
        if restart_if_needed:
            log.warning(f"Verification failed for {len(verification_failures)} ports. Attempting device restart...")
            
            if self.restart_device(device_id):
                log.info("Waiting for device to restart and come back online...")
                time.sleep(60)  # Wait for device to restart
                
                # Re-verify after restart
                log.info("Re-verifying port names after device restart...")
                final_verification_failures = []
                for port_idx, expected_name in port_updates.items():
                    if not self.api_client.verify_port_update(device_id, port_idx, expected_name, max_retries=10):
                        final_verification_failures.append((port_idx, expected_name))
                
                if not final_verification_failures:
                    log.info("✓ All port name updates verified successfully after device restart!")
                    return True
                else:
                    log.error(f"✗ {len(final_verification_failures)} port updates still failed after restart")
                    return False
            else:
                log.error("Device restart failed")
                return False
        else:
            log.error(f"✗ {len(verification_failures)} port updates failed verification")
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Fix UniFi port name persistence issues')
    parser.add_argument('--url', help='URL of the UniFi Controller')
    parser.add_argument('--site', default='default', help='Site name')
    parser.add_argument('--token', help='API token for authentication')
    parser.add_argument('--username', help='Username for authentication')
    parser.add_argument('--password', help='Password for authentication')
    parser.add_argument('--env', action='store_true', 
                        help='Use environment variables instead of command line arguments')
    parser.add_argument('--device-id', required=True, help='Device ID to update')
    parser.add_argument('--port-updates', required=True, 
                        help='JSON string of port updates, e.g. \'{"2": "Genos", "3": "Server"}\'')
    parser.add_argument('--no-provision', action='store_true', 
                        help='Skip force provisioning step')
    parser.add_argument('--allow-restart', action='store_true', 
                        help='Allow device restart if other methods fail')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse port updates
    try:
        port_updates = json.loads(args.port_updates)
        # Convert string keys to integers
        port_updates = {int(k): v for k, v in port_updates.items()}
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Invalid port updates JSON: {e}")
        return 1
    
    # Load environment variables if requested
    if args.env:
        load_dotenv()
        url = os.getenv('UNIFI_URL')
        site = os.getenv('UNIFI_SITE', 'default')
        token = os.getenv('UNIFI_CONSOLE_API_TOKEN')
        username = os.getenv('UNIFI_USERNAME')
        password = os.getenv('UNIFI_PASSWORD')
    else:
        url = args.url
        site = args.site
        token = args.token
        username = args.username
        password = args.password
    
    if not url:
        log.error("UniFi Controller URL is required")
        return 1
    
    if not token and not (username and password):
        log.error("Either API token or username/password is required for authentication")
        return 1
    
    # Create API client
    api_client = UnifiApiClient(
        base_url=url,
        site=site,
        api_token=token,
        username=username,
        password=password,
        verify_ssl=False
    )
    
    # Login
    if not api_client.login():
        log.error("Failed to login to UniFi Controller")
        return 1
    
    log.info("Successfully authenticated with UniFi Controller")
    
    # Create fixer and apply updates
    fixer = UnifiPortPersistenceFixer(api_client)
    
    success = fixer.update_port_with_persistence_fixes(
        device_id=args.device_id,
        port_updates=port_updates,
        force_provision=not args.no_provision,
        restart_if_needed=args.allow_restart
    )
    
    if success:
        log.info("✓ Port updates completed successfully!")
        return 0
    else:
        log.error("✗ Port updates failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())