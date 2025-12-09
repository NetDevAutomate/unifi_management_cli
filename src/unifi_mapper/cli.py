#!/usr/bin/env python3
"""
CLI entry point for UniFi Network Mapper.
Enables running from anywhere with config file specification.
"""

import os
import sys
import argparse
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)


def load_env_from_config(config_path: str) -> None:
    """
    Load environment variables from specified config file.

    Args:
        config_path: Path to .env configuration file
    """
    env_file = Path(config_path).expanduser().resolve()

    if not env_file.exists():
        log.error(f"Configuration file not found: {env_file}")
        sys.exit(1)

    try:
        with env_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value
                except ValueError:
                    log.warning(f"Invalid line in {env_file}:{line_num}: {line}")

        log.info(f"Loaded configuration from: {env_file}")

    except Exception as e:
        log.error(f"Error reading config file: {e}")
        sys.exit(1)


def main():
    """
    Main CLI entry point with config file support.
    """
    parser = argparse.ArgumentParser(
        description="UniFi Network Mapper - Run from anywhere with config file",
        epilog="Example: unifi-mapper --config ~/.unifi/prod.env --format png"
    )

    parser.add_argument(
        "--config",
        "-c",
        help="Path to .env configuration file (default: .env in current directory)",
        default=".env"
    )

    parser.add_argument(
        "--output",
        "-o",
        help="Output path for report (default: ./reports/port_mapping_report.md)"
    )

    parser.add_argument(
        "--diagram",
        "-d",
        help="Output path for diagram (default: ./diagrams/network_diagram.png)"
    )

    parser.add_argument(
        "--format",
        choices=["png", "svg", "dot", "mermaid", "html"],
        default="html",
        help="Diagram format (default: html)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (don't apply port name changes)"
    )

    parser.add_argument(
        "--connected-devices",
        action="store_true",
        help="Include non-UniFi connected devices"
    )

    args = parser.parse_args()

    # Configure debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration from specified file
    load_env_from_config(args.config)

    # Import after env loaded
    try:
        from .config import UnifiConfig
        from .api_client import UnifiApiClient
        from .run_methods import run_port_mapper
        from .port_mapper import UnifiPortMapper
    except ImportError as e:
        log.error(f"Import error: {e}")
        log.error("Make sure you've installed the package: uv pip install -e .")
        sys.exit(1)

    # Create config from environment
    try:
        config = UnifiConfig.from_env()
    except ValueError as e:
        log.error(f"Configuration error: {e}")
        log.error(f"Check your config file: {args.config}")
        sys.exit(1)

    # Set default output paths relative to current directory
    output_path = args.output or Path.cwd() / "reports" / "port_mapping_report.md"
    diagram_path = args.diagram or Path.cwd() / "diagrams" / f"network_diagram.{args.format}"

    # Ensure directories exist
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(diagram_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        # Create API client
        port_mapper = UnifiPortMapper(
            base_url=config.base_url,
            site=config.site,
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
        )

        # Run port mapper
        devices, connections = run_port_mapper(
            port_mapper=port_mapper,
            site_id=config.site,
            dry_run=args.dry_run,
            output_path=output_path,
            diagram_path=diagram_path,
            diagram_format=args.format,
            debug=args.debug,
            show_connected_devices=args.connected_devices,
            verify_updates=False
        )

        log.info(f"✅ Completed successfully!")
        log.info(f"Report: {output_path}")
        log.info(f"Diagram: {diagram_path}")
        log.info(f"Devices: {len(devices)}, Connections: {len(connections)}")

        return 0

    except KeyboardInterrupt:
        log.info("Operation cancelled by user")
        return 1
    except Exception as e:
        log.error(f"Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
