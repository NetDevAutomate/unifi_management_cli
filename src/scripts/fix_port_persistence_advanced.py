#!/usr/bin/env python3
"""
Advanced fix for UniFi port name persistence issues.

This script addresses the specific issue where UniFi API calls return HTTP 200 success
but the port name changes don't actually persist in the controller database.

Key strategies:
1. Force device provisioning after updates
2. Use complete device configuration context
3. Handle configuration versioning properly
4. Add device restart triggers if needed
"""

import argparse
import json
import logging
import os
import sys
import time
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


def force_device_provisioning(api_client: UnifiApiClient, device_id: str) -> bool:
    """Force device to re-provision its configuration."""
    log.info(f"Forcing device provisioning for {device_id}")

    # Get device details to find MAC
    device_details = api_client.get_device_details(api_client.site, device_id)
    if not device_details:
        log.error("Failed to get device details for provisioning")
        return False

    device_mac = device_details.get("mac")
    if not device_mac:
        log.error("Device MAC not found")
        return False

    # Try different provisioning command endpoints
    provision_endpoints = [
        f"{api_client.base_url}/proxy/network/api/s/{api_client.site}/cmd/devmgr",
        f"{api_client.base_url}/api/s/{api_client.site}/cmd/devmgr",
    ]

    provision_commands = [
        {"cmd": "force-provision", "mac": device_mac},
        {"cmd": "provision", "mac": device_mac},
        {"cmd": "restart", "mac": device_mac, "reboot_type": "soft"},
    ]

    for endpoint in provision_endpoints:
        for cmd_data in provision_commands:
            try:
                log.info(f"Trying provisioning command: {cmd_data['cmd']}")
                api_client.session.headers.update(api_client.legacy_headers)
                response = api_client.session.post(endpoint, json=cmd_data, timeout=10)

                if response.status_code == 200:
                    log.info(f"✓ Provisioning command successful: {cmd_data['cmd']}")
                    time.sleep(3)  # Wait for provisioning to take effect
                    return True
                else:
                    log.debug(f"Provisioning command failed: {response.status_code}")

            except Exception as e:
                log.debug(f"Provisioning command error: {e}")

    log.warning("Failed to trigger device provisioning")
    return False


def update_with_full_context(
    api_client: UnifiApiClient, device_id: str, port_updates: Dict[int, str]
) -> bool:
    """Update device with complete configuration context."""
    log.info(f"Updating device {device_id} with full configuration context")

    # Get comprehensive device details
    device_details = api_client.get_device_details(api_client.site, device_id)
    if not device_details:
        log.error("Failed to get device details")
        return False

    log.info(
        f"Current device: {device_details.get('name', 'Unknown')} ({device_details.get('model', 'Unknown')})"
    )

    # Get current port table
    port_table = device_details.get("port_table", [])
    if not port_table:
        log.error("No port table found in device details")
        return False

    log.info(f"Found {len(port_table)} ports in device configuration")

    # Apply port updates
    updated_ports = 0
    for port in port_table:
        port_idx = port.get("port_idx")
        if port_idx in port_updates:
            old_name = port.get("name", f"Port {port_idx}")
            new_name = port_updates[port_idx]
            port["name"] = new_name
            updated_ports += 1
            log.info(f"  Port {port_idx}: '{old_name}' -> '{new_name}'")

    if updated_ports == 0:
        log.error("No matching ports found to update")
        return False

    # Create comprehensive update payload
    update_data = {
        # Core device identity
        "_id": device_details.get("_id"),
        "mac": device_details.get("mac"),
        "model": device_details.get("model"),
        "type": device_details.get("type"),
        # Configuration versioning (critical for persistence)
        "version": device_details.get("version"),
        "cfgversion": device_details.get("cfgversion"),
        # Updated port table
        "port_table": port_table,
        # Include all other device configuration to avoid conflicts
        "adopted": device_details.get("adopted", True),
        "disabled": device_details.get("disabled", False),
        "name": device_details.get("name", ""),
        "site_id": device_details.get("site_id", api_client.site),
    }

    # Include any additional configuration fields that exist
    additional_fields = [
        "config_network",
        "ethernet_table",
        "radio_table",
        "switch_caps",
        "port_overrides",
        "mgmt_network_id",
        "outdoor_mode_override",
        "lcm_brightness_override",
        "lcm_idle_timeout_override",
    ]

    for field in additional_fields:
        if field in device_details:
            update_data[field] = device_details[field]

    log.info(f"Update payload includes {len(update_data)} configuration fields")

    # Try multiple update approaches
    update_endpoints = [
        f"{api_client.base_url}/proxy/network/api/s/{api_client.site}/rest/device/{device_id}",
        f"{api_client.base_url}/api/s/{api_client.site}/rest/device/{device_id}",
    ]

    for endpoint in update_endpoints:
        try:
            log.info(f"Attempting update via: {endpoint}")
            api_client.session.headers.update(api_client.legacy_headers)

            response = api_client.session.put(endpoint, json=update_data, timeout=15)

            if response.status_code == 200:
                log.info(f"✓ Update successful via {endpoint}")

                # Wait for update to process
                log.info("Waiting for configuration to process...")
                time.sleep(3)

                # Force provisioning to ensure changes are applied
                log.info("Forcing device provisioning...")
                force_device_provisioning(api_client, device_id)

                # Wait additional time for provisioning
                log.info("Waiting for provisioning to complete...")
                time.sleep(5)

                return True
            else:
                log.warning(f"Update failed via {endpoint}: {response.status_code}")
                if response.status_code == 400:
                    log.warning(f"Error details: {response.text[:200]}")

        except Exception as e:
            log.warning(f"Update error via {endpoint}: {e}")

    return False


