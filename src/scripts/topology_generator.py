#!/usr/bin/env python3
"""
Network Topology Generator for UniFi networks.

This script generates comprehensive network topology diagrams and reports
using the NetworkTopology class from the unifi_mapper package.
"""

import argparse
import logging
import os
import sys

from src.unifi_mapper.network_topology import (
    NetworkTopology,
    UnifiApiClient,
    create_topology_from_env,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
log = logging.getLogger(__name__)


def main():
    """Main entry point for the network topology generator."""
    # Create directories if they don't exist
    os.makedirs("diagrams", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    os.makedirs("tmp", exist_ok=True)

    # Default output paths
    default_report = os.path.join("reports", "network_topology_report.md")
    default_diagram = os.path.join("diagrams", "network_diagram.png")

    parser = argparse.ArgumentParser(description="Generate a network topology diagram")
    parser.add_argument(
        "--output",
        "-o",
        default=default_report,
        help="Output file for the network topology report",
    )
    parser.add_argument(
        "--diagram",
        "-d",
        default=default_diagram,
        help="Output file for the network diagram (PNG format)",
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
        "--format",
        choices=["png", "svg", "dot", "mermaid", "all"],
        default="all",
        help="Output format for the diagram",
    )

    args = parser.parse_args()

    if args.env:
        # Use environment variables
        topology = create_topology_from_env()
    else:
        # Use command line arguments
        if not args.url:
            log.error("UniFi Controller URL is required")
            return 1

        if not args.token and not (args.username and args.password):
            log.error(
                "Either API token or username/password is required for authentication"
            )
            return 1

        # Create the API client
        api_client = UnifiApiClient(
            base_url=args.url,
            site=args.site,
            api_token=args.token,
            username=args.username,
            password=args.password,
        )

        # Create the network topology
        topology = NetworkTopology(api_client)

    if not topology:
        log.error("Failed to create network topology")
        return 1

    log.info("Starting network topology generator...")

    try:
        # Load devices from API
        topology.load_devices_from_api()

        # Infer connections
        topology.infer_connections()

        # Generate the report
        topology.generate_report(args.output)
        log.info(f"Network topology report saved to {args.output}")

        # Generate diagrams in requested format(s)
        if args.format == "all" or args.format == "png":
            png_path = f"{os.path.splitext(args.diagram)[0]}.png"
            topology.generate_network_diagram(png_path)
            log.info(f"PNG diagram saved to {png_path}")

        if args.format == "all" or args.format == "svg":
            svg_path = f"{os.path.splitext(args.diagram)[0]}.svg"
            topology.generate_network_diagram(svg_path)
            log.info(f"SVG diagram saved to {svg_path}")

        if args.format == "all" or args.format == "dot":
            dot_path = f"{os.path.splitext(args.diagram)[0]}.dot"
            try:
                topology.generate_dot_file(dot_path)
                log.info(f"DOT file saved to {dot_path}")
            except Exception as e:
                log.warning(f"Could not generate DOT file: {e}")

        if args.format == "all" or args.format == "mermaid":
            mermaid_path = f"{os.path.splitext(args.diagram)[0]}.mmd"
            with open(mermaid_path, "w") as f:
                f.write(topology.generate_mermaid_diagram())
            log.info(f"Mermaid diagram saved to {mermaid_path}")

            # Print the Mermaid diagram
            print("\nMermaid Diagram:")
            print(topology.generate_mermaid_diagram())

        log.info("Network topology generation completed successfully")
    except Exception as e:
        log.error(f"Error generating network topology: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
