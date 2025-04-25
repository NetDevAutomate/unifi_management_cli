#!/usr/bin/env python3
"""
UniFi Port Mapper - A tool to automatically name ports based on LLDP/CDP information.
Main entry point for the application.
"""

import os
import sys
import argparse
import logging
import getpass
from typing import Dict, List, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# Import the port mapper modules
try:
    from .port_mapper import UnifiPortMapper
except ImportError:
    # Allow running as a standalone script
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from unifi_mapper.port_mapper import UnifiPortMapper


def parse_args():
    """
    Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='UniFi Port Mapper - Automatically name ports based on LLDP/CDP information')
    
    # Connection options
    parser.add_argument('-u', '--url', help='URL of the UniFi Controller (e.g., https://unifi.local:8443)')
    parser.add_argument('-s', '--site', default='default', help='Site name (default: default)')
    parser.add_argument('-t', '--token', help='API token for authentication')
    parser.add_argument('-n', '--username', help='Username for authentication')
    parser.add_argument('-p', '--password', help='Password for authentication (if not provided, will prompt)')
    parser.add_argument('-k', '--insecure', action='store_true', help='Allow insecure SSL connections')
    parser.add_argument('--timeout', type=int, default=10, help='Connection timeout in seconds (default: 10)')
    
    # Action options
    parser.add_argument('--dry-run', action='store_true', help='Show proposed changes without applying them')
    parser.add_argument('--test-connection', action='store_true', help='Test the connection to the UniFi Controller')
    parser.add_argument('--apply', action='store_true', help='Apply port name changes')
    parser.add_argument('--report', default='port_mapping_report.md', help='Path to save the report to (default: port_mapping_report.md)')
    parser.add_argument('--diagram', default='network_diagram.png', help='Path to save the network diagram to (default: network_diagram.png)')
    parser.add_argument('--mermaid', action='store_true', help='Generate a Mermaid diagram of the network topology')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    
    return parser.parse_args()


def main(args=None):
    """
    Main entry point for the application.
    
    Args:
        args: Command line arguments (if None, will parse from sys.argv)
    """
    if args is None:
        args = parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Get password if not provided
    password = args.password
    if args.username and not password:
        password = getpass.getpass('Password: ')
    
    # Create the port mapper
    port_mapper = UnifiPortMapper(
        base_url=args.url,
        site=args.site,
        verify_ssl=not args.insecure,
        username=args.username,
        password=password,
        api_token=args.token,
        timeout=args.timeout
    )
    
    # Run the port mapper
    if args.test_connection:
        # Test the connection
        if port_mapper.login():
            log.info("Connection successful!")
            port_mapper.logout()
            return 0
        else:
            log.error("Connection failed!")
            return 1
    
    # Run the port mapper
    success = port_mapper.run(apply_changes=args.apply, report_filename=args.report)
    
    # Generate network diagram if requested
    if success and args.diagram:
        log.info(f"Generating network diagram to {args.diagram}...")
        port_mapper.generate_network_diagram(args.diagram)
    
    # Generate Mermaid diagram if requested
    if success and args.mermaid:
        log.info("Generating Mermaid diagram...")
        mermaid = port_mapper.generate_mermaid_diagram()
        print("\nMermaid Diagram:")
        print(mermaid)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
