"""CLI entry point for UniFi Network Mapper.

Enables running from anywhere with config file specification.
"""

import argparse
import importlib.metadata
import logging
import os
import sys
from .core.utils.envfile import parse_env_value
from pathlib import Path


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)


def load_env_from_config(config_path: str) -> None:
    """Load environment variables from specified config file.

    Args:
        config_path: Path to .env configuration file
    """
    env_file = Path(config_path).expanduser().resolve()

    if not env_file.exists():
        if env_file == Path('.env').resolve():
            # The legacy fallback is only reached when no config was given and none of the
            # searched files exist, so name them all: a new user who put the file somewhere
            # else learns where the CLI looked, not just that ./.env is missing.
            searched = '\n'.join(f'  {p}' for p in default_config_candidates())
            log.error(
                'No configuration file found. Nothing was given with --config or '
                f'UNIFI_CONFIG, and none of these exist:\n{searched}\n'
                'Create the first one with at least UNIFI_URL and UNIFI_CONSOLE_API_TOKEN '
                '(or UNIFI_USERNAME and UNIFI_PASSWORD); .env.example in the repository '
                'documents every key.'
            )
        else:
            log.error(f'Configuration file not found: {env_file}')
        sys.exit(1)

    try:
        with env_file.open('r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                try:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = parse_env_value(value)
                except ValueError:
                    # Never echo the line: a password typed with a space instead of '='
                    # has no name=value shape for redact_text to mask.
                    log.warning(f"Invalid line in {env_file}:{line_num} (no '=' found)")

        log.info(f'Loaded configuration from: {env_file}')

    except Exception as e:
        from .core.utils.redact import redact_text

        log.error(f'Error reading config file: {redact_text(e)}')
        sys.exit(1)


def default_config_candidates() -> list[Path]:
    """The config files the CLI looks for when none is given, in search order.

    1. ``prod.env`` in ``$XDG_CONFIG_HOME/unifi_management_cli/``, or in
       ``~/.config/unifi_management_cli/`` when ``XDG_CONFIG_HOME`` is unset
    2. ``default.env`` in that same directory
    3. ``.env`` in the current directory (legacy fallback), as an absolute path
    """
    xdg_config_home = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config_home:
        config_dir = Path(xdg_config_home) / 'unifi_management_cli'
    else:
        config_dir = Path.home() / '.config' / 'unifi_management_cli'
    return [config_dir / 'prod.env', config_dir / 'default.env', Path('.env').resolve()]


def get_default_config_path() -> Path:
    """Get default config path following XDG Base Directory specification.

    The first file in :func:`default_config_candidates` that exists wins; when none does,
    the legacy ``.env`` (current directory) is returned even though it is missing, and
    :func:`load_env_from_config` then reports the whole search.

    A set ``XDG_CONFIG_HOME`` replaces ``~/.config`` here; the MCP server's search
    (``mcp.config.resolve_config_path``) tries it first and then ``~/.config`` too.

    Returns:
        Path to default config file.
    """
    for candidate in default_config_candidates()[:-1]:
        if candidate.exists():
            return candidate

    # Fallback to .env in current directory (legacy)
    return Path('.env')


def main():
    """Main CLI entry point with subcommand support and XDG Base Directory support."""
    # Check for install-completions subcommand first
    if len(sys.argv) > 1 and sys.argv[1] == 'install-completions':
        from .completions import main as completions_main

        # Remove the 'install-completions' argument and let completions handle the rest
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        completions_main()
        return

    parser = argparse.ArgumentParser(
        description='UniFi Network Mapper - Run from anywhere with config file',
        epilog=(
            'Examples:\n'
            '  unifi-mapper --config ~/.config/unifi_management_cli/prod.env --format png\n'
            '  unifi-mapper install-completions bash\n'
            '  unifi-mapper --verify-updates --debug'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--config',
        '-c',
        help='Path to .env configuration file (default: XDG_CONFIG_HOME or .env)',
        default=get_default_config_path(),
    )

    parser.add_argument(
        '--output',
        '-o',
        help='Output path for report (default: ./reports/port_mapping_report.md)',
    )

    parser.add_argument(
        '--diagram',
        '-d',
        help='Output path for diagram (default: ./diagrams/network_diagram.png)',
    )

    parser.add_argument(
        '--format',
        choices=['png', 'svg', 'dot', 'mermaid', 'html'],
        default=None,  # Will use config file default
        help="Diagram format (default: from config file or 'png')",
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {importlib.metadata.version("unifi-management-cli")}',
    )
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview the port names without writing them (the default; kept for scripts)',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Write the proposed port names to the controller (previews without it)',
    )

    parser.add_argument(
        '--connected-devices',
        action='store_true',
        help='Include non-UniFi connected devices',
    )

    parser.add_argument(
        '--verify-updates',
        action='store_true',
        help='Verify that port name updates were successfully applied (recommended for debugging)',
    )

    args = parser.parse_args()

    # Preview unless --apply (issue 015: the same default as `unifi-mapper discover`).
    if args.apply and args.dry_run:
        parser.exit(2, 'error: choose --apply or --dry-run, not both\n')
    dry_run = not args.apply

    # Configure debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load configuration from specified file
    load_env_from_config(args.config)

    # Import after env loaded
    try:
        from .config import UnifiConfig
        from .port_mapper import UnifiPortMapper
        from .run_methods import run_port_mapper
    except ImportError as e:
        from .core.utils.redact import redact_text

        log.error(f'Import error: {redact_text(e)}')
        log.error("Make sure the project's dependencies are installed: uv sync")
        sys.exit(1)

    # Create config from environment
    try:
        # Re-read --config itself: a stray ./.env must never override it.
        config = UnifiConfig.from_env(str(args.config))
    except ValueError as e:
        from .core.utils.redact import redact_text

        log.error(f'Configuration error: {redact_text(e)}')
        log.error(f'Check your config file: {args.config}')
        sys.exit(1)

    # Get format from config or use PNG default
    diagram_format = args.format or config.default_format

    # Set output paths from config or defaults
    if args.output:
        output_path = Path(args.output)
    elif config.default_output_dir:
        output_path = Path(config.default_output_dir) / 'port_mapping_report.md'
    else:
        output_path = Path.cwd() / 'reports' / 'port_mapping_report.md'

    if args.diagram:
        diagram_path = Path(args.diagram)
    elif config.default_diagram_dir:
        diagram_path = Path(config.default_diagram_dir) / f'network_diagram.{diagram_format}'
    else:
        diagram_path = Path.cwd() / 'diagrams' / f'network_diagram.{diagram_format}'

    log.info(f'Using format: {diagram_format}')
    log.info(f'Output: {output_path}')
    log.info(f'Diagram: {diagram_path}')

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
            log.info('🧠 Using Smart Port Mapping with device-aware capabilities...')
            from .run_methods import get_devices_and_lldp_data
            from .smart_port_mapper import SmartPortMapper

            # Get devices and LLDP data
            devices_data, lldp_data = get_devices_and_lldp_data(port_mapper, config.site)

            # Use smart mapper
            smart_mapper = SmartPortMapper(port_mapper.api_client)
            smart_results = smart_mapper.smart_update_ports(
                devices_data, lldp_data, verify_updates=args.verify_updates, dry_run=dry_run
            )

            # Generate and display smart mapping report
            smart_report = smart_mapper.generate_smart_mapping_report(smart_results)
            print('\n' + smart_report)

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
                dry_run=dry_run,
                output_path=output_path,
                diagram_path=diagram_path,
                diagram_format=diagram_format,
                debug=args.debug,
                show_connected_devices=args.connected_devices,
                verify_updates=args.verify_updates,
            )

        log.info('✅ Completed successfully!')
        log.info(f'Report: {output_path}')
        log.info(f'Diagram: {diagram_path}')
        log.info(f'Devices: {len(devices)}, Connections: {len(connections)}')

        return 0

    except KeyboardInterrupt:
        log.info('Operation cancelled by user')
        return 1
    except Exception as e:
        from .core.utils.redact import redact_text, redact_traceback

        log.error(f'Error: {redact_text(e)}')
        if args.debug:
            sys.stderr.write(redact_traceback(e))
        return 1


if __name__ == '__main__':
    sys.exit(main())
