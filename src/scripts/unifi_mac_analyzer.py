#!/usr/bin/env python3
"""
MAC Table Analyzer CLI tool for UniFi networks.

Analyzes MAC address tables across switches to detect flapping,
unauthorized devices, and potential security issues.
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
from unifi_mapper.analyzers.mac_analyzer import MACTableAnalyzer


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
    parser = argparse.ArgumentParser(
        description='UniFi MAC Table Analyzer - Detect MAC flapping, loops, and unauthorized devices'
    )

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

    # Analysis options
    parser.add_argument('--allowed-macs', help='Path to file with allowed MAC addresses (one per line)')
    parser.add_argument('--output', help='Output file for analysis report')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')

    # Logging
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Configure logging
    configure_logging(debug=args.debug)
    logger = logging.getLogger(__name__)

    api_client = None
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

        # Load allowed MACs if specified
        allowed_macs = set()
        if args.allowed_macs:
            if os.path.exists(args.allowed_macs):
                with open(args.allowed_macs, 'r') as f:
                    for line in f:
                        mac = line.strip().lower()
                        if mac and not mac.startswith('#'):
                            allowed_macs.add(mac)
                logger.info(f"Loaded {len(allowed_macs)} allowed MAC addresses")

        # Run analysis
        analyzer = MACTableAnalyzer(api_client, site)
        if allowed_macs:
            analyzer.allowed_macs = allowed_macs

        logger.info("Running MAC table analysis...")
        result = analyzer.analyze()

        # Generate output
        if args.json:
            import json
            output = json.dumps(result.summary(), indent=2)
        else:
            output = analyzer.generate_report(result)

        # Output report
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            logger.info(f"Analysis report saved to: {args.output}")
        else:
            print(output)

        # Return code based on findings
        if result.flapping_events:
            logger.warning(f"Found {len(result.flapping_events)} MAC flapping events!")
            return 1
        elif result.unauthorized_macs:
            logger.warning(f"Found {len(result.unauthorized_macs)} unauthorized MAC addresses!")
            return 1

        logger.info("MAC table analysis complete - no critical issues found")
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
        if api_client:
            try:
                api_client.logout()
            except:
                pass


if __name__ == '__main__':
    sys.exit(main())