def verify_port_updates(
    api_client: UnifiApiClient,
    device_id: str,
    expected_updates: Dict[int, str],
    max_attempts: int = 10,
) -> bool:
    """Verify that port updates have persisted with extended retry logic."""
    log.info(f"Verifying port updates with up to {max_attempts} attempts...")

    for attempt in range(max_attempts):
        if attempt > 0:
            wait_time = min(attempt * 2, 10)  # Progressive backoff, max 10 seconds
            log.info(f"Waiting {wait_time}s before verification attempt {attempt + 1}")
            time.sleep(wait_time)

        try:
            # Get fresh device details
            device_details = api_client.get_device_details(api_client.site, device_id)
            if not device_details:
                log.warning(
                    f"Failed to get device details for verification attempt {attempt + 1}"
                )
                continue

            port_table = device_details.get("port_table", [])
            if not port_table:
                log.warning(f"No port table in verification attempt {attempt + 1}")
                continue

            # Check each expected update
            all_verified = True
            for port in port_table:
                port_idx = port.get("port_idx")
                if port_idx in expected_updates:
                    actual_name = port.get("name", f"Port {port_idx}")
                    expected_name = expected_updates[port_idx]

                    if actual_name == expected_name:
                        log.info(f"✓ Port {port_idx} verified: '{actual_name}'")
                    else:
                        log.warning(
                            f"✗ Port {port_idx} mismatch - expected: '{expected_name}', actual: '{actual_name}'"
                        )
                        all_verified = False

            if all_verified:
                log.info(
                    f"🎉 All port updates verified successfully after {attempt + 1} attempts!"
                )
                return True

        except Exception as e:
            log.warning(f"Verification error on attempt {attempt + 1}: {e}")

    log.error(f"❌ Port update verification failed after {max_attempts} attempts")
    return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Advanced fix for UniFi port name persistence"
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
    parser.add_argument("--device-id", required=True, help="Device ID to update")
    parser.add_argument(
        "--port-updates",
        required=True,
        help='JSON string of port updates (e.g., {"2": "Genos", "3": "PC"})',
    )
    parser.add_argument(
        "--force-restart",
        action="store_true",
        help="Force device restart after update (use with caution)",
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
        verify_ssl=False,
    )

    # Login
    if not api_client.login():
        log.error("Failed to login to UniFi Controller")
        return 1

    log.info("Successfully authenticated with UniFi Controller")
    print("=" * 80)

    # Apply the advanced fix
    log.info("🚀 Starting advanced port persistence fix...")
    success = update_with_full_context(api_client, args.device_id, port_updates)

    if success:
        log.info("✅ Port update completed, verifying persistence...")
        verified = verify_port_updates(api_client, args.device_id, port_updates)

        if verified:
            print("\\n🎉 SUCCESS: Port updates have been applied and verified!")
            return 0
        else:
            print("\\n⚠️  PARTIAL SUCCESS: Update completed but verification failed")
            log.warning(
                "Consider checking the UniFi UI manually or trying --force-restart"
            )
            return 2
    else:
        print("\\n❌ FAILED: Port update could not be completed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
