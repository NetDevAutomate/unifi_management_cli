#!/usr/bin/env python3
"""Typer-based CLI for UniFi Network Mapper with automatic completions."""

import logging
import typer
from .cli import get_default_config_path, load_env_from_config
from .inventory_cli import inventory_app
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from typing import Annotated, Any, Optional, cast


# Setup rich console
console = Console()
JsonDict = dict[str, Any]


# Global state for config path
class State:
    """Global CLI state."""
    config_path: Optional[Path] = None
    debug: bool = False


state = State()


def setup_logging(debug: bool = False):
    """Configure rich logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )


# Create main Typer app
app = typer.Typer(
    name="unifi-mapper",
    help="🚀 Enterprise UniFi Network Automation Platform",
    epilog="Built with systematic debugging and AI-assisted development 🤖",
    rich_markup_mode="rich",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config', '-c',
            help='📁 Path to .env configuration file',
            envvar='UNIFI_CONFIG',
        )
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            '--debug',
            help='🐛 Enable debug logging',
        )
    ] = False,
    # Top-level shortcuts for discover command
    connected_devices: Annotated[
        bool,
        typer.Option(
            '--connected-devices',
            help='📱 Include non-UniFi connected devices (runs discover)',
        )
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            help='🔍 Dry run mode (runs discover)',
        )
    ] = False,
    verify_updates: Annotated[
        bool,
        typer.Option(
            '--verify-updates',
            help='✅ Verify port name updates (runs discover)',
        )
    ] = False,
):
    """🚀 Enterprise UniFi Network Automation Platform.

    Global options apply to all commands. Use --connected-devices, --dry-run,
    or --verify-updates as shortcuts to run the discover command.
    """
    # Set global state
    state.config_path = config if config else get_default_config_path()
    state.debug = debug

    if debug:
        setup_logging(debug=True)

    # If no subcommand but discover-related flags provided, run discover
    if ctx.invoked_subcommand is None:
        if connected_devices or dry_run or verify_updates:
            # Run discover with the provided flags
            discover(
                output=None,
                diagram=None,
                format='png',
                dry_run=dry_run,
                verify_updates=verify_updates,
                connected_devices=connected_devices,
            )
        else:
            # Show help if no command and no flags
            console.print(ctx.get_help())

# Create subcommands
find_app = typer.Typer(help="🔍 Device and resource discovery")
analyze_app = typer.Typer(help="📊 Network analysis and diagnostics")
diagnose_app = typer.Typer(help="🏥 Network health and troubleshooting")
stp_app = typer.Typer(help="🌳 STP topology analysis and optimization")
radio_app = typer.Typer(help="📶 Wi-Fi radio configuration management")

app.add_typer(find_app, name="find")
app.add_typer(analyze_app, name="analyze")
app.add_typer(diagnose_app, name="diagnose")
app.add_typer(inventory_app, name="inventory")
app.add_typer(stp_app, name="stp")
app.add_typer(radio_app, name="radio")


@app.command()
def discover(
    output: Annotated[
        Optional[Path],
        typer.Option('--output', '-o', help='📄 Output path for report')
    ] = None,
    diagram: Annotated[
        Optional[Path],
        typer.Option('--diagram', '-d', help='🖼️ Output path for diagram')
    ] = None,
    format: Annotated[
        str,
        typer.Option('--format', help='🎨 Diagram format (png, svg, html, mermaid, dot)')
    ] = 'png',
    dry_run: Annotated[
        bool,
        typer.Option('--dry-run', help='🔍 Show what would be changed without applying')
    ] = False,
    verify_updates: Annotated[
        bool,
        typer.Option('--verify-updates', help='✅ Verify that port name updates persist')
    ] = False,
    connected_devices: Annotated[
        bool,
        typer.Option('--connected-devices', help='📱 Include non-UniFi connected devices')
    ] = False,
):
    """🔍 Discover network topology and update port names with LLDP intelligence."""
    # Use global state
    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    if debug:
        console.print("🐛 [bold yellow]Debug logging enabled[/bold yellow]")

    if dry_run:
        console.print("🔍 [bold cyan]Dry run mode - no changes will be applied[/bold cyan]")

    if verify_updates:
        console.print("🧠 [bold green]Using Smart Port Mapping with device-aware capabilities[/bold green]")

    try:
        # Load configuration
        from .config import UnifiConfig

        console.print(f"📁 Config: [cyan]{config}[/cyan]")
        load_env_from_config(str(config))
        unifi_config = UnifiConfig.from_env()

        # Set default paths
        output_path = output or Path.cwd() / "reports" / "port_mapping_report.md"
        diagram_path = diagram or Path.cwd() / "diagrams" / f"network_diagram.{format}"

        # Ensure directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        diagram_path.parent.mkdir(parents=True, exist_ok=True)

        console.print(f"📄 Output: [cyan]{output_path}[/cyan]")
        console.print(f"🖼️ Diagram: [cyan]{diagram_path}[/cyan]")

        # Create port mapper
        from .port_mapper import UnifiPortMapper

        port_mapper = UnifiPortMapper(
            base_url=unifi_config.base_url,
            site=unifi_config.site,
            api_token=unifi_config.api_token or '',
            username=unifi_config.username or '',
            password=unifi_config.password or '',
            verify_ssl=unifi_config.verify_ssl,
            timeout=unifi_config.timeout,
        )

        if verify_updates:
            # Use smart mapping system
            from .run_methods import (
                get_devices_and_lldp_data,  # pyright: ignore[reportUnknownVariableType]
            )
            from .smart_port_mapper import SmartPortMapper

            get_devices_and_lldp_data_func = cast(Any, get_devices_and_lldp_data)
            devices_data, lldp_data = cast(
                tuple[list[JsonDict], dict[str, JsonDict]],
                get_devices_and_lldp_data_func(port_mapper, unifi_config.site),
            )
            smart_mapper = cast(Any, SmartPortMapper(port_mapper.api_client))

            smart_results = cast(
                JsonDict,
                smart_mapper.smart_update_ports(
                    devices_data,
                    lldp_data,
                    verify_updates=verify_updates,
                    dry_run=dry_run,
                ),
            )

            # Display smart mapping report
            smart_report = smart_mapper.generate_smart_mapping_report(smart_results)
            console.print("\n" + smart_report)

        # Generate traditional report
        from .run_methods import run_port_mapper  # pyright: ignore[reportUnknownVariableType]

        run_port_mapper_func = cast(Any, run_port_mapper)
        devices, connections = cast(
            tuple[list[object], list[object]],
            run_port_mapper_func(
                port_mapper=port_mapper,
                site_id=unifi_config.site,
                dry_run=dry_run if not verify_updates else True,  # Avoid duplicate updates
                output_path=output_path,
                diagram_path=diagram_path,
                diagram_format=format,
                debug=debug,
                show_connected_devices=connected_devices,
                verify_updates=False if verify_updates else verify_updates,
            ),
        )

        console.print("✅ [bold green]Discovery completed successfully![/bold green]")
        console.print(f"📊 Devices: [cyan]{len(devices)}[/cyan], Connections: [cyan]{len(connections)}[/cyan]")

    except KeyboardInterrupt:
        console.print("\n⚠️ [bold yellow]Operation cancelled by user[/bold yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@app.command()
def install_completions(
    shell: str = typer.Argument(
        ...,
        help="Shell to install completions for (bash/zsh/fish/all)"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="🔄 Overwrite existing completion files"
    )
):
    """💻 Install shell completions (automatic via Typer).

    Note: You can also use the built-in Typer completion:
    unifi-mapper --install-completion
    """
    if shell.lower() not in ["bash", "zsh", "fish", "all"]:
        console.print(f"❌ [bold red]Unsupported shell: {shell}[/bold red]")
        console.print("Supported shells: [cyan]bash, zsh, fish, all[/cyan]")
        console.print("\n💡 [bold blue]Alternative - Use Typer's built-in completion:[/bold blue]")
        console.print("   [cyan]unifi-mapper --install-completion[/cyan]")
        raise typer.Exit(1)

    console.print(f"🔧 Installing [bold]{shell}[/bold] completions...")

    # Use the original manual completion system for compatibility
    try:
        from .completions import install_completions as manual_install
        success = manual_install(shell, force)

        if success:
            console.print("✅ [bold green]Manual completions installed successfully![/bold green]")
        else:
            console.print("❌ [bold red]Manual completion installation failed[/bold red]")
            console.print("\n💡 [bold blue]Try Typer's automatic completion instead:[/bold blue]")
            console.print("   [cyan]unifi-mapper --install-completion[/cyan]")

    except Exception as e:
        console.print(f"❌ [bold red]Completion installation failed: {e}[/bold red]")
        console.print("\n💡 [bold blue]Alternative - Use Typer's built-in completion:[/bold blue]")
        console.print("   [cyan]unifi-mapper --install-completion[/cyan]")
        console.print("   [cyan]unifi-mapper --show-completion[/cyan]")

    console.print("\n📝 [bold]To enable completions:[/bold]")
    console.print("  🐚 Bash: [dim]source ~/.bashrc[/dim]")
    console.print("  🐚 Zsh: [dim]source ~/.zshrc[/dim]")
    console.print("  🐚 Fish: [dim]Automatic on restart[/dim]")
    console.print("\n🎯 [bold blue]Or use Typer's automatic completion:[/bold blue]")
    console.print("   [cyan]unifi-mapper --install-completion[/cyan]")




@find_app.command("device")
def find_device(
    query: str = typer.Argument(..., help="🔍 Device name, IP, or MAC to search for")
):
    """🔍 Find device by name, IP, or MAC address."""
    console.print(f"🔍 Searching for device: [cyan]{query}[/cyan]")
    console.print("💡 Integration with enhanced device discovery in network_cli")


@analyze_app.command("link-quality")
def analyze_link_quality(
    device: Optional[str] = typer.Option(None, "--device", help="🖥️ Specific device to analyze")
):
    """📊 Analyze port statistics and error rates."""
    console.print("📊 [bold]Link Quality Analysis[/bold]")
    console.print("💡 Full implementation available via: [cyan]unifi-network-toolkit analyze link-quality[/cyan]")


@analyze_app.command("port-profiles")
def analyze_port_profiles():
    """🔌 Validate port profile safety for STP Edge, BPDU Guard, and uplinks."""
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("🔌 [bold]Port Profile Validation[/bold]")

    try:
        load_env_from_config(str(config))

        from .analysis.port_profile_validation import validate_port_profiles

        report = asyncio.run(validate_port_profiles())
        console.print(f"Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]")
        console.print(f"Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")

        if report.findings:
            table = Table(title="Port Profile Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Category", style="cyan")
            table.add_column("Device", style="magenta")
            table.add_column("Port", style="yellow")
            table.add_column("Profile")
            table.add_column("Finding")

            for finding in report.findings:
                severity_style = 'red' if finding.severity == 'CRITICAL' else 'yellow'
                if finding.severity == 'INFO':
                    severity_style = 'blue'
                table.add_row(
                    f'[{severity_style}]{finding.severity}[/]',
                    finding.category,
                    finding.device_name,
                    str(finding.port_idx),
                    finding.profile_name,
                    finding.message,
                )
            console.print(table)
        else:
            console.print("✅ [bold green]No port profile findings detected[/bold green]")

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("lag-candidates")
def analyze_lag_candidates(
    min_links: int = typer.Option(2, "--min-links", help="Minimum parallel links", min=2),
):
    """🔗 Find parallel links that may be LACP candidates."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("🔗 [bold]LAG Candidate Finder[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.lag_monitoring import find_lag_candidates

        report = asyncio.run(find_lag_candidates(min_links=min_links))
        console.print(f"Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]")
        console.print(f"Candidates: [yellow]{report.candidate_count}[/yellow]")

        if report.candidates:
            table = Table(title="LAG Candidates", show_header=True)
            table.add_column("Device A", style="cyan")
            table.add_column("Ports A", style="yellow")
            table.add_column("Device B", style="magenta")
            table.add_column("Links")
            table.add_column("Capacity")
            for candidate in report.candidates:
                table.add_row(
                    candidate.device_a,
                    ','.join(str(port) for port in candidate.device_a_ports),
                    candidate.device_b,
                    str(candidate.link_count),
                    f'{candidate.total_capacity_mbps} Mbps',
                )
            console.print(table)
        else:
            console.print("No LAG candidates detected.")
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("mtu")
def analyze_mtu():
    """📏 Audit MTU consistency across inter-switch links."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("📏 [bold]MTU Consistency Audit[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.mtu_audit import audit_mtu_consistency

        report = asyncio.run(audit_mtu_consistency())
        console.print(f"Links analyzed: [cyan]{report.links_analyzed}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")
        if report.findings:
            table = Table(title="MTU Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Link", style="cyan")
            table.add_column("MTU")
            table.add_column("Finding")
            for finding in report.findings:
                table.add_row(
                    finding.severity,
                    f'{finding.device_a}:{finding.port_a} -> {finding.device_b}:{finding.port_b or ""}',
                    f'{finding.mtu_a}/{finding.mtu_b or "unknown"}',
                    finding.message,
                )
            console.print(table)
        if not report.validation_passed:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("radio")
def analyze_radio():
    """📶 Analyze Wi-Fi radio channel and transmit power optimisation."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("📶 [bold]Radio Optimisation Analysis[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.radio_optimization import analyze_radio_optimization

        report = asyncio.run(analyze_radio_optimization())
        console.print(f"APs analyzed: [cyan]{report.aps_analyzed}[/cyan]")
        console.print(f"Radios analyzed: [cyan]{report.radios_analyzed}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")
        if report.findings:
            table = Table(title="Radio Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Category", style="cyan")
            table.add_column("AP", style="magenta")
            table.add_column("Band")
            table.add_column("Channel")
            table.add_column("Finding")
            for finding in report.findings:
                table.add_row(
                    finding.severity,
                    finding.category,
                    finding.ap_name,
                    finding.band,
                    str(finding.channel or ''),
                    finding.message,
                )
            console.print(table)
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("sfp")
def analyze_sfp():
    """🔦 Audit SFP/SFP+ transceiver diagnostics."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("🔦 [bold]SFP Diagnostics[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.sfp_diagnostics import audit_sfp_diagnostics

        report = asyncio.run(audit_sfp_diagnostics())
        console.print(f"SFP ports analyzed: [cyan]{report.ports_analyzed}[/cyan]")
        console.print(f"Modules found: [cyan]{report.modules_found}[/cyan]")
        console.print(f"Diagnostics available: [cyan]{report.diagnostics_available}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")

        if report.modules:
            table = Table(title="SFP Modules", show_header=True)
            table.add_column("Device", style="cyan")
            table.add_column("Port", style="yellow")
            table.add_column("Vendor")
            table.add_column("Part")
            table.add_column("Temp C")
            table.add_column("Tx dBm")
            table.add_column("Rx dBm")
            for module in report.modules:
                table.add_row(
                    module.device_name,
                    str(module.port_idx),
                    module.vendor,
                    module.part,
                    '' if module.temperature_c is None else f'{module.temperature_c:.1f}',
                    '' if module.tx_power_dbm is None else f'{module.tx_power_dbm:.2f}',
                    '' if module.rx_power_dbm is None else f'{module.rx_power_dbm:.2f}',
                )
            console.print(table)

        if report.findings:
            findings_table = Table(title="SFP Findings", show_header=True)
            findings_table.add_column("Severity", style="bold")
            findings_table.add_column("Category", style="cyan")
            findings_table.add_column("Device", style="magenta")
            findings_table.add_column("Port", style="yellow")
            findings_table.add_column("Finding")
            for finding in report.findings:
                findings_table.add_row(
                    finding.severity,
                    finding.category,
                    finding.device_name,
                    str(finding.port_idx),
                    finding.message,
                )
            console.print(findings_table)
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("vlan-coverage")
def analyze_vlan_coverage(
    required_vlans: str = typer.Option(
        ...,
        "--required-vlans",
        help="Comma-separated VLAN IDs required on trunk/planned uplink ports",
    ),
    planned_uplink: list[str] = typer.Option(
        [],
        "--planned-uplink",
        help="Planned uplink target name/model to treat as critical",
    ),
):
    """🔀 Audit VLAN coverage on trunk and planned uplink ports."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("🔀 [bold]VLAN Coverage Audit[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.vlan_coverage import audit_vlan_coverage

        vlans = _parse_csv_ints(required_vlans)
        report = asyncio.run(audit_vlan_coverage(vlans, planned_uplinks=planned_uplink))
        console.print(f"Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]")
        console.print(f"Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]")
        console.print(f"Required VLANs: [cyan]{', '.join(str(v) for v in report.required_vlans)}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")

        if report.findings:
            table = Table(title="VLAN Coverage Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Device", style="cyan")
            table.add_column("Port", style="yellow")
            table.add_column("Missing VLANs")
            table.add_column("Finding")
            for finding in report.findings:
                table.add_row(
                    finding.severity,
                    finding.device,
                    str(finding.port),
                    ', '.join(str(vlan) for vlan in finding.missing_vlans),
                    finding.message,
                )
            console.print(table)
        if not report.validation_passed:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@analyze_app.command("traffic-matrix")
def analyze_traffic_matrix_cmd(
    top: int = typer.Option(10, "--top", help="Number of flows/talkers to show", min=1),
):
    """📈 Analyze traffic matrix/top talkers from available UniFi statistics."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print("📈 [bold]Traffic Matrix[/bold]")

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.traffic_matrix import analyze_traffic_matrix

        report = asyncio.run(analyze_traffic_matrix(top_n=top))
        console.print(f"Records analyzed: [cyan]{report.records_analyzed}[/cyan]")
        console.print(f"Flows: [cyan]{report.flow_count}[/cyan]")
        console.print(f"Total bytes: [cyan]{report.total_bytes}[/cyan]")

        if report.top_flows:
            table = Table(title="Top Flows", show_header=True)
            table.add_column("Endpoint A", style="cyan")
            table.add_column("Endpoint B", style="magenta")
            table.add_column("Bytes", style="yellow")
            table.add_column("Peak bps")
            for flow in report.top_flows:
                table.add_row(
                    flow.endpoint_a.identifier,
                    flow.endpoint_b.identifier,
                    str(flow.total_bytes),
                    '' if flow.max_bps is None else f'{flow.max_bps:.0f}',
                )
            console.print(table)
        else:
            console.print("No endpoint-pair flow records found in available UniFi statistics.")

        if report.recommendations:
            console.print("\nRecommendations:")
            for recommendation in report.recommendations:
                console.print(f"  • {recommendation.recommendation}")
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if state.debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@diagnose_app.command("all")
def diagnose_all():
    """🏥 Run ALL diagnostics and print a pass/warn/fail summary table."""
    import asyncio
    from typing import Callable, Coroutine

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("🏥 [bold]Comprehensive Diagnostics Runner[/bold]\n")

    try:
        load_env_from_config(str(config))

        from .analysis.capacity_planning import get_capacity_report
        from .analysis.client_density import analyze_client_density
        from .analysis.dhcp_pool import check_dhcp_pool_utilization
        from .analysis.firmware_advisor import get_firmware_report
        from .analysis.link_quality import analyze_link_quality
        from .analysis.mtu_audit import audit_mtu_consistency
        from .analysis.poe_budget import check_poe_budget
        from .analysis.port_profile_validation import validate_port_profiles
        from .analysis.radio_optimization import analyze_radio_optimization
        from .analysis.sfp_diagnostics import audit_sfp_diagnostics
        from .analysis.uplink_redundancy import check_uplink_redundancy
        from .analysis.vlan_coverage import audit_vlan_coverage

        # Each check: (name, async callable, result → status extractor)
        checks: list[tuple[str, Callable[[], Coroutine]]] = [
            ('Link Quality', analyze_link_quality),
            ('Capacity Planning', get_capacity_report),
            ('Port Profiles', validate_port_profiles),
            ('MTU Consistency', audit_mtu_consistency),
            ('SFP Diagnostics', audit_sfp_diagnostics),
            ('Radio Optimization', analyze_radio_optimization),
            ('Firmware Skew', get_firmware_report),
            ('DHCP Pool', check_dhcp_pool_utilization),
            ('PoE Budget', check_poe_budget),
            ('Client Density', analyze_client_density),
            ('Uplink Redundancy', check_uplink_redundancy),
        ]

        results: list[tuple[str, str]] = []

        for name, coro_fn in checks:
            console.print(f"  ▶ {name}...", end=' ')
            try:
                report = asyncio.run(coro_fn())
                status = _extract_status(report)
                results.append((name, status))
                style = {'PASS': 'green', 'WARN': 'yellow', 'FAIL': 'red'}.get(status, 'white')
                console.print(f"[{style}]{status}[/]")
            except Exception as exc:
                results.append((name, 'FAIL'))
                console.print(f"[red]FAIL[/] ({exc})")

        # Summary table
        console.print()
        table = Table(title="Diagnostics Summary", show_header=True)
        table.add_column("Check", style="cyan")
        table.add_column("Result", style="bold")
        for name, status in results:
            style = {'PASS': 'green', 'WARN': 'yellow', 'FAIL': 'red'}.get(status, 'white')
            table.add_row(name, f'[{style}]{status}[/]')
        console.print(table)

        pass_count = sum(1 for _, s in results if s == 'PASS')
        warn_count = sum(1 for _, s in results if s == 'WARN')
        fail_count = sum(1 for _, s in results if s == 'FAIL')
        console.print(
            f"\n✅ {pass_count} passed  ⚠️ {warn_count} warnings  ❌ {fail_count} failed"
        )

        if fail_count > 0:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


def _extract_status(report: object) -> str:
    """Extract pass/warn/fail from a report object by inspecting common fields."""
    # Check explicit validation_passed field
    if hasattr(report, 'validation_passed'):
        if not report.validation_passed:  # type: ignore[union-attr]
            return 'FAIL'

    # Check for warnings list
    warnings = getattr(report, 'warnings', None)
    if isinstance(warnings, list) and warnings:
        return 'WARN'

    # Check overall_health field
    health = getattr(report, 'overall_health', None)
    if health == 'CRITICAL':
        return 'FAIL'
    if health == 'DEGRADED':
        return 'WARN'

    # Check network_healthy field
    healthy = getattr(report, 'network_healthy', None)
    if healthy is False:
        return 'FAIL'

    # Check findings_count
    findings = getattr(report, 'findings_count', None)
    if isinstance(findings, int) and findings > 0:
        return 'WARN'

    # Check recommendations list as a soft signal
    recs = getattr(report, 'recommendations', None)
    if isinstance(recs, list) and recs:
        return 'WARN'

    return 'PASS'


@diagnose_app.command("health")
def diagnose_health(
    detailed: bool = typer.Option(False, "--detailed", help="🔬 Include detailed device analysis")
):
    """🏥 Overall network health check."""
    console.print("🏥 [bold]Network Health Check[/bold]")
    console.print("💡 Full implementation available via: [cyan]unifi-network-toolkit diagnose network-health[/cyan]")


@diagnose_app.command("latency-matrix")
def diagnose_latency_matrix(
    ping_count: int = typer.Option(3, "--count", "-c", help="Pings per target"),
    timeout: int = typer.Option(2, "--timeout", "-t", help="Ping timeout seconds"),
    devices_only: bool = typer.Option(False, "--devices-only", help="Skip clients, only ping infrastructure"),
):
    """📡 SSH to gateway and ping all devices to build a latency matrix."""
    import asyncio
    from rich.table import Table

    from unifi_mapper.analysis.latency_matrix import run_latency_matrix

    if not state.debug:
        setup_logging(debug=False)

    load_env_from_config(str(state.config_path))
    console.print("📡 [bold]Gateway Latency Matrix[/bold]\n")

    try:
        report = asyncio.run(
            run_latency_matrix(
                ping_count=ping_count,
                timeout=timeout,
                include_clients=not devices_only,
            )
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Summary
    console.print(f"Gateway: [cyan]{report.gateway_host}[/cyan]")
    console.print(f"Targets: {report.targets_reachable}/{report.targets_total} reachable\n")

    # Results table
    table = Table(title="Latency Results")
    table.add_column("Name", style="cyan")
    table.add_column("IP", style="dim")
    table.add_column("Type")
    table.add_column("RTT avg", justify="right")
    table.add_column("RTT max", justify="right")
    table.add_column("Loss", justify="right")
    table.add_column("Status")

    # Sort: unreachable first, then by avg RTT descending
    sorted_results = sorted(
        report.results,
        key=lambda r: (r.reachable, -(r.rtt_avg or 0)),
    )

    for r in sorted_results:
        if r.reachable:
            status = "[green]✅[/green]"
            rtt_avg = f"{r.rtt_avg:.1f}ms" if r.rtt_avg else "—"
            rtt_max = f"{r.rtt_max:.1f}ms" if r.rtt_max else "—"
            loss = f"{r.packet_loss:.0f}%" if r.packet_loss > 0 else "0%"
        else:
            status = "[red]❌[/red]"
            rtt_avg = "—"
            rtt_max = "—"
            loss = "[red]100%[/red]"

        table.add_row(r.name, r.ip, r.target_type, rtt_avg, rtt_max, loss, status)

    console.print(table)

    if report.unreachable_devices:
        console.print(f"\n[red]Unreachable ({len(report.unreachable_devices)}):[/red]")
        for name in report.unreachable_devices:
            console.print(f"  ❌ {name}")


@diagnose_app.command("inter-vlan")
def diagnose_inter_vlan(
    source: str = typer.Argument(..., help="Source endpoint IP, MAC, hostname, or device name"),
    destination: str = typer.Argument(..., help="Destination endpoint IP, MAC, hostname, or device name"),
    protocol: str = typer.Option("icmp", "--protocol", help="Protocol to check"),
    port: Optional[str] = typer.Option(None, "--port", help="Optional destination port"),
):
    """🔀 Check inter-VLAN routing and firewall verdict between two endpoints."""
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("🔀 [bold]Inter-VLAN Routing Check[/bold]")
    console.print(f"Source: [cyan]{source}[/cyan]")
    console.print(f"Destination: [cyan]{destination}[/cyan]")

    try:
        load_env_from_config(str(config))

        from .connectivity.inter_vlan import check_inter_vlan_routing

        report = asyncio.run(
            check_inter_vlan_routing(
                source=source,
                destination=destination,
                protocol=protocol,
                port=port,
            )
        )

        verdict_style = {
            'allow': 'green',
            'deny': 'red',
            'unknown': 'yellow',
        }.get(report.verdict, 'white')
        console.print(f"Verdict: [{verdict_style}]{report.verdict.upper()}[/]")
        console.print(f"Source VLAN: [cyan]{report.source_vlan or 'unknown'}[/cyan]")
        console.print(f"Destination VLAN: [cyan]{report.destination_vlan or 'unknown'}[/cyan]")
        console.print(f"Route required: [cyan]{'yes' if report.route_required else 'no'}[/cyan]")

        if report.matching_rules:
            console.print("Matching rules:")
            for rule in report.matching_rules:
                console.print(f"  - {rule}")

        if report.recommendations:
            console.print("Recommendations:")
            for recommendation in report.recommendations:
                console.print(f"  - {recommendation}")

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@app.command()
def diagram(
    output: Annotated[
        Optional[Path],
        typer.Option('--output', '-o', help='🖼️ Output path for diagram')
    ] = None,
    format: Annotated[
        str,
        typer.Option('--format', '-f', help='🎨 Diagram format (png, svg, html)')
    ] = 'png',
    all_devices: Annotated[
        bool,
        typer.Option('--all-devices', '-a', help='📱 Include all devices (not just infrastructure)')
    ] = False,
):
    """🖼️ Generate network topology diagram only (no port renaming).

    Generates a visual diagram of your UniFi infrastructure without
    performing any LLDP analysis or port name updates.
    """
    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        from .config import UnifiConfig

        console.print(f"📁 Config: [cyan]{config}[/cyan]")
        load_env_from_config(str(config))
        unifi_config = UnifiConfig.from_env()

        # Set output path
        diagram_path = output or Path.cwd() / "diagrams" / f"network_diagram.{format}"
        diagram_path.parent.mkdir(parents=True, exist_ok=True)

        console.print(f"🖼️ Diagram: [cyan]{diagram_path}[/cyan]")
        console.print(f"📊 Mode: [cyan]{'All devices' if all_devices else 'Infrastructure only'}[/cyan]")

        # Create port mapper just to get device data
        from .enhanced_network_topology import NetworkTopology
        from .models import DeviceInfo, PortInfo
        from .port_mapper import UnifiPortMapper

        port_mapper = UnifiPortMapper(
            base_url=unifi_config.base_url,
            site=unifi_config.site,
            api_token=unifi_config.api_token or '',
            username=unifi_config.username or '',
            password=unifi_config.password or '',
            verify_ssl=unifi_config.verify_ssl,
            timeout=unifi_config.timeout,
        )

        # Get ALL UniFi devices for the diagram
        console.print("🔍 [dim]Fetching devices...[/dim]")
        all_devices_response = cast(Any, port_mapper.api_client.get_devices(unifi_config.site))
        if isinstance(all_devices_response, dict):
            raw_devices = cast(dict[str, Any], all_devices_response).get("data", [])
            all_devices_list = cast(list[JsonDict], raw_devices if isinstance(raw_devices, list) else [])
        else:
            all_devices_list = cast(list[JsonDict], all_devices_response)

        # Filter to UniFi infrastructure devices (gateway, switches, APs)
        unifi_types = ["ugw", "usg", "udm", "usw", "uap"]
        infrastructure_devices = [
            d for d in all_devices_list
            if d.get("type") in unifi_types
        ]

        # Get LLDP data for devices that support it
        console.print("🔍 [dim]Fetching LLDP data...[/dim]")
        lldp_data: dict[str, dict[str, JsonDict]] = {}
        for device in infrastructure_devices:
            device_id = str(device.get("_id") or "")
            device_type = str(device.get("type") or "")
            # Only switches and gateways have LLDP data
            if device_type in ["ugw", "usg", "udm", "usw"] and device_id:
                device_lldp = port_mapper.api_client.get_lldp_info(unifi_config.site, device_id)
                if device_lldp:
                    lldp_data[device_id] = device_lldp

        # Build device dict and MAC lookup for ALL infrastructure devices
        devices: dict[str, DeviceInfo] = {}
        mac_to_id: dict[str, str] = {}
        routers_found = 0
        switches_found = 0
        aps_found = 0

        for device_data in infrastructure_devices:
            device_id = str(device_data.get("_id") or "")
            device_mac = str(device_data.get("mac") or "")
            device_model = str(device_data.get("model") or "")
            device_type = str(device_data.get("type") or "")

            # Count device types for debug
            if device_type in ["ugw", "usg", "udm"]:
                routers_found += 1
            elif device_type == "usw":
                switches_found += 1
            elif device_type == "uap":
                aps_found += 1

            # Extract port information from device data
            ports: list[PortInfo] = []
            port_table = cast(list[JsonDict], device_data.get("port_table", []))
            port_overrides = {
                int(port.get("port_idx") or 0): port
                for port in cast(list[JsonDict], device_data.get("port_overrides", []))
            }

            for port_data in port_table:
                port_idx = int(port_data.get("port_idx") or 0)
                # Check for custom name in overrides first
                override = port_overrides.get(port_idx, {})
                port_name = str(override.get("name") or port_data.get("name", f"Port {port_idx}"))

                port_info = PortInfo(
                    idx=port_idx,
                    name=port_name,
                    up=bool(port_data.get("up", False)),
                    enabled=bool(port_data.get("enabled", True)),
                    poe=bool(port_data.get("poe_enable", False)),
                    media=str(port_data.get("media", "RJ45")),
                    speed=int(port_data.get("speed") or 0),
                    lldp_info={},
                )
                ports.append(port_info)

            device = DeviceInfo(
                id=device_id,
                name=str(device_data.get("name") or "Unknown"),
                model=device_model,
                mac=device_mac,
                ip=str(device_data.get("ip") or ""),
                ports=ports,
                lldp_info=lldp_data.get(device_id, {}),
            )
            devices[device_id] = device
            if device_mac:
                normalized_mac = device_mac.lower().replace(":", "").replace("-", "")
                mac_to_id[normalized_mac] = device_id

        console.print(f"📊 [dim]Device types: {routers_found} routers, {switches_found} switches, {aps_found} APs[/dim]")

        # Create topology and generate diagram
        topology = NetworkTopology(devices)

        # Add connections from LLDP data
        connection_count = 0
        for device_id, device_lldp in lldp_data.items():
            for port_idx_str, port_lldp in device_lldp.items():
                chassis_id = str(port_lldp.get("chassis_id") or "")
                if not chassis_id:
                    continue
                # Normalize chassis_id MAC format
                normalized_chassis = chassis_id.lower().replace(":", "").replace("-", "")
                # Find connected device by normalized MAC
                if normalized_chassis in mac_to_id:
                    other_id = mac_to_id[normalized_chassis]
                    if other_id != device_id:  # Avoid self-connections
                        try:
                            port_idx = int(port_idx_str)
                        except ValueError:
                            port_idx = 0
                        topology.add_connection(device_id, other_id, port_idx, 0)
                        connection_count += 1

        topology_connections = cast(list[object], cast(Any, topology).connections)
        console.print(
            f"🔗 [dim]Found {connection_count} LLDP connections "
            f"(topology has {len(topology_connections)})[/dim]"
        )

        # Generate diagram
        if format.lower() == "png":
            topology.generate_png_diagram(str(diagram_path))
        elif format.lower() == "svg":
            topology.generate_svg_diagram(str(diagram_path))
        elif format.lower() == "html":
            topology.generate_html_diagram(str(diagram_path), all_devices)
        else:
            console.print(f"❌ [bold red]Unsupported format: {format}[/bold red]")
            raise typer.Exit(1)

        console.print(f"✅ [bold green]Diagram generated: {diagram_path}[/bold green]")
        console.print(
            f"📊 Devices: [cyan]{len(devices)}[/cyan], "
            f"Connections: [cyan]{len(topology_connections)}[/cyan]"
        )

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@app.command()
def version():
    """📋 Show version information."""
    console.print("🚀 [bold cyan]UniFi Network Port Mapper[/bold cyan]")
    console.print("Version: [green]2.0.0[/green] (Enterprise Edition)")
    console.print("Framework: [blue]Typer + Rich + Multi-AI Analysis[/blue]")
    console.print("Features: [dim]100% Verified Port Naming + Device Intelligence[/dim]")


@app.command()
def capabilities():
    """🧠 Analyze device capabilities for port naming support."""
    console.print("🧠 [bold]Device Capability Analysis[/bold]")

    try:
        # Run the capability analysis
        from .analyze_network_capabilities import main as analyze_main
        analyze_main()

    except Exception as e:
        console.print(f"❌ [bold red]Capability analysis failed: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def verify(
    all_ports: bool = typer.Option(
        False,
        "--all",
        help="✅ Verify all LLDP-discovered ports"
    ),
    device: Optional[str] = typer.Option(
        None,
        "--device",
        help="🖥️ Specific device to verify"
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        help="🔌 Specific port to verify"
    ),
    expected: Optional[str] = typer.Option(
        None,
        "--expected",
        help="📝 Expected port name"
    ),
    consistency_check: bool = typer.Option(
        False,
        "--consistency-check",
        help="🔄 Perform multi-read consistency verification"
    ),
    reads: int = typer.Option(
        5,
        "--reads",
        help="📊 Number of consistency reads",
        min=3, max=10
    )
):
    """✅ Comprehensive port name verification with ground truth checking."""
    console.print("✅ [bold]Ground Truth Verification[/bold]")

    if device and port is not None and expected:
        console.print(f"🔍 Verifying single port: [cyan]{device}[/cyan] Port {port} = '{expected}'")
    elif all_ports:
        console.print("🔍 Verifying all LLDP-discovered ports")
    else:
        console.print("📊 Analyzing current network state")

    try:
        # Use the existing verify CLI functionality
        # Build arguments for the existing CLI
        import sys
        from .verify_cli import main as verify_main
        original_argv = sys.argv[:]
        sys.argv = ["verify"]

        if all_ports:
            sys.argv.append("--verify-all")
        if consistency_check:
            sys.argv.append("--consistency-check")
            sys.argv.extend(["--reads", str(reads)])
        if device:
            sys.argv.extend(["--device", device])
        if port is not None:
            sys.argv.extend(["--port", str(port)])
        if expected:
            sys.argv.extend(["--expected", expected])

        try:
            verify_main()
        finally:
            sys.argv = original_argv

    except SystemExit as e:
        # verify_main uses sys.exit, handle gracefully
        if e.code != 0:
            exit_code = e.code if isinstance(e.code, int) else 1
            raise typer.Exit(exit_code)
    except Exception as e:
        console.print(f"❌ [bold red]Verification failed: {e}[/bold red]")
        raise typer.Exit(1)


# =============================================================================
# STP Commands
# =============================================================================

@stp_app.command("analyze")
def stp_analyze(
    device: Annotated[
        Optional[str],
        typer.Option('--device', '-d', help='🖥️ Specific switch to analyze')
    ] = None,
):
    """🌳 Analyze current STP topology and display hierarchy.

    Shows all switches with their STP configuration, bridge priorities,
    and hierarchy tiers (Core, Distribution, Access).
    """
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("🌳 [bold]STP Topology Analysis[/bold]")

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import discover_stp_topology

        topology = asyncio.run(discover_stp_topology(device_id=device))

        # Display summary
        console.print("\n📊 [bold]Summary[/bold]")
        console.print(f"  Switches: [cyan]{len(topology.switches)}[/cyan]")
        console.print(f"  Root Bridge: [green]{topology.root_bridge_name or 'Unknown'}[/green]")
        console.print(f"  Root Priority: [yellow]{topology.root_bridge_priority}[/yellow]")
        console.print(f"  Blocked Ports: [{'red' if topology.blocked_ports_count else 'green'}]{topology.blocked_ports_count}[/]")

        # Display topology table
        table = Table(title="STP Topology", show_header=True)
        table.add_column("Switch", style="cyan")
        table.add_column("Priority", style="yellow")
        table.add_column("Tier", style="blue")
        table.add_column("Root", style="green")
        table.add_column("Gateway", style="magenta")

        tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}
        for switch in topology.switches:
            tier_name = tier_names.get(switch.hierarchy_tier, f'Tier {switch.hierarchy_tier}')
            root_marker = '✅' if switch.is_root_bridge else ''
            gw_marker = '✅' if switch.connected_to_gateway else ''
            table.add_row(
                switch.name,
                str(switch.current_priority),
                tier_name,
                root_marker,
                gw_marker
            )

        console.print(table)

        if topology.blocked_ports_count > 0:
            console.print(f"\n⚠️ [yellow]Found {topology.blocked_ports_count} blocked port(s) - indicates redundant paths[/yellow]")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("optimize")
def stp_optimize(
    dry_run: Annotated[
        bool,
        typer.Option('--dry-run', help='🔍 Preview changes without applying (default)')
    ] = True,
    apply: Annotated[
        bool,
        typer.Option('--apply', help='⚡ Apply the changes')
    ] = False,
    force: Annotated[
        bool,
        typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying')
    ] = False,
    plan: Annotated[
        Optional[Path],
        typer.Option('--plan', help='📄 Write reversible STP change plan JSON')
    ] = None,
):
    """🔧 Calculate and optionally apply optimal STP priorities.

    Analyzes network topology and calculates optimal bridge priorities:
    - Tier 0 (Core): Priority 4096 - Switches connected to gateway
    - Tier 1 (Distribution): Priority 8192 - One hop from core
    - Tier 2+ (Access): Priority 16384+ - Two+ hops from core

    Default is --dry-run to preview changes. Use --apply to make changes.
    """
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    # --apply overrides --dry-run
    if apply:
        dry_run = False

    console.print("🔧 [bold]STP Optimization[/bold]")

    if dry_run:
        console.print("🔍 [cyan]Dry run mode - no changes will be applied[/cyan]")
    else:
        console.print("⚡ [yellow]Apply mode - changes will be made[/yellow]")

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import (
            apply_stp_changes,
            calculate_optimal_priorities,
            discover_stp_topology,
        )

        # Discover topology
        console.print("📡 [dim]Discovering STP topology...[/dim]")
        topology = asyncio.run(discover_stp_topology())

        # Calculate optimal priorities
        console.print("🧮 [dim]Calculating optimal priorities...[/dim]")
        changes = asyncio.run(calculate_optimal_priorities(topology))

        if not changes:
            console.print("✅ [bold green]STP configuration is already optimal![/bold green]")
            return

        # Display changes table
        table = Table(title="Recommended Changes", show_header=True)
        table.add_column("Switch", style="cyan")
        table.add_column("Current", style="red")
        table.add_column("Optimal", style="green")
        table.add_column("Tier", style="blue")
        table.add_column("Reason", style="dim")

        tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}
        for change in changes:
            tier_name = tier_names.get(change.hierarchy_tier, f'Tier {change.hierarchy_tier}')
            table.add_row(
                change.device_name,
                str(change.current_priority),
                str(change.new_priority),
                tier_name,
                change.reason[:40] + '...' if len(change.reason) > 40 else change.reason
            )

        console.print(table)
        console.print(f"\n📊 [bold]{len(changes)} change(s) recommended[/bold]")

        if plan:
            from .analysis.stp_change_plan import create_stp_change_plan

            change_plan = create_stp_change_plan(changes)
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text(change_plan.model_dump_json(indent=2))
            console.print(f"📄 STP change plan saved to [cyan]{plan}[/cyan]")

        if not dry_run:
            if not force:
                confirm = typer.confirm(
                    f"\n⚠️ Apply {len(changes)} STP priority change(s)? This may cause brief network disruption.",
                    default=False
                )
                if not confirm:
                    console.print("❌ [yellow]Operation cancelled[/yellow]")
                    raise typer.Exit(0)

            console.print("🚀 [dim]Applying changes...[/dim]")
            result = asyncio.run(apply_stp_changes(changes, dry_run=False))

            applied_count = len(result.get('applied', []))
            failed_count = len(result.get('failed', []))

            if applied_count > 0:
                console.print(f"✅ [bold green]Applied {applied_count} change(s)[/bold green]")

            if failed_count > 0:
                console.print(f"❌ [bold red]Failed {failed_count} change(s)[/bold red]")
                for failure in result.get('failed', []):
                    console.print(f"   • {failure['device_name']}: {failure['error']}")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("apply")
def stp_apply_plan(
    plan: Annotated[
        Path,
        typer.Option('--plan', help='📄 STP change plan JSON from stp optimize --plan')
    ],
    dry_run: Annotated[
        bool,
        typer.Option('--dry-run/--no-dry-run', help='🔍 Preview plan application without applying')
    ] = True,
    force: Annotated[
        bool,
        typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying')
    ] = False,
):
    """Apply a saved convergence-aware STP plan."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_change_plan import STPChangePlan
        from .analysis.stp_optimizer import apply_stp_changes

        change_plan = STPChangePlan.model_validate_json(plan.read_text())
        console.print("⚡ [bold]STP Plan Apply[/bold]")
        console.print(f"Plan: [cyan]{plan}[/cyan]")
        console.print(f"Changes: [yellow]{len(change_plan.changes)}[/yellow]")

        if not dry_run and not force:
            confirm = typer.confirm(
                f"Apply {len(change_plan.changes)} STP change(s)? This may cause brief network disruption.",
                default=False,
            )
            if not confirm:
                console.print("❌ [yellow]Operation cancelled[/yellow]")
                raise typer.Exit(0)

        result = asyncio.run(apply_stp_changes(change_plan.changes, dry_run=dry_run))
        _print_stp_apply_result(result)

        if result.get('failed'):
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("rollback")
def stp_rollback_plan(
    plan: Annotated[
        Path,
        typer.Argument(help='📄 STP change plan JSON to roll back')
    ],
    dry_run: Annotated[
        bool,
        typer.Option('--dry-run/--no-dry-run', help='🔍 Preview rollback without applying')
    ] = True,
    force: Annotated[
        bool,
        typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying rollback')
    ] = False,
):
    """Roll back a saved STP change plan."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_change_plan import STPChangePlan
        from .analysis.stp_optimizer import apply_stp_changes

        change_plan = STPChangePlan.model_validate_json(plan.read_text())
        console.print("↩️ [bold]STP Plan Rollback[/bold]")
        console.print(f"Plan: [cyan]{plan}[/cyan]")
        console.print(f"Rollback changes: [yellow]{len(change_plan.rollback)}[/yellow]")

        if not dry_run and not force:
            confirm = typer.confirm(
                f"Apply {len(change_plan.rollback)} rollback change(s)? This may cause brief network disruption.",
                default=False,
            )
            if not confirm:
                console.print("❌ [yellow]Operation cancelled[/yellow]")
                raise typer.Exit(0)

        result = asyncio.run(apply_stp_changes(change_plan.rollback, dry_run=dry_run))
        _print_stp_apply_result(result)

        if result.get('failed'):
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("report")
def stp_report(
    output: Annotated[
        Path,
        typer.Option('--output', '-o', help='📄 Output file path (required)')
    ],
):
    """📝 Generate comprehensive STP optimization report.

    Creates a markdown report with:
    - Current topology analysis
    - Recommended changes
    - Mermaid diagrams (current vs optimal)
    - Configuration diff
    """
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("📝 [bold]STP Report Generation[/bold]")
    console.print(f"📄 Output: [cyan]{output}[/cyan]")

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import (
            calculate_optimal_priorities,
            discover_stp_topology,
            format_stp_report_markdown,
            generate_stp_report,
        )

        # Discover topology
        console.print("📡 [dim]Discovering STP topology...[/dim]")
        topology = asyncio.run(discover_stp_topology())

        # Calculate optimal priorities
        console.print("🧮 [dim]Calculating optimal priorities...[/dim]")
        changes = asyncio.run(calculate_optimal_priorities(topology))

        # Generate report
        console.print("📝 [dim]Generating report...[/dim]")
        report = asyncio.run(generate_stp_report(topology, changes))

        # Format and write markdown
        markdown = format_stp_report_markdown(report)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown)

        console.print(f"✅ [bold green]Report saved to {output}[/bold green]")
        console.print(f"📊 Analyzed: [cyan]{report.switches_analyzed}[/cyan] switches")
        console.print(f"🔄 Changes: [yellow]{report.changes_required}[/yellow] recommended")

        if report.issues:
            console.print("\n⚠️ [bold yellow]Issues Found:[/bold yellow]")
            for issue in report.issues:
                console.print(f"   • {issue}")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("snapshot")
def stp_snapshot(
    output: Annotated[
        Path,
        typer.Option('--output', '-o', help='📄 Output STP snapshot JSON path')
    ],
):
    """Capture a replayable STP topology snapshot."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_optimizer import discover_stp_topology
        from .analysis.stp_snapshot import snapshot_stp_topology

        console.print("📸 [bold]STP Snapshot[/bold]")
        topology = asyncio.run(discover_stp_topology())
        snapshot = snapshot_stp_topology(topology)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(snapshot.model_dump_json(indent=2))
        console.print(f"📄 Snapshot saved to [cyan]{output}[/cyan]")
        console.print(f"Root bridge: [green]{snapshot.root_bridge_name or 'Unknown'}[/green]")
        console.print(f"Switches: [cyan]{len(snapshot.switches)}[/cyan]")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("diff")
def stp_diff(
    baseline: Annotated[
        Path,
        typer.Argument(help='📄 Baseline STP snapshot JSON')
    ],
    output: Annotated[
        Optional[Path],
        typer.Option('--output', '-o', help='Optional output diff JSON path')
    ] = None,
):
    """Diff a saved STP snapshot against the current live topology."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_optimizer import discover_stp_topology
        from .analysis.stp_snapshot import (
            STPSnapshot,
            diff_stp_snapshots,
            snapshot_stp_topology,
        )

        console.print("🔎 [bold]STP Snapshot Diff[/bold]")
        before = STPSnapshot.model_validate_json(baseline.read_text())
        topology = asyncio.run(discover_stp_topology())
        after = snapshot_stp_topology(topology)
        diff = diff_stp_snapshots(before, after)

        console.print(f"Changes: [yellow]{len(diff.changes)}[/yellow]")
        if diff.changes:
            table = Table(title="STP Changes", show_header=True)
            table.add_column("Type", style="cyan")
            table.add_column("Subject", style="magenta")
            table.add_column("Before")
            table.add_column("After")
            for change in diff.changes:
                table.add_row(
                    change.change_type,
                    change.subject,
                    str(change.before),
                    str(change.after),
                )
            console.print(table)
        else:
            console.print("✅ [bold green]No STP changes detected[/bold green]")

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(diff.model_dump_json(indent=2))
            console.print(f"📄 Diff saved to [cyan]{output}[/cyan]")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("preflight")
def stp_preflight(
    planned_switches: Annotated[
        str,
        typer.Option(
            '--simulate-add',
            help='Planned switch model/count, for example USW-Flex-XG:2',
        ),
    ] = 'USW-Flex-XG:2',
    uplink: Annotated[
        list[str],
        typer.Option('--uplink', help='Expected uplink target switch name')
    ] = [],
    output: Annotated[
        Optional[Path],
        typer.Option('--output', '-o', help='Optional preflight report JSON path')
    ] = None,
):
    """Simulate adding planned switches and report expected STP root/priority state."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_optimizer import discover_stp_topology
        from .analysis.stp_preflight import stp_preflight_simulate_add

        console.print("🧪 [bold]STP Preflight Simulation[/bold]")
        planned_models = _parse_planned_switches(planned_switches)
        topology = asyncio.run(discover_stp_topology())
        report = stp_preflight_simulate_add(
            topology,
            planned_models=planned_models,
            uplink_targets=uplink,
        )

        console.print(f"Simulated switches added: [cyan]{report.simulated_switches_added}[/cyan]")
        console.print(f"Expected root: [green]{report.expected_root or 'Unknown'}[/green]")

        table = Table(title="Required Priorities", show_header=True)
        table.add_column("Switch", style="cyan")
        table.add_column("Priority", style="yellow")
        for switch_name, priority in report.required_priorities.items():
            table.add_row(switch_name, str(priority))
        console.print(table)

        if report.checklist:
            console.print("\nChecklist:")
            for item in report.checklist:
                console.print(f"  • {item}")

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report.model_dump_json(indent=2))
            console.print(f"📄 Preflight report saved to [cyan]{output}[/cyan]")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("guard")
def stp_guard(
    tcn_threshold: int = typer.Option(
        10,
        "--tcn-threshold",
        help="STP topology-change count threshold before warning",
        min=1,
    ),
):
    """🛡️ Audit Root Guard candidates and STP topology-change counters."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_guard import audit_stp_guard_recommendations
        from .analysis.stp_optimizer import discover_stp_topology

        console.print("🛡️ [bold]STP Guard Audit[/bold]")
        topology = asyncio.run(discover_stp_topology())
        report = audit_stp_guard_recommendations(topology, tcn_threshold=tcn_threshold)

        console.print(f"Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")

        if report.findings:
            table = Table(title="STP Guard Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Category", style="cyan")
            table.add_column("Device", style="magenta")
            table.add_column("Port", style="yellow")
            table.add_column("Finding")
            for finding in report.findings:
                table.add_row(
                    finding.severity,
                    finding.category,
                    finding.device_name,
                    str(finding.port_idx),
                    finding.message,
                )
            console.print(table)
        else:
            console.print("✅ [bold green]No STP guard findings detected[/bold green]")

    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("drift")
def stp_drift(
    intent: Path = typer.Option(
        ...,
        "--intent",
        help="Path to stp_intent.yaml/json desired priority file",
    ),
):
    """📋 Compare live STP state against an intent file."""
    import asyncio

    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    try:
        load_env_from_config(str(state.config_path))

        from .analysis.stp_drift import (
            STPIntentMapping,
            detect_stp_config_drift,
            load_stp_intent,
        )
        from .analysis.stp_optimizer import discover_stp_topology

        console.print("📋 [bold]STP Config Drift[/bold]")
        topology = asyncio.run(discover_stp_topology())
        desired = cast(STPIntentMapping, load_stp_intent(intent))
        report = detect_stp_config_drift(topology, desired)

        console.print(f"Devices checked: [cyan]{report.devices_checked}[/cyan]")
        console.print(f"Findings: [yellow]{report.findings_count}[/yellow]")

        if report.findings:
            table = Table(title="STP Drift Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Type", style="cyan")
            table.add_column("Device", style="magenta")
            table.add_column("Expected")
            table.add_column("Actual")
            table.add_column("Finding")
            for finding in report.findings:
                table.add_row(
                    finding.severity,
                    finding.finding_type,
                    finding.device_name or finding.identifier,
                    str(finding.expected),
                    str(finding.actual),
                    finding.message,
                )
            console.print(table)
            raise typer.Exit(2)
        console.print("✅ [bold green]No STP drift detected[/bold green]")

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


@stp_app.command("validate-10g")
def stp_validate_10g(
    planned_switches: Annotated[
        int,
        typer.Option(
            '--planned-switches',
            help='Number of USW Flex XG switches planned for installation',
            min=1,
        ),
    ] = 2,
    target_speed: Annotated[
        int,
        typer.Option('--target-speed', help='Target uplink speed in Mbps'),
    ] = 10000,
    drops_threshold: Annotated[
        int,
        typer.Option(
            '--drops-threshold',
            help='Drops-only counter threshold before reporting a warning',
            min=0,
        ),
    ] = 100000,
    output: Annotated[
        Optional[Path],
        typer.Option('--output', '-o', help='Optional markdown report path'),
    ] = None,
):
    """Validate STP, 10G uplinks, and port errors before adding Flex XG switches."""
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print("🌳 [bold]10G Expansion Validation[/bold]")
    console.print(f"🔌 Planned USW Flex XG switches: [cyan]{planned_switches}[/cyan]")

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import (
            format_10g_validation_report_markdown,
            validate_10g_expansion_readiness,
        )

        console.print("📡 [dim]Discovering STP topology and port counters...[/dim]")
        report = asyncio.run(
            validate_10g_expansion_readiness(
                planned_flex_xg_switches=planned_switches,
                target_speed_mbps=target_speed,
                drops_threshold=drops_threshold,
            )
        )

        status_style = {
            'READY': 'green',
            'READY_WITH_WARNINGS': 'yellow',
            'NOT_READY': 'red',
        }.get(report.readiness, 'white')
        console.print(f"\n📊 Readiness: [{status_style}]{report.readiness}[/]")
        console.print(f"  Switches: [cyan]{report.switches_analyzed}[/cyan]")
        console.print(f"  Inter-switch links: [cyan]{report.inter_switch_links}[/cyan]")
        console.print(f"  10G ports: [cyan]{report.ten_gig_links}[/cyan]")
        console.print(f"  Blocked STP ports: [yellow]{report.blocked_ports_count}[/yellow]")
        console.print(f"  STP changes required: [yellow]{report.stp_changes_required}[/yellow]")

        if report.findings:
            table = Table(title="Validation Findings", show_header=True)
            table.add_column("Severity", style="bold")
            table.add_column("Category", style="cyan")
            table.add_column("Device", style="magenta")
            table.add_column("Port", style="yellow")
            table.add_column("Finding")
            table.add_column("Recommendation", style="dim")

            for finding in report.findings:
                severity_style = 'red' if finding.severity == 'CRITICAL' else 'yellow'
                table.add_row(
                    f'[{severity_style}]{finding.severity}[/]',
                    finding.category,
                    finding.device_name or '',
                    str(finding.port_idx) if finding.port_idx is not None else '',
                    finding.message,
                    finding.recommendation,
                )
            console.print(table)
        else:
            console.print("✅ [bold green]No critical or warning findings detected[/bold green]")

        if output:
            markdown = format_10g_validation_report_markdown(report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(markdown)
            console.print(f"📄 Report saved to [cyan]{output}[/cyan]")

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"❌ [bold red]Error: {e}[/bold red]")
        if debug:
            console.print_exception(show_locals=True)
        raise typer.Exit(1)


def _print_stp_apply_result(result: dict[str, object]) -> None:
    applied = result.get('applied', [])
    failed = result.get('failed', [])
    console.print(str(result.get('message', '')))
    if isinstance(applied, list) and applied:
        table = Table(
            title="Applied Changes" if not result.get('dry_run') else "Planned Changes",
            show_header=True,
        )
        table.add_column("Switch", style="cyan")
        table.add_column("Current", style="red")
        table.add_column("New", style="green")
        table.add_column("Status")
        for item in cast(list[object], applied):
            if not isinstance(item, dict):
                continue
            applied_item = cast(dict[str, object], item)
            table.add_row(
                str(applied_item.get('device_name', '')),
                str(applied_item.get('current_priority', '')),
                str(applied_item.get('new_priority', '')),
                str(applied_item.get('status', '')),
            )
        console.print(table)
    if isinstance(failed, list) and failed:
        failed_items = cast(list[object], failed)
        console.print(f"❌ [bold red]Failed {len(failed_items)} change(s)[/bold red]")
        for item in failed_items:
            if isinstance(item, dict):
                failed_item = cast(dict[str, object], item)
                console.print(
                    f"   • {failed_item.get('device_name', '')}: {failed_item.get('error', '')}"
                )


def _parse_planned_switches(value: str) -> dict[str, int]:
    planned: dict[str, int] = {}
    for raw_part in value.split(','):
        part = raw_part.strip()
        if not part:
            continue
        if ':' in part:
            model, count_text = part.rsplit(':', 1)
            planned[model.strip()] = int(count_text)
        else:
            planned[part] = 1
    if not planned:
        raise typer.BadParameter('At least one planned switch model is required')
    return planned


def _parse_csv_ints(value: str) -> list[int]:
    values: list[int] = []
    for item in value.split(','):
        stripped = item.strip()
        if not stripped:
            continue
        values.append(int(stripped))
    if not values:
        raise typer.BadParameter('At least one integer value is required')
    return values


if __name__ == "__main__":
    app()


# ─── Radio Configuration Commands ────────────────────────────────────────────


@radio_app.command("snapshot")
def radio_snapshot(
    output: str = typer.Option("reports/radio-snapshot.json", "--output", "-o", help="Output file path"),
):
    """📸 Snapshot current radio config for all APs (backup before changes)."""
    import asyncio

    from unifi_mapper.analysis.radio_config import snapshot_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("📸 [bold]Radio Configuration Snapshot[/bold]\n")

    snapshot = asyncio.run(snapshot_radio_config(output_path=output))
    console.print(f"APs captured: [cyan]{len(snapshot['aps'])}[/cyan]")
    console.print(f"Saved to: [green]{output}[/green]")
    console.print(f"\n💡 Use [cyan]unifi-mapper radio restore --snapshot {output}[/cyan] to revert changes")


@radio_app.command("optimize")
def radio_optimize(
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview changes without applying"),
    snapshot: str = typer.Option("reports/radio-snapshot.json", "--snapshot", "-s", help="Auto-snapshot before apply"),
):
    """⚡ Apply recommended radio optimisations (80MHz 5GHz, reduce 2.4GHz power, min RSSI)."""
    import asyncio

    from rich.table import Table

    from unifi_mapper.analysis.radio_config import (
        apply_radio_config,
        build_optimisation_plan,
        snapshot_radio_config,
    )
    from unifi_mapper.core.utils.client import UniFiClient

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("⚡ [bold]Radio Optimisation[/bold]\n")

    async def run():
        async with UniFiClient() as client:
            devices = await client.get_devices()
        return devices

    devices = asyncio.run(run())
    changes = build_optimisation_plan(devices)

    if not changes:
        console.print("[green]No optimisations needed — config already optimal.[/green]")
        return

    # Show plan
    table = Table(title="Optimisation Plan")
    table.add_column("AP", style="cyan")
    table.add_column("Radio")
    table.add_column("Changes")

    device_names = {d["_id"]: d.get("name", "Unknown") for d in devices if "_id" in d}
    for c in changes:
        name = device_names.get(c["device_id"], "Unknown")
        radio = "5GHz" if c["radio"] == "na" else "2.4GHz"
        change_desc = ", ".join(f"{k}={v}" for k, v in c.items() if k not in ("device_id", "radio"))
        table.add_row(name, radio, change_desc)

    console.print(table)

    if dry_run:
        console.print(f"\n[yellow]DRY RUN[/yellow] — {len(changes)} changes planned")
        console.print("Run with [cyan]--apply[/cyan] to execute")
        console.print(f"A snapshot will be saved to [cyan]{snapshot}[/cyan] before applying")
        return

    # Take snapshot before applying
    console.print(f"\n📸 Saving snapshot to [cyan]{snapshot}[/cyan]...")
    asyncio.run(snapshot_radio_config(output_path=snapshot))

    # Apply
    console.print("⚡ Applying changes...")
    results = asyncio.run(apply_radio_config(changes, dry_run=False))

    for r in results:
        status = r["status"]
        icon = "✅" if status == "APPLIED" else "❌"
        console.print(f"  {icon} {r['name']} ({r['radio']}): {status}")

    console.print(f"\n💡 To revert: [cyan]unifi-mapper radio restore --snapshot {snapshot}[/cyan]")


@radio_app.command("restore")
def radio_restore(
    snapshot_path: str = typer.Option("reports/radio-snapshot.json", "--snapshot", "-s", help="Snapshot file to restore from"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview restore without applying"),
):
    """🔄 Restore radio config from a snapshot file."""
    import asyncio

    from unifi_mapper.analysis.radio_config import restore_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("🔄 [bold]Radio Configuration Restore[/bold]\n")
    console.print(f"Snapshot: [cyan]{snapshot_path}[/cyan]\n")

    results = asyncio.run(restore_radio_config(snapshot_path, dry_run=dry_run))

    for r in results:
        status = r["status"]
        if "DRY_RUN" in status:
            icon = "🔍"
        elif "RESTORED" in status:
            icon = "✅"
        else:
            icon = "❌"
        console.print(f"  {icon} {r['name']}: {status}")

    if dry_run:
        console.print(f"\n[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to restore")


# ─── Radio Channel Optimiser Commands ────────────────────────────────────────


@radio_app.command("auto-channel")
def radio_auto_channel(
    band: str = typer.Option("both", "--band", "-b", help="Band to optimise: 5ghz, 2.4ghz, or both"),
    dry_run: bool = typer.Option(True, "--dry-run/--apply", help="Preview changes without applying"),
    report_file: Optional[str] = typer.Option(None, "--report", "-r", help="Write markdown report to file"),
):
    """📶 Auto-optimise channel assignments based on utilization data."""
    import asyncio
    from pathlib import Path

    from rich.table import Table

    from unifi_mapper.analysis.channel_optimiser import (
        analyze_channels,
        format_report_markdown,
        generate_report,
        optimize_24ghz,
        optimize_5ghz,
    )
    from unifi_mapper.analysis.radio_config import apply_radio_config, snapshot_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("📶 [bold]Auto-Channel Optimiser[/bold]\n")

    # Analyze current state
    channel_state = asyncio.run(analyze_channels())
    aps = channel_state["aps"]
    nb = channel_state.get("neighbour_scores", {})

    # Generate recommendations
    rec_5 = optimize_5ghz(aps, neighbour_data=nb.get("5ghz")) if band in ("5ghz", "both") else []
    rec_24 = optimize_24ghz(aps, neighbour_data=nb.get("24ghz")) if band in ("2.4ghz", "both") else []
    console.print(f"📡 Neighbour data: {len(nb.get('5ghz', {}))} 5GHz channels, {len(nb.get('24ghz', {}))} 2.4GHz channels scored")
    report = generate_report(channel_state, rec_5, rec_24)

    # Display table
    if rec_5:
        table5 = Table(title="5GHz Channel Plan")
        table5.add_column("AP", style="cyan")
        table5.add_column("Current")
        table5.add_column("Recommended")
        table5.add_column("Util", justify="right")
        table5.add_column("Action")
        for r in rec_5:
            action = "[yellow]CHANGE[/yellow]" if r["change_needed"] else "[green]keep[/green]"
            table5.add_row(r["name"], f"Ch {r['current_channel']}", f"Ch {r['recommended_channel']}",
                           f"{r['current_utilization']}%", action)
        console.print(table5)
        console.print()

    if rec_24:
        table24 = Table(title="2.4GHz Channel Plan")
        table24.add_column("AP", style="cyan")
        table24.add_column("Current")
        table24.add_column("Recommended")
        table24.add_column("Util", justify="right")
        table24.add_column("Action")
        for r in rec_24:
            action = "[yellow]CHANGE[/yellow]" if r["change_needed"] else "[green]keep[/green]"
            table24.add_row(r["name"], f"Ch {r['current_channel']}", f"Ch {r['recommended_channel']}",
                           f"{r['current_utilization']}%", action)
        console.print(table24)

    # Summary
    changes_5 = [r for r in rec_5 if r["change_needed"]]
    changes_24 = [r for r in rec_24 if r["change_needed"]]
    total = len(changes_5) + len(changes_24)
    console.print(f"\n{'⚡' if total else '✅'} {total} changes needed "
                  f"(5GHz: {len(changes_5)}, 2.4GHz: {len(changes_24)})")

    # Write markdown report
    if report_file:
        md = format_report_markdown(report)
        Path(report_file).parent.mkdir(parents=True, exist_ok=True)
        Path(report_file).write_text(md)
        console.print(f"📄 Report saved to [green]{report_file}[/green]")

    if dry_run or total == 0:
        if total and dry_run:
            console.print("\n[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to execute")
        return

    # Snapshot before applying
    console.print("\n📸 Saving snapshot...")
    asyncio.run(snapshot_radio_config(output_path="reports/radio-pre-autochannel.json"))

    # Build change list
    changes = []
    for r in changes_5:
        changes.append({"device_id": r["device_id"], "radio": "na", "channel": r["recommended_channel"]})
    for r in changes_24:
        changes.append({"device_id": r["device_id"], "radio": "ng", "channel": r["recommended_channel"]})

    # Apply
    console.print("⚡ Applying channel changes...")
    results = asyncio.run(apply_radio_config(changes, dry_run=False))
    for r in results:
        icon = "✅" if r["status"] == "APPLIED" else "❌"
        console.print(f"  {icon} {r['name']} ({r['radio']}): {r['status']}")

    console.print(f"\n💡 To revert: [cyan]unifi-mapper radio restore -s reports/radio-pre-autochannel.json --apply[/cyan]")


@radio_app.command("report")
def radio_report(
    output: str = typer.Option("reports/channel-report.md", "--output", "-o", help="Output markdown file"),
):
    """📄 Generate a channel utilization report (table + markdown)."""
    import asyncio
    from pathlib import Path

    from rich.table import Table

    from unifi_mapper.analysis.channel_optimiser import (
        analyze_channels,
        format_report_markdown,
        generate_report,
        optimize_24ghz,
        optimize_5ghz,
    )

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("📄 [bold]Channel Report[/bold]\n")

    channel_state = asyncio.run(analyze_channels())
    aps = channel_state["aps"]
    rec_5 = optimize_5ghz(aps)
    rec_24 = optimize_24ghz(aps)
    report = generate_report(channel_state, rec_5, rec_24)

    # Display current state table
    table = Table(title="Current Channel Utilization")
    table.add_column("AP", style="cyan")
    table.add_column("2.4GHz Ch")
    table.add_column("2.4GHz Util", justify="right")
    table.add_column("5GHz Ch")
    table.add_column("5GHz Util", justify="right")
    table.add_column("5GHz Width")

    for ap in sorted(aps, key=lambda a: a["name"]):
        r24 = ap["radios"].get("2.4GHz", {})
        r5 = ap["radios"].get("5GHz", {})
        table.add_row(
            ap["name"],
            str(r24.get("channel", "—")),
            f"{r24.get('utilization', 0)}%",
            str(r5.get("channel", "—")),
            f"{r5.get('utilization', 0)}%",
            f"{r5.get('ht', '?')}MHz",
        )

    console.print(table)

    # Write markdown
    md = format_report_markdown(report)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(md)
    console.print(f"\n📄 Markdown report saved to [green]{output}[/green]")
    console.print(f"   Changes needed: 5GHz={report['summary']['changes_5ghz']}, "
                  f"2.4GHz={report['summary']['changes_24ghz']}")


# ─── Link Error Tracking Commands ────────────────────────────────────────────


@analyze_app.command("link-errors")
def analyze_link_errors(
    snapshot: bool = typer.Option(False, "--snapshot", help="Take a baseline snapshot"),
    baseline: str = typer.Option("reports/link-error-baseline.json", "--baseline", "-b", help="Baseline file path"),
    threshold: float = typer.Option(10.0, "--threshold", "-t", help="Error rate threshold (errors/min)"),
):
    """📈 Track link error rates between snapshots to detect active degradation."""
    import asyncio

    from rich.table import Table

    from unifi_mapper.analysis.link_error_tracking import compare_link_errors, snapshot_link_errors

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot:
        console.print("📸 [bold]Link Error Baseline Snapshot[/bold]\n")
        result = asyncio.run(snapshot_link_errors(baseline))
        dev_count = len(result["devices"])
        port_count = sum(len(d["ports"]) for d in result["devices"])
        console.print(f"Captured: {dev_count} devices, {port_count} ports")
        console.print(f"Saved to: [green]{baseline}[/green]")
        console.print("\n💡 Run again without --snapshot to compare against this baseline")
        return

    console.print("📈 [bold]Link Error Rate Analysis[/bold]\n")
    try:
        report = asyncio.run(compare_link_errors(baseline, threshold))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"Baseline: {report['baseline_timestamp']}")
    console.print(f"Elapsed: {report['elapsed_minutes']} minutes")
    console.print(f"Ports with new errors: {report['ports_with_new_errors']}")
    console.print(f"Ports flagged (>{threshold}/min): [{'red' if report['ports_flagged'] else 'green'}]{report['ports_flagged']}[/{'red' if report['ports_flagged'] else 'green'}]\n")

    # Surface devices that rebooted between snapshots — their counter deltas
    # are suppressed from flagging because the reset to 0 makes rates meaningless.
    rebooted = report.get("rebooted_devices", [])
    if rebooted:
        reboot_names = ", ".join(d["name"] for d in rebooted)
        console.print(
            f"[yellow]⚠️  {len(rebooted)} device(s) rebooted since baseline: {reboot_names}[/yellow]"
        )
        console.print("[dim]   Their port deltas are shown but excluded from flagging (counters reset on boot).[/dim]\n")

    if report["all_deltas"]:
        table = Table(title="Error Rate Deltas (top 20)")
        table.add_column("Device", style="cyan")
        table.add_column("Port")
        table.add_column("Errors Δ", justify="right")
        table.add_column("Drops Δ", justify="right")
        table.add_column("Rate/min", justify="right")
        table.add_column("Status")

        for d in report["all_deltas"]:
            rate = d["rate_per_min"]
            if d.get("reboot_detected"):
                status = "[yellow]🔄 REBOOT[/yellow]"
            elif rate > 100:
                status = "[red]🚨 CRITICAL[/red]"
            elif rate >= threshold:
                status = "[yellow]⚠️ WARNING[/yellow]"
            else:
                status = "[green]OK[/green]"
            table.add_row(
                d["device"], d["port_name"],
                str(d["rx_errors_delta"] + d["tx_errors_delta"]),
                str(d["rx_dropped_delta"] + d["tx_dropped_delta"]),
                f"{rate:.1f}", status,
            )
        console.print(table)
    else:
        console.print("[green]✅ No new errors since baseline[/green]")


# ─── Client Roaming Commands ─────────────────────────────────────────────────


@analyze_app.command("roaming")
def analyze_roaming_cmd(
    snapshot: bool = typer.Option(False, "--snapshot", help="Record current client associations"),
    history: str = typer.Option("reports/client-roaming-history.json", "--history", "-h", help="History file path"),
):
    """📡 Analyze client roaming patterns and detect sticky clients."""
    import asyncio

    from rich.table import Table

    from unifi_mapper.analysis.roaming_analysis import analyze_roaming, snapshot_client_associations

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot:
        console.print("📸 [bold]Client Association Snapshot[/bold]\n")
        result = asyncio.run(snapshot_client_associations(history))
        console.print(f"Clients tracked: {result['clients_tracked']}")
        console.print(f"Snapshots stored: {result['snapshots_stored']}")
        console.print(f"History: [green]{history}[/green]")
        console.print("\n💡 Run periodically (every 5 min) to build roaming history")
        return

    console.print("📡 [bold]Client Roaming Analysis[/bold]\n")
    try:
        report = asyncio.run(analyze_roaming(history))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"Snapshots analyzed: {report['snapshots_analyzed']}")
    console.print(f"Time span: {report['time_span']}")
    console.print(f"Clients tracked: {report['clients_tracked']}")
    console.print(f"Roaming clients: {report['roaming_clients']}")
    console.print(f"Sticky clients: {report['sticky_clients']}\n")

    if report["roamers"]:
        table = Table(title="Roaming Clients")
        table.add_column("Client", style="cyan")
        table.add_column("Transitions", justify="right")
        table.add_column("APs Used")
        table.add_column("Avg RSSI", justify="right")

        for r in report["roamers"][:15]:
            table.add_row(r["client"], str(r["transitions"]), ", ".join(r["aps_used"]), str(r["avg_rssi"]))
        console.print(table)

    if report["sticky"]:
        console.print()
        table = Table(title="Sticky Clients (low RSSI, not roaming)")
        table.add_column("Client", style="cyan")
        table.add_column("Stuck On")
        table.add_column("Avg RSSI", justify="right")
        table.add_column("Min RSSI", justify="right")

        for s in report["sticky"]:
            table.add_row(s["client"], s["stuck_on"], str(s["avg_rssi"]), f"[red]{s['min_rssi']}[/red]")
        console.print(table)


# ─── Configuration Drift Commands ────────────────────────────────────────────


@analyze_app.command("config-drift")
def analyze_config_drift(
    snapshot: bool = typer.Option(False, "--snapshot", help="Take a config baseline snapshot"),
    baseline: str = typer.Option("reports/config-baseline.json", "--baseline", "-b", help="Baseline file path"),
):
    """🔍 Detect configuration drift from baseline (catches manual UI changes)."""
    import asyncio

    from rich.table import Table

    from unifi_mapper.analysis.config_drift import detect_drift, snapshot_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot:
        console.print("📸 [bold]Configuration Baseline Snapshot[/bold]\n")
        result = asyncio.run(snapshot_config(baseline))
        console.print(f"Devices captured: {len(result['devices'])}")
        console.print(f"Saved to: [green]{baseline}[/green]")
        console.print("\n💡 Run without --snapshot to detect drift from this baseline")
        return

    console.print("🔍 [bold]Configuration Drift Detection[/bold]\n")
    try:
        report = asyncio.run(detect_drift(baseline))
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"Baseline: {report['baseline_timestamp']}")
    console.print(f"Devices checked: {report['devices_checked']}")
    console.print(f"Drifts detected: [{'red' if report['drifts_detected'] else 'green'}]{report['drifts_detected']}[/{'red' if report['drifts_detected'] else 'green'}]\n")

    if report["drifts"]:
        table = Table(title="Configuration Drifts")
        table.add_column("Device", style="cyan")
        table.add_column("Field")
        table.add_column("Type")
        table.add_column("Details")

        for drift in report["drifts"]:
            dtype = drift["type"]
            style = "[red]" if dtype == "REMOVED" else "[yellow]"
            if dtype == "CHANGED":
                details = f"changed"
            elif dtype == "REMOVED":
                details = "field removed"
            else:
                details = drift.get("details", "")
            table.add_row(drift["device"], drift.get("field", "—"), f"{style}{dtype}[/]", details)
        console.print(table)
    else:
        console.print("[green]✅ No configuration drift detected[/green]")


# ─── Neighbour AP Scan Commands ──────────────────────────────────────────────


@analyze_app.command("neighbours")
def analyze_neighbours(
    ap_name: Optional[str] = typer.Option(None, "--ap", "-a", help="Specific AP to scan (default: all)"),
    cached: bool = typer.Option(False, "--cached", help="DEPRECATED: no-op, data is always fresh"),
):
    """📡 Scan for neighbouring APs and external interference sources."""
    import asyncio

    from rich.table import Table

    from unifi_mapper.analysis.neighbour_scan import scan_neighbours

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if cached:
        console.print("[yellow]⚠️  --cached is deprecated (neighbour data is now always fresh). Flag will be removed in a future release.[/yellow]")

    console.print("📡 [bold]Neighbour AP Scan[/bold]\n")

    report = asyncio.run(scan_neighbours(ap_name=ap_name))

    if not report["aps"]:
        console.print("[yellow]No neighbour data available.[/yellow]")
        return

    for ap_entry in report["aps"]:
        ap_display = ap_entry["ap_name"]
        total = ap_entry["total_neighbours"]
        console.print(f"\n[bold]{ap_display}[/bold] — {total} neighbours")

        # Channel summary
        ch_summary = ap_entry.get("channel_summary", {})
        if ch_summary:
            ch_str = ", ".join(f"ch{ch}:{count}" for ch, count in sorted(ch_summary.items()))
            console.print(f"  Channels: {ch_str}")

        # Strongest neighbours (by signal dBm)
        strongest = ap_entry.get("strongest", [])
        if strongest:
            table = Table(show_header=True, title=f"Strongest Neighbours ({ap_display})")
            table.add_column("SSID")
            table.add_column("Channel", justify="right")
            table.add_column("Signal (dBm)", justify="right")
            table.add_column("BSSID", style="dim")

            for n in strongest[:10]:
                signal = n.get("signal", -100)
                style = "red" if signal > -50 else "yellow" if signal > -70 else "green"
                table.add_row(
                    n.get("essid", "<hidden>") or "<hidden>",
                    str(n.get("channel", "?")),
                    f"[{style}]{signal}[/{style}]",
                    n.get("bssid", ""),
                )
            console.print(table)


# ─── Bandwidth Test Commands ─────────────────────────────────────────────────


@diagnose_app.command("bandwidth")
def diagnose_bandwidth(
    target: str = typer.Argument(..., help="Target IP running iperf3 -s"),
    duration: int = typer.Option(10, "--duration", "-d", help="Test duration in seconds"),
    reverse: bool = typer.Option(False, "--reverse", "-R", help="Test download (target→UDM) instead of upload"),
    bidirectional: bool = typer.Option(False, "--bidir", help="Test both directions"),
    parallel: int = typer.Option(1, "--parallel", "-P", help="Number of parallel streams"),
):
    """⚡ Run iperf3 bandwidth test from UDM to a target device."""
    import asyncio

    from unifi_mapper.analysis.bandwidth_test import run_bandwidth_test

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print("⚡ [bold]Bandwidth Test (iperf3 via SSH)[/bold]\n")
    console.print(f"Target: [cyan]{target}[/cyan]")
    console.print(f"Duration: {duration}s | Streams: {parallel}\n")

    if bidirectional:
        # Upload
        console.print("▶ Upload (UDM → target)...")
        up = asyncio.run(run_bandwidth_test(target, duration, reverse=False, parallel=parallel))
        if up["status"] == "OK":
            console.print(f"  [green]{up['throughput_mbps']} Mbps[/green] ({up['throughput_gbps']} Gbps)")
            if "retransmits" in up:
                console.print(f"  Retransmits: {up['retransmits']}")
        else:
            console.print(f"  [red]FAILED: {up.get('error', 'unknown')}[/red]")

        # Download
        console.print("\n▼ Download (target → UDM)...")
        down = asyncio.run(run_bandwidth_test(target, duration, reverse=True, parallel=parallel))
        if down["status"] == "OK":
            console.print(f"  [green]{down['throughput_mbps']} Mbps[/green] ({down['throughput_gbps']} Gbps)")
            if "retransmits" in down:
                console.print(f"  Retransmits: {down['retransmits']}")
        else:
            console.print(f"  [red]FAILED: {down.get('error', 'unknown')}[/red]")
    else:
        direction = "download" if reverse else "upload"
        console.print(f"{'▼' if reverse else '▶'} Testing {direction}...")
        result = asyncio.run(run_bandwidth_test(target, duration, reverse=reverse, parallel=parallel))

        if result["status"] == "OK":
            console.print(f"\n  [green]{result['throughput_mbps']} Mbps[/green] ({result['throughput_gbps']} Gbps)")
            console.print(f"  Direction: {result['direction']}")
            if "retransmits" in result:
                console.print(f"  Retransmits: {result['retransmits']}")
            if "bytes_transferred" in result:
                gb = result["bytes_transferred"] / 1_073_741_824
                console.print(f"  Transferred: {gb:.2f} GB")
        else:
            console.print(f"\n  [red]FAILED: {result.get('error', 'unknown')}[/red]")
