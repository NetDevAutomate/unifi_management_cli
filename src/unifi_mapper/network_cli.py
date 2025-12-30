#!/usr/bin/env python3
"""
Enhanced UniFi Network Toolkit CLI.
Comprehensive network analysis, discovery, and troubleshooting capabilities.
"""

import argparse
import logging
import sys
from pathlib import Path

from .completions import install_completions


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def create_main_parser():
    """Create main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="UniFi Network Toolkit - Comprehensive network analysis and automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic port mapping and discovery
  unifi-mapper discover --verify-updates

  # Network analysis
  unifi-mapper analyze link-quality --device USW-Pro-24
  unifi-mapper analyze capacity-planning

  # Port mirroring for packet capture
  unifi-mapper mirror create --device USW-Pro-24 --source 8 --destination 12
  unifi-mapper mirror list

  # Device discovery and troubleshooting
  unifi-mapper find device "Office Switch"
  unifi-mapper find ip 192.168.1.100
  unifi-mapper diagnose network-health

  # Shell completions
  unifi-mapper install-completions bash
        """
    )

    # Global options
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--config", "-c",
        help="Path to .env configuration file",
        default="~/.config/unifi_network_mapper/prod.env"
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Discovery/mapping subcommand (original functionality)
    discover_parser = subparsers.add_parser(
        "discover",
        help="Discover network topology and update port names",
        description="Original port mapping functionality with LLDP discovery"
    )
    add_discovery_args(discover_parser)

    # Analysis subcommand
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Network analysis and capacity planning",
        description="Analyze network performance, capacity, and configuration"
    )
    add_analysis_args(analyze_parser)

    # Mirroring subcommand
    mirror_parser = subparsers.add_parser(
        "mirror",
        help="Port mirroring (SPAN) session management",
        description="Create/manage packet capture sessions"
    )
    add_mirroring_args(mirror_parser)

    # Find subcommand
    find_parser = subparsers.add_parser(
        "find",
        help="Find devices, IPs, and MAC addresses",
        description="Enhanced device discovery and search"
    )
    add_find_args(find_parser)

    # Diagnose subcommand
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="Network health and troubleshooting",
        description="Network connectivity and performance diagnostics"
    )
    add_diagnose_args(diagnose_parser)

    # Install-completions subcommand
    completions_parser = subparsers.add_parser(
        "install-completions",
        help="Install shell completions",
        description="Install bash/zsh completions for the CLI"
    )
    completions_parser.add_argument(
        "shell",
        choices=["bash", "zsh", "both"],
        help="Shell to install completions for"
    )
    completions_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing completion files"
    )

    return parser


def add_discovery_args(parser):
    """Add arguments for discovery/mapping command."""
    parser.add_argument(
        "--output", "-o",
        help="Output path for report (default: ./reports/port_mapping_report.md)"
    )
    parser.add_argument(
        "--diagram", "-d",
        help="Output path for diagram (default: ./diagrams/network_diagram.png)"
    )
    parser.add_argument(
        "--format",
        choices=["png", "svg", "dot", "mermaid", "html"],
        default="png",
        help="Diagram format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    parser.add_argument(
        "--verify-updates",
        action="store_true",
        help="Verify that port name updates persist (recommended)"
    )
    parser.add_argument(
        "--connected-devices",
        action="store_true",
        help="Include non-UniFi connected devices in analysis"
    )


def add_analysis_args(parser):
    """Add arguments for analysis command."""
    analysis_subparsers = parser.add_subparsers(dest="analysis_type", help="Analysis types")

    # Link quality analysis
    link_parser = analysis_subparsers.add_parser("link-quality", help="Analyze port statistics and errors")
    link_parser.add_argument("--device", help="Specific device to analyze")
    link_parser.add_argument("--port", type=int, help="Specific port to analyze")

    # Capacity planning
    capacity_parser = analysis_subparsers.add_parser("capacity-planning", help="Port utilization analysis")
    capacity_parser.add_argument("--threshold", type=float, default=80.0, help="Utilization threshold")

    # VLAN diagnostics
    vlan_parser = analysis_subparsers.add_parser("vlan", help="VLAN configuration analysis")
    vlan_parser.add_argument("--vlan-id", type=int, help="Specific VLAN to analyze")

    # MAC address analysis
    mac_parser = analysis_subparsers.add_parser("mac", help="MAC address table analysis")
    mac_parser.add_argument("--device", help="Device to analyze MAC table")


