#!/usr/bin/env python3
"""
Client Path Tracer CLI tool for UniFi networks.

Traces the path of a client through the switch fabric to identify
connectivity issues and verify VLAN tagging.
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
from unifi_mapper.tracers.client_tracer import ClientPathTracer


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
        description='UniFi Client Path Tracer - Trace client connectivity through the network'
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

    # Trace options
    parser.add_argument('--mac', help='Client MAC address to trace')
    parser.add_argument('--ip', help='Client IP address to trace')
    parser.add_argument('--hostname', help='Client hostname to trace')
    parser.add_argument('--destination', help='Destination IP or gateway for path trace')
    parser.add_argument('--output', help='Output file for trace report')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')

    # Logging
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Configure logging
    configure_logging(debug=args.debug)
    logger = logging.getLogger(__name__)

    # Validate trace target
    if not any([args.mac, args.ip, args.hostname]):
        parser.error("At least one of --mac, --ip, or --hostname is required")

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

        # Run trace
        tracer = ClientPathTracer(api_client, site)

        # Determine client identifier
        client_id = args.mac or args.ip or args.hostname
        logger.info(f"Tracing path for client: {client_id}")

        result = tracer.trace(
            client_mac=args.mac,
            client_ip=args.ip,
            hostname=args.hostname,
            destination_ip=args.destination,
        )

        # Generate output
        if args.json:
            import json
            output = json.dumps(result.summary(), indent=2)
        else:
            output = tracer.generate_report(result)

        # Output report
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
            logger.info(f"Path trace report saved to: {args.output}")
        else:
            print(output)

        # Return code based on findings
        if not result.paths:
            logger.error("Client not found in the network")
            return 1

        paths_with_issues = [p for p in result.paths if p.issues]
        if paths_with_issues:
            logger.warning(f"Found {len(paths_with_issues)} paths with issues")
            return 1

        logger.info("Path trace complete - client path verified")
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
