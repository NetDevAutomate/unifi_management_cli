#!/usr/bin/env python3
"""
Automated network testing and optimization CLI.
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
from unifi_mapper.network_automation import NetworkAutomation

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
    parser = argparse.ArgumentParser(description='Automated Network Testing and Optimization')
    
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
    
    # Automation options
    parser.add_argument('--apply-trunk-profiles', action='store_true', 
                       help='Apply trunk profiles to uplink ports')
    parser.add_argument('--profile-name', default='Trunk Default+VLAN10',
                       help='Name of trunk profile to apply')
    
    parser.add_argument('--test-connectivity', action='store_true',
                       help='Test inter-VLAN connectivity')
    parser.add_argument('--test-targets', nargs='+', 
                       default=['192.168.125.1', '192.168.10.1'],
                       help='IP addresses to test connectivity to')
    
    parser.add_argument('--full-automation', action='store_true',
                       help='Run complete automation: apply profiles + test connectivity')
    
    parser.add_argument('--output', help='Output file for test report')
    
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
        
        # Initialize automation
        automation = NetworkAutomation(api_client, site)
        
        port_results = []
        connectivity_results = {}
        
        # Apply trunk profiles
        if args.apply_trunk_profiles or args.full_automation:
            logger.info(f"Applying trunk profile '{args.profile_name}' to uplink ports")
            
            if args.dry_run:
                uplinks = automation.find_uplink_ports()
                logger.info(f"Would apply trunk profile to {len(uplinks)} uplink ports:")
                for uplink in uplinks:
                    logger.info(f"  - {uplink['device_name']} Port {uplink['port_idx']} → {uplink['connected_to']}")
            else:
                port_results = automation.apply_trunk_profile_to_uplinks(args.profile_name)
                
                successful = sum(1 for r in port_results if r.success)
                total = len(port_results)
                logger.info(f"Port profile application: {successful}/{total} successful")
                
                for result in port_results:
                    status = "✅" if result.success else "❌"
                    logger.info(f"{status} {result.device_name} Port {result.port_idx}: {result.message}")
        
        # Test connectivity
        if args.test_connectivity or args.full_automation:
            logger.info(f"Testing connectivity to: {', '.join(args.test_targets)}")
            
            if args.dry_run:
                logger.info(f"Would test connectivity to {len(args.test_targets)} targets")
            else:
                connectivity_results = automation.comprehensive_connectivity_test(args.test_targets)
                
                successful = sum(1 for r in connectivity_results.values() if r.success)
                total = len(connectivity_results)
                logger.info(f"Connectivity tests: {successful}/{total} successful")
                
                for target, result in connectivity_results.items():
                    status = "✅" if result.success else "❌"
                    if result.success and result.avg_latency:
                        logger.info(f"{status} {target}: {result.avg_latency:.2f}ms avg, {result.packet_loss}% loss")
                    else:
                        logger.info(f"{status} {target}: {result.packet_loss}% packet loss")
        
        # Generate report
        if not args.dry_run and (port_results or connectivity_results):
            report = automation.generate_test_report(connectivity_results, port_results)
            
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(report)
                logger.info(f"Test report saved to: {args.output}")
            else:
                print("\n" + report)
        
        # Determine exit code
        if args.dry_run:
            return 0
        
        port_success = not port_results or all(r.success for r in port_results)
        connectivity_success = not connectivity_results or all(r.success for r in connectivity_results.values())
        
        if port_success and connectivity_success:
            logger.info("🎉 All automation tasks completed successfully!")
            return 0
        else:
            logger.error("Some automation tasks failed - check the results above")
            return 1
        
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