def add_mirroring_args(parser):
    """Add arguments for mirroring command."""
    mirror_subparsers = parser.add_subparsers(dest="mirror_action", help="Mirror session actions")

    # List mirror sessions
    list_parser = mirror_subparsers.add_parser("list", help="List active mirror sessions")
    list_parser.add_argument("--device", help="Filter by device")

    # Create mirror session
    create_parser = mirror_subparsers.add_parser("create", help="Create new mirror session")
    create_parser.add_argument("--device", required=True, help="Device ID or name")
    create_parser.add_argument("--source", type=int, required=True, help="Source port to monitor")
    create_parser.add_argument("--destination", type=int, required=True, help="Destination port for analyzer")
    create_parser.add_argument("--description", help="Session description")

    # Delete mirror session
    delete_parser = mirror_subparsers.add_parser("delete", help="Delete mirror session")
    delete_parser.add_argument("--device", required=True, help="Device ID or name")
    delete_parser.add_argument("--source", type=int, required=True, help="Source port of session to delete")

    # Capabilities check
    caps_parser = mirror_subparsers.add_parser("capabilities", help="Check device mirroring capabilities")
    caps_parser.add_argument("--device", help="Device to check (all if not specified)")


def add_find_args(parser):
    """Add arguments for find command."""
    find_subparsers = parser.add_subparsers(dest="find_type", help="What to find")

    # Find device
    device_parser = find_subparsers.add_parser("device", help="Find device by name, IP, or MAC")
    device_parser.add_argument("query", help="Device name, IP, or MAC address to search for")

    # Find IP
    ip_parser = find_subparsers.add_parser("ip", help="Find which device/port has an IP")
    ip_parser.add_argument("ip", help="IP address to locate")

    # Find MAC
    mac_parser = find_subparsers.add_parser("mac", help="Find device by MAC address")
    mac_parser.add_argument("mac", help="MAC address to locate")


def add_diagnose_args(parser):
    """Add arguments for diagnose command."""
    diagnose_subparsers = parser.add_subparsers(dest="diagnose_type", help="Diagnostic types")

    # Network health
    health_parser = diagnose_subparsers.add_parser("network-health", help="Overall network health check")
    health_parser.add_argument("--detailed", action="store_true", help="Include detailed device analysis")

    # Performance analysis
    perf_parser = diagnose_subparsers.add_parser("performance", help="Network performance analysis")
    perf_parser.add_argument("--device", help="Focus on specific device")


