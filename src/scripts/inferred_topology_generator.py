#!/usr/bin/env python3
"""
Inferred Network Topology Generator for UniFi networks.

This script generates network topology diagrams based on device types and naming conventions
when LLDP/CDP information is unavailable or incomplete.
"""

import os
import sys
import logging
import argparse
from dotenv import load_dotenv
from src.unifi_mapper.inferred_topology import (
    generate_inferred_topology,
    create_inferred_topology_from_env,
    InferredNetworkTopology
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def main():
    """Main entry point for the inferred network topology generator."""
    # Load environment variables
    load_dotenv()
    
    # Create directories if they don't exist
    os.makedirs('diagrams', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    os.makedirs('tmp', exist_ok=True)
    
    # Default output paths
    default_report = os.path.join('reports', 'inferred_topology_report.md')
    default_diagram = os.path.join('diagrams', 'inferred_topology_diagram.png')
    
    parser = argparse.ArgumentParser(description='Generate an inferred network topology diagram')
    parser.add_argument('--output', '-o', default=default_report,
                        help='Output file for the network topology report')
    parser.add_argument('--diagram', '-d', default=default_diagram,
                        help='Output file for the network diagram (PNG format)')
    parser.add_argument('--url', help='URL of the UniFi Controller')
    parser.add_argument('--site', default='default', help='Site name')
    parser.add_argument('--token', help='API token for authentication')
    parser.add_argument('--username', help='Username for authentication')
    parser.add_argument('--password', help='Password for authentication')
    parser.add_argument('--env', action='store_true', 
                        help='Use environment variables instead of command line arguments')
    parser.add_argument('--format', choices=['png', 'svg', 'dot', 'mermaid', 'all'], default='all',
                        help='Output format for the diagram')
    
    args = parser.parse_args()
    
    if args.env:
        # Use environment variables
        topology = create_inferred_topology_from_env()
    else:
        # Use command line arguments
        if not args.url:
            log.error("UniFi Controller URL is required")
            return 1
        
        if not args.token and not (args.username and args.password):
            log.error("Either API token or username/password is required for authentication")
            return 1
        
        # Generate inferred topology
        topology = generate_inferred_topology(
            base_url=args.url,
            site=args.site,
            api_token=args.token,
            username=args.username,
            password=args.password,
            output_path=args.output,
            diagram_path=args.diagram
        )
    
    if not topology:
        log.error("Failed to create inferred network topology")
        return 1
    
    log.info("Inferred network topology generation completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
