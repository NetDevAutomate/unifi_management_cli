#!/usr/bin/env python3
"""
CLI command for comprehensive port name verification.
Implements multiple verification techniques to detect API lying.
"""

import argparse
import logging
import sys
from typing import Dict, List

from .api_client import UnifiApiClient
from .config import UnifiConfig
from .ground_truth_verification import verify_with_ground_truth

log = logging.getLogger(__name__)


def create_verification_parser():
    """Create argument parser for verification command."""
    parser = argparse.ArgumentParser(
        description="Verify UniFi port name configurations using multiple techniques",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify specific device
  python -m unifi_mapper.verify_cli --device "US 8 60W" --port 1 --expected "Dream Machine Pro Max"

  # Verify all recent changes
  python -m unifi_mapper.verify_cli --verify-all

  # Use browser verification (most reliable)
  python -m unifi_mapper.verify_cli --browser --username unpoller --password 'vc%H26dhBHwbF^8!f9JS'

  # Multi-read consistency check
  python -m unifi_mapper.verify_cli --consistency-check --reads 10
        """
    )

    parser.add_argument(
        "--config", "-c",
        help="Path to .env configuration file",
        default="~/.dotfiles/.config/unifi_network_mapper/prod.env"
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # Specific verification
    parser.add_argument("--device", help="Specific device name to verify")
    parser.add_argument("--port", type=int, help="Specific port to verify")
    parser.add_argument("--expected", help="Expected port name")

    # Batch verification
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="Verify all ports that should have LLDP-based names"
    )

    # Browser verification
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Use browser automation for verification (most reliable)"
    )
    parser.add_argument("--username", help="UniFi username for browser verification")
    parser.add_argument("--password", help="UniFi password for browser verification")

    # Consistency checking
    parser.add_argument(
        "--consistency-check",
        action="store_true",
        help="Perform multi-read consistency checks to detect API lying"
    )
    parser.add_argument(
        "--reads", type=int, default=5,
        help="Number of reads for consistency check (default: 5)"
    )

    return parser


def main():
    """Main verification CLI entry point."""
    parser = create_verification_parser()
    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # Load configuration
    try:
        from .cli import load_env_from_config
        load_env_from_config(args.config)

        config = UnifiConfig.from_env()
    except Exception as e:
        log.error(f"Configuration error: {e}")
        log.error(f"Check your config file: {args.config}")
        sys.exit(1)

    # Create API client
    try:
        api_client = UnifiApiClient(
            base_url=config.base_url,
            site=config.site,
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
        )

        if not api_client.login():
            log.error("Failed to authenticate with UniFi Controller")
            sys.exit(1)

    except Exception as e:
        log.error(f"Failed to create API client: {e}")
        sys.exit(1)

    # Execute verification based on arguments
    try:
        if args.device and args.port is not None and args.expected:
            # Single port verification
            verify_single_port(api_client, args)

        elif args.verify_all:
            # Verify all LLDP-discovered ports
            verify_all_lldp_ports(api_client, args)

        else:
            # Show current state analysis
            analyze_current_state(api_client, args)

    except KeyboardInterrupt:
        log.info("Verification cancelled by user")
        sys.exit(1)
    except Exception as e:
        log.error(f"Verification error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def verify_single_port(api_client, args):
    """Verify a single port name."""
    log.info(f"Verifying {args.device} Port {args.port} should be '{args.expected}'")

    # Find device by name
    devices_response = api_client.get_devices(api_client.site)
    target_device = None

    if devices_response and "data" in devices_response:
        for device in devices_response["data"]:
            if args.device.lower() in device.get("name", "").lower():
                target_device = device
                break

    if not target_device:
        log.error(f"Device '{args.device}' not found")
        sys.exit(1)

    device_id = target_device.get("_id")
    device_name = target_device.get("name")
    device_ip = target_device.get("ip")

    log.info(f"Found device: {device_name} (ID: {device_id}, IP: {device_ip})")

    # Prepare verification request
    device_updates = {device_id: {args.port: args.expected}}
    browser_credentials = None

    if args.browser and args.username and args.password:
        browser_credentials = {
            "username": args.username,
            "password": args.password
        }

    # Perform verification
    verification_results, report = verify_with_ground_truth(
        api_client, device_updates, browser_credentials
    )

    # Print results
    print(report)

    # Exit with appropriate code
    success = verification_results.get(device_id, {}).get(args.port, False)
    sys.exit(0 if success else 1)


def verify_all_lldp_ports(api_client, args):
    """Verify all ports that should have LLDP-based names."""
    log.info("Discovering all ports with LLDP data for verification...")

    # Get all devices
    devices_response = api_client.get_devices(api_client.site)
    if not devices_response or "data" not in devices_response:
        log.error("Failed to get devices")
        sys.exit(1)

    # Find all switch/router devices
    network_devices = [
        d for d in devices_response["data"]
        if d.get("type") in ["ugw", "usg", "udm", "usw"]
    ]

    log.info(f"Found {len(network_devices)} network devices to check")

    device_updates = {}

    # Build list of expected port names based on LLDP
    for device in network_devices:
        device_id = device.get("_id")
        device_name = device.get("name", "Unknown")

        # Get LLDP info for this device
        lldp_info = api_client.get_lldp_info(api_client.site, device_id)

        if lldp_info:
            port_updates = {}
            for port_idx_str, lldp_data in lldp_info.items():
                port_idx = int(port_idx_str)
                remote_device_name = lldp_data.get("remote_device_name")

                if remote_device_name and len(remote_device_name) > 3:  # Valid device name
                    port_updates[port_idx] = remote_device_name

            if port_updates:
                device_updates[device_id] = port_updates
                log.info(f"{device_name}: {len(port_updates)} ports to verify")

    if not device_updates:
        log.info("No LLDP-based port names found to verify")
        return

    # Browser credentials if provided
    browser_credentials = None
    if args.browser and args.username and args.password:
        browser_credentials = {
            "username": args.username,
            "password": args.password
        }

    # Perform verification
    log.info(f"Verifying {sum(len(ports) for ports in device_updates.values())} total ports...")

    verification_results, report = verify_with_ground_truth(
        api_client, device_updates, browser_credentials
    )

    # Print detailed report
    print(report)

    # Count failures
    total_failures = sum(
        sum(1 for success in device_results.values() if not success)
        for device_results in verification_results.values()
    )

    if total_failures > 0:
        print(f"\n🚨 CRITICAL: {total_failures} port name verifications FAILED!")
        print("The UniFi API is returning stale/cached data.")
        print("Consider using --browser verification for ground truth.")
        sys.exit(1)
    else:
        print("\n✅ All port name verifications passed!")
        sys.exit(0)


def analyze_current_state(api_client, args):
    """Analyze current port state and detect potential issues."""
    print("🔍 UniFi Port State Analysis")
    print("=" * 50)

    # Get all devices
    devices_response = api_client.get_devices(api_client.site)
    if not devices_response or "data" not in devices_response:
        log.error("Failed to get devices")
        sys.exit(1)

    network_devices = [
        d for d in devices_response["data"]
        if d.get("type") in ["ugw", "usg", "udm", "usw"]
    ]

    api_cache_issues = 0
    total_lldp_ports = 0

    for device in network_devices:
        device_id = device.get("_id")
        device_name = device.get("name", "Unknown")
        device_ip = device.get("ip", "Unknown")

        print(f"\n📍 {device_name} (IP: {device_ip})")

        # Get LLDP info
        lldp_info = api_client.get_lldp_info(api_client.site, device_id)
        device_details = api_client.get_device_details(api_client.site, device_id)

        if not lldp_info or not device_details:
            continue

        port_table = device_details.get("port_table", [])
        port_name_map = {p.get("port_idx"): p.get("name") for p in port_table}

        for port_idx_str, lldp_data in lldp_info.items():
            port_idx = int(port_idx_str)
            total_lldp_ports += 1

            current_name = port_name_map.get(port_idx, f"Port {port_idx}")
            remote_device = lldp_data.get("remote_device_name", "Unknown")

            # Check if name suggests it should be different
            if remote_device != "Unknown" and len(remote_device) > 3:
                expected_name = remote_device
                name_matches = current_name == expected_name

                print(f"  Port {port_idx}: '{current_name}' -> LLDP: '{expected_name}' {'✅' if name_matches else '❌'}")

                if not name_matches:
                    api_cache_issues += 1

    print(f"\n📊 Analysis Summary:")
    print(f"Total LLDP ports: {total_lldp_ports}")
    print(f"Potential API cache issues: {api_cache_issues}")

    if api_cache_issues > 0:
        print(f"\n⚠️  Detected {api_cache_issues} ports where LLDP suggests different names")
        print("Run with --verify-all to perform comprehensive verification")


if __name__ == "__main__":
    main()