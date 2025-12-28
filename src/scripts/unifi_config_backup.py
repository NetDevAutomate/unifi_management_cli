#!/usr/bin/env python3
"""
Configuration Backup & Diff CLI tool for UniFi networks.

Creates configuration backups and compares them to detect changes.
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
from unifi_mapper.backup.config_backup import ConfigBackup


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
        description='UniFi Configuration Backup & Diff - Manage configuration snapshots'
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

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create a new backup')
    backup_parser.add_argument('--description', '-d', help='Backup description')

    # List command
    list_parser = subparsers.add_parser('list', help='List available backups')
    list_parser.add_argument('--limit', '-n', type=int, default=10, help='Number of backups to show')

    # Diff command
    diff_parser = subparsers.add_parser('diff', help='Compare configurations')
    diff_parser.add_argument('baseline', help='Baseline backup ID')
    diff_parser.add_argument('--compare', '-c', help='Comparison backup ID (default: current config)')
    diff_parser.add_argument('--output', '-o', help='Output file for diff report')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a backup')
    delete_parser.add_argument('backup_id', help='Backup ID to delete')

    # Common options
    parser.add_argument('--backup-dir', help='Directory for storing backups')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

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

        # Initialize backup manager
        backup_dir = Path(args.backup_dir) if args.backup_dir else None
        backup_manager = ConfigBackup(api_client, site, backup_dir)

        # Execute command
        if args.command == 'backup':
            logger.info("Creating configuration backup...")
            metadata = backup_manager.create_backup(args.description or "")
            print(f"\nBackup created successfully!")
            print(f"  ID: {metadata.backup_id}")
            print(f"  Timestamp: {metadata.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Devices: {metadata.devices_count}")
            print(f"  Networks: {metadata.networks_count}")
            print(f"  Port Profiles: {metadata.port_profiles_count}")
            print(f"  File: {metadata.file_path}")
            return 0

        elif args.command == 'list':
            backups = backup_manager.list_backups()[:args.limit]
            if not backups:
                print("No backups found.")
                return 0

            print(f"\nAvailable backups ({len(backups)} shown):\n")
            print(f"{'ID':<30} {'Timestamp':<20} {'Devices':<8} {'Description'}")
            print("-" * 80)
            for backup in backups:
                desc = backup.description[:30] + "..." if len(backup.description) > 30 else backup.description
                print(f"{backup.backup_id:<30} {backup.timestamp.strftime('%Y-%m-%d %H:%M'):<20} {backup.devices_count:<8} {desc}")
            return 0

        elif args.command == 'diff':
            logger.info(f"Comparing configurations: {args.baseline} vs {args.compare or 'current'}")
            try:
                diff = backup_manager.compare(args.baseline, args.compare)
                report = backup_manager.generate_diff_report(diff)

                if args.output:
                    with open(args.output, 'w') as f:
                        f.write(report)
                    logger.info(f"Diff report saved to: {args.output}")
                else:
                    print(report)

                if diff.critical_changes > 0:
                    return 2
                elif diff.has_changes:
                    return 1
                return 0

            except ValueError as e:
                logger.error(str(e))
                return 1

        elif args.command == 'delete':
            if backup_manager.delete_backup(args.backup_id):
                print(f"Backup {args.backup_id} deleted successfully.")
                return 0
            else:
                logger.error(f"Backup {args.backup_id} not found.")
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
        if api_client:
            try:
                api_client.logout()
            except:
                pass


if __name__ == '__main__':
    sys.exit(main())
