#!/usr/bin/env python3
"""
Debug utility for UniFi port update issues.

This script helps diagnose why UniFi API port name updates return HTTP 200
but don't persist in the UI. It provides detailed debugging information about
device configuration, API endpoints, and update attempts.
"""

import argparse
import logging
import os
import sys
from typing import Dict

from dotenv import load_dotenv

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unifi_mapper.api_client import UnifiApiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def debug_device_configuration(api_client: UnifiApiClient, device_id: str) -> None:
    """Debug device configuration and API endpoints."""
    log.info(f"=== Debugging Device Configuration for {device_id} ===")

    # Get comprehensive debug information
    debug_info = api_client.debug_device_config(device_id)

    print("\n" + "=" * 60)
    print("DEVICE DEBUG INFORMATION")
    print("=" * 60)

    print(f"Device ID: {debug_info['device_id']}")
    print(f"Timestamp: {debug_info['timestamp']}")
    print(f"UniFi OS Mode: {api_client.is_unifi_os}")
    print(f"Site: {api_client.site}")

    # Configuration fields
    print("\nCONFIGURATION FIELDS:")
    config_fields = debug_info.get("config_fields", {})
    for field, value in config_fields.items():
        print(f"  {field}: {value}")

    # API endpoints tested
    print("\nAPI ENDPOINTS TESTED:")
    for endpoint_info in debug_info.get("api_endpoints_tried", []):
        status = "✓" if endpoint_info.get("available") else "✗"
        print(
            f"  {status} {endpoint_info['endpoint']} (Status: {endpoint_info['status_code']})"
        )
        if "error" in endpoint_info:
            print(f"    Error: {endpoint_info['error']}")

    # Port table information
    port_table = debug_info.get("port_table", [])
    print(f"\nPORT TABLE ({len(port_table)} ports):")
    for port in port_table[:5]:  # Show first 5 ports
        port_idx = port.get("port_idx", "Unknown")
        port_name = port.get("name", "Unknown")
        port_up = port.get("up", False)
        port_enabled = port.get("enable", True)
        print(
            f"  Port {port_idx}: '{port_name}' (Up: {port_up}, Enabled: {port_enabled})"
        )

    if len(port_table) > 5:
        print(f"  ... and {len(port_table) - 5} more ports")

    # Errors
    errors = debug_info.get("errors", [])
    if errors:
        print("\nERRORS:")
        for error in errors:
            print(f"  ✗ {error}")

    print("=" * 60)


def test_port_update(
    api_client: UnifiApiClient, device_id: str, port_idx: int, new_name: str
) -> None:
    """Test updating a specific port name with detailed logging."""
    log.info(
        f"=== Testing Port Update: Device {device_id}, Port {port_idx} -> '{new_name}' ==="
    )

    # Get current port name
    device_details = api_client.get_device_details(api_client.site, device_id)
    if not device_details:
        log.error("Failed to get device details")
        return

    port_table = device_details.get("port_table", [])
    current_name = None
    for port in port_table:
        if port.get("port_idx") == port_idx:
            current_name = port.get("name", f"Port {port_idx}")
            break

    if current_name is None:
        log.error(f"Port {port_idx} not found in device port table")
        return

    log.info(f"Current port name: '{current_name}'")
    log.info(f"Target port name: '{new_name}'")

    # Create test port table with updated name
    updated_port_table = []
    for port in port_table:
        port_copy = port.copy()
        if port_copy.get("port_idx") == port_idx:
            port_copy["name"] = new_name
        updated_port_table.append(port_copy)

    # Test the update
    log.info("Attempting port table update...")
    success = api_client.update_device_port_table(device_id, updated_port_table)

    if success:
        log.info("✓ Update API call returned success (HTTP 200)")

        # Verify the change
        log.info("Verifying port name change...")
        verification_success = api_client.verify_port_update(
            device_id, port_idx, new_name, max_retries=5
        )

        if verification_success:
            log.info("✓ Port name update verified successfully!")
        else:
            log.error("✗ Port name update verification failed - change did not persist")

            # Get fresh device details to see what happened
            fresh_details = api_client.get_device_details(api_client.site, device_id)
            if fresh_details:
                fresh_port_table = fresh_details.get("port_table", [])
                for port in fresh_port_table:
                    if port.get("port_idx") == port_idx:
                        actual_name = port.get("name", f"Port {port_idx}")
                        log.error(f"Actual port name after update: '{actual_name}'")
                        break
    else:
        log.error("✗ Update API call failed")


