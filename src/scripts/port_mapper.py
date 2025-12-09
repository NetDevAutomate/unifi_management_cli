#!/usr/bin/env python3
"""
UniFi Port Mapper - Map ports on UniFi devices based on LLDP/CDP information.

This script provides comprehensive port mapping functionality for UniFi devices,
including automatic port naming based on LLDP/CDP information, port status reporting,
and network topology visualization.
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from src.unifi_mapper.port_mapper import UnifiPortMapper, run_port_mapper

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def main():
    """Main entry point for the UniFi Port Mapper."""
    # Load environment variables
    load_dotenv()

    # Create directories if they don't exist
    os.makedirs("reports", exist_ok=True)
    os.makedirs("diagrams", exist_ok=True)

    # Default output paths
    default_report = os.path.join("reports", "port_mapping_report.md")
    default_diagram = os.path.join("diagrams", "network_diagram.png")

    parser = argparse.ArgumentParser(
        description="UniFi Port Mapper - Map ports on UniFi devices"
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
        "--no-diagram", action="store_true", help="Do not generate network diagram"
    )
    parser.add_argument(
        "--no-report", action="store_true", help="Do not generate port mapping report"
    )
    parser.add_argument(
        "--discover-all",
        action="store_true",
        help="Discover all devices in the network",
    )
    parser.add_argument(
        "--patch-only",
        action="store_true",
        help="Only apply port naming patches without generating reports",
    )

    args = parser.parse_args()

    if args.env:
        # Use environment variables
        url = os.getenv("UNIFI_URL")
        site = os.getenv("UNIFI_SITE", "default")
        token = os.getenv("UNIFI_CONSOLE_API_TOKEN")
        username = os.getenv("UNIFI_USERNAME")
        password = os.getenv("UNIFI_PASSWORD")
    else:
        # Use command line arguments
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

    # Create the UniFi Port Mapper
    port_mapper = UnifiPortMapper(
        base_url=url, site=site, api_token=token, username=username, password=password
    )

    # Run the port mapper with the appropriate options
    if args.patch_only:
        # Only apply port naming patches
        log.info("Applying port naming patches only")
        return port_mapper.apply_port_name_changes(port_mapper.update_port_names())
    else:
        # Run the full port mapper
        return run_port_mapper(
            port_mapper=port_mapper,
            output_path=None if args.no_report else args.output,
            diagram_path=None if args.no_diagram else args.diagram,
            dry_run=args.dry_run,
            discover_all=args.discover_all,
        )


if __name__ == "__main__":
    sys.exit(main())
