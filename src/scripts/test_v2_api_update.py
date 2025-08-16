#!/usr/bin/env python3
"""
Test V2 API updates for UniFi port names.

This script tests the newer V2 API endpoints that were discovered to be available
on your UniFi controller, which might be the key to making port updates persist.
"""

import os
import sys
import json
import logging
import argparse
import requests
from typing import Dict, Any, List
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


def get_device_via_v2_api(api_client: UnifiApiClient, device_id: str) -> Dict[str, Any]:
    """Get device details via V2 API."""
    log.info(f"Getting device details via V2 API for {device_id}")
    
    # Try the V2 endpoints that were discovered to work
    v2_endpoints = [
        f"{api_client.base_url}/v2/api/site/{api_client.site}/device/{device_id}",
        f"{api_client.base_url}/proxy/network/v2/api/site/{api_client.site}/device/{device_id}",
    ]
    
    for endpoint in v2_endpoints:
        try:
            log.info(f"Trying V2 endpoint: {endpoint}")
            response = api_client.session.get(endpoint, timeout=10)
            
            if response.status_code == 200:
                log.info(f"✓ Success with {endpoint}")
                data = response.json()
                
                # Print the structure to understand what we're working with
                print(f"\\nV2 API Response Structure:")
                print(f"Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"Keys: {list(data.keys())}")
                    if 'data' in data:
                        print(f"Data type: {type(data['data'])}")
                        if isinstance(data['data'], list) and len(data['data']) > 0:
                            device = data['data'][0]
                            print(f"Device keys: {list(device.keys())}")
                            if 'port_table' in device:
                                print(f"Port table found with {len(device['port_table'])} ports")
                            else:
                                print("No port_table found in device data")
                
                return data
            else:
                log.warning(f"✗ Failed with {endpoint}: {response.status_code}")
                
        except Exception as e:
            log.warning(f"✗ Error with {endpoint}: {e}")
    
    return {}


def update_device_via_v2_api(api_client: UnifiApiClient, device_id: str, port_updates: Dict[int, str]) -> bool:
    """Try to update device via V2 API."""
    log.info(f"Attempting to update device {device_id} via V2 API")
    
    # First get the current device data
    device_data = get_device_via_v2_api(api_client, device_id)
    if not device_data:
        log.error("Failed to get device data via V2 API")
        return False
    
    # Extract the device info
    device = None
    if isinstance(device_data, dict) and 'data' in device_data and len(device_data['data']) > 0:
        device = device_data['data'][0]
    elif isinstance(device_data, dict):
        device = device_data
    
    if not device:
        log.error("Could not extract device info from V2 API response")
        return False
    
    log.info(f"Current device name: {device.get('name', 'Unknown')}")
    log.info(f"Current device model: {device.get('model', 'Unknown')}")
    
    # Check if we have port_table
    if 'port_table' not in device:
        log.error("No port_table found in device data")
        return False
    
    # Update the port table
    port_table = device['port_table'].copy()
    for port in port_table:
        port_idx = port.get('port_idx')
        if port_idx in port_updates:
            old_name = port.get('name', f'Port {port_idx}')
            new_name = port_updates[port_idx]
            port['name'] = new_name
            log.info(f"  Updating port {port_idx}: '{old_name}' -> '{new_name}'")
    
    # Try different V2 update endpoints
    update_endpoints = [
        f"{api_client.base_url}/v2/api/site/{api_client.site}/device/{device_id}",
        f"{api_client.base_url}/proxy/network/v2/api/site/{api_client.site}/device/{device_id}",
        f"{api_client.base_url}/v2/api/site/{api_client.site}/device",  # Without device_id
        f"{api_client.base_url}/proxy/network/v2/api/site/{api_client.site}/device",  # Without device_id
    ]
    
    for endpoint in update_endpoints:
        try:
            log.info(f"Trying update endpoint: {endpoint}")
            
            # Create update payload
            update_data = device.copy()
            update_data['port_table'] = port_table
            
            # Try PUT request
            response = api_client.session.put(endpoint, json=update_data, timeout=10)
            log.info(f"PUT {endpoint}: {response.status_code}")
            
            if response.status_code in [200, 201, 202]:
                log.info(f"✓ Update successful with PUT {endpoint}")
                
                # Wait and verify
                import time
                time.sleep(2)
                
                # Verify the update
                verification_data = get_device_via_v2_api(api_client, device_id)
                if verification_data:
                    verify_device = None
                    if isinstance(verification_data, dict) and 'data' in verification_data and len(verification_data['data']) > 0:
                        verify_device = verification_data['data'][0]
                    elif isinstance(verification_data, dict):
                        verify_device = verification_data
                    
                    if verify_device and 'port_table' in verify_device:
                        verify_port_table = verify_device['port_table']
                        for port in verify_port_table:
                            port_idx = port.get('port_idx')
                            if port_idx in port_updates:
                                actual_name = port.get('name', f'Port {port_idx}')
                                expected_name = port_updates[port_idx]
                                if actual_name == expected_name:
                                    log.info(f"✓ Port {port_idx} verified: '{actual_name}'")
                                    return True
                                else:
                                    log.warning(f"✗ Port {port_idx} mismatch: expected '{expected_name}', got '{actual_name}'")
                
                return True
            else:
                log.warning(f"PUT failed with {response.status_code}: {response.text[:200]}")
                
                # Try POST request
                response = api_client.session.post(endpoint, json=update_data, timeout=10)
                log.info(f"POST {endpoint}: {response.status_code}")
                
                if response.status_code in [200, 201, 202]:
                    log.info(f"✓ Update successful with POST {endpoint}")
                    return True
                else:
                    log.warning(f"POST failed with {response.status_code}: {response.text[:200]}")
                
        except Exception as e:
            log.warning(f"✗ Error with {endpoint}: {e}")
    
    log.error("All V2 API update attempts failed")
    return False


def test_command_endpoints(api_client: UnifiApiClient, device_id: str, port_updates: Dict[int, str]) -> bool:
    """Test command-based endpoints for device updates."""
    log.info("Testing command-based device update endpoints")
    
    # Get device MAC address first
    device_data = get_device_via_v2_api(api_client, device_id)
    if not device_data:
        return False
    
    device = None
    if isinstance(device_data, dict) and 'data' in device_data and len(device_data['data']) > 0:
        device = device_data['data'][0]
    elif isinstance(device_data, dict):
        device = device_data
    
    if not device:
        return False
    
    device_mac = device.get('mac')
    if not device_mac:
        log.error("Could not get device MAC address")
        return False
    
    log.info(f"Device MAC: {device_mac}")
    
    # Test command endpoints
    command_endpoints = [
        f"{api_client.base_url}/v2/api/site/{api_client.site}/cmd/devmgr",
        f"{api_client.base_url}/proxy/network/v2/api/site/{api_client.site}/cmd/devmgr",
        f"{api_client.base_url}/api/s/{api_client.site}/cmd/devmgr",  # Try legacy just in case
        f"{api_client.base_url}/proxy/network/api/s/{api_client.site}/cmd/devmgr",
    ]
    
    # Create port updates as separate commands
    for port_idx, new_name in port_updates.items():
        for endpoint in command_endpoints:
            try:
                log.info(f"Trying command endpoint: {endpoint}")
                
                # Different command formats to try
                command_formats = [
                    {
                        "cmd": "set-port-name",
                        "mac": device_mac,
                        "port_idx": port_idx,
                        "name": new_name
                    },
                    {
                        "cmd": "set-port-conf",
                        "mac": device_mac,
                        "port_overrides": [{"port_idx": port_idx, "name": new_name}]
                    },
                    {
                        "cmd": "set-device-settings",
                        "mac": device_mac,
                        "port_table": [{"port_idx": port_idx, "name": new_name}]
                    }
                ]
                
                for cmd_data in command_formats:
                    response = api_client.session.post(endpoint, json=cmd_data, timeout=10)
                    log.info(f"Command {cmd_data['cmd']}: {response.status_code}")
                    
                    if response.status_code in [200, 201, 202]:
                        log.info(f"✓ Command successful: {cmd_data['cmd']}")
                        
                        # Wait and verify
                        import time
                        time.sleep(3)
                        return True
                    else:
                        log.debug(f"Command failed: {response.text[:100]}")
                        
            except Exception as e:
                log.debug(f"Command endpoint error: {e}")
    
    return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Test V2 API updates for UniFi port names')
    parser.add_argument('--url', help='URL of the UniFi Controller')
    parser.add_argument('--site', default='default', help='Site name')
    parser.add_argument('--token', help='API token for authentication')
    parser.add_argument('--username', help='Username for authentication')
    parser.add_argument('--password', help='Password for authentication')
    parser.add_argument('--env', action='store_true', 
                        help='Use environment variables instead of command line arguments')
    parser.add_argument('--device-id', required=True, help='Device ID to update')
    parser.add_argument('--port-updates', required=True, 
                        help='JSON string of port updates (e.g., {\"2\": \"Genos\", \"3\": \"PC\"})')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
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
    
    # Parse port updates
    try:
        port_updates = json.loads(args.port_updates)
        port_updates = {int(k): v for k, v in port_updates.items()}
        log.info(f"Port updates to apply: {port_updates}")
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"Invalid JSON in --port-updates: {e}")
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
    print("=" * 80)
    
    # Test V2 API updates
    success = update_device_via_v2_api(api_client, args.device_id, port_updates)
    
    if not success:
        print("\\n" + "=" * 80)
        log.info("V2 API direct updates failed, trying command-based approach...")
        success = test_command_endpoints(api_client, args.device_id, port_updates)
    
    if success:
        print("\\n🎉 SUCCESS: Port update appears to have worked!")
        log.info("Port update successful via V2 API")
    else:
        print("\\n❌ FAILED: All V2 API update methods failed")
        log.error("All V2 API update attempts failed")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())