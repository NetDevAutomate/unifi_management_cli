#!/usr/bin/env python3
"""
UniFi API Client - Interface with the UniFi Controller API.

This script provides a command-line interface to the UniFi API Client,
allowing you to query various endpoints and retrieve device information.
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

from src.unifi_mapper.api_client import UnifiApiClient

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def main():
    """Main entry point for the UniFi API Client."""
    # Load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="UniFi API Client - Interface with the UniFi Controller API"
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
        "--endpoint",
        default="devices",
        choices=["devices", "ports", "clients", "sites", "stats", "topology", "custom"],
        help="API endpoint to query",
    )
    parser.add_argument(
        "--custom-endpoint", help="Custom API endpoint path (when --endpoint=custom)"
    )
    parser.add_argument(
        "--output", "-o", help="Output file for the API response (JSON format)"
    )
    parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="pretty",
        help="Output format (json or pretty-printed json)",
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

    # Create the UniFi API Client
    api_client = UnifiApiClient(
        base_url=url, site=site, api_token=token, username=username, password=password
    )

    # Login to the UniFi Controller
    if not api_client.login():
        log.error("Failed to login to the UniFi Controller")
        return 1

    # Query the API endpoint
    try:
        if args.endpoint == "devices":
            data = api_client.get_devices()
            log.info(f"Retrieved {len(data)} devices")
        elif args.endpoint == "ports":
            data = api_client.get_ports()
            log.info("Retrieved port information")
        elif args.endpoint == "clients":
            data = api_client.get_clients()
            log.info("Retrieved client information")
        elif args.endpoint == "sites":
            data = api_client.get_sites()
            log.info("Retrieved site information")
        elif args.endpoint == "stats":
            data = api_client.get_stats()
            log.info("Retrieved statistics information")
        elif args.endpoint == "topology":
            data = api_client.get_topology()
            log.info("Retrieved topology information")
        elif args.endpoint == "custom" and args.custom_endpoint:
            data = api_client.get_api_data(args.custom_endpoint)
            log.info(f"Retrieved data from custom endpoint: {args.custom_endpoint}")
        else:
            log.error("Invalid endpoint or missing custom endpoint path")
            return 1

        # Format the output
        if args.format == "pretty":
            formatted_data = json.dumps(data, indent=2)
        else:
            formatted_data = json.dumps(data)

        # Output the data
        if args.output:
            with open(args.output, "w") as f:
                f.write(formatted_data)
            log.info(f"API response saved to {args.output}")
        else:
            print(formatted_data)
    except Exception as e:
        log.error(f"Error querying API endpoint: {e}")
        return 1
    finally:
        # Logout from the UniFi Controller
        api_client.logout()

    return 0


if __name__ == "__main__":
    sys.exit(main())