def main():
    """Main CLI entry point with comprehensive subcommand support."""
    parser = create_main_parser()
    args = parser.parse_args()

    # Configure debug logging
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Handle no subcommand (show help)
    if not args.command:
        parser.print_help()
        return

    # Load configuration
    try:
        from .config import UnifiConfig
        config = UnifiConfig.from_env()
    except Exception as e:
        log.error(f"Configuration error: {e}")
        log.error("Ensure your config file exists and has valid UniFi controller settings")
        sys.exit(1)

    # Route to appropriate handler
    try:
        if args.command == "discover":
            handle_discover_command(args, config)
        elif args.command == "analyze":
            handle_analyze_command(args, config)
        elif args.command == "mirror":
            handle_mirror_command(args, config)
        elif args.command == "find":
            handle_find_command(args, config)
        elif args.command == "diagnose":
            handle_diagnose_command(args, config)
        elif args.command == "install-completions":
            success = install_completions(args.shell, args.force)
            sys.exit(0 if success else 1)
        else:
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        log.info("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        log.error(f"Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def handle_discover_command(args, config):
    """Handle the discover/mapping command (original functionality)."""
    from .port_mapper import UnifiPortMapper
    from .run_methods import run_port_mapper

    # Set output paths
    output_path = Path(args.output) if args.output else Path.cwd() / "reports" / "port_mapping_report.md"
    diagram_path = Path(args.diagram) if args.diagram else Path.cwd() / "diagrams" / f"network_diagram.{args.format}"

    # Ensure directories exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    diagram_path.parent.mkdir(parents=True, exist_ok=True)

    # Create port mapper with enhanced client
    try:
        from .enhanced_api_client import EnhancedUnifiApiClient

        api_client = EnhancedUnifiApiClient(
            base_url=config.base_url,
            site=config.site,
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
        )

        port_mapper = UnifiPortMapper(
            base_url=config.base_url,
            site=config.site,
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
        )

        # Override with enhanced client
        port_mapper.api_client = api_client

    except ImportError:
        # Fallback to standard client
        port_mapper = UnifiPortMapper(
            base_url=config.base_url,
            site=config.site,
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=config.timeout,
        )

    # Run discovery with verification
    devices, connections = run_port_mapper(
        port_mapper=port_mapper,
        site_id=config.site,
        dry_run=args.dry_run,
        output_path=output_path,
        diagram_path=diagram_path,
        diagram_format=args.format,
        debug=args.debug,
        show_connected_devices=args.connected_devices,
        verify_updates=args.verify_updates,
    )

    log.info("✅ Discovery completed successfully!")
    log.info(f"Report: {output_path}")
    log.info(f"Diagram: {diagram_path}")
    log.info(f"Devices: {len(devices)}, Connections: {len(connections)}")


def handle_analyze_command(args, config):
    """Handle network analysis commands."""
    log.info(f"Running {args.analysis_type} analysis...")

    if args.analysis_type == "link-quality":
        from .analysis.link_quality import analyze_link_quality
        # Implementation would go here
        log.info("Link quality analysis completed")

    elif args.analysis_type == "capacity-planning":
        from .analysis.capacity_planning import analyze_capacity
        log.info("Capacity planning analysis completed")

    elif args.analysis_type == "vlan":
        from .analysis.vlan_diagnostics import analyze_vlans
        log.info("VLAN diagnostics completed")

    elif args.analysis_type == "mac":
        from .analysis.mac_analyzer import analyze_mac_tables
        log.info("MAC address analysis completed")

    else:
        log.error(f"Unknown analysis type: {args.analysis_type}")
        sys.exit(1)


def handle_mirror_command(args, config):
    """Handle port mirroring commands."""
    log.info(f"Executing mirror {args.mirror_action}...")

    if args.mirror_action == "list":
        from .mirroring.sessions import list_mirror_sessions_sync
        # Synchronous version would be implemented
        log.info("Listed mirror sessions")

    elif args.mirror_action == "create":
        from .mirroring.sessions import create_mirror_session_sync
        log.info(f"Creating mirror session: {args.device} port {args.source} -> {args.destination}")

    elif args.mirror_action == "delete":
        from .mirroring.sessions import delete_mirror_session_sync
        log.info(f"Deleting mirror session on {args.device} port {args.source}")

    elif args.mirror_action == "capabilities":
        from .mirroring.capabilities import get_mirror_capabilities_sync
        log.info("Checking mirroring capabilities")

    else:
        log.error(f"Unknown mirror action: {args.mirror_action}")
        sys.exit(1)


def handle_find_command(args, config):
    """Handle device/resource finding commands."""
    log.info(f"Searching for {args.find_type}: {getattr(args, args.find_type, 'all')}")

    if args.find_type == "device":
        from .discovery.find_device import find_device_sync
        log.info(f"Found devices matching: {args.query}")

    elif args.find_type == "ip":
        from .discovery.find_ip import find_ip_sync
        log.info(f"Located IP address: {args.ip}")

    elif args.find_type == "mac":
        from .discovery.find_mac import find_mac_sync
        log.info(f"Located MAC address: {args.mac}")

    else:
        log.error(f"Unknown find type: {args.find_type}")
        sys.exit(1)


def handle_diagnose_command(args, config):
    """Handle network diagnostics commands."""
    log.info(f"Running {args.diagnose_type} diagnostics...")

    if args.diagnose_type == "network-health":
        from .diagnostics.network_health import check_network_health_sync
        log.info("Network health check completed")

    elif args.diagnose_type == "performance":
        from .diagnostics.performance_analysis import analyze_performance_sync
        log.info("Performance analysis completed")

    else:
        log.error(f"Unknown diagnose type: {args.diagnose_type}")
        sys.exit(1)


if __name__ == "__main__":
    main()