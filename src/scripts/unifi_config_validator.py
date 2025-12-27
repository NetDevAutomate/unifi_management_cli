#!/usr/bin/env python3
"""
UniFi Configuration Validator CLI

Validates UniFi network configurations against best practices, detecting:
- VLAN routing issues (ports blocking tagged traffic)
- STP configuration problems (non-deterministic root bridge)
- Security vulnerabilities (missing isolation, weak configs)
- Operational issues (unnamed devices, firmware inconsistency)
- DHCP misconfigurations (missing gateway, overlapping ranges)

Usage:
    unifi_config_validator --config ~/.config/unifi/prod.env
    unifi_config_validator --config ~/.config/unifi/prod.env --output report.md
    unifi_config_validator --config ~/.config/unifi/prod.env --check trunk
    unifi_config_validator --config ~/.config/unifi/prod.env --severity critical,high
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
    from unifi_mapper.config_validation import (
        ConfigValidator,
        Severity,
        Category,
        ValidationResult,
    )
except ImportError:
    # Add parent directory to path for direct execution
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.unifi_mapper.api_client import UnifiApiClient
    from src.unifi_mapper.config_validation import (
        ConfigValidator,
        Severity,
        Category,
        ValidationResult,
    )


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


def filter_results(result: ValidationResult,
                   severities: Optional[List[str]] = None,
                   categories: Optional[List[str]] = None) -> ValidationResult:
    """Filter validation results by severity and/or category."""
    if not severities and not categories:
        return result

    filtered = ValidationResult()
    filtered.devices_checked = result.devices_checked
    filtered.ports_checked = result.ports_checked
    filtered.networks_checked = result.networks_checked
    filtered.timestamp = result.timestamp

    for finding in result.findings:
        include = True

        if severities:
            if finding.severity.value.lower() not in [s.lower() for s in severities]:
                include = False

        if categories and include:
            if finding.category.value.lower() not in [c.lower() for c in categories]:
                include = False

        if include:
            filtered.add_finding(finding)

    return filtered


def print_summary(result: ValidationResult) -> None:
    """Print validation summary to console."""
    status = "✅ PASSED" if result.passed else "❌ FAILED"

    print("\n" + "=" * 60)
    print("UNIFI CONFIGURATION VALIDATION RESULTS")
    print("=" * 60)
    print(f"\nStatus: {status}")
    print(f"Timestamp: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nChecked:")
    print(f"  Devices: {result.devices_checked}")
    print(f"  Ports: {result.ports_checked}")
    print(f"  Networks: {result.networks_checked}")
    print(f"\nFindings:")
    print(f"  🔴 Critical: {result.critical_count}")
    print(f"  🟠 High: {result.high_count}")
    print(f"  🟡 Medium: {result.medium_count}")
    print(f"  🔵 Low: {result.low_count}")
    print(f"  ⚪ Info: {result.info_count}")


def print_findings(result: ValidationResult, verbose: bool = False) -> None:
    """Print findings to console."""
    if not result.findings:
        print("\n✅ No issues found!")
        return

    severity_icons = {
        Severity.CRITICAL: "🔴",
        Severity.HIGH: "🟠",
        Severity.MEDIUM: "🟡",
        Severity.LOW: "🔵",
        Severity.INFO: "⚪",
    }

    # Group by severity
    for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
                    Severity.LOW, Severity.INFO]:
        findings = result.get_by_severity(severity)
        if not findings:
            continue

        print(f"\n{severity_icons[severity]} {severity.value} ISSUES ({len(findings)})")
        print("-" * 50)

        for i, finding in enumerate(findings, 1):
            print(f"\n{i}. {finding.title}")
            print(f"   Device: {finding.device_name}", end="")
            if finding.port_idx is not None:
                print(f" (Port {finding.port_idx})", end="")
            print()

            if verbose:
                print(f"   Category: {finding.category.value}")
                print(f"   {finding.description}")
                if finding.current_value:
                    print(f"   Current: {finding.current_value}")
                if finding.recommended_value:
                    print(f"   Recommended: {finding.recommended_value}")
                if finding.remediation:
                    print(f"   Fix: {finding.remediation}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="UniFi Configuration Validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full validation with default output
  %(prog)s --config ~/.config/unifi/prod.env

  # Save markdown report
  %(prog)s --config ~/.config/unifi/prod.env --output report.md

  # Check only trunk/VLAN routing
  %(prog)s --config ~/.config/unifi/prod.env --check trunk

  # Show only critical and high severity
  %(prog)s --config ~/.config/unifi/prod.env --severity critical,high

  # Verbose output with remediation steps
  %(prog)s --config ~/.config/unifi/prod.env --verbose

  # JSON output for scripting
  %(prog)s --config ~/.config/unifi/prod.env --format json

Available checks:
  trunk       - VLAN routing and trunk port configuration
  stp         - Spanning Tree Protocol configuration
  security    - Security best practices
  operational - Operational best practices (naming, firmware)
  dhcp        - DHCP configuration
  all         - All checks (default)
        """
    )

    parser.add_argument(
        '--config', '-c',
        required=True,
        help='Path to configuration file (e.g., ~/.config/unifi/prod.env)'
    )

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
        '--check',
        choices=['trunk', 'stp', 'security', 'operational', 'dhcp', 'all'],
        default='all',
        help='Specific check to run (default: all)'
    )

    parser.add_argument(
        '--severity', '-s',
        help='Filter by severity (comma-separated: critical,high,medium,low,info)'
    )

    parser.add_argument(
        '--category',
        help='Filter by category (comma-separated)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed findings with remediation'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Only output critical/high findings'
    )

    parser.add_argument(
        '--exit-code',
        action='store_true',
        help='Exit with non-zero code if validation fails'
    )

    args = parser.parse_args()

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

        # Create validator
        validator = ConfigValidator(client, config['site'])

        # Run validation
        logger.info(f"Running {args.check} validation...")

        if args.check == 'trunk':
            result = validator.validate_trunk_ports()
        elif args.check == 'stp':
            result = validator.validate_stp()
        elif args.check == 'security':
            result = validator.validate_security()
        elif args.check == 'operational':
            result = validator.validate_operational()
        elif args.check == 'dhcp':
            result = validator.validate_dhcp()
        else:
            result = validator.validate_all()

        # Apply filters
        severities = args.severity.split(',') if args.severity else None
        categories = args.category.split(',') if args.category else None

        if args.quiet:
            severities = ['critical', 'high']

        if severities or categories:
            result = filter_results(result, severities, categories)

        # Output results
        if args.format == 'json':
            output = validator.generate_report(result, format='json')
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")
            else:
                print(output)

        elif args.format == 'markdown' or (args.output and args.output.endswith('.md')):
            output = validator.generate_report(result, format='markdown')
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")
            else:
                print(output)

        else:
            # Text output
            print_summary(result)
            print_findings(result, verbose=args.verbose)

            if args.output:
                # Save markdown version
                output = validator.generate_report(result, format='markdown')
                with open(args.output, 'w') as f:
                    f.write(output)
                logger.info(f"Report saved to {args.output}")

        # Exit code
        if args.exit_code and not result.passed:
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
