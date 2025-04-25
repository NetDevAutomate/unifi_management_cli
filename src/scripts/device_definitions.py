#!/usr/bin/env python3
"""
UniFi Device Definitions Manager - Manage device definitions for the UniFi Port Mapper.

This script provides functionality to view and manage device definitions used by
the UniFi Port Mapper for port naming and device type detection.
"""

import os
import sys
import logging
import json
import argparse
from src.unifi_mapper.device_definitions import get_device_definitions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


def main():
    """Main entry point for the UniFi Device Definitions Manager."""
    parser = argparse.ArgumentParser(description='UniFi Device Definitions Manager')
    parser.add_argument('--output', '-o', help='Output file for device definitions (JSON format)')
    parser.add_argument('--format', choices=['json', 'text'], default='text',
                        help='Output format (json or text)')
    
    args = parser.parse_args()
    
    # Get device definitions
    device_defs = get_device_definitions()
    
    # Display device definitions
    if args.format == 'json':
        # Convert device definitions to JSON-serializable format
        json_defs = {}
        for key, value in device_defs.items():
            json_defs[key] = {
                'name': value.name,
                'port_count': value.port_count,
                'port_naming_scheme': value.port_naming_scheme,
                'special_ports': value.special_ports,
                'sfp_ports': value.sfp_ports
            }
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(json_defs, f, indent=2)
            log.info(f"Device definitions saved to {args.output}")
        else:
            print(json.dumps(json_defs, indent=2))
    else:
        # Display in text format
        print("UniFi Device Definitions:")
        for key, value in device_defs.items():
            print(f"\n{key}:")
            print(f"  Name: {value.name}")
            print(f"  Port Count: {value.port_count}")
            print(f"  Port Naming Scheme: {value.port_naming_scheme}")
            if value.special_ports:
                print("  Special Ports:")
                for port_idx, port_name in value.special_ports.items():
                    print(f"    {port_idx}: {port_name}")
            if value.sfp_ports:
                print("  SFP Ports:")
                for port_idx in value.sfp_ports:
                    print(f"    {port_idx}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
