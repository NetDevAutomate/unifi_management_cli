#!/usr/bin/env python3
"""
CLI entry point for UniFi Network Mapper.
Enables running from anywhere with config file specification.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
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


def get_default_config_path() -> Path:
    """Get default config path following XDG Base Directory specification.

    Priority:
    1. XDG_CONFIG_HOME/unifi_management_cli/prod.env
    2. ~/.config/unifi_management_cli/prod.env
    3. XDG_CONFIG_HOME/unifi_management_cli/default.env
    4. ~/.config/unifi_management_cli/default.env
    5. .env (current directory - legacy fallback)

    Returns:
        Path to default config file.
    """
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config_home:
        config_dir = Path(xdg_config_home) / 'unifi_management_cli'
    else:
        config_dir = Path.home() / '.config' / 'unifi_management_cli'

    # Try prod.env first (most common production use case)
    prod_config = config_dir / 'prod.env'
    if prod_config.exists():
        return prod_config

    # Try default.env
    default_config = config_dir / 'default.env'
    if default_config.exists():
        return default_config

    # Fallback to .env in current directory (legacy)
    return Path('.env')


def main():
    """
    Main CLI entry point with subcommand support and XDG Base Directory support.
    """
    # Check for install-completions subcommand first
    if len(sys.argv) > 1 and sys.argv[1] == "install-completions":
        from .completions import main as completions_main
        # Remove the 'install-completions' argument and let completions handle the rest
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        completions_main()
        return

    parser = argparse.ArgumentParser(
        description="UniFi Network Mapper - Run from anywhere with config file",
        epilog=(
            "Examples:\n"
            "  unifi-mapper --config ~/.config/unifi_management_cli/prod.env --format png\n"
            "  unifi-mapper install-completions bash\n"
            "  unifi-mapper --verify-updates --debug"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--config",
        "-c",
        help="Path to .env configuration file (default: XDG_CONFIG_HOME or .env)",
        default=get_default_config_path(),
    )

    parser.add_argument(
        "--output",
        "-o",
        help="Output path for report (default: ./reports/port_mapping_report.md)",
    )

    parser.add_argument(
        "--diagram",
        "-d",
        help="Output path for diagram (default: ./diagrams/network_diagram.png)",
    )

    parser.add_argument(
        "--format",
        choices=["png", "svg", "dot", "mermaid", "html"],
        default=None,  # Will use config file default
        help="Diagram format (default: from config file or 'png')",
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (don't apply port name changes)",
    )

    parser.add_argument(
        "--connected-devices",
        action="store_true",
        help="Include non-UniFi connected devices",
    )

    parser.add_argument(
        "--verify-updates",
        action="store_true",
        help="Verify that port name updates were successfully applied (recommended for debugging)",
    )

    args = parser.parse_args()

    # Configure debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration from specified file
    load_env_from_config(args.config)

    # Import after env loaded
    try:
        from .api_client import UnifiApiClient
        from .config import UnifiConfig
        from .port_mapper import UnifiPortMapper
        from .run_methods import run_port_mapper
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

    # Get format from config or use PNG default
    diagram_format = args.format or config.default_format

    # Set output paths from config or defaults
    if args.output:
        output_path = Path(args.output)
    elif config.default_output_dir:
        output_path = Path(config.default_output_dir) / "port_mapping_report.md"
    else:
        output_path = Path.cwd() / "reports" / "port_mapping_report.md"

    if args.diagram:
        diagram_path = Path(args.diagram)
    elif config.default_diagram_dir:
        diagram_path = (
            Path(config.default_diagram_dir) / f"network_diagram.{diagram_format}"
        )
    else:
        diagram_path = Path.cwd() / "diagrams" / f"network_diagram.{diagram_format}"

    log.info(f"Using format: {diagram_format}")
    log.info(f"Output: {output_path}")
    log.info(f"Diagram: {diagram_path}")

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

        # Check if smart mapping is needed (when verification is enabled)
        if args.verify_updates:
            log.info("🧠 Using Smart Port Mapping with device-aware capabilities...")
            from .smart_port_mapper import SmartPortMapper
            from .run_methods import get_devices_and_lldp_data

            # Get devices and LLDP data
            devices_data, lldp_data = get_devices_and_lldp_data(port_mapper, config.site)

            # Use smart mapper
            smart_mapper = SmartPortMapper(port_mapper.api_client)
            smart_results = smart_mapper.smart_update_ports(
                devices_data, lldp_data,
                verify_updates=args.verify_updates,
                dry_run=args.dry_run
            )

            # Generate and display smart mapping report
            smart_report = smart_mapper.generate_smart_mapping_report(smart_results)
            print("\n" + smart_report)

            # Still generate traditional report for compatibility
            devices, connections = run_port_mapper(
                port_mapper=port_mapper,
                site_id=config.site,
                dry_run=True,  # Force dry run to avoid duplicate updates
                output_path=output_path,
                diagram_path=diagram_path,
                diagram_format=diagram_format,
                debug=args.debug,
                show_connected_devices=args.connected_devices,
                verify_updates=False,  # Verification already done by smart mapper
            )
        else:
            # Use traditional approach when verification disabled
            devices, connections = run_port_mapper(
                port_mapper=port_mapper,
                site_id=config.site,
                dry_run=args.dry_run,
                output_path=output_path,
                diagram_path=diagram_path,
                diagram_format=diagram_format,
                debug=args.debug,
                show_connected_devices=args.connected_devices,
                verify_updates=args.verify_updates,
            )

        log.info("✅ Completed successfully!")
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
