#!/usr/bin/env python3
"""
UniFi Configuration Auto-Fix CLI

Automatically fixes configuration issues detected by the validator,
with a focus on VLAN blocking issues that cause inter-VLAN routing failures.

Usage:
    # Dry run - see what would be fixed
    unifi-config-autofix --config ~/.config/unifi/prod.env --dry-run

    # Fix all VLAN blocking issues
    unifi-config-autofix --config ~/.config/unifi/prod.env --fix-all

    # Fix only tagged_vlan_mgmt: block_all issues
    unifi-config-autofix --config ~/.config/unifi/prod.env --fix-block-all

    # Fix specific device
    unifi-config-autofix --config ~/.config/unifi/prod.env --fix-all --device "Dream Machine"

    # Generate rollback script
    unifi-config-autofix --config ~/.config/unifi/prod.env --fix-all --rollback-script rollback.sh
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

# Handle imports for both direct execution and installed package
try:
    from unifi_mapper.api_client import UnifiApiClient
    from unifi_mapper.config_autofix import ConfigAutoFix, FixStatus
except ImportError:
    # Add parent directory to path for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.unifi_mapper.api_client import UnifiApiClient
    from src.unifi_mapper.config_autofix import ConfigAutoFix, FixStatus


def setup_logging(debug: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def load_config(config_path: str) -> dict:
    """Load configuration from environment file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    load_dotenv(config_path)

    return {
        'url': os.getenv('UNIFI_URL'),
        'site': os.getenv('UNIFI_SITE', 'default'),
        'api_token': os.getenv('UNIFI_CONSOLE_API_TOKEN'),
        'username': os.getenv('UNIFI_USERNAME'),
        'password': os.getenv('UNIFI_PASSWORD'),
        'verify_ssl': os.getenv('UNIFI_VERIFY_SSL', 'false').lower() == 'true',
        'timeout': int(os.getenv('UNIFI_TIMEOUT', '30')),
    }


def create_client(config: dict) -> UnifiApiClient:
    """Create and authenticate API client."""
    client = UnifiApiClient(
        base_url=config['url'],
        site=config['site'],
        verify_ssl=config['verify_ssl'],
        username=config.get('username'),
        password=config.get('password'),
        api_token=config.get('api_token'),
        timeout=config['timeout'],
    )

    if not client.login():
        raise ConnectionError("Failed to authenticate with UniFi controller")

    return client


def print_summary(result, dry_run: bool) -> None:
    """Print fix summary to console."""
    mode = "DRY RUN" if dry_run else "LIVE"
    status = "✅ ALL SUCCEEDED" if result.all_succeeded else "⚠️ SOME FAILED"

    if result.success_count == 0 and result.failed_count == 0:
        status = "ℹ️ NO FIXES NEEDED"

    print("\n" + "=" * 60)
    print("UNIFI CONFIG AUTO-FIX RESULTS")
    print("=" * 60)
    print(f"\nMode: {mode}")
    print(f"Status: {status}")
    print(f"Timestamp: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nFixes:")
    print(f"  ✅ Success: {result.success_count}")
    print(f"  ❌ Failed: {result.failed_count}")
    print(f"  ⏭️ Skipped: {result.skipped_count}")