def list_devices(api_client: UnifiApiClient) -> None:
    """List all devices with their IDs and names."""
    log.info("=== Listing All Devices ===\n")

    devices = api_client.list_devices_with_names()

    if not devices:
        print("No devices found.")
        return

    print(f"Found {len(devices)} devices:\n")
    print(f"{'ID':<26} {'Name':<25} {'Model':<20} {'Type':<10} {'IP':<15} {'State'}")
    print("-" * 120)

    for device in devices:
        device_id = (
            device["id"][:24] + "..." if len(device["id"]) > 24 else device["id"]
        )
        name = (
            device["name"][:23] + "..." if len(device["name"]) > 23 else device["name"]
        )
        model = (
            device["model"][:18] + "..."
            if len(device["model"]) > 18
            else device["model"]
        )
        device_type = (
            device["type"][:8] + "..." if len(device["type"]) > 8 else device["type"]
        )
        ip = device["ip"][:13] + "..." if len(device["ip"]) > 13 else device["ip"]
        state = device["state"]

        print(
            f"{device_id:<26} {name:<25} {model:<20} {device_type:<10} {ip:<15} {state}"
        )

    print("\nTo debug a specific device, use: --device-id <DEVICE_ID>")


def test_port_updates(
    api_client: UnifiApiClient, device_id: str, port_updates: Dict[int, str]
) -> None:
    """Test updating multiple port names."""
    log.info(f"=== Testing Port Updates for Device {device_id} ===")

    for port_idx, new_name in port_updates.items():
        print(f"\nTesting port {port_idx} -> '{new_name}'")
        test_port_update(api_client, device_id, port_idx, new_name)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Debug UniFi port update persistence issues"
    )
    parser.add_argument("--url", help="URL of the UniFi Controller")
    parser.add_argument("--site", default="default", help="Site name")
    parser.add_argument("--token", help="API token for authentication")
    parser.add_argument("--username", help="Username for authentication")
    parser.add_argument("--password", help="Password for authentication")
    parser.add_argument(
        "--env",
        action="store_true",
        help="Use environment variables instead of command line arguments",
    )
    parser.add_argument("--device-id", help="Device ID to debug")
    parser.add_argument(
        "--test-port", type=int, help="Port index to test update (optional)"
    )
    parser.add_argument(
        "--test-name", default="TEST-PORT", help="Test name for port update"
    )
    parser.add_argument(
        "--port-updates",
        help='JSON string of port updates (e.g., {"2": "Genos", "3": "PC"})',
    )
    parser.add_argument(
        "--list-device-ids",
        action="store_true",
        help="List all devices with their IDs and names",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load environment variables if requested
    if args.env:
        load_dotenv()
        url = os.getenv("UNIFI_URL")
        site = os.getenv("UNIFI_SITE", "default")
        token = os.getenv("UNIFI_CONSOLE_API_TOKEN")
        username = os.getenv("UNIFI_USERNAME")
        password = os.getenv("UNIFI_PASSWORD")
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
        log.error(
            "Either API token or username/password is required for authentication"
        )
        return 1

    # Create API client
    api_client = UnifiApiClient(
        base_url=url,
        site=site,
        api_token=token,
        username=username,
        password=password,
        verify_ssl=False,
    )

    # Login
    if not api_client.login():
        log.error("Failed to login to UniFi Controller")
        return 1

    log.info("Successfully authenticated with UniFi Controller")

    # List devices if requested
    if args.list_device_ids:
        list_devices(api_client)
        return 0

    # Require device ID for other operations
    if not args.device_id:
        log.error("--device-id is required unless using --list-device-ids")
        return 1

    # Debug device configuration
    debug_device_configuration(api_client, args.device_id)

    # Test port updates if provided
    if args.port_updates:
        try:
            import json

            port_updates = json.loads(args.port_updates)
            # Convert string keys to integers
            port_updates = {int(k): v for k, v in port_updates.items()}
            print("\n")
            test_port_updates(api_client, args.device_id, port_updates)
        except (json.JSONDecodeError, ValueError) as e:
            log.error(f"Invalid JSON in --port-updates: {e}")
            log.error('Example: --port-updates \'{"2": "Genos", "3": "PC"}\'')

    # Test single port update if requested
    elif args.test_port is not None:
        print("\n")
        test_port_update(api_client, args.device_id, args.test_port, args.test_name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
