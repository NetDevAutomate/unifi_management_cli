#!/usr/bin/env python3
"""
UniFi Network Mapper - Main entry point for the UniFi Network Topology Visualization Toolkit.

This script provides a unified interface for:
1. Discovering UniFi devices
2. Mapping ports based on LLDP/CDP information
3. Generating network topology diagrams
4. Creating detailed port mapping reports
5. Network health analysis and monitoring
6. Security posture assessment
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Tuple

import urllib3

# Suppress InsecureRequestWarning for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging with modern format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Add the src directory to the Python path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Import the UnifiPortMapper class
from unifi_mapper.port_mapper import UnifiPortMapper


def load_env_file(env_file: str = ".env") -> None:
    """
    Load environment variables from a .env file with error handling.

    Args:
        env_file: Path to the environment file
    """
    env_path = Path(env_file)
    if not env_path.exists():
        log.debug(f"Environment file {env_file} not found, skipping")
        return

    try:
        with env_path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")  # Remove quotes
                    os.environ[key] = value
                except ValueError:
                    log.warning(f"Invalid line format in {env_file}:{line_num}: {line}")
                    continue

        log.debug(f"Loaded environment variables from {env_file}")

    except Exception as e:
        log.error(f"Error reading environment file {env_file}: {e}")
        raise


def setup_directories() -> Tuple[Path, Path]:
    """
    Create output directories and return default paths.

    Returns:
        Tuple of (reports_dir, diagrams_dir)
    """
    reports_dir = Path("reports")
    diagrams_dir = Path("diagrams")

    reports_dir.mkdir(exist_ok=True)
    diagrams_dir.mkdir(exist_ok=True)

    return reports_dir, diagrams_dir


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments with comprehensive options.

    Returns:
        Parsed arguments namespace
    """
    reports_dir, diagrams_dir = setup_directories()

    default_report = reports_dir / "port_mapping_report.md"
    default_diagram = diagrams_dir / "network_diagram.png"

    parser = argparse.ArgumentParser(
        description="UniFi Network Mapper - Visualize and manage UniFi network topology"
    )
    parser.add_argument(
        "--output",
        "-o",
        default=default_report,
        help="Output file for the port mapping report",
    )
    parser.add_argument(
        "--diagram",
        "-d",
        default=default_diagram,
        help="Output file for the network diagram",
    )
    parser.add_argument("--url", help="URL of the UniFi Controller")
    parser.add_argument("--site", default="default", help="Site name")
    parser.add_argument("--token", help="API token for authentication")
    parser.add_argument("--username", help="Username for authentication")
    parser.add_argument("--password", help="Password for authentication")
    parser.add_argument(
        "--env",
        action="store_true",
        help="Use environment variables instead of command line arguments",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Dry run mode (do not apply changes)"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="Do not verify SSL certificates"
    )
    parser.add_argument(
        "--format",
        choices=["png", "svg", "dot", "mermaid", "html"],
        default="png",
        help="Format for the network diagram",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument(
        "--connected-devices",
        action="store_true",
        help="Include non-UniFi connected devices in the diagram and enable client-based port naming",
    )
    parser.add_argument(
        "--only-default-ports",
        action="store_true",
        help="Only rename ports with default names (Port 1, Port 2, etc.) when using --connected-devices",
    )
    parser.add_argument(
        "--verify-updates",
        action="store_true",
        help="Enable verification of port name updates (disabled by default due to UniFi controller behavior)",
    )

    args = parser.parse_args()

    if args.env:
        # Use environment variables
        url = os.environ.get("UNIFI_URL")
        site = os.environ.get("UNIFI_SITE", "default")
        token = os.environ.get("UNIFI_CONSOLE_API_TOKEN")
        username = os.environ.get("UNIFI_USERNAME")
        password = os.environ.get("UNIFI_PASSWORD")
        verify_ssl = os.environ.get("UNIFI_VERIFY_SSL", "true").lower() != "false"
        timeout = int(os.environ.get("UNIFI_TIMEOUT", "10"))
    else:
        # Use command line arguments
        url = args.url
        site = args.site
        token = args.token
        username = args.username
        password = args.password
        verify_ssl = not args.no_verify
        timeout = 10

    if not url:
        log.error("UniFi Controller URL is required")
        return 1

    if not token and not (username and password):
        log.error(
            "Either API token or username/password is required for authentication"
        )
        return 1

    # Store configuration for run_unifi_port_mapper
    args.url = url
    args.token = token
    args.username = username
    args.password = password
    args.verify_ssl = verify_ssl
    args.timeout = timeout

    return args


def run_unifi_port_mapper(args: argparse.Namespace) -> int:
    """
    Execute the UniFi port mapper with the given configuration.

    Args:
        args: Parsed command line arguments with configuration

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Create the UniFi Port Mapper
        port_mapper = UnifiPortMapper(
            base_url=args.url,
            site=args.site,
            api_token=args.token,
            username=args.username,
            password=args.password,
            verify_ssl=args.verify_ssl,
            timeout=args.timeout,
        )

        # Import run_port_mapper function
        from src.unifi_mapper.run_methods import run_port_mapper

        # Execute the port mapping
        devices, connections = run_port_mapper(
            port_mapper=port_mapper,
            site_id=args.site,
            dry_run=args.dry_run,
            output_path=args.output,
            diagram_path=args.diagram,
            diagram_format=args.format,
            debug=args.debug,
            show_connected_devices=args.connected_devices,
            verify_updates=args.verify_updates,
        )

        # Only print devices and connections in debug mode
        if args.debug:
            print(f"Devices: {len(devices) if devices else 0}")
            print(f"Connections: {len(connections) if connections else 0}")

        log.info("UniFi port mapping completed successfully")
        return 0

    except Exception as e:
        log.error(f"Error during port mapping execution: {e}")
        return 1


def main() -> int:
    """
    Main entry point for the UniFi Network Mapper.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Load environment variables if .env file exists
        load_env_file()

        # Parse command line arguments and get configuration
        args = parse_arguments()
        if isinstance(args, int):  # Error occurred
            return args

        # Configure debug logging if requested
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            log.debug("Debug logging enabled")

        # Execute the port mapper
        return run_unifi_port_mapper(args)

    except KeyboardInterrupt:
        log.info("Operation cancelled by user")
        return 1
    except Exception as e:
        log.error(f"Unexpected error in main: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
