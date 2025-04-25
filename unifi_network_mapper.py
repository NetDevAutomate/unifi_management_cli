#!/usr/bin/env python3
"""
UniFi Network Mapper - Main entry point for the UniFi Network Topology Visualization Toolkit.

This script provides a unified interface for:
1. Discovering UniFi devices
2. Mapping ports based on LLDP/CDP information
3. Generating network topology diagrams
4. Creating detailed port mapping reports
"""

import os
import sys
import logging
import argparse
import warnings
import datetime
import urllib3

# Suppress InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)

# Add the src directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import the UnifiPortMapper class
from src.unifi_mapper.port_mapper import UnifiPortMapper
from src.unifi_mapper.models import DeviceInfo, PortInfo


def load_env_file(env_file=".env"):
    """
    Simple function to load environment variables from a .env file
    """
    if not os.path.exists(env_file):
        return

    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            key, value = line.split("=", 1)
            os.environ[key] = value


def main():
    """Main entry point for the UniFi Network Mapper."""
    # Load environment variables
    load_env_file()

    # Create directories if they don't exist
    os.makedirs("reports", exist_ok=True)
    os.makedirs("diagrams", exist_ok=True)

    # Default output paths
    default_report = os.path.join("reports", "port_mapping_report.md")
    default_diagram = os.path.join("diagrams", "network_diagram.png")

    parser = argparse.ArgumentParser(
        description="UniFi Network Mapper - Visualize and manage UniFi network topology"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=default_report,
        help="Output file for the port mapping report",
    )
    parser.add_argument(
        "--diagram",
        "-d",
        default=default_diagram,
        help="Output file for the network diagram",
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
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run mode (do not apply changes)"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="Do not verify SSL certificates"
    )
    parser.add_argument(
        "--format",
        choices=["png", "svg", "dot", "mermaid", "html"],
        default="png",
        help="Format for the network diagram",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--connected-devices",
        action="store_true",
        help="Include non-UniFi connected devices in the diagram",
    )

    args = parser.parse_args()

    if args.env:
        # Use environment variables
        url = os.environ.get("UNIFI_URL")
        site = os.environ.get("UNIFI_SITE", "default")
        token = os.environ.get("UNIFI_CONSOLE_API_TOKEN")
        username = os.environ.get("UNIFI_USERNAME")
        password = os.environ.get("UNIFI_PASSWORD")
        verify_ssl = os.environ.get("UNIFI_VERIFY_SSL", "true").lower() != "false"
        timeout = int(os.environ.get("UNIFI_TIMEOUT", "10"))
    else:
        # Use command line arguments
        url = args.url
        site = args.site
        token = args.token
        username = args.username
        password = args.password
        verify_ssl = not args.no_verify
        timeout = 10

    if not url:
        log.error("UniFi Controller URL is required")
        return 1

    if not token and not (username and password):
        log.error(
            "Either API token or username/password is required for authentication"
        )
        return 1

    # Create the UniFi Port Mapper
    port_mapper = UnifiPortMapper(
        base_url=url,
        site=site,
        api_token=token,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        timeout=timeout,
    )

    # Run the port mapper
    from src.unifi_mapper.run_methods import run_port_mapper

    devices, connections = run_port_mapper(
        api_client=port_mapper.api_client,
        site_id=args.site,
        dry_run=args.dry_run,
        output_path=args.output,
        diagram_path=args.diagram,
        diagram_format=args.format,
        debug=args.debug,
        show_connected_devices=args.connected_devices,
    )

    # Only print devices and connections in debug mode
    if args.debug:
        print(devices, connections)

    return 0


if __name__ == "__main__":
    sys.exit(main())