def print_fixes(result, verbose: bool = False) -> None:
    """Print detailed fix information."""
    if not result.fixes:
        print("\n✅ No issues found that need fixing!")
        return

    status_icons = {
        FixStatus.SUCCESS: "✅",
        FixStatus.FAILED: "❌",
        FixStatus.SKIPPED: "⏭️",
        FixStatus.DRY_RUN: "🔍",
        FixStatus.PENDING: "⏳",
    }

    # Group by status
    for status in [FixStatus.SUCCESS, FixStatus.DRY_RUN, FixStatus.FAILED, FixStatus.SKIPPED]:
        fixes = [f for f in result.fixes if f.status == status]
        if not fixes:
            continue

        print(f"\n{status_icons[status]} {status.value.upper()} ({len(fixes)})")
        print("-" * 50)

        for i, fix in enumerate(fixes, 1):
            print(f"\n{i}. {fix.finding.device_name} - Port {fix.finding.port_idx}")
            print(f"   Issue: {fix.finding.title}")
            print(f"   {fix.message}")

            if verbose:
                if fix.original_value and fix.new_value:
                    print(f"   Changed: {fix.original_value} → {fix.new_value}")
                if fix.error:
                    print(f"   Error: {fix.error}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="UniFi Configuration Auto-Fix Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - preview what would be fixed
  %(prog)s --config ~/.config/unifi/prod.env --dry-run

  # Fix all VLAN blocking issues (tagged_vlan_mgmt + forward: native)
  %(prog)s --config ~/.config/unifi/prod.env --fix-all

  # Fix only tagged_vlan_mgmt: block_all issues
  %(prog)s --config ~/.config/unifi/prod.env --fix-block-all

  # Fix only forward: native issues
  %(prog)s --config ~/.config/unifi/prod.env --fix-forward-native

  # Fix specific device only
  %(prog)s --config ~/.config/unifi/prod.env --fix-all --device "Dream Machine Pro Max"

  # Fix specific ports only
  %(prog)s --config ~/.config/unifi/prod.env --fix-all --port 10 --port 11

  # Generate rollback script
  %(prog)s --config ~/.config/unifi/prod.env --fix-all --rollback-script rollback.sh

  # Save detailed report
  %(prog)s --config ~/.config/unifi/prod.env --fix-all --output report.md

Fix types:
  --fix-all           Fix both tagged_vlan_mgmt: block_all AND forward: native
  --fix-block-all     Fix only tagged_vlan_mgmt: block_all (most common issue)
  --fix-forward-native Fix only forward: native on trunk ports
        """
    )

    parser.add_argument(
        '--config', '-c',
        required=True,
        help='Path to configuration file (e.g., ~/.config/unifi/prod.env)'
    )

    # Fix type options (mutually exclusive)
    fix_group = parser.add_mutually_exclusive_group()
    fix_group.add_argument(
        '--fix-all',
        action='store_true',
        help='Fix all VLAN blocking issues (tagged_vlan_mgmt + forward: native)'
    )
    fix_group.add_argument(
        '--fix-block-all',
        action='store_true',
        help='Fix only tagged_vlan_mgmt: block_all issues'
    )
    fix_group.add_argument(
        '--fix-forward-native',
        action='store_true',
        help='Fix only forward: native issues on trunk ports'
    )

    # Filters
    parser.add_argument(
        '--device', '-d',
        action='append',
        help='Limit fixes to specific device name(s) (can be used multiple times)'
    )

    parser.add_argument(
        '--port', '-p',
        type=int,
        action='append',
        help='Limit fixes to specific port index(es) (can be used multiple times)'
    )

    # Output options
    parser.add_argument(
        '--output', '-o',
        help='Output file for report (supports .md and .json)'
    )

    parser.add_argument(
        '--format', '-f',
        choices=['text', 'markdown', 'json'],
        default='text',
        help='Output format (default: text)'
    )

    parser.add_argument(
        '--rollback-script',
        help='Generate rollback script to specified file'
    )

    # Mode options
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be fixed without making changes (RECOMMENDED first!)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed fix information'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt (use with caution!)'
    )

    args = parser.parse_args()

    # Validate that at least one fix type is specified
    if not (args.fix_all or args.fix_block_all or args.fix_forward_native or args.dry_run):
        parser.error("Must specify --fix-all, --fix-block-all, --fix-forward-native, or --dry-run")

    # Setup logging
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)

    # Disable SSL warnings if needed
    import urllib3
    urllib3.disable_warnings()

    try:
        # Load configuration
        logger.info(f"Loading configuration from {args.config}")
        config = load_config(args.config)

        # Create client
        logger.info(f"Connecting to {config['url']}")
        client = create_client(config)
        logger.info("Connected successfully")

        # Create auto-fixer
        fixer = ConfigAutoFix(client, config['site'])

        # Determine dry_run mode
        # If only --dry-run is specified without a fix type, default to fix-all for preview
        dry_run = args.dry_run
        if args.dry_run and not (args.fix_all or args.fix_block_all or args.fix_forward_native):
            args.fix_all = True  # Default to showing all potential fixes

        # Confirmation prompt for live runs
        if not dry_run and not args.yes:
            print("\n⚠️  WARNING: This will modify your UniFi configuration!")
            print("    Run with --dry-run first to preview changes.")
            response = input("\n    Type 'yes' to proceed: ")
            if response.lower() != 'yes':
                print("Aborted.")
                sys.exit(0)

        # Run the appropriate fix
        logger.info(f"Running {'dry run' if dry_run else 'LIVE'} fix...")

        if args.fix_all or (args.dry_run and not args.fix_block_all and not args.fix_forward_native):
            result = fixer.fix_all_vlan_blocking(
                dry_run=dry_run,
                device_filter=args.device,
                port_filter=args.port
            )
        elif args.fix_block_all:
            result = fixer.fix_tagged_vlan_blocking(
                dry_run=dry_run,
                device_filter=args.device,
                port_filter=args.port
            )
        elif args.fix_forward_native:
            result = fixer.fix_forward_native(
                dry_run=dry_run,
                device_filter=args.device,
                port_filter=args.port
            )

        # Output results
        if args.format == 'json':
            output = fixer.generate_report(result, format='json')
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")
            else:
                print(output)

        elif args.format == 'markdown' or (args.output and args.output.endswith('.md')):
            output = fixer.generate_report(result, format='markdown')
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")
            else:
                print(output)

        else:
            # Text output
            print_summary(result, dry_run)
            print_fixes(result, verbose=args.verbose)

            if args.output:
                # Save markdown version
                output = fixer.generate_report(result, format='markdown')
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")

        # Generate rollback script if requested
        if args.rollback_script and result.success_count > 0:
            rollback = result.get_rollback_script()
            with open(args.rollback_script, 'w') as f:
                f.write(rollback)
            logger.info(f"Rollback script saved to {args.rollback_script}")

        # Final status
        if not dry_run:
            if result.all_succeeded:
                print("\n🎉 All fixes applied successfully!")
            elif result.failed_count > 0:
                print(f"\n⚠️ {result.failed_count} fixes failed. Check the output above.")
                sys.exit(1)

    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except ConnectionError as e:
        logger.error(f"Connection failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
