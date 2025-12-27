#!/usr/bin/env python3
"""
VLAN Auto-Fix CLI tool for UniFi networks.
"""

import argparse
import logging
import sys
import os
import urllib3
from pathlib import Path
from dotenv import load_dotenv

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unifi_mapper.api_client import UnifiApiClient
from unifi_mapper.vlan_configurator import VLANConfigurator

def configure_logging(debug=False):
    """Configure logging with appropriate level."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def load_env_file(env_file_path):
    """Load environment variables from file."""
    if not os.path.exists(env_file_path):
        raise FileNotFoundError(f"Configuration file not found: {env_file_path}")
    
    load_dotenv(env_file_path)
    
    return {
        'UNIFI_URL': os.getenv('UNIFI_URL'),
        'UNIFI_CONSOLE_API_TOKEN': os.getenv('UNIFI_CONSOLE_API_TOKEN'),
        'UNIFI_USERNAME': os.getenv('UNIFI_USERNAME'),
        'UNIFI_PASSWORD': os.getenv('UNIFI_PASSWORD'),
        'UNIFI_SITE': os.getenv('UNIFI_SITE', 'default'),
        'UNIFI_VERIFY_SSL': os.getenv('UNIFI_VERIFY_SSL', 'false'),
        'UNIFI_TIMEOUT': os.getenv('UNIFI_TIMEOUT', '10'),
    }

def handle_self_signed_certs():
    """Disable SSL warnings for self-signed certificates."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def main():
    parser = argparse.ArgumentParser(description='UniFi VLAN Auto-Configuration Tool')
    
    # Configuration options
    parser.add_argument('--config', help='Path to configuration file')
    parser.add_argument('--env', action='store_true', help='Load configuration from .env file')
    
    # Connection options
    parser.add_argument('--url', help='UniFi Controller URL')
    parser.add_argument('--token', help='API token')
    parser.add_argument('--username', help='Username')
    parser.add_argument('--password', help='Password')
    parser.add_argument('--site', default='default', help='Site name (default: default)')
    parser.add_argument('--verify-ssl', action='store_true', help='Verify SSL certificates')
    parser.add_argument('--timeout', type=int, default=10, help='Request timeout in seconds')
    
    # Auto-fix options
    parser.add_argument('--auto-fix', action='store_true', help='Automatically fix VLAN connectivity')
    parser.add_argument('--source-vlan', type=int, default=1, help='Source VLAN ID (default: 1)')
    parser.add_argument('--dest-vlan', type=int, default=10, help='Destination VLAN ID (default: 10)')
    parser.add_argument('--source-subnet', default='192.168.125.0/24', help='Source VLAN subnet')
    parser.add_argument('--dest-subnet', default='192.168.10.0/24', help='Destination VLAN subnet')
    parser.add_argument('--source-gateway', default='192.168.125.1', help='Source VLAN gateway')
    parser.add_argument('--dest-gateway', default='192.168.10.1', help='Destination VLAN gateway')
    
    # Individual actions
    parser.add_argument('--create-network', help='Create network: "name,vlan_id,subnet,gateway"')
    parser.add_argument('--fix-gateway', help='Fix gateway: "network_id,gateway_ip"')
    parser.add_argument('--create-trunk', help='Create trunk profile: "name,native_vlan,tagged_vlans"')
    
    # Logging
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    
    args = parser.parse_args()
    
    # Configure logging
    configure_logging(debug=args.debug)
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        config = {}
        if args.config:
            config = load_env_file(args.config)
        elif args.env:
            config = load_env_file('.env')
        
        # Override with command line arguments
        url = args.url or config.get('UNIFI_URL')
        token = args.token or config.get('UNIFI_CONSOLE_API_TOKEN')
        username = args.username or config.get('UNIFI_USERNAME')
        password = args.password or config.get('UNIFI_PASSWORD')
        site = args.site or config.get('UNIFI_SITE', 'default')
        verify_ssl = args.verify_ssl or config.get('UNIFI_VERIFY_SSL', 'false').lower() == 'true'
        timeout = args.timeout or int(config.get('UNIFI_TIMEOUT', '10'))
        
        if not url:
            logger.error("UniFi Controller URL is required")
            return 1
        
        if not (token or (username and password)):
            logger.error("Either API token or username/password is required")
            return 1
        
        # Handle self-signed certificates
        if not verify_ssl:
            handle_self_signed_certs()
        
        if args.dry_run:
            logger.info("DRY RUN MODE - No changes will be made")
        
        # Initialize API client
        logger.info(f"Connecting to UniFi Controller at {url}")
        api_client = UnifiApiClient(
            base_url=url,
            site=site,
            verify_ssl=verify_ssl,
            timeout=timeout,
            username=username,
            password=password,
            api_token=token
        )
        
        # Authenticate
        success = api_client.login()
        if not success:
            logger.error("Authentication failed")
            return 1
        
        logger.info("Successfully authenticated")
        
        # Initialize configurator
        configurator = VLANConfigurator(api_client, site)
        
        if args.auto_fix:
            logger.info(f"Auto-fixing VLAN connectivity: VLAN {args.source_vlan} ↔ VLAN {args.dest_vlan}")
            
            if args.dry_run:
                logger.info("Would perform the following actions:")
                logger.info(f"1. Create VLAN {args.source_vlan} network if missing")
                logger.info(f"2. Fix VLAN {args.dest_vlan} gateway configuration")
                logger.info(f"3. Create trunk profile for VLANs {args.source_vlan} and {args.dest_vlan}")
                return 0
            
            results = configurator.auto_fix_vlan_connectivity(
                source_vlan=args.source_vlan,
                dest_vlan=args.dest_vlan,
                source_subnet=args.source_subnet,
                dest_subnet=args.dest_subnet,
                source_gateway=args.source_gateway,
                dest_gateway=args.dest_gateway
            )
            
            # Report results
            success_count = sum(results.values())
            total_count = len(results)
            
            logger.info(f"Auto-fix completed: {success_count}/{total_count} actions successful")
            for action, success in results.items():
                status = "✅" if success else "❌"
                action_name = action.replace('_', ' ').title()
                logger.info(f"{status} {action_name}: {'Success' if success else 'Failed'}")
            
            if success_count == total_count:
                logger.info("🎉 All VLAN connectivity issues have been resolved!")
                return 0
            else:
                logger.error("Some issues remain - check the logs above")
                return 1
        
        # Individual actions
        if args.create_network:
            parts = args.create_network.split(',')
            if len(parts) != 4:
                logger.error("create-network format: name,vlan_id,subnet,gateway")
                return 1
            
            name, vlan_id, subnet, gateway = parts
            if args.dry_run:
                logger.info(f"Would create network: {name} (VLAN {vlan_id})")
            else:
                success = configurator.create_network(name, int(vlan_id), subnet, gateway)
                logger.info(f"Network creation: {'Success' if success else 'Failed'}")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        try:
            api_client.logout()
        except:
            pass

if __name__ == '__main__':
    sys.exit(main())
