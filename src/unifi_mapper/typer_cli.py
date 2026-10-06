"""Typer-based CLI for UniFi Network Mapper with automatic completions."""

import json
import logging
import typer
from .cli import get_default_config_path, load_env_from_config
from .inventory_cli import inventory_app
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.table import Table
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Coroutine,
    Iterator,
    NoReturn,
    Optional,
    cast,
)


if TYPE_CHECKING:
    from .core.utils.client import SharedControllerClient


# Setup rich console
console = Console()
# Errors and progress go to stderr so `--json` output on stdout stays parseable.
err_console = Console(stderr=True)
JsonDict = dict[str, Any]


# Global state for config path
class State:
    """Global CLI state."""

    config_path: Optional[Path] = None
    debug: bool = False
    # Root discover shortcuts given before the ``discover`` subcommand (issue 027). The root
    # callback clears them on every invocation and ``discover`` takes them, so they never
    # leak into a later in-process invocation.
    root_dry_run: bool = False
    root_connected_devices: bool = False
    root_verify_updates: bool = False
    # Set once the gateway SSH notice has been printed; the root callback clears it on every
    # invocation, so it prints once per command even when a command opens SSH twice.
    ssh_notice_shown: bool = False

    def take_root_shortcuts(self) -> tuple[bool, bool, bool]:
        """Return and clear the root ``--dry-run``, ``--connected-devices``, ``--verify-updates``.

        Returns:
            The three flags as the root callback stored them for ``discover``.
        """
        taken = (self.root_dry_run, self.root_connected_devices, self.root_verify_updates)
        self.root_dry_run = self.root_connected_devices = self.root_verify_updates = False
        return taken


state = State()

# Before a subcommand, Typer parses each level on its own, so a root flag never reaches the
# subcommand. --apply is refused before any subcommand (code-review F11); the other discover
# shortcuts are passed on to discover and refused before anything else (issue 027).
_ROOT_APPLY_HINT = (
    '--apply must follow the subcommand and its arguments '
    '(e.g. unifi-mapper discover --apply, unifi-mapper ports refresh --apply)'
)
_ROOT_SHORTCUT_HINTS = {
    '--dry-run': (
        '--dry-run before a subcommand only reaches discover: '
        'read-only subcommands need no flag, '
        'and those with their own --dry-run take it after their arguments '
        '(e.g. unifi-mapper ports refresh --dry-run)'
    ),
    '--connected-devices': (
        '--connected-devices only applies to discover (unifi-mapper discover --connected-devices)'
    ),
    '--verify-updates': (
        '--verify-updates only applies to discover (unifi-mapper discover --verify-updates)'
    ),
}


def setup_logging(debug: bool = False):
    """Configure rich logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(message)s',
        datefmt='[%X]',
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


# Create main Typer app
app = typer.Typer(
    name='unifi-mapper',
    help='🚀 Enterprise UniFi Network Automation Platform',
    epilog='Built with systematic debugging and AI-assisted development 🤖',
    rich_markup_mode='rich',
    invoke_without_command=True,
    # Typer < 0.23 prints each frame's locals in a traceback; a config holds credentials.
    pretty_exceptions_show_locals=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        Optional[Path],
        typer.Option(
            '--config',
            '-c',
            help='📁 Path to .env configuration file',
            envvar='UNIFI_CONFIG',
        ),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option(
            '--debug',
            help='🐛 Enable debug logging',
        ),
    ] = False,
    # Top-level shortcuts for discover command
    connected_devices: Annotated[
        bool,
        typer.Option(
            '--connected-devices',
            help='📱 Include non-UniFi connected devices (runs discover)',
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run',
            help='🔍 Preview port names without writing (runs discover; the default)',
        ),
    ] = False,
    apply: Annotated[
        bool,
        typer.Option(
            '--apply',
            help='⚡ Write port names (runs discover); after a subcommand use discover --apply',
        ),
    ] = False,
    verify_updates: Annotated[
        bool,
        typer.Option(
            '--verify-updates',
            help='✅ Verify port name updates (runs discover)',
        ),
    ] = False,
):
    """🚀 Enterprise UniFi Network Automation Platform.

    Global options apply to all commands. Use --connected-devices, --verify-updates,
    --dry-run or --apply as shortcuts to run the discover command. Discover previews
    by default; only --apply writes port names to the controller. Before the discover
    subcommand, --dry-run, --connected-devices and --verify-updates are passed on to it.
    Before any other subcommand they exit 2, and so does --apply before any subcommand:
    put a subcommand's own flags after it (``discover --apply``).
    """
    from .core.utils.logging import replace_default_loguru_handler

    replace_default_loguru_handler()  # before anything logs: loguru's default has diagnose on
    # Set global state
    state.config_path = config if config else get_default_config_path()
    state.debug = debug
    state.take_root_shortcuts()  # clear whatever an earlier in-process invocation left
    state.ssh_notice_shown = False

    if debug:
        setup_logging(debug=True)

    if apply and dry_run:
        _fail('choose --apply or --dry-run', code=2)
    subcommand = ctx.invoked_subcommand
    if apply and subcommand is not None:
        # Refuse rather than preview (or run another command) after a write request.
        _fail(_ROOT_APPLY_HINT, code=2)
    if subcommand is not None and subcommand != 'discover':
        given = {
            '--dry-run': dry_run,
            '--connected-devices': connected_devices,
            '--verify-updates': verify_updates,
        }
        for flag, on in given.items():
            if on:
                _fail(_ROOT_SHORTCUT_HINTS[flag], code=2)
    if subcommand == 'discover':
        state.root_dry_run = dry_run
        state.root_connected_devices = connected_devices
        state.root_verify_updates = verify_updates

    # If no subcommand but discover-related flags provided, run discover
    if ctx.invoked_subcommand is None:
        if connected_devices or dry_run or verify_updates or apply:
            # Run discover with the provided flags (a preview unless --apply)
            discover(
                output=None,
                diagram=None,
                format='png',
                apply=apply,
                verify_updates=verify_updates,
                connected_devices=connected_devices,
            )
        else:
            # Show help if no command and no flags
            console.print(ctx.get_help())


# Create subcommands
find_app = typer.Typer(
    help='🔍 Device and resource discovery', pretty_exceptions_show_locals=False
)
analyze_app = typer.Typer(
    help='📊 Network analysis and diagnostics', pretty_exceptions_show_locals=False
)
diagnose_app = typer.Typer(
    help='🏥 Network health and troubleshooting', pretty_exceptions_show_locals=False
)
stp_app = typer.Typer(
    help='🌳 STP topology analysis and optimization', pretty_exceptions_show_locals=False
)
radio_app = typer.Typer(
    help='📶 Wi-Fi radio configuration management', pretty_exceptions_show_locals=False
)
ports_app = typer.Typer(
    help='🔌 Switch port labels and read-only port diagnostics',
    pretty_exceptions_show_locals=False,
)
controller_app = typer.Typer(
    help='🗂️ Read-only controller config objects and change history',
    pretty_exceptions_show_locals=False,
)
backup_app = typer.Typer(
    help='💾 Offline checks of downloaded config backups', pretty_exceptions_show_locals=False
)
gateway_app = typer.Typer(
    help="🛰️ Live probes run on the gateway over SSH (the gateway's host key is not verified)",
    pretty_exceptions_show_locals=False,
)
vlan_traffic_app = typer.Typer(
    help='📊 Per-VLAN traffic: sample the gateway over SSH into a local store, then report',
    pretty_exceptions_show_locals=False,
)

app.add_typer(find_app, name='find')
app.add_typer(analyze_app, name='analyze')
app.add_typer(diagnose_app, name='diagnose')
app.add_typer(inventory_app, name='inventory')
app.add_typer(stp_app, name='stp')
app.add_typer(radio_app, name='radio')
app.add_typer(ports_app, name='ports')
app.add_typer(controller_app, name='controller')
app.add_typer(backup_app, name='backup')
app.add_typer(gateway_app, name='gateway')
app.add_typer(vlan_traffic_app, name='vlan-traffic')


@app.command()
def discover(
    output: Annotated[
        Optional[Path], typer.Option('--output', '-o', help='📄 Output path for report')
    ] = None,
    diagram: Annotated[
        Optional[Path], typer.Option('--diagram', '-d', help='🖼️ Output path for diagram')
    ] = None,
    format: Annotated[
        str, typer.Option('--format', help='🎨 Diagram format (png, svg, html, mermaid, dot)')
    ] = 'png',
    apply: Annotated[
        bool,
        typer.Option(
            '--apply/--dry-run',
            help='⚡ Write port names to the controller (default: preview only)',
        ),
    ] = False,
    verify_updates: Annotated[
        bool, typer.Option('--verify-updates', help='✅ Verify that port name updates persist')
    ] = False,
    connected_devices: Annotated[
        bool, typer.Option('--connected-devices', help='📱 Include non-UniFi connected devices')
    ] = False,
):
    """🔍 Discover network topology and propose port names with LLDP intelligence.

    Previews by default: the report and diagram are written locally, but no port
    name reaches the controller unless --apply is given. A root --dry-run,
    --connected-devices or --verify-updates given before ``discover`` is passed on to
    it, and a root --dry-run with ``discover --apply`` exits 2.
    """
    root_dry_run, root_connected_devices, root_verify_updates = state.take_root_shortcuts()
    if root_dry_run and apply:
        _fail('choose --apply or --dry-run (a root --dry-run was given before discover)', code=2)
    connected_devices = connected_devices or root_connected_devices
    verify_updates = verify_updates or root_verify_updates

    # Use global state
    config = state.config_path
    debug = state.debug
    dry_run = not apply

    if not state.debug:
        setup_logging(debug=False)

    if debug:
        console.print('🐛 [bold yellow]Debug logging enabled[/bold yellow]')

    if dry_run:
        console.print('🔍 [bold cyan]Preview mode - no port names will be written[/bold cyan]')

    if verify_updates:
        console.print(
            '🧠 [bold green]Using Smart Port Mapping with device-aware capabilities[/bold green]'
        )

    try:
        # Load configuration
        from .config import UnifiConfig

        console.print(f'📁 Config: [cyan]{config}[/cyan]')
        load_env_from_config(str(config))
        # Re-read the same file: a stray ./.env must never override --config.
        unifi_config = UnifiConfig.from_env(str(config))

        # Set default paths
        output_path = output or Path.cwd() / 'reports' / 'port_mapping_report.md'
        diagram_path = diagram or Path.cwd() / 'diagrams' / f'network_diagram.{format}'

        # Ensure directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        diagram_path.parent.mkdir(parents=True, exist_ok=True)

        console.print(f'📄 Output: [cyan]{output_path}[/cyan]')
        console.print(f'🖼️ Diagram: [cyan]{diagram_path}[/cyan]')

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
            console.print('\n' + smart_report)

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

        console.print('✅ [bold green]Discovery completed successfully![/bold green]')
        console.print(
            f'📊 Devices: [cyan]{len(devices)}[/cyan], Connections: [cyan]{len(connections)}[/cyan]'
        )
        if dry_run:
            console.print('[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to write')

    except KeyboardInterrupt:
        console.print('\n⚠️ [bold yellow]Operation cancelled by user[/bold yellow]')
        raise typer.Exit(1)
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@app.command()
def install_completions(
    shell: str = typer.Argument(..., help='Shell to install completions for (bash/zsh/fish/all)'),
    force: bool = typer.Option(False, '--force', help='🔄 Overwrite existing completion files'),
):
    """💻 Install shell completions (automatic via Typer).

    Note: You can also use the built-in Typer completion:
    unifi-mapper --install-completion
    """
    if shell.lower() not in ['bash', 'zsh', 'fish', 'all']:
        console.print(f'❌ [bold red]Unsupported shell: {shell}[/bold red]')
        console.print('Supported shells: [cyan]bash, zsh, fish, all[/cyan]')
        console.print("\n💡 [bold blue]Alternative - Use Typer's built-in completion:[/bold blue]")
        console.print('   [cyan]unifi-mapper --install-completion[/cyan]')
        raise typer.Exit(1)

    console.print(f'🔧 Installing [bold]{shell}[/bold] completions...')

    # Use the original manual completion system for compatibility
    try:
        from .completions import install_completions as manual_install

        success = manual_install(shell, force)

        if success:
            console.print('✅ [bold green]Manual completions installed successfully![/bold green]')
        else:
            console.print('❌ [bold red]Manual completion installation failed[/bold red]')
            console.print("\n💡 [bold blue]Try Typer's automatic completion instead:[/bold blue]")
            console.print('   [cyan]unifi-mapper --install-completion[/cyan]')

    except Exception as e:
        console.print(f'❌ [bold red]Completion installation failed: {_error_text(e)}[/bold red]')
        console.print("\n💡 [bold blue]Alternative - Use Typer's built-in completion:[/bold blue]")
        console.print('   [cyan]unifi-mapper --install-completion[/cyan]')
        console.print('   [cyan]unifi-mapper --show-completion[/cyan]')

    console.print('\n📝 [bold]To enable completions:[/bold]')
    console.print('  🐚 Bash: [dim]source ~/.bashrc[/dim]')
    console.print('  🐚 Zsh: [dim]source ~/.zshrc[/dim]')
    console.print('  🐚 Fish: [dim]Automatic on restart[/dim]')
    console.print("\n🎯 [bold blue]Or use Typer's automatic completion:[/bold blue]")
    console.print('   [cyan]unifi-mapper --install-completion[/cyan]')


@find_app.command('device')
def find_device(
    query: str = typer.Argument(..., help='🔍 Device name, IP, or MAC to search for'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🔍 Find device by name, IP, or MAC address.

    Searches UniFi devices first, then connected clients. Exits 1 when nothing
    matches. Read-only.
    """
    from .discovery.find_device import find_device as run_find_device

    device = _run_analysis(lambda: run_find_device(identifier=query))
    if as_json:
        _emit_json(device.model_dump(mode='json'))
        return
    table = Table(title=f'Device matching {escape(query)}', show_header=False)
    table.add_column('Field', style='cyan')
    table.add_column('Value')
    for field, value in device.model_dump().items():
        if value is not None:
            table.add_row(field, escape(str(value)))
    console.print(table)


@analyze_app.command('link-quality')
def analyze_link_quality(
    device: Optional[str] = typer.Option(None, '--device', help='🖥️ Specific device to analyze'),
    include_healthy: bool = typer.Option(
        False, '--include-healthy', help='Also list ports with a health score of 90 or more'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📊 Analyze port statistics and error rates.

    Scores every switch port 0-100 from its error, drop and collision counters and
    lists the degraded and critical ones, worst first. --device takes a device _id
    or MAC. Read-only.
    """
    from .analysis.link_quality import analyze_link_quality as run_link_quality

    report = _run_analysis(
        lambda: run_link_quality(device_id=device, include_healthy=include_healthy)
    )
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('📊 [bold]Link Quality Analysis[/bold]')
    console.print(
        f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]  '
        f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]  '
        f'Healthy: [green]{report.healthy_ports}[/green]  '
        f'Degraded: [yellow]{report.degraded_ports}[/yellow]  '
        f'Critical: [red]{report.critical_ports}[/red]'
    )
    health_style = {'CRITICAL': 'red', 'DEGRADED': 'yellow'}.get(report.overall_health, 'green')
    console.print(f'Overall: [{health_style}]{escape(report.overall_health)}[/]')
    if report.port_metrics:
        table = Table(title='Port Link Quality (worst first)', show_header=True)
        table.add_column('Device', style='cyan')
        table.add_column('Port', style='yellow')
        table.add_column('Speed')
        table.add_column('Score', style='bold')
        table.add_column('RX/TX errors')
        table.add_column('RX/TX dropped')
        table.add_column('Issues', style='dim')
        for m in report.port_metrics:
            score_style = 'green' if m.health_score >= 90 else 'yellow'
            if m.health_score < 70:
                score_style = 'red'
            table.add_row(
                escape(m.device_name),
                f'{m.port_idx} {escape(m.port_name)}',
                escape(m.link_speed),
                f'[{score_style}]{m.health_score}[/]',
                f'{m.rx_errors}/{m.tx_errors}',
                f'{m.rx_dropped}/{m.tx_dropped}',
                escape(', '.join(m.issues)) or '—',
            )
        console.print(table)
    else:
        console.print('✅ No degraded or critical ports.')
    for issue in report.top_issues:
        console.print(f'  • {escape(issue)}')


@analyze_app.command('port-profiles')
def analyze_port_profiles():
    """🔌 Validate port profile safety for STP Edge, BPDU Guard, and uplinks.

    For usage and speed forcing see `analyze port-profile-usage`.
    """
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔌 [bold]Port Profile Validation[/bold]')

    try:
        load_env_from_config(str(config))

        from .analysis.port_profile_validation import validate_port_profiles

        report = asyncio.run(validate_port_profiles())
        console.print(f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]')
        console.print(f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='Port Profile Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Category', style='cyan')
            table.add_column('Device', style='magenta')
            table.add_column('Port', style='yellow')
            table.add_column('Profile')
            table.add_column('Finding')

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
            console.print('✅ [bold green]No port profile findings detected[/bold green]')

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('lag-candidates')
def analyze_lag_candidates(
    min_links: int = typer.Option(2, '--min-links', help='Minimum parallel links', min=2),
):
    """🔗 Find parallel links that may be LACP candidates."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔗 [bold]LAG Candidate Finder[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.lag_monitoring import find_lag_candidates

        report = asyncio.run(find_lag_candidates(min_links=min_links))
        console.print(f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]')
        console.print(f'Candidates: [yellow]{report.candidate_count}[/yellow]')

        if report.candidates:
            table = Table(title='LAG Candidates', show_header=True)
            table.add_column('Device A', style='cyan')
            table.add_column('Ports A', style='yellow')
            table.add_column('Device B', style='magenta')
            table.add_column('Links')
            table.add_column('Capacity')
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
            console.print('No LAG candidates detected.')
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('mtu')
def analyze_mtu():
    """📏 Audit MTU consistency across inter-switch links."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('📏 [bold]MTU Consistency Audit[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.mtu_audit import audit_mtu_consistency

        report = asyncio.run(audit_mtu_consistency())
        console.print(f'Links analyzed: [cyan]{report.links_analyzed}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')
        if report.findings:
            table = Table(title='MTU Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Link', style='cyan')
            table.add_column('MTU')
            table.add_column('Finding')
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
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('radio')
def analyze_radio():
    """📶 Analyze Wi-Fi radio channel and transmit power optimisation."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('📶 [bold]Radio Optimisation Analysis[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.radio_optimization import analyze_radio_optimization

        report = asyncio.run(analyze_radio_optimization())
        console.print(f'APs analyzed: [cyan]{report.aps_analyzed}[/cyan]')
        console.print(f'Radios analyzed: [cyan]{report.radios_analyzed}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')
        if report.findings:
            table = Table(title='Radio Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Category', style='cyan')
            table.add_column('AP', style='magenta')
            table.add_column('Band')
            table.add_column('Channel')
            table.add_column('Finding')
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
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('sfp')
def analyze_sfp():
    """🔦 Audit SFP/SFP+ transceiver diagnostics."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔦 [bold]SFP Diagnostics[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.sfp_diagnostics import audit_sfp_diagnostics

        report = asyncio.run(audit_sfp_diagnostics())
        console.print(f'SFP ports analyzed: [cyan]{report.ports_analyzed}[/cyan]')
        console.print(f'Modules found: [cyan]{report.modules_found}[/cyan]')
        console.print(f'Diagnostics available: [cyan]{report.diagnostics_available}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.modules:
            table = Table(title='SFP Modules', show_header=True)
            table.add_column('Device', style='cyan')
            table.add_column('Port', style='yellow')
            table.add_column('Vendor')
            table.add_column('Part')
            table.add_column('Temp C')
            table.add_column('Tx dBm')
            table.add_column('Rx dBm')
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
            findings_table = Table(title='SFP Findings', show_header=True)
            findings_table.add_column('Severity', style='bold')
            findings_table.add_column('Category', style='cyan')
            findings_table.add_column('Device', style='magenta')
            findings_table.add_column('Port', style='yellow')
            findings_table.add_column('Finding')
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
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('vlan-coverage')
def analyze_vlan_coverage(
    required_vlans: str = typer.Option(
        ...,
        '--required-vlans',
        help='Comma-separated VLAN IDs required on trunk/planned uplink ports',
    ),
    planned_uplink: list[str] = typer.Option(
        [],
        '--planned-uplink',
        help='Planned uplink target name/model to treat as critical',
    ),
):
    """🔀 Audit VLAN coverage on trunk and planned uplink ports."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔀 [bold]VLAN Coverage Audit[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.vlan_coverage import audit_vlan_coverage

        vlans = _parse_csv_ints(required_vlans)
        report = asyncio.run(audit_vlan_coverage(vlans, planned_uplinks=planned_uplink))
        console.print(f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]')
        console.print(f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]')
        console.print(
            f'Required VLANs: [cyan]{", ".join(str(v) for v in report.required_vlans)}[/cyan]'
        )
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='VLAN Coverage Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Device', style='cyan')
            table.add_column('Port', style='yellow')
            table.add_column('Missing VLANs')
            table.add_column('Finding')
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
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('uplink-transparency')
def analyze_uplink_transparency(
    mgmt_vlan: int = typer.Option(
        None,
        '--mgmt-vlan',
        help='Management VLAN ID (inferred from device IPs when omitted)',
    ),
    stale_after: int = typer.Option(
        1800,
        '--stale-after',
        help="Seconds after which a non-informing device's port data is treated as unverifiable",
    ),
):
    """🚧 Check that each switch's elected uplink can actually carry tagged VLANs."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('🚧 [bold]Uplink VLAN Transparency Audit[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.uplink_transparency import audit_uplink_transparency

        report = asyncio.run(
            audit_uplink_transparency(mgmt_vlan=mgmt_vlan, stale_after_seconds=stale_after)
        )
        console.print(f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]')
        console.print(f'Uplinks analyzed: [cyan]{report.uplinks_analyzed}[/cyan]')
        console.print(
            f'Tagged VLANs: [cyan]{", ".join(str(v) for v in report.tagged_vlans) or "none"}[/cyan]'
        )
        console.print(f'Management VLAN: [cyan]{report.management_vlan or "unknown"}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='Uplink VLAN Transparency Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Device', style='cyan')
            table.add_column('Uplink', style='yellow')
            table.add_column('Profile')
            table.add_column('Severed VLANs', style='red')
            table.add_column('Fresh')
            for finding in report.findings:
                if not finding.topology_verifiable:
                    freshness = 'UNVERIFIABLE'
                elif finding.device_informing:
                    freshness = 'yes'
                else:
                    freshness = 'STALE'
                table.add_row(
                    finding.severity,
                    finding.device,
                    f'p{finding.uplink_port}',
                    finding.profile_name or '—',
                    ', '.join(str(vlan) for vlan in finding.severed_vlans) or '—',
                    freshness,
                )
            console.print(table)
            for finding in report.findings:
                console.print(
                    f'\n[bold]{finding.device} p{finding.uplink_port}[/bold]: {finding.message}'
                )
                console.print(f'  → {finding.recommendation}')
        else:
            console.print("✅ Every elected uplink carries the site's tagged VLANs.")

        if not report.validation_passed:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('power-budget')
def analyze_power_budget(
    warn_pct: float = typer.Option(
        80.0,
        '--warn-pct',
        help='Flag devices whose estimated load exceeds this % of supply ceiling',
    ),
    base_watts: float = typer.Option(
        None,
        '--base-watts',
        help='Override assumed base draw in watts (default: per-model published estimate)',
    ),
):
    """🔌 Audit switch INPUT power headroom (distinct from PoE output budget)."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔌 [bold]Device Input Power Budget Audit[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.power_budget import audit_power_budget

        report = asyncio.run(audit_power_budget(warn_pct=warn_pct, base_watts=base_watts))
        console.print(f'Switches analyzed: [cyan]{report.devices_analyzed}[/cyan]')
        if report.skipped_not_informing:
            console.print(
                f'Skipped (not informing): [yellow]{report.skipped_not_informing}[/yellow]'
            )
        if report.unknown_models:
            console.print(
                f'Models without published power data: [dim]{", ".join(report.unknown_models)}[/dim]'
            )
        if report.models_without_supply_rating:
            console.print(
                'Models with no published SUPPLY rating (not judged): '
                f'[dim]{", ".join(report.models_without_supply_rating)}[/dim]'
            )
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='Input Power Budget Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Device', style='cyan')
            table.add_column('Model')
            table.add_column('Ports', style='yellow')
            table.add_column('Est. load')
            table.add_column('Ceiling')
            table.add_column('% used', style='red')
            for f in report.findings:
                table.add_row(
                    f.severity,
                    f.device,
                    f.model,
                    str(f.active_ports),
                    f'{f.estimated_load_watts:.1f}W',
                    f'{f.dc_supply_watts:.1f}W' if f.dc_supply_watts else '—',
                    f'{f.dc_utilisation_pct:.0f}%' if f.dc_utilisation_pct else '—',
                )
            console.print(table)
            for f in report.findings:
                console.print(f'\n[bold]{f.device}[/bold]: {f.message}')
                console.print(f'  → {f.recommendation}')
                console.print(f'  [dim]spec: {f.spec_source}[/dim]')
                console.print(f'  [dim]ports: {", ".join(f.port_detail)}[/dim]')
        else:
            console.print('✅ No switch is near its published input power ceiling.')

        console.print(f'\n[dim]{report.estimate_caveat}[/dim]')
        if not report.validation_passed:
            raise typer.Exit(2)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@analyze_app.command('link-speeds')
def analyze_link_speeds(
    switch: Optional[str] = typer.Option(
        None, '--switch', '-s', help='Audit only this switch (name, MAC or IP)'
    ),
    include_ok: bool = typer.Option(
        False, '--include-ok', help='Also list ports with unknown capability and healthy ports'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🚦 Find ports below their capability or forced into a speed trap, fleet-wide.

    Flags half duplex, forced-speed ports that are down or linked at another rate,
    and autonegotiated ports below the Integration API's maxSpeedMbps (for example a
    10G NAS linked at 5G). The raw speed_caps value is never decoded. Exits 2 when a
    CRITICAL or HIGH finding exists. For usage and speed forcing see
    `analyze port-profile-usage`; for one port in depth see `ports inspect`. Read-only.
    """
    from .analysis.link_speed_audit import MAX_LIMIT, collect_link_speed_audit

    with _diagnostic_errors(), _readonly_client() as (client, site):
        report = collect_link_speed_audit(
            client, site, switch=switch, include_ok=include_ok, limit=MAX_LIMIT
        )
    if as_json:
        _emit_json(report.model_dump(mode='json'))
    else:
        _render_link_speed_audit(report)
    if not report.validation_passed:
        raise typer.Exit(2)


def _render_link_speed_audit(report: Any) -> None:
    """Print a link-speed audit as tables."""
    console.print('🚦 [bold]Link Speed Audit[/bold]')
    console.print(
        f'Switches analyzed: [cyan]{report.switches_analyzed}[/cyan]  '
        f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]  '
        f'Findings: [yellow]{report.findings_total}[/yellow]'
    )
    integration = report.integration
    note = f' ({escape(integration.reason)})' if integration.reason else ''
    console.print(f'Integration API: {integration.status}{note}')
    for warning in report.data_freshness_warnings:
        console.print(f'[yellow]⚠ {escape(warning)}[/yellow]')
    if report.findings:
        table = Table(title='Link Speed Findings', show_header=True)
        table.add_column('Severity', style='bold')
        table.add_column('Code', style='cyan')
        table.add_column('Switch', style='magenta')
        table.add_column('Port', style='yellow')
        table.add_column('Profile')
        table.add_column('Negotiated')
        table.add_column('Max')
        table.add_column('Source', style='dim')
        for f in report.findings:
            style = {'CRITICAL': 'red', 'HIGH': 'red', 'WARNING': 'yellow'}.get(f.severity, 'blue')
            table.add_row(
                f'[{style}]{f.severity}[/]',
                f.code,
                escape(str(f.switch)),
                str(f.port_idx),
                escape(str(f.profile_name or '—')),
                f'{f.negotiated_mbps} Mbps' if f.negotiated_mbps else '—',
                f'{f.local_max_mbps} Mbps' if f.local_max_mbps else '—',
                f.capability_source,
            )
        console.print(table)
        for f in report.findings:
            if f.severity == 'OK':
                continue
            console.print(
                f'\n[bold]{escape(str(f.switch))} port {f.port_idx}[/bold]: {escape(f.message)}'
            )
            if f.recommendation:
                console.print(f'  → {escape(f.recommendation)}')
    else:
        console.print('✅ No port below its capability or forced into a speed trap.')
    if report.truncated:
        console.print(f'[dim]{len(report.findings)} of {report.findings_total} shown.[/dim]')
    for error in report.errors:
        err_console.print(f'[yellow]⚠ {escape(error.section)}: {escape(error.error)}[/yellow]')


@analyze_app.command('port-profile-usage')
def analyze_port_profile_usage(
    profile: Optional[str] = typer.Option(
        None, '--profile', help='Report only this port profile (exact name or _id)'
    ),
    hide_unused: bool = typer.Option(False, '--hide-unused', help='Hide profiles no port uses'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🧩 Where each port profile is used, and which profiles are traps.

    Lists every profile with the ports it is the effective profile of (an override
    wins over the port table), whether it forces a speed, its native network and
    forward mode. Flags forced-speed profiles, overrides that shadow their profile,
    ports referencing a deleted profile, and duplicate or unused profiles. Exits 2
    when a port references a missing profile. For STP edge/BPDU safety see
    `analyze port-profiles`; to compare two profiles key by key see
    `ports profile-diff`; for how each port linked see `analyze link-speeds`. Read-only.
    """
    from .analysis.port_profile_usage import MAX_LIMIT, collect_port_profile_usage

    with _diagnostic_errors(), _readonly_client() as (client, site):
        report = collect_port_profile_usage(
            client, site, profile=profile, include_unused=not hide_unused, limit=MAX_LIMIT
        )
    if as_json:
        _emit_json(report.model_dump(mode='json'))
    else:
        _render_port_profile_usage(report)
    if not report.validation_passed:
        raise typer.Exit(2)


def _render_port_profile_usage(report: Any) -> None:
    """Print a port-profile usage audit as tables."""
    console.print('🧩 [bold]Port Profile Usage[/bold]')
    console.print(
        f'Profiles: [cyan]{report.profiles_total}[/cyan]  '
        f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]  '
        f'Findings: [yellow]{report.findings_total}[/yellow]'
    )
    if report.profiles:
        table = Table(title='Port Profiles', show_header=True)
        table.add_column('Profile', style='cyan')
        table.add_column('Ports', style='yellow')
        table.add_column('Speed')
        table.add_column('Native network')
        table.add_column('Forward')
        table.add_column('PoE', style='dim')
        for p in report.profiles:
            speed = f'forced {p.forced_speed_mbps} Mbps' if p.forces_speed else 'auto'
            native = (
                f'{p.native_network_name} (VLAN {p.native_vlan})'
                if p.native_network_name
                else (p.native_network_id or '—')
            )
            table.add_row(
                escape(str(p.name or p.id)),
                f'{p.port_count}{"+" if p.ports_truncated else ""}',
                speed,
                escape(str(native)),
                escape(str(p.forward or '—')),
                escape(str(p.poe_mode or '—')),
            )
        console.print(table)
    if report.findings:
        table = Table(title='Port Profile Findings', show_header=True)
        table.add_column('Severity', style='bold')
        table.add_column('Code', style='cyan')
        table.add_column('Finding')
        for f in report.findings:
            style = {'HIGH': 'red', 'WARNING': 'yellow'}.get(f.severity, 'blue')
            table.add_row(f'[{style}]{f.severity}[/]', f.code, escape(f.message))
        console.print(table)
    else:
        console.print('✅ No port profile usage findings.')
    if report.truncated:
        console.print(
            f'[dim]{len(report.profiles)} of {report.profiles_total} profiles shown.[/dim]'
        )
    for error in report.errors:
        err_console.print(f'[yellow]⚠ {escape(error.section)}: {escape(error.error)}[/yellow]')


def _new_shared_client() -> 'SharedControllerClient':
    """Build the read-only shared controller client one command borrows (``_guarded``)."""
    from .core.utils.client import SharedControllerClient

    return SharedControllerClient()


# What ``_guarded`` installs; tests replace it to drive the real guard over a mock transport.
_shared_client_factory: Callable[[], 'SharedControllerClient'] = _new_shared_client


async def _guarded[T](load: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run ``load()`` with a read-only ``SharedControllerClient`` installed, then close it.

    Every ``UniFiClient()`` the command opens without explicit credentials borrows the
    holder, so its requests go through ``ReadOnlyAsyncTransport``, as under the MCP server:
    a write is refused before it leaves the host. One login serves the whole command.
    """
    from .core.utils.client import use_shared_controller_client

    shared = _shared_client_factory()
    try:
        with use_shared_controller_client(shared):
            return await load()
    finally:
        await shared.aclose()


def _run_analysis[T](load: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Load the config, run one async read-only analysis and return its report.

    The analysis runs behind the read-only transport (``_guarded``). A domain ``ToolError``
    (or any other failure) prints its message in red on stderr and exits 1, so ``--json``
    output on stdout stays parseable.
    """
    import asyncio
    from .core.utils.errors import ToolError
    from .core.utils.redact import redact_text

    load_env_from_config(str(state.config_path or get_default_config_path()))
    try:
        return asyncio.run(_guarded(load))
    except ToolError as e:
        _fail(e.message)
    except Exception as e:  # noqa: BLE001 - every failure ends the command cleanly
        if state.debug:
            _print_debug_traceback(err_console)
        _fail(f'Error: {redact_text(e)}')


def _status_cell(status: str) -> str:
    """Colour an OK/WARNING/CRITICAL status for a Rich table."""
    style = {'CRITICAL': 'red', 'WARNING': 'yellow', 'OK': 'green'}.get(status, 'white')
    return f'[{style}]{escape(status)}[/]'


def _print_notes(report: Any) -> None:
    """Print a report's warnings and recommendations lists."""
    for warning in report.warnings:
        console.print(f'[yellow]⚠ {escape(warning)}[/yellow]')
    for recommendation in report.recommendations:
        console.print(f'  → {escape(recommendation)}')


@analyze_app.command('poe-budget')
def analyze_poe_budget(
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """⚡ PoE OUTPUT budget per switch: watts drawn by powered devices vs the PoE budget.

    Reports each PoE switch's budget, consumption, headroom and high-draw ports (over
    5 W), WARNING at 80% and CRITICAL at 90%. Distinct from `analyze power-budget`,
    which audits the switch's own INPUT power (adapter or PoE-in) against its PHYs.
    Read-only.
    """
    from .analysis.poe_budget import check_poe_budget

    report = _run_analysis(check_poe_budget)
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('⚡ [bold]PoE Output Budget[/bold]')
    console.print(
        f'Devices analyzed: [cyan]{report.devices_analyzed}[/cyan]  '
        f'Budget: [cyan]{report.total_budget:.1f}W[/cyan]  '
        f'Consumption: [cyan]{report.total_consumption:.1f}W[/cyan]'
    )
    if report.devices:
        table = Table(title='PoE Budget per Switch', show_header=True)
        table.add_column('Device', style='cyan')
        table.add_column('Model')
        table.add_column('Budget')
        table.add_column('Drawn')
        table.add_column('Available')
        table.add_column('% used', style='yellow')
        table.add_column('High-draw ports', style='dim')
        table.add_column('Status', style='bold')
        for d in report.devices:
            ports = ', '.join(f'{p.port_idx} ({p.poe_power:.1f}W)' for p in d.high_draw_ports)
            table.add_row(
                escape(d.device_name),
                escape(d.model),
                f'{d.poe_budget:.1f}W',
                f'{d.poe_consumption:.1f}W',
                f'{d.poe_available:.1f}W',
                f'{d.utilization_percent:.1f}%',
                ports or '—',
                _status_cell(d.status),
            )
        console.print(table)
    else:
        console.print('No switch reports a PoE budget.')
    _print_notes(report)


@analyze_app.command('uplink-redundancy')
def analyze_uplink_redundancy(
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🔀 Uplink count per switch: single-uplink switches are single points of failure.

    Counts the ports each switch reports as uplinks, with speed and state. Read-only.
    """
    from .analysis.uplink_redundancy import check_uplink_redundancy

    report = _run_analysis(check_uplink_redundancy)
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('🔀 [bold]Uplink Redundancy[/bold]')
    console.print(
        f'Switches analyzed: [cyan]{report.devices_analyzed}[/cyan]  '
        f'Redundant: [green]{report.redundant_devices}[/green]  '
        f'Single uplink: [yellow]{report.single_uplink_devices}[/yellow]'
    )
    if report.devices:
        table = Table(title='Uplinks per Switch', show_header=True)
        table.add_column('Device', style='cyan')
        table.add_column('Model')
        table.add_column('Uplinks', style='yellow')
        table.add_column('Ports (speed, state)')
        table.add_column('Total speed')
        table.add_column('Status', style='bold')
        for d in report.devices:
            ports = ', '.join(
                f'{u.port_idx} ({u.speed_mbps} Mbps, {"up" if u.is_up else "down"})'
                for u in d.uplinks
            )
            table.add_row(
                escape(d.device_name),
                escape(d.model),
                str(d.uplink_count),
                ports or '—',
                f'{d.total_uplink_speed_mbps} Mbps',
                _status_cell(d.status),
            )
        console.print(table)
    else:
        console.print('No switches found.')
    _print_notes(report)


@analyze_app.command('client-density')
def analyze_client_density(
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📡 Wireless clients per access point, with average signal.

    WARNING above 30 clients on one AP and CRITICAL above 50. Read-only.
    """
    from .analysis.client_density import analyze_client_density as run_client_density

    report = _run_analysis(run_client_density)
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('📡 [bold]Client Density[/bold]')
    console.print(
        f'APs with clients: [cyan]{report.aps_analyzed}[/cyan]  '
        f'Wireless clients: [cyan]{report.total_wireless_clients}[/cyan]'
    )
    if report.access_points:
        table = Table(title='Clients per Access Point', show_header=True)
        table.add_column('Access point', style='cyan')
        table.add_column('Model')
        table.add_column('Clients', style='yellow')
        table.add_column('Avg signal')
        table.add_column('Status', style='bold')
        for ap in report.access_points:
            signal = '—' if ap.avg_signal_dbm is None else f'{ap.avg_signal_dbm:.1f} dBm'
            table.add_row(
                escape(ap.device_name),
                escape(ap.model),
                str(ap.client_count),
                signal,
                _status_cell(ap.status),
            )
        console.print(table)
    else:
        console.print('No wireless clients associated.')
    _print_notes(report)


@analyze_app.command('dhcp-pools')
def analyze_dhcp_pools(
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🧮 DHCP pool utilisation per network: active clients vs the configured range.

    WARNING at 80% and CRITICAL at 90% of the pool. Read-only.
    """
    from .analysis.dhcp_pool import check_dhcp_pool_utilization

    report = _run_analysis(check_dhcp_pool_utilization)
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('🧮 [bold]DHCP Pool Utilisation[/bold]')
    console.print(
        f'Networks analyzed: [cyan]{report.networks_analyzed}[/cyan]  '
        f'Addresses: [cyan]{report.total_pool_size}[/cyan]  '
        f'Active clients: [cyan]{report.total_active_clients}[/cyan]'
    )
    if report.pools:
        table = Table(title='DHCP Pools', show_header=True)
        table.add_column('Network', style='cyan')
        table.add_column('VLAN')
        table.add_column('Range')
        table.add_column('Size')
        table.add_column('Clients', style='yellow')
        table.add_column('% used')
        table.add_column('Status', style='bold')
        for p in report.pools:
            table.add_row(
                escape(p.network_name),
                '—' if p.vlan_id is None else str(p.vlan_id),
                f'{p.pool_start} – {p.pool_stop}',
                str(p.pool_size),
                str(p.active_clients),
                f'{p.utilization_percent:.1f}%',
                _status_cell(p.status),
            )
        console.print(table)
    else:
        console.print('No DHCP-enabled network with a pool range.')
    _print_notes(report)


@analyze_app.command('traffic-matrix')
def analyze_traffic_matrix_cmd(
    top: int = typer.Option(10, '--top', help='Number of flows/talkers to show', min=1),
):
    """📈 Analyze traffic matrix/top talkers from available UniFi statistics."""
    import asyncio

    if not state.debug:
        setup_logging(debug=False)

    console.print('📈 [bold]Traffic Matrix[/bold]')

    try:
        load_env_from_config(str(state.config_path))
        from .analysis.traffic_matrix import analyze_traffic_matrix

        report = asyncio.run(analyze_traffic_matrix(top_n=top))
        console.print(f'Records analyzed: [cyan]{report.records_analyzed}[/cyan]')
        console.print(f'Flows: [cyan]{report.flow_count}[/cyan]')
        console.print(f'Total bytes: [cyan]{report.total_bytes}[/cyan]')

        if report.top_flows:
            table = Table(title='Top Flows', show_header=True)
            table.add_column('Endpoint A', style='cyan')
            table.add_column('Endpoint B', style='magenta')
            table.add_column('Bytes', style='yellow')
            table.add_column('Peak bps')
            for flow in report.top_flows:
                table.add_row(
                    flow.endpoint_a.identifier,
                    flow.endpoint_b.identifier,
                    str(flow.total_bytes),
                    '' if flow.max_bps is None else f'{flow.max_bps:.0f}',
                )
            console.print(table)
        else:
            console.print('No endpoint-pair flow records found in available UniFi statistics.')

        if report.recommendations:
            console.print('\nRecommendations:')
            for recommendation in report.recommendations:
                console.print(f'  • {recommendation.recommendation}')
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if state.debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@diagnose_app.command('all')
def diagnose_all():
    """🏥 Run ALL diagnostics and print a pass/warn/fail summary table."""
    import asyncio
    from typing import Callable, Coroutine

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print('🏥 [bold]Comprehensive Diagnostics Runner[/bold]\n')

    try:
        load_env_from_config(str(config))

        from .analysis.capacity_planning import get_capacity_report
        from .analysis.client_density import analyze_client_density
        from .analysis.device_freshness import summarise_freshness
        from .analysis.dhcp_pool import check_dhcp_pool_utilization
        from .analysis.firmware_advisor import get_firmware_report
        from .analysis.foreign_bridges import detect_foreign_bridges
        from .analysis.link_quality import analyze_link_quality
        from .analysis.mtu_audit import audit_mtu_consistency
        from .analysis.poe_budget import check_poe_budget
        from .analysis.port_profile_validation import validate_port_profiles
        from .analysis.power_budget import audit_power_budget
        from .analysis.radio_optimization import analyze_radio_optimization
        from .analysis.sfp_diagnostics import audit_sfp_diagnostics
        from .analysis.uplink_redundancy import check_uplink_redundancy
        from .analysis.uplink_transparency import audit_uplink_transparency

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
            ('Uplink VLAN Transparency', audit_uplink_transparency),
            ('Device Power Budget', audit_power_budget),
            ('Foreign Bridges', detect_foreign_bridges),
            ('Telemetry Freshness', summarise_freshness),
        ]

        results: list[tuple[str, str]] = []

        for name, coro_fn in checks:
            console.print(f'  ▶ {name}...', end=' ')
            try:
                report = asyncio.run(coro_fn())
                status = _extract_status(report)
                results.append((name, status))
                style = {'PASS': 'green', 'WARN': 'yellow', 'FAIL': 'red'}.get(status, 'white')
                console.print(f'[{style}]{status}[/]')
            except Exception as exc:
                results.append((name, 'FAIL'))
                console.print(f'[red]FAIL[/] ({_error_text(exc)})')

        # Summary table
        console.print()
        table = Table(title='Diagnostics Summary', show_header=True)
        table.add_column('Check', style='cyan')
        table.add_column('Result', style='bold')
        for name, status in results:
            style = {'PASS': 'green', 'WARN': 'yellow', 'FAIL': 'red'}.get(status, 'white')
            table.add_row(name, f'[{style}]{status}[/]')
        console.print(table)

        pass_count = sum(1 for _, s in results if s == 'PASS')
        warn_count = sum(1 for _, s in results if s == 'WARN')
        fail_count = sum(1 for _, s in results if s == 'FAIL')
        console.print(f'\n✅ {pass_count} passed  ⚠️ {warn_count} warnings  ❌ {fail_count} failed')

        if fail_count > 0:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
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


@diagnose_app.command('health')
def diagnose_health(
    detailed: bool = typer.Option(False, '--detailed', help='🔬 Include detailed device analysis'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🏥 Overall network health check.

    Scores the network 0-100 from device state, adoption, CPU/memory/load, uplinks
    and firmware, with critical issues, warnings and recommendations: 100 when every
    device is online with no issue. Connectivity gives 70 to 100 (offline devices cost
    up to 30 points in proportion), then each finding costs points: 15 per critical
    issue, 10 per uplink issue, 5 per warning and 3 per CPU or memory alert, down to 0.
    90 or more is healthy, 70 or more a warning. An uplink counts as down only when
    its state says so. --detailed adds the per-device findings. Read-only.
    """
    from .diagnostics.network_health import network_health_check

    report = _run_analysis(network_health_check)
    if as_json:
        _emit_json(report.model_dump(mode='json'))
        return
    console.print('🏥 [bold]Network Health Check[/bold]')
    status_style = {'healthy': 'green', 'warning': 'yellow'}.get(report.status, 'red')
    table = Table(title='Network Health', show_header=False)
    table.add_column('Metric', style='cyan')
    table.add_column('Value')
    table.add_row('Score', f'[{status_style}]{report.overall_score}/100 ({report.status})[/]')
    table.add_row('Devices', str(report.total_devices))
    table.add_row('Online / offline', f'{report.devices_online} / {report.devices_offline}')
    table.add_row('Adopted', str(report.devices_adopted))
    table.add_row('Clients connected', str(report.clients_connected))
    if detailed:
        sections = [
            ('High CPU', report.high_cpu_devices),
            ('High memory', report.high_memory_devices),
            ('High load', report.high_load_devices),
            ('Uplink issues', report.uplink_issues),
            ('Firmware outdated', report.firmware_outdated),
        ]
        for label, devices in sections:
            table.add_row(label, escape(', '.join(devices)) or '—')
    console.print(table)
    for issue in report.critical_issues:
        console.print(f'[red]✖ {escape(issue)}[/red]')
    for warning in report.warnings:
        console.print(f'[yellow]⚠ {escape(warning)}[/yellow]')
    for recommendation in report.recommendations:
        console.print(f'  → {escape(recommendation)}')


@diagnose_app.command('latency-matrix')
def diagnose_latency_matrix(
    ping_count: int = typer.Option(3, '--count', '-c', help='Pings per target'),
    timeout: int = typer.Option(2, '--timeout', '-t', help='Ping timeout seconds'),
    devices_only: bool = typer.Option(
        False, '--devices-only', help='Skip clients, only ping infrastructure'
    ),
):
    """📡 SSH to gateway and ping all devices to build a latency matrix."""
    from rich.table import Table
    from unifi_mapper.analysis.latency_matrix import run_latency_matrix

    if not state.debug:
        setup_logging(debug=False)

    load_env_from_config(str(state.config_path))
    console.print('📡 [bold]Gateway Latency Matrix[/bold]\n')

    report = _run_gateway_ssh(
        lambda: run_latency_matrix(
            ping_count=ping_count, timeout=timeout, include_clients=not devices_only
        )
    )

    # Summary
    console.print(f'Gateway: [cyan]{report.gateway_host}[/cyan]')
    console.print(f'Targets: {report.targets_reachable}/{report.targets_total} reachable\n')

    # Results table
    table = Table(title='Latency Results')
    table.add_column('Name', style='cyan')
    table.add_column('IP', style='dim')
    table.add_column('Type')
    table.add_column('RTT avg', justify='right')
    table.add_column('RTT max', justify='right')
    table.add_column('Loss', justify='right')
    table.add_column('Status')

    # Sort: unreachable first, then by avg RTT descending
    sorted_results = sorted(
        report.results,
        key=lambda r: (r.reachable, -(r.rtt_avg or 0)),
    )

    for r in sorted_results:
        if r.reachable:
            status = '[green]✅[/green]'
            rtt_avg = f'{r.rtt_avg:.1f}ms' if r.rtt_avg else '—'
            rtt_max = f'{r.rtt_max:.1f}ms' if r.rtt_max else '—'
            loss = f'{r.packet_loss:.0f}%' if r.packet_loss > 0 else '0%'
        else:
            status = '[red]❌[/red]'
            rtt_avg = '—'
            rtt_max = '—'
            loss = '[red]100%[/red]'

        table.add_row(r.name, r.ip, r.target_type, rtt_avg, rtt_max, loss, status)

    console.print(table)

    if report.unreachable_devices:
        console.print(f'\n[red]Unreachable ({len(report.unreachable_devices)}):[/red]')
        for name in report.unreachable_devices:
            console.print(f'  ❌ {name}')

    if report.skipped_targets:
        console.print(
            f'\n[yellow]Not pinged, no valid IP ({len(report.skipped_targets)}):[/yellow]'
        )
        for skipped in report.skipped_targets:
            console.print(f'  ⚠ {escape(skipped.name)}: {escape(skipped.reason)}')


@diagnose_app.command('inter-vlan')
def diagnose_inter_vlan(
    source: str = typer.Argument(..., help='Source endpoint IP, MAC, hostname, or device name'),
    destination: str = typer.Argument(
        ..., help='Destination endpoint IP, MAC, hostname, or device name'
    ),
    protocol: str = typer.Option('icmp', '--protocol', help='Protocol to check'),
    port: Optional[str] = typer.Option(None, '--port', help='Optional destination port'),
):
    """🔀 Check inter-VLAN routing and firewall verdict between two endpoints."""
    import asyncio

    config = state.config_path
    debug = state.debug

    if not state.debug:
        setup_logging(debug=False)

    console.print('🔀 [bold]Inter-VLAN Routing Check[/bold]')
    console.print(f'Source: [cyan]{source}[/cyan]')
    console.print(f'Destination: [cyan]{destination}[/cyan]')

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
        console.print(f'Verdict: [{verdict_style}]{report.verdict.upper()}[/]')
        console.print(f'Source VLAN: [cyan]{report.source_vlan or "unknown"}[/cyan]')
        console.print(f'Destination VLAN: [cyan]{report.destination_vlan or "unknown"}[/cyan]')
        console.print(f'Route required: [cyan]{"yes" if report.route_required else "no"}[/cyan]')

        if report.matching_rules:
            console.print('Matching rules:')
            for rule in report.matching_rules:
                console.print(f'  - {rule}')

        if report.recommendations:
            console.print('Recommendations:')
            for recommendation in report.recommendations:
                console.print(f'  - {recommendation}')

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@app.command()
def diagram(
    output: Annotated[
        Optional[Path], typer.Option('--output', '-o', help='🖼️ Output path for diagram')
    ] = None,
    format: Annotated[
        str, typer.Option('--format', '-f', help='🎨 Diagram format (png, svg, html)')
    ] = 'png',
    all_devices: Annotated[
        bool,
        typer.Option(
            '--all-devices', '-a', help='📱 Include all devices (not just infrastructure)'
        ),
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

        console.print(f'📁 Config: [cyan]{config}[/cyan]')
        load_env_from_config(str(config))
        # Re-read the same file: a stray ./.env must never override --config.
        unifi_config = UnifiConfig.from_env(str(config))

        # Set output path
        diagram_path = output or Path.cwd() / 'diagrams' / f'network_diagram.{format}'
        diagram_path.parent.mkdir(parents=True, exist_ok=True)

        console.print(f'🖼️ Diagram: [cyan]{diagram_path}[/cyan]')
        console.print(
            f'📊 Mode: [cyan]{"All devices" if all_devices else "Infrastructure only"}[/cyan]'
        )

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
        console.print('🔍 [dim]Fetching devices...[/dim]')
        all_devices_response = cast(Any, port_mapper.api_client.get_devices(unifi_config.site))
        if isinstance(all_devices_response, dict):
            raw_devices = cast(dict[str, Any], all_devices_response).get('data', [])
            all_devices_list = cast(
                list[JsonDict], raw_devices if isinstance(raw_devices, list) else []
            )
        else:
            all_devices_list = cast(list[JsonDict], all_devices_response)

        # Filter to UniFi infrastructure devices (gateway, switches, APs)
        unifi_types = ['ugw', 'usg', 'udm', 'usw', 'uap']
        infrastructure_devices = [d for d in all_devices_list if d.get('type') in unifi_types]

        # Get LLDP data for devices that support it
        console.print('🔍 [dim]Fetching LLDP data...[/dim]')
        lldp_data: dict[str, dict[str, JsonDict]] = {}
        for device in infrastructure_devices:
            device_id = str(device.get('_id') or '')
            device_type = str(device.get('type') or '')
            # Only switches and gateways have LLDP data
            if device_type in ['ugw', 'usg', 'udm', 'usw'] and device_id:
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
            device_id = str(device_data.get('_id') or '')
            device_mac = str(device_data.get('mac') or '')
            device_model = str(device_data.get('model') or '')
            device_type = str(device_data.get('type') or '')

            # Count device types for debug
            if device_type in ['ugw', 'usg', 'udm']:
                routers_found += 1
            elif device_type == 'usw':
                switches_found += 1
            elif device_type == 'uap':
                aps_found += 1

            # Extract port information from device data
            ports: list[PortInfo] = []
            port_table = cast(list[JsonDict], device_data.get('port_table', []))
            port_overrides = {
                int(port.get('port_idx') or 0): port
                for port in cast(list[JsonDict], device_data.get('port_overrides', []))
            }

            for port_data in port_table:
                port_idx = int(port_data.get('port_idx') or 0)
                # Check for custom name in overrides first
                override = port_overrides.get(port_idx, {})
                port_name = str(override.get('name') or port_data.get('name', f'Port {port_idx}'))

                port_info = PortInfo(
                    idx=port_idx,
                    name=port_name,
                    up=bool(port_data.get('up', False)),
                    enabled=bool(port_data.get('enabled', True)),
                    poe=bool(port_data.get('poe_enable', False)),
                    media=str(port_data.get('media', 'RJ45')),
                    speed=int(port_data.get('speed') or 0),
                    lldp_info={},
                )
                ports.append(port_info)

            device = DeviceInfo(
                id=device_id,
                name=str(device_data.get('name') or 'Unknown'),
                model=device_model,
                mac=device_mac,
                ip=str(device_data.get('ip') or ''),
                ports=ports,
                lldp_info=lldp_data.get(device_id, {}),
            )
            devices[device_id] = device
            if device_mac:
                normalized_mac = device_mac.lower().replace(':', '').replace('-', '')
                mac_to_id[normalized_mac] = device_id

        console.print(
            f'📊 [dim]Device types: {routers_found} routers, {switches_found} switches, {aps_found} APs[/dim]'
        )

        # Create topology and generate diagram
        topology = NetworkTopology(devices)

        # Add connections from LLDP data
        connection_count = 0
        for device_id, device_lldp in lldp_data.items():
            for port_idx_str, port_lldp in device_lldp.items():
                chassis_id = str(port_lldp.get('chassis_id') or '')
                if not chassis_id:
                    continue
                # Normalize chassis_id MAC format
                normalized_chassis = chassis_id.lower().replace(':', '').replace('-', '')
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
            f'🔗 [dim]Found {connection_count} LLDP connections '
            f'(topology has {len(topology_connections)})[/dim]'
        )

        # Generate diagram
        if format.lower() == 'png':
            topology.generate_png_diagram(str(diagram_path))
        elif format.lower() == 'svg':
            topology.generate_svg_diagram(str(diagram_path))
        elif format.lower() == 'html':
            topology.generate_html_diagram(str(diagram_path), all_devices)
        else:
            console.print(f'❌ [bold red]Unsupported format: {format}[/bold red]')
            raise typer.Exit(1)

        console.print(f'✅ [bold green]Diagram generated: {diagram_path}[/bold green]')
        console.print(
            f'📊 Devices: [cyan]{len(devices)}[/cyan], '
            f'Connections: [cyan]{len(topology_connections)}[/cyan]'
        )

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@app.command()
def version():
    """📋 Show version information."""
    console.print('🚀 [bold cyan]UniFi Network Port Mapper[/bold cyan]')
    console.print('Version: [green]2.0.0[/green] (Enterprise Edition)')
    console.print('Framework: [blue]Typer + Rich + Multi-AI Analysis[/blue]')
    console.print('Features: [dim]100% Verified Port Naming + Device Intelligence[/dim]')


@app.command()
def capabilities():
    """🧠 Analyze device capabilities for port naming support."""
    console.print('🧠 [bold]Device Capability Analysis[/bold]')

    try:
        # Run the capability analysis
        from .analyze_network_capabilities import main as analyze_main

        analyze_main()

    except Exception as e:
        console.print(f'❌ [bold red]Capability analysis failed: {_error_text(e)}[/bold red]')
        raise typer.Exit(1)


@app.command()
def verify(
    all_ports: bool = typer.Option(False, '--all', help='✅ Verify all LLDP-discovered ports'),
    device: Optional[str] = typer.Option(None, '--device', help='🖥️ Specific device to verify'),
    port: Optional[int] = typer.Option(None, '--port', help='🔌 Specific port to verify'),
    expected: Optional[str] = typer.Option(None, '--expected', help='📝 Expected port name'),
    consistency_check: bool = typer.Option(
        False, '--consistency-check', help='🔄 Perform multi-read consistency verification'
    ),
    reads: int = typer.Option(5, '--reads', help='📊 Number of consistency reads', min=3, max=10),
):
    """✅ Comprehensive port name verification with ground truth checking."""
    console.print('✅ [bold]Ground Truth Verification[/bold]')

    if device and port is not None and expected:
        console.print(
            f"🔍 Verifying single port: [cyan]{device}[/cyan] Port {port} = '{expected}'"
        )
    elif all_ports:
        console.print('🔍 Verifying all LLDP-discovered ports')
    else:
        console.print('📊 Analyzing current network state')

    try:
        # Use the existing verify CLI functionality
        # Build arguments for the existing CLI
        import sys
        from .verify_cli import main as verify_main

        original_argv = sys.argv[:]
        sys.argv = ['verify']

        if all_ports:
            sys.argv.append('--verify-all')
        if consistency_check:
            sys.argv.append('--consistency-check')
            sys.argv.extend(['--reads', str(reads)])
        if device:
            sys.argv.extend(['--device', device])
        if port is not None:
            sys.argv.extend(['--port', str(port)])
        if expected:
            sys.argv.extend(['--expected', expected])

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
        console.print(f'❌ [bold red]Verification failed: {_error_text(e)}[/bold red]')
        raise typer.Exit(1)


# =============================================================================
# STP Commands
# =============================================================================


@stp_app.command('analyze')
def stp_analyze(
    device: Annotated[
        Optional[str], typer.Option('--device', '-d', help='🖥️ Specific switch to analyze')
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

    console.print('🌳 [bold]STP Topology Analysis[/bold]')

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import discover_stp_topology

        topology = asyncio.run(discover_stp_topology(device_id=device))

        # Display summary
        console.print('\n📊 [bold]Summary[/bold]')
        console.print(f'  Switches: [cyan]{len(topology.switches)}[/cyan]')
        console.print(f'  Root Bridge: [green]{topology.root_bridge_name or "Unknown"}[/green]')
        console.print(f'  Root Priority: [yellow]{topology.root_bridge_priority}[/yellow]')
        console.print(
            f'  Blocked Ports: [{"red" if topology.blocked_ports_count else "green"}]{topology.blocked_ports_count}[/]'
        )

        # Display topology table
        table = Table(title='STP Topology', show_header=True)
        table.add_column('Switch', style='cyan')
        table.add_column('Priority', style='yellow')
        table.add_column('Tier', style='blue')
        table.add_column('Root', style='green')
        table.add_column('Gateway', style='magenta')

        tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}
        for switch in topology.switches:
            tier_name = tier_names.get(switch.hierarchy_tier, f'Tier {switch.hierarchy_tier}')
            root_marker = '✅' if switch.is_root_bridge else ''
            gw_marker = '✅' if switch.connected_to_gateway else ''
            table.add_row(
                switch.name, str(switch.current_priority), tier_name, root_marker, gw_marker
            )

        console.print(table)

        if topology.blocked_ports_count > 0:
            console.print(
                f'\n⚠️ [yellow]Found {topology.blocked_ports_count} blocked port(s) - indicates redundant paths[/yellow]'
            )

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


# The MCP tool's bound on its device parameter (Field(min_length=1, max_length=128)).
_DEVICE_MAX_LENGTH = 128


def _device_query(
    ctx: typer.Context, param: typer.CallbackParam, value: Optional[str]
) -> Optional[str]:
    """Refuse a --device the MCP tool would refuse: empty, or over 128 characters."""
    if value is not None and not 1 <= len(value) <= _DEVICE_MAX_LENGTH:
        raise typer.BadParameter(
            f'give 1 to {_DEVICE_MAX_LENGTH} characters (a name, MAC or ID)', ctx=ctx, param=param
        )
    return value


@stp_app.command('audit-priorities')
def stp_audit_priorities(
    device: Optional[str] = typer.Option(
        None, '--device', help='Only this switch: its name, MAC or ID', callback=_device_query
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """📋 One-shot STP priority audit: each switch's current vs recommended priority.

    Discovers the whole fleet (tiers need every switch), computes the recommended
    priorities and reports the delta per switch, a warning when two non-core switches tie
    at the lowest priority, and the gateway, which is skipped. --device narrows the rows and
    the verdict to one switch, by name, MAC or ID, and prints the fleet's verdict after it.
    Writes no plan: stp optimize --plan does. Read-only.
    """
    from .analysis.stp_audit import audit_stp_priorities

    report = _run_analysis(lambda: audit_stp_priorities(device))
    if as_json:
        _emit_json(report)
        return
    root = escape(str(report['current_root'] or '—'))
    console.print(f'Current root: {root} (priority {report["current_root_priority"]})')
    table = Table(title='📋 STP priorities', show_header=True)
    for column in ('Switch', 'Tier', 'Current', 'Recommended', 'Δ', 'Root'):
        table.add_column(column)
    for row in report['switches']:
        delta = row['delta']
        table.add_row(
            escape(row['name']),
            escape(row['tier_label']),
            str(row['current_priority']),
            str(row['optimal_priority']),
            f'[yellow]{delta:+d}[/yellow]' if delta else '0',
            'yes' if row['is_root'] else '',
        )
    console.print(table)
    for skipped in report['skipped']:
        console.print(f'[dim]Skipped {escape(skipped["name"])}: {escape(skipped["reason"])}[/dim]')
    if report['root_tie_break_warning']:
        console.print(f'[yellow]⚠ {escape(report["root_tie_break_warning"])}[/yellow]')
    console.print(escape(report['summary']))
    if 'fleet_summary' in report:
        console.print(f'[dim]Fleet: {escape(report["fleet_summary"])}[/dim]')
    if report['remediation']['changes']:
        console.print('To plan and apply the changes:')
        for command in report['remediation']['commands']:
            console.print(f'  {escape(command)}')
    for note in report.get('notes', []):
        console.print(f'[dim]{escape(note)}[/dim]')


@stp_app.command('optimize')
def stp_optimize(
    dry_run: Annotated[
        bool, typer.Option('--dry-run', help='🔍 Preview changes without applying (default)')
    ] = True,
    apply: Annotated[bool, typer.Option('--apply', help='⚡ Apply the changes')] = False,
    force: Annotated[
        bool, typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying')
    ] = False,
    plan: Annotated[
        Optional[Path], typer.Option('--plan', help='📄 Write reversible STP change plan JSON')
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

    console.print('🔧 [bold]STP Optimization[/bold]')

    if dry_run:
        console.print('🔍 [cyan]Dry run mode - no changes will be applied[/cyan]')
    else:
        console.print('⚡ [yellow]Apply mode - changes will be made[/yellow]')

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import (
            apply_stp_changes,
            calculate_optimal_priorities,
            discover_stp_topology,
            gateway_skipped_line,
            is_gateway_switch,
        )

        # Discover topology
        console.print('📡 [dim]Discovering STP topology...[/dim]')
        topology = asyncio.run(discover_stp_topology())

        # Calculate optimal priorities
        console.print('🧮 [dim]Calculating optimal priorities...[/dim]')
        changes = asyncio.run(calculate_optimal_priorities(topology))
        for switch in topology.switches:
            if is_gateway_switch(switch, topology):
                console.print(f'[dim]{escape(gateway_skipped_line(switch))}[/dim]')

        if not changes:
            console.print('✅ [bold green]STP configuration is already optimal![/bold green]')
            return

        # Display changes table
        table = Table(title='Recommended Changes', show_header=True)
        table.add_column('Switch', style='cyan')
        table.add_column('Current', style='red')
        table.add_column('Optimal', style='green')
        table.add_column('Tier', style='blue')
        table.add_column('Reason', style='dim')

        tier_names = {0: 'Core', 1: 'Distribution', 2: 'Access'}
        for change in changes:
            tier_name = tier_names.get(change.hierarchy_tier, f'Tier {change.hierarchy_tier}')
            table.add_row(
                change.device_name,
                str(change.current_priority),
                str(change.new_priority),
                tier_name,
                change.reason[:40] + '...' if len(change.reason) > 40 else change.reason,
            )

        console.print(table)
        console.print(f'\n📊 [bold]{len(changes)} change(s) recommended[/bold]')

        if plan:
            from .analysis.stp_change_plan import create_stp_change_plan

            change_plan = create_stp_change_plan(changes)
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text(change_plan.model_dump_json(indent=2))
            console.print(f'📄 STP change plan saved to [cyan]{plan}[/cyan]')

        if not dry_run:
            if not force:
                confirm = typer.confirm(
                    f'\n⚠️ Apply {len(changes)} STP priority change(s)? This may cause brief network disruption.',
                    default=False,
                )
                if not confirm:
                    console.print('❌ [yellow]Operation cancelled[/yellow]')
                    raise typer.Exit(0)

            console.print('🚀 [dim]Applying changes...[/dim]')
            result = asyncio.run(apply_stp_changes(changes, dry_run=False))

            applied_count = len(result.get('applied', []))
            failed_count = len(result.get('failed', []))

            if applied_count > 0:
                console.print(f'✅ [bold green]Applied {applied_count} change(s)[/bold green]')

            if failed_count > 0:
                console.print(f'❌ [bold red]Failed {failed_count} change(s)[/bold red]')
                for failure in result.get('failed', []):
                    console.print(f'   • {failure["device_name"]}: {failure["error"]}')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('apply')
def stp_apply_plan(
    plan: Annotated[
        Path, typer.Option('--plan', help='📄 STP change plan JSON from stp optimize --plan')
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            '--dry-run/--no-dry-run', help='🔍 Preview plan application without applying'
        ),
    ] = True,
    force: Annotated[
        bool, typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying')
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
        console.print('⚡ [bold]STP Plan Apply[/bold]')
        console.print(f'Plan: [cyan]{plan}[/cyan]')
        console.print(f'Changes: [yellow]{len(change_plan.changes)}[/yellow]')

        if not dry_run and not force:
            confirm = typer.confirm(
                f'Apply {len(change_plan.changes)} STP change(s)? This may cause brief network disruption.',
                default=False,
            )
            if not confirm:
                console.print('❌ [yellow]Operation cancelled[/yellow]')
                raise typer.Exit(0)

        result = asyncio.run(apply_stp_changes(change_plan.changes, dry_run=dry_run))
        _print_stp_apply_result(result)

        if result.get('failed'):
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('rollback')
def stp_rollback_plan(
    plan: Annotated[Path, typer.Argument(help='📄 STP change plan JSON to roll back')],
    dry_run: Annotated[
        bool, typer.Option('--dry-run/--no-dry-run', help='🔍 Preview rollback without applying')
    ] = True,
    force: Annotated[
        bool, typer.Option('--force', '-f', help='⚠️ Skip confirmation when applying rollback')
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
        console.print('↩️ [bold]STP Plan Rollback[/bold]')
        console.print(f'Plan: [cyan]{plan}[/cyan]')
        console.print(f'Rollback changes: [yellow]{len(change_plan.rollback)}[/yellow]')

        if not dry_run and not force:
            confirm = typer.confirm(
                f'Apply {len(change_plan.rollback)} rollback change(s)? This may cause brief network disruption.',
                default=False,
            )
            if not confirm:
                console.print('❌ [yellow]Operation cancelled[/yellow]')
                raise typer.Exit(0)

        result = asyncio.run(apply_stp_changes(change_plan.rollback, dry_run=dry_run))
        _print_stp_apply_result(result)

        if result.get('failed'):
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('report')
def stp_report(
    output: Annotated[Path, typer.Option('--output', '-o', help='📄 Output file path (required)')],
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

    console.print('📝 [bold]STP Report Generation[/bold]')
    console.print(f'📄 Output: [cyan]{output}[/cyan]')

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
        console.print('📡 [dim]Discovering STP topology...[/dim]')
        topology = asyncio.run(discover_stp_topology())

        # Calculate optimal priorities
        console.print('🧮 [dim]Calculating optimal priorities...[/dim]')
        changes = asyncio.run(calculate_optimal_priorities(topology))

        # Generate report
        console.print('📝 [dim]Generating report...[/dim]')
        report = asyncio.run(generate_stp_report(topology, changes))

        # Format and write markdown
        markdown = format_stp_report_markdown(report)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown)

        console.print(f'✅ [bold green]Report saved to {output}[/bold green]')
        console.print(f'📊 Analyzed: [cyan]{report.switches_analyzed}[/cyan] switches')
        console.print(f'🔄 Changes: [yellow]{report.changes_required}[/yellow] recommended')

        if report.issues:
            console.print('\n⚠️ [bold yellow]Issues Found:[/bold yellow]')
            for issue in report.issues:
                console.print(f'   • {issue}')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('snapshot')
def stp_snapshot(
    output: Annotated[
        Path, typer.Option('--output', '-o', help='📄 Output STP snapshot JSON path')
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

        console.print('📸 [bold]STP Snapshot[/bold]')
        topology = asyncio.run(discover_stp_topology())
        snapshot = snapshot_stp_topology(topology)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(snapshot.model_dump_json(indent=2))
        console.print(f'📄 Snapshot saved to [cyan]{output}[/cyan]')
        console.print(f'Root bridge: [green]{snapshot.root_bridge_name or "Unknown"}[/green]')
        console.print(f'Switches: [cyan]{len(snapshot.switches)}[/cyan]')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('diff')
def stp_diff(
    baseline: Annotated[Path, typer.Argument(help='📄 Baseline STP snapshot JSON')],
    output: Annotated[
        Optional[Path], typer.Option('--output', '-o', help='Optional output diff JSON path')
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

        console.print('🔎 [bold]STP Snapshot Diff[/bold]')
        before = STPSnapshot.model_validate_json(baseline.read_text())
        topology = asyncio.run(discover_stp_topology())
        after = snapshot_stp_topology(topology)
        diff = diff_stp_snapshots(before, after)

        console.print(f'Changes: [yellow]{len(diff.changes)}[/yellow]')
        if diff.changes:
            table = Table(title='STP Changes', show_header=True)
            table.add_column('Type', style='cyan')
            table.add_column('Subject', style='magenta')
            table.add_column('Before')
            table.add_column('After')
            for change in diff.changes:
                table.add_row(
                    change.change_type,
                    change.subject,
                    str(change.before),
                    str(change.after),
                )
            console.print(table)
        else:
            console.print('✅ [bold green]No STP changes detected[/bold green]')

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(diff.model_dump_json(indent=2))
            console.print(f'📄 Diff saved to [cyan]{output}[/cyan]')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('preflight')
def stp_preflight(
    planned_switches: Annotated[
        str,
        typer.Option(
            '--simulate-add',
            help='Planned switch model/count, for example USW-Flex-XG:2',
        ),
    ] = 'USW-Flex-XG:2',
    uplink: Annotated[
        list[str], typer.Option('--uplink', help='Expected uplink target switch name')
    ] = [],
    output: Annotated[
        Optional[Path], typer.Option('--output', '-o', help='Optional preflight report JSON path')
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

        console.print('🧪 [bold]STP Preflight Simulation[/bold]')
        planned_models = _parse_planned_switches(planned_switches)
        topology = asyncio.run(discover_stp_topology())
        report = stp_preflight_simulate_add(
            topology,
            planned_models=planned_models,
            uplink_targets=uplink,
        )

        console.print(f'Simulated switches added: [cyan]{report.simulated_switches_added}[/cyan]')
        console.print(f'Expected root: [green]{report.expected_root or "Unknown"}[/green]')

        table = Table(title='Required Priorities', show_header=True)
        table.add_column('Switch', style='cyan')
        table.add_column('Priority', style='yellow')
        for switch_name, priority in report.required_priorities.items():
            table.add_row(switch_name, str(priority))
        console.print(table)

        if report.checklist:
            console.print('\nChecklist:')
            for item in report.checklist:
                console.print(f'  • {item}')

        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report.model_dump_json(indent=2))
            console.print(f'📄 Preflight report saved to [cyan]{output}[/cyan]')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('guard')
def stp_guard(
    tcn_threshold: int = typer.Option(
        10,
        '--tcn-threshold',
        help='STP topology-change count threshold before warning',
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

        console.print('🛡️ [bold]STP Guard Audit[/bold]')
        topology = asyncio.run(discover_stp_topology())
        report = audit_stp_guard_recommendations(topology, tcn_threshold=tcn_threshold)

        console.print(f'Ports analyzed: [cyan]{report.ports_analyzed}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='STP Guard Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Category', style='cyan')
            table.add_column('Device', style='magenta')
            table.add_column('Port', style='yellow')
            table.add_column('Finding')
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
            console.print('✅ [bold green]No STP guard findings detected[/bold green]')

    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('drift')
def stp_drift(
    intent: Path = typer.Option(
        ...,
        '--intent',
        help='Path to stp_intent.yaml/json desired priority file',
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

        console.print('📋 [bold]STP Config Drift[/bold]')
        topology = asyncio.run(discover_stp_topology())
        desired = cast(STPIntentMapping, load_stp_intent(intent))
        report = detect_stp_config_drift(topology, desired)

        console.print(f'Devices checked: [cyan]{report.devices_checked}[/cyan]')
        console.print(f'Findings: [yellow]{report.findings_count}[/yellow]')

        if report.findings:
            table = Table(title='STP Drift Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Type', style='cyan')
            table.add_column('Device', style='magenta')
            table.add_column('Expected')
            table.add_column('Actual')
            table.add_column('Finding')
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
        console.print('✅ [bold green]No STP drift detected[/bold green]')

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


@stp_app.command('validate-10g')
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

    console.print('🌳 [bold]10G Expansion Validation[/bold]')
    console.print(f'🔌 Planned USW Flex XG switches: [cyan]{planned_switches}[/cyan]')

    try:
        from .cli import load_env_from_config

        load_env_from_config(str(config))

        from .analysis.stp_optimizer import (
            format_10g_validation_report_markdown,
            validate_10g_expansion_readiness,
        )

        console.print('📡 [dim]Discovering STP topology and port counters...[/dim]')
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
        console.print(f'\n📊 Readiness: [{status_style}]{report.readiness}[/]')
        console.print(f'  Switches: [cyan]{report.switches_analyzed}[/cyan]')
        console.print(f'  Inter-switch links: [cyan]{report.inter_switch_links}[/cyan]')
        console.print(f'  10G ports: [cyan]{report.ten_gig_links}[/cyan]')
        console.print(f'  Blocked STP ports: [yellow]{report.blocked_ports_count}[/yellow]')
        console.print(f'  STP changes required: [yellow]{report.stp_changes_required}[/yellow]')

        if report.findings:
            table = Table(title='Validation Findings', show_header=True)
            table.add_column('Severity', style='bold')
            table.add_column('Category', style='cyan')
            table.add_column('Device', style='magenta')
            table.add_column('Port', style='yellow')
            table.add_column('Finding')
            table.add_column('Recommendation', style='dim')

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
            console.print('✅ [bold green]No critical or warning findings detected[/bold green]')

        if output:
            markdown = format_10g_validation_report_markdown(report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(markdown)
            console.print(f'📄 Report saved to [cyan]{output}[/cyan]')

        if not report.validation_passed:
            raise typer.Exit(2)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f'❌ [bold red]Error: {_error_text(e)}[/bold red]')
        if debug:
            _print_debug_traceback(console)
        raise typer.Exit(1)


def _print_stp_apply_result(result: dict[str, object]) -> None:
    applied = result.get('applied', [])
    failed = result.get('failed', [])
    console.print(str(result.get('message', '')))
    if isinstance(applied, list) and applied:
        table = Table(
            title='Applied Changes' if not result.get('dry_run') else 'Planned Changes',
            show_header=True,
        )
        table.add_column('Switch', style='cyan')
        table.add_column('Current', style='red')
        table.add_column('New', style='green')
        table.add_column('Status')
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
        console.print(f'❌ [bold red]Failed {len(failed_items)} change(s)[/bold red]')
        for item in failed_items:
            if isinstance(item, dict):
                failed_item = cast(dict[str, object], item)
                console.print(
                    f'   • {failed_item.get("device_name", "")}: {failed_item.get("error", "")}'
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


# ─── Switch Port Label Commands ──────────────────────────────────────────────


@ports_app.command('refresh')
def ports_refresh(
    apply_changes: bool = typer.Option(
        False, '--apply/--dry-run', help='Write the changes (default: preview only)'
    ),
):
    """🔌 Refresh switch port labels from live LLDP and wired-client data.

    Resolves each connected port to its LLDP peer (via the adopted-device registry, so
    APs resolve even though they send no system_name) or its wired client. A
    DISCONNECTED port is reverted to its default (``Port N``), since a label naming
    hardware that is no longer plugged in is misinformation; a down port already
    carrying a factory placeholder such as ``PoE Out + Data`` is left alone. Four
    guards prevent losing information or churning labels.
    """
    import asyncio
    from rich.table import Table
    from unifi_mapper.analysis.port_naming import analyse_port_names, apply_port_names

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print('🔌 [bold]Port Label Refresh[/bold]\n')

    plan = asyncio.run(analyse_port_names())
    if not plan.count:
        console.print('[green]All port labels already match live topology.[/green]')
        return

    grouped = plan.by_device()
    for device in sorted(grouped):
        table = Table(title=device)
        table.add_column('Port', justify='right', style='cyan')
        table.add_column('Current')
        table.add_column('Proposed', style='green')
        table.add_column('Source', style='dim')
        for rename in grouped[device]:
            table.add_row(
                str(rename.port_idx), rename.current or '—', rename.proposed, rename.reason
            )
        console.print(table)

    console.print(f'\n⚡ {plan.count} port(s) across {len(grouped)} switch(es)')

    if not apply_changes:
        console.print('[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to write')
        return

    for result in asyncio.run(apply_port_names(plan, dry_run=False)):
        icon = '✅' if result['status'] == 'APPLIED' else '❌'
        console.print(
            f'  {icon} {result["device"]}: {result["ports"]} port(s) — {result["status"]}'
        )

    console.print('\n💡 Re-run to verify; a clean run reports no changes needed.')


# ─── Read-only port diagnostics ──────────────────────────────────────────────


# Long enough that a real message is never cut; redact_text's default (300) is for the
# one-line summaries of unexpected exceptions.
_FAIL_TEXT_LIMIT = 4000


def _fail(message: object, code: int = 1) -> NoReturn:
    """Print an error to stderr (unwrapped, so names and MACs stay intact) and exit.

    The text goes through ``redact_text`` first: a ``ToolError`` can carry a lower layer's
    exception text, and a secret-looking assignment in it is masked.
    """
    from .core.utils.redact import redact_text

    text = redact_text(str(message), limit=_FAIL_TEXT_LIMIT)
    err_console.print(f'[red]❌ {escape(text)}[/red]', soft_wrap=True)
    raise typer.Exit(code=code)


def _error_text(error: object) -> str:
    """Return an exception's text for a Rich markup line: redacted, then markup-escaped."""
    from .core.utils.redact import redact_text

    return escape(redact_text(error))


def _print_debug_traceback(target: Console) -> None:
    """Print the exception being handled as a traceback (``--debug``), its messages redacted.

    Every frame, no local variables, as Rich's own traceback without locals; but each
    exception message (causes, groups and notes included) goes through ``redact_text``, so a
    secret-looking assignment in it is masked.
    """
    import sys
    from .core.utils.redact import redact_text
    from rich.traceback import Traceback

    exc_type, exc_value, tb = sys.exc_info()
    if exc_type is None or exc_value is None:
        return
    trace = Traceback.extract(exc_type, exc_value, tb, show_locals=False)
    pending = list(trace.stacks)
    while pending:
        stack = pending.pop()
        stack.exc_value = redact_text(stack.exc_value, limit=_FAIL_TEXT_LIMIT)
        stack.notes = [redact_text(note, limit=_FAIL_TEXT_LIMIT) for note in stack.notes]
        if stack.syntax_error is not None:
            stack.syntax_error.msg = redact_text(stack.syntax_error.msg)
            stack.syntax_error.line = redact_text(stack.syntax_error.line)
        for group in stack.exceptions:
            pending.extend(group.stacks)
    target.print(Traceback(trace, show_locals=False))


def _path_not_a_flag(
    ctx: typer.Context, param: typer.CallbackParam, value: Optional[str]
) -> Optional[str]:
    """Reject a path option whose value is another option (``--baseline --json``).

    Click consumes the next token as an option's value even when it looks like a
    flag, so without this ``--link-error-baseline --json`` silently read ``--json``
    as the path and dropped the JSON output.
    """
    if value is not None and value.startswith('-'):
        # Click prefixes "Invalid value for '--option':", so the message need not repeat it.
        raise typer.BadParameter(
            f'expected a file path, got the option {value!r}', ctx=ctx, param=param
        )
    return value


def _existing_read_only_path(
    ctx: typer.Context, param: typer.CallbackParam, value: Optional[str]
) -> Optional[str]:
    """A read-only path option: not a flag, and an explicit path must exist.

    Omitting the option keeps the resolved default, where a missing file is
    reported as ``found: false`` rather than an error.
    """
    value = _path_not_a_flag(ctx, param, value)
    if value is None or Path(value).exists():
        return value
    if param.name == 'history':
        from .analysis.counter_history import default_history_path

        kind, default = 'history', default_history_path()
    else:
        from .analysis.link_error_tracking import resolve_link_error_baseline

        kind, default = 'baseline', resolve_link_error_baseline(None)[0]
    raise typer.BadParameter(
        f'{kind} file not found: {value}; omit the option to use {default}',
        ctx=ctx,
        param=param,
    )


def _emit_json(data: Any) -> None:
    """Print ``data`` as JSON on stdout, with no Rich markup and secrets stripped."""
    from .core.utils.redact import strip_secrets

    clean, _ = strip_secrets(data)
    typer.echo(json.dumps(clean, indent=2, default=str))


@contextmanager
def _readonly_client() -> Iterator[tuple[Any, str]]:
    """Yield an authenticated ``UnifiApiClient`` behind the read-only guard, and its site.

    Configuration comes only from ``--config`` (or the default config path).
    The implicit ``./.env`` that ``UnifiConfig.from_env()`` would otherwise
    read is never consulted, so a stray ``.env`` in the working directory
    cannot redirect these commands to another controller. The guard refuses
    any controller write before it reaches the network.
    """
    from .api_client import UnifiApiClient
    from .config import UnifiConfig
    from .core.utils.readonly import install_read_only_guard
    from .core.utils.redact import redact_text

    config_path = str(state.config_path or get_default_config_path())
    load_env_from_config(config_path)
    if not state.debug:
        setup_logging(debug=False)
    try:
        unifi_config = UnifiConfig.from_env(config_path)
    except ValueError as e:
        _fail(e)

    client = UnifiApiClient(
        base_url=unifi_config.base_url,
        site=unifi_config.site,
        verify_ssl=unifi_config.verify_ssl,
        username=unifi_config.username,
        password=unifi_config.password,
        api_token=unifi_config.api_token,
        timeout=unifi_config.timeout,
    )
    try:
        authenticated = client.login()
    except Exception as e:  # noqa: BLE001 - every login failure ends the command cleanly
        _fail(f'Could not authenticate to the controller: {redact_text(e)}')
    if not authenticated:
        _fail('Could not authenticate to the controller')

    install_read_only_guard(client, unifi_config.site)
    try:
        yield client, unifi_config.site
    finally:
        client.logout()


@contextmanager
def _diagnostic_errors() -> Iterator[None]:
    """Turn diagnostic failures into clean exits: 1 for not-found, 2 for bad input.

    Anything else ends as one redacted ``Error:`` line on stderr (exit 1), never Typer's
    traceback, which would print the frames' locals, the config's credentials among them.
    """
    from .core.utils.readonly import ReadOnlyViolation
    from .core.utils.redact import redact_text

    try:
        yield
    except ReadOnlyViolation as e:
        _fail(f'Refused a controller write. This is a bug, please report it: {e}')
    except LookupError as e:
        _fail(e)
    except ValueError as e:
        _fail(e, code=2)
    except (typer.Exit, typer.Abort):
        raise  # _fail raises typer.Exit, a RuntimeError, inside this block too
    except Exception as e:  # noqa: BLE001 - never Typer's traceback, which prints locals
        if state.debug:
            _print_debug_traceback(err_console)
        _fail(f'Error: {redact_text(e)}')


@contextmanager
def _offline_errors() -> Iterator[None]:
    """Turn failures of a command that never contacts the controller into clean exits.

    A ``ToolError`` exits 2 when it is ``CONFIG_INVALID`` (a bad path or argument) and 1
    otherwise (no data, a missing file); a ``ValueError`` exits 2; anything else ends as
    one redacted ``Error:`` line (exit 1), never Typer's traceback.
    """
    from .core.utils.errors import ErrorCodes, ToolError
    from .core.utils.redact import redact_text

    try:
        yield
    except ToolError as e:
        _fail(e, code=2 if e.error_code == ErrorCodes.CONFIG_INVALID else 1)
    except ValueError as e:
        _fail(e, code=2)
    except (typer.Exit, typer.Abort):
        raise
    except Exception as e:  # noqa: BLE001 - never Typer's traceback, which prints locals
        if state.debug:
            _print_debug_traceback(err_console)
        _fail(f'Error: {redact_text(e)}')


def _resolve(client: Any, site: str, query: str, *, any_device: bool = False) -> JsonDict:
    """Resolve a switch (or any device) or exit 1 listing the candidates."""
    from .diagnostic_reads import resolve_device

    device, _, _ = resolve_device(
        client, site, query, device_types=None if any_device else ('usw',)
    )
    return device


def _slug(text: str) -> str:
    return ''.join(ch if ch.isalnum() else '-' for ch in text.lower()).strip('-') or 'switch'


@ports_app.command('inspect')
def ports_inspect(
    switch: str = typer.Argument(
        ..., help="Switch name, model, IP or MAC (e.g. 'Office Desk Flex 5')"
    ),
    port: int = typer.Argument(..., help='Port index (1-based)'),
    as_json: bool = typer.Option(
        False, '--json', help='Print the inspection as JSON instead of tables'
    ),
):
    """🔎 Inspect one switch port: link state, LLDP peer, client identity and counters.

    Gathers every fact the controller holds about a single port and flags when cached
    controller state disagrees with ground truth, which is the usual cause of a port
    that looks down but is actually carrying traffic.

    Useful when a port misbehaves and the label alone is not enough — for example a
    host that links up but never obtains DHCP. Read-only.
    """
    from .port_inspect import inspect_port

    with _diagnostic_errors(), _readonly_client() as (client, site):
        target = _resolve(client, site, switch)
        result = inspect_port(client, site, target, port)
        if as_json:
            _emit_json(result.to_dict())
        else:
            result.render(console)


@ports_app.command('list')
def ports_list(
    switch: str = typer.Argument(..., help='Switch name, MAC or IP (an exact name or MAC wins)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
    raw: bool = typer.Option(False, '--raw', help='Include the full sanitised stat/device record'),
):
    """📋 Every port on a switch: speed, duplex, autoneg, profile, LLDP peer and clients.

    Also reports the switch's identity: model, firmware (and any pending upgrade,
    recorded only), uptime, state and system stats. Read-only.
    """
    from .port_diagnostics import list_switch_ports
    from .port_diagnostics_render import render_switch_ports

    with _diagnostic_errors(), _readonly_client() as (client, site):
        report = list_switch_ports(client, site, _resolve(client, site, switch), include_raw=raw)
    if as_json:
        _emit_json(report.to_json_dict())
    else:
        render_switch_ports(console, report)


@ports_app.command('profile-diff')
def ports_profile_diff(
    profile_a: str = typer.Argument(..., help='First port profile name or _id'),
    profile_b: str = typer.Argument(..., help='Second port profile name or _id'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🆚 Diff two port profiles key by key, and list every port using each one.

    Settings are separated from bookkeeping keys (_id, name, site_id, attr_*), the
    networks they reference are resolved to names and VLANs, and each profile's live
    ports are listed with their negotiated speed. Read-only.
    """
    from .port_diagnostics import diff_port_profiles
    from .port_diagnostics_render import render_profile_diff

    with _diagnostic_errors(), _readonly_client() as (client, site):
        diff = diff_port_profiles(client, site, profile_a, profile_b)
    if as_json:
        _emit_json(diff.to_json_dict())
    else:
        render_profile_diff(console, diff)


@ports_app.command('client')
def ports_client(
    identifier: str = typer.Argument(
        ..., metavar='CLIENT', help='Client MAC (any notation), IP, or a name/hostname substring'
    ),
    switch: Optional[str] = typer.Option(
        None, '--switch', help='Check each record against this switch'
    ),
    port: Optional[int] = typer.Option(
        None, '--port', min=1, help='Check against this port (needs --switch)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """🧭 Where does the controller place a client? Every client table, current and offline.

    Reads stat/sta, v2 clients/active and clients/history, rest/user and stat/user. With
    --switch/--port, each record is checked against that port from the record's own
    location fields, independently of how the record was found. Read-only.
    """
    from .port_diagnostics import get_client_history
    from .port_diagnostics_render import render_client_history

    if port is not None and switch is None:
        _fail('--port needs --switch', code=2)
    with _diagnostic_errors(), _readonly_client() as (client, site):
        target = _resolve(client, site, switch) if switch else None
        history = get_client_history(client, site, identifier, switch=target, port_idx=port)
    if as_json:
        _emit_json(history.to_json_dict())
    else:
        render_client_history(console, history)


@ports_app.command('events')
def ports_events(
    device: str = typer.Argument(..., metavar='SWITCH', help='Device name, MAC or IP'),
    port: Optional[int] = typer.Argument(None, min=1, help='Only flag entries for this port'),
    clients: Optional[list[str]] = typer.Option(
        None, '--client', help='Also match entries for this client MAC (repeatable)'
    ),
    since_days: int = typer.Option(
        365, '--since-days', min=1, max=3650, help='How far back to ask for history'
    ),
    max_events: int = typer.Option(
        500, '--max-events', min=1, max=5000, help='Keep at most this many matches (newest)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📜 Events, alarms, system log and admin audit entries for a device, port or client.

    Pages stat/event, reads list/alarm and pages the v2 system-log classes
    (device-alert, admin-activity, update-alert, client-alert). Each source reports the
    earliest entry it returned, which is the controller's observed retention. Read-only:
    the POSTs are query endpoints on an allowlist.
    """
    from .diagnostic_reads import rows
    from .port_diagnostics_render import render_event_history
    from .port_history import collect_events

    with _diagnostic_errors(), _readonly_client() as (client, site):
        target = _resolve(client, site, device, any_device=True)
        names = [str(d.get('name')) for d in rows(client.get_devices(site)) if d.get('name')]
        history = collect_events(
            client,
            site,
            target,
            port_idx=port,
            client_macs=clients or [],
            since_days=since_days,
            max_events=max_events,
            known_device_names=names,
        )
    if as_json:
        _emit_json(history.to_json_dict())
    else:
        render_event_history(console, history)


@ports_app.command('counters')
def ports_counters(
    switch: str = typer.Argument(..., help='Switch name, MAC or IP'),
    port: int = typer.Argument(..., min=1, help='Port index (1-based)'),
    samples: int = typer.Option(2, '--samples', min=1, max=5, help='Number of samples'),
    interval: int = typer.Option(
        100,
        '--interval',
        min=30,
        max=300,
        help='Seconds between samples (devices inform every ~75-90 s)',
    ),
    link_error_baseline: Optional[str] = typer.Option(
        None,
        '--link-error-baseline',
        callback=_existing_read_only_path,
        help=(
            'Baseline from `analyze link-errors --snapshot` to compare against (read only; '
            'default: the XDG state baseline, else a legacy ./reports/ one)'
        ),
    ),
    history: Optional[str] = typer.Option(
        None,
        '--history',
        callback=_existing_read_only_path,
        help=(
            'Counter history from `analyze link-errors --record` (read only; '
            'default: $XDG_STATE_HOME/unifi_mapper/port-counter-history.jsonl)'
        ),
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📈 Sample one port's error counters and report per-minute rates with a trust verdict.

    Blocks for (samples - 1) x interval seconds. Rates are withheld when the device did
    not inform between samples (a stale snapshot would read as zero errors) or when a
    counter or uptime went down. Existing baselines and the recorded counter history
    are compared, never written.
    """
    from .port_diagnostics_render import render_counter_trend
    from .port_history import sample_port_counters

    with _diagnostic_errors(), _readonly_client() as (client, site):
        target = _resolve(client, site, switch)
        wait = (samples - 1) * interval
        with err_console.status(f'Sampling port {port} ({wait}s)…'):
            trend = sample_port_counters(
                client,
                site,
                target,
                port,
                samples=samples,
                interval_seconds=interval,
                link_error_baseline_path=link_error_baseline,
                history_path=Path(history) if history else None,
            )
    if as_json:
        _emit_json(trend.to_json_dict())
    else:
        render_counter_trend(console, trend)


@ports_app.command('diagnose')
def ports_diagnose(
    switch: str = typer.Argument(..., help='Switch name, MAC or IP (an exact name or MAC wins)'),
    port: int = typer.Argument(..., min=1, help='Port index (1-based)'),
    clients: Optional[list[str]] = typer.Option(
        None,
        '--client',
        help='Client MAC, IP or name to locate (repeatable; default: whatever is on the port)',
    ),
    compare_profiles: Optional[list[str]] = typer.Option(
        None, '--compare-profile', help='Port profile to diff; give exactly twice'
    ),
    since_days: int = typer.Option(365, '--since-days', min=1, max=3650, help='History window'),
    samples: int = typer.Option(2, '--samples', min=1, max=5, help='Counter samples'),
    interval: int = typer.Option(
        100, '--interval', min=30, max=300, help='Seconds between counter samples'
    ),
    max_events: int = typer.Option(500, '--max-events', min=1, max=5000, help='Event cap'),
    output: Optional[Path] = typer.Option(
        None,
        '--output',
        '-o',
        help='Bundle path (default: reports/port-diagnostics-<switch>-p<N>-<timestamp>.json)',
    ),
    as_json: bool = typer.Option(
        False, '--json', help='Also print the bundle JSON instead of the summary'
    ),
):
    """🧾 Collect a read-only evidence bundle for one switch port (for vendor tickets).

    One JSON file with the switch identity and application version, the raw port entry
    and override, both profiles diffed, where the controller places each client, events
    and system log, counter samples, every port on the switch and the Integration API
    view. A transport guard refuses any controller write, secrets are stripped, and the
    requests made are listed in request_audit as proof.
    """
    import time
    from .port_diagnostics import BundleQuery, build_port_diagnostic_bundle
    from .port_diagnostics_render import render_bundle_summary

    if compare_profiles and len(compare_profiles) != 2:
        _fail('--compare-profile must be given exactly twice (profile A and profile B)', code=2)
    query = BundleQuery(
        switch=switch,
        port=port,
        clients=clients or [],
        compare_profiles=compare_profiles or [],
        since_days=since_days,
        counter_samples=samples,
        interval_seconds=interval,
        max_events=max_events,
    )
    with _diagnostic_errors(), _readonly_client() as (client, site):
        wait = (samples - 1) * interval
        with err_console.status(f'Collecting port {port} evidence (≈{wait}s of sampling)…'):
            bundle = build_port_diagnostic_bundle(client, site, query)

    data = bundle.to_json_dict()
    if output is None:
        name = (bundle.device.name if bundle.device else None) or switch
        stamp = time.strftime('%Y%m%d-%H%M%S')
        output = Path('reports') / f'port-diagnostics-{_slug(name)}-p{port}-{stamp}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, default=str) + '\n', encoding='utf-8')
    if as_json:
        _emit_json(data)
        err_console.print(f'💾 Evidence bundle written to {output}')
    else:
        render_bundle_summary(console, bundle, output)


# ─── Radio Configuration Commands ────────────────────────────────────────────


@radio_app.command('snapshot')
def radio_snapshot(
    output: str = typer.Option(
        'reports/radio-snapshot.json', '--output', '-o', help='Output file path'
    ),
):
    """📸 Snapshot current radio config for all APs (backup before changes)."""
    import asyncio
    from unifi_mapper.analysis.radio_config import snapshot_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print('📸 [bold]Radio Configuration Snapshot[/bold]\n')

    snapshot = asyncio.run(snapshot_radio_config(output_path=output))
    console.print(f'APs captured: [cyan]{len(snapshot["aps"])}[/cyan]')
    console.print(f'Saved to: [green]{output}[/green]')
    console.print(
        f'\n💡 Use [cyan]unifi-mapper radio restore --snapshot {output}[/cyan] to revert changes'
    )


@radio_app.command('optimize')
def radio_optimize(
    dry_run: bool = typer.Option(
        True, '--dry-run/--apply', help='Preview changes without applying'
    ),
    snapshot: str = typer.Option(
        'reports/radio-snapshot.json', '--snapshot', '-s', help='Auto-snapshot before apply'
    ),
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

    console.print('⚡ [bold]Radio Optimisation[/bold]\n')

    async def run():
        async with UniFiClient() as client:
            devices = await client.get_devices()
        return devices

    devices = asyncio.run(run())
    changes = build_optimisation_plan(devices)

    if not changes:
        console.print('[green]No optimisations needed — config already optimal.[/green]')
        return

    # Show plan
    table = Table(title='Optimisation Plan')
    table.add_column('AP', style='cyan')
    table.add_column('Radio')
    table.add_column('Changes')

    device_names = {d['_id']: d.get('name', 'Unknown') for d in devices if '_id' in d}
    for c in changes:
        name = device_names.get(c['device_id'], 'Unknown')
        radio = '5GHz' if c['radio'] == 'na' else '2.4GHz'
        change_desc = ', '.join(
            f'{k}={v}' for k, v in c.items() if k not in ('device_id', 'radio')
        )
        table.add_row(name, radio, change_desc)

    console.print(table)

    if dry_run:
        console.print(f'\n[yellow]DRY RUN[/yellow] — {len(changes)} changes planned')
        console.print('Run with [cyan]--apply[/cyan] to execute')
        console.print(f'A snapshot will be saved to [cyan]{snapshot}[/cyan] before applying')
        return

    # Take snapshot before applying
    console.print(f'\n📸 Saving snapshot to [cyan]{snapshot}[/cyan]...')
    asyncio.run(snapshot_radio_config(output_path=snapshot))

    # Apply
    console.print('⚡ Applying changes...')
    results = asyncio.run(apply_radio_config(changes, dry_run=False))

    for r in results:
        status = r['status']
        icon = '✅' if status == 'APPLIED' else '❌'
        console.print(f'  {icon} {r["name"]} ({r["radio"]}): {status}')

    console.print(f'\n💡 To revert: [cyan]unifi-mapper radio restore --snapshot {snapshot}[/cyan]')


@radio_app.command('restore')
def radio_restore(
    snapshot_path: str = typer.Option(
        'reports/radio-snapshot.json', '--snapshot', '-s', help='Snapshot file to restore from'
    ),
    dry_run: bool = typer.Option(
        True, '--dry-run/--apply', help='Preview restore without applying'
    ),
):
    """🔄 Restore radio config from a snapshot file."""
    import asyncio
    from unifi_mapper.analysis.radio_config import restore_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print('🔄 [bold]Radio Configuration Restore[/bold]\n')
    console.print(f'Snapshot: [cyan]{snapshot_path}[/cyan]\n')

    results = asyncio.run(restore_radio_config(snapshot_path, dry_run=dry_run))

    for r in results:
        status = r['status']
        if 'DRY_RUN' in status:
            icon = '🔍'
        elif 'RESTORED' in status:
            icon = '✅'
        else:
            icon = '❌'
        console.print(f'  {icon} {r["name"]}: {status}')

    if dry_run:
        console.print('\n[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to restore')


# ─── Radio Channel Optimiser Commands ────────────────────────────────────────


@radio_app.command('auto-channel')
def radio_auto_channel(
    band: str = typer.Option(
        'both', '--band', '-b', help='Band to optimise: 5ghz, 2.4ghz, or both'
    ),
    dry_run: bool = typer.Option(
        True, '--dry-run/--apply', help='Preview changes without applying'
    ),
    report_file: Optional[str] = typer.Option(
        None, '--report', '-r', help='Write markdown report to file'
    ),
):
    """📶 Auto-optimise channel assignments based on utilization data."""
    import asyncio
    from pathlib import Path
    from rich.table import Table
    from unifi_mapper.analysis.channel_optimiser import (
        analyze_channels,
        format_report_markdown,
        generate_report,
        optimize_5ghz,
        optimize_24ghz,
    )
    from unifi_mapper.analysis.radio_config import apply_radio_config, snapshot_radio_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print('📶 [bold]Auto-Channel Optimiser[/bold]\n')

    # Analyze current state
    channel_state = asyncio.run(analyze_channels())
    aps = channel_state['aps']
    nb = channel_state.get('neighbour_scores', {})

    # Generate recommendations
    rec_5 = optimize_5ghz(aps, neighbour_data=nb.get('5ghz')) if band in ('5ghz', 'both') else []
    rec_24 = (
        optimize_24ghz(aps, neighbour_data=nb.get('24ghz')) if band in ('2.4ghz', 'both') else []
    )
    console.print(
        f'📡 Neighbour data: {len(nb.get("5ghz", {}))} 5GHz channels, {len(nb.get("24ghz", {}))} 2.4GHz channels scored'
    )
    report = generate_report(channel_state, rec_5, rec_24)

    # Display table
    if rec_5:
        table5 = Table(title='5GHz Channel Plan')
        table5.add_column('AP', style='cyan')
        table5.add_column('Current')
        table5.add_column('Recommended')
        table5.add_column('Util', justify='right')
        table5.add_column('Action')
        for r in rec_5:
            action = '[yellow]CHANGE[/yellow]' if r['change_needed'] else '[green]keep[/green]'
            table5.add_row(
                r['name'],
                f'Ch {r["current_channel"]}',
                f'Ch {r["recommended_channel"]}',
                f'{r["current_utilization"]}%',
                action,
            )
        console.print(table5)
        console.print()

    if rec_24:
        table24 = Table(title='2.4GHz Channel Plan')
        table24.add_column('AP', style='cyan')
        table24.add_column('Current')
        table24.add_column('Recommended')
        table24.add_column('Util', justify='right')
        table24.add_column('Action')
        for r in rec_24:
            action = '[yellow]CHANGE[/yellow]' if r['change_needed'] else '[green]keep[/green]'
            table24.add_row(
                r['name'],
                f'Ch {r["current_channel"]}',
                f'Ch {r["recommended_channel"]}',
                f'{r["current_utilization"]}%',
                action,
            )
        console.print(table24)

    # Summary
    changes_5 = [r for r in rec_5 if r['change_needed']]
    changes_24 = [r for r in rec_24 if r['change_needed']]
    total = len(changes_5) + len(changes_24)
    console.print(
        f'\n{"⚡" if total else "✅"} {total} changes needed '
        f'(5GHz: {len(changes_5)}, 2.4GHz: {len(changes_24)})'
    )

    # Write markdown report
    if report_file:
        md = format_report_markdown(report)
        Path(report_file).parent.mkdir(parents=True, exist_ok=True)
        Path(report_file).write_text(md)
        console.print(f'📄 Report saved to [green]{report_file}[/green]')

    if dry_run or total == 0:
        if total and dry_run:
            console.print('\n[yellow]DRY RUN[/yellow] — run with [cyan]--apply[/cyan] to execute')
        return

    # Snapshot before applying
    console.print('\n📸 Saving snapshot...')
    asyncio.run(snapshot_radio_config(output_path='reports/radio-pre-autochannel.json'))

    # Build change list
    changes = []
    for r in changes_5:
        changes.append(
            {'device_id': r['device_id'], 'radio': 'na', 'channel': r['recommended_channel']}
        )
    for r in changes_24:
        changes.append(
            {'device_id': r['device_id'], 'radio': 'ng', 'channel': r['recommended_channel']}
        )

    # Apply
    console.print('⚡ Applying channel changes...')
    results = asyncio.run(apply_radio_config(changes, dry_run=False))
    for r in results:
        icon = '✅' if r['status'] == 'APPLIED' else '❌'
        console.print(f'  {icon} {r["name"]} ({r["radio"]}): {r["status"]}')

    console.print(
        '\n💡 To revert: [cyan]unifi-mapper radio restore -s reports/radio-pre-autochannel.json --apply[/cyan]'
    )


@radio_app.command('report')
def radio_report(
    output: str = typer.Option(
        'reports/channel-report.md', '--output', '-o', help='Output markdown file'
    ),
):
    """📄 Generate a channel utilization report (table + markdown)."""
    import asyncio
    from pathlib import Path
    from rich.table import Table
    from unifi_mapper.analysis.channel_optimiser import (
        analyze_channels,
        format_report_markdown,
        generate_report,
        optimize_5ghz,
        optimize_24ghz,
    )

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    console.print('📄 [bold]Channel Report[/bold]\n')

    channel_state = asyncio.run(analyze_channels())
    aps = channel_state['aps']
    rec_5 = optimize_5ghz(aps)
    rec_24 = optimize_24ghz(aps)
    report = generate_report(channel_state, rec_5, rec_24)

    # Display current state table
    table = Table(title='Current Channel Utilization')
    table.add_column('AP', style='cyan')
    table.add_column('2.4GHz Ch')
    table.add_column('2.4GHz Util', justify='right')
    table.add_column('5GHz Ch')
    table.add_column('5GHz Util', justify='right')
    table.add_column('5GHz Width')

    for ap in sorted(aps, key=lambda a: a['name']):
        r24 = ap['radios'].get('2.4GHz', {})
        r5 = ap['radios'].get('5GHz', {})
        table.add_row(
            ap['name'],
            str(r24.get('channel', '—')),
            f'{r24.get("utilization", 0)}%',
            str(r5.get('channel', '—')),
            f'{r5.get("utilization", 0)}%',
            f'{r5.get("ht", "?")}MHz',
        )

    console.print(table)

    # Write markdown
    md = format_report_markdown(report)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(md)
    console.print(f'\n📄 Markdown report saved to [green]{output}[/green]')
    console.print(
        f'   Changes needed: 5GHz={report["summary"]["changes_5ghz"]}, '
        f'2.4GHz={report["summary"]["changes_24ghz"]}'
    )


# ─── Link Error Tracking Commands ────────────────────────────────────────────


@analyze_app.command('link-errors')
def analyze_link_errors(
    snapshot: bool = typer.Option(
        False,
        '--snapshot',
        help='Set the comparison baseline: writes the link-error and port-counter baselines',
    ),
    record: bool = typer.Option(
        False,
        '--record',
        help='Append one counter snapshot of every switch port to the history',
    ),
    baseline: Optional[str] = typer.Option(
        None,
        '--baseline',
        '-b',
        callback=_path_not_a_flag,
        help=(
            'Baseline file path (default: $XDG_STATE_HOME/unifi_mapper/link-error-baseline.json; '
            'a legacy ./reports/link-error-baseline.json is still read)'
        ),
    ),
    history: Optional[str] = typer.Option(
        None,
        '--history',
        callback=_path_not_a_flag,
        help='History file (default: $XDG_STATE_HOME/unifi_mapper/port-counter-history.jsonl)',
    ),
    retention_days: int = typer.Option(
        14, '--retention-days', min=1, max=365, help='Days of history to keep when recording'
    ),
    threshold: float = typer.Option(
        10.0, '--threshold', '-t', help='Error rate threshold (errors/min)'
    ),
):
    """📈 Track link error rates between snapshots to detect active degradation.

    A plain run only compares against the baseline (read only). --snapshot sets the
    baseline; --record appends to the counter history read by `ports counters`,
    `ports diagnose` and the MCP port tools. Both write only under the XDG state
    directory and can be combined (one controller read).
    """
    import asyncio
    import time
    from datetime import datetime
    from rich.table import Table
    from unifi_mapper.analysis.counter_history import append_history, build_history_records
    from unifi_mapper.analysis.link_error_tracking import (
        compare_link_errors,
        default_link_error_baseline_path,
        fetch_devices,
        snapshot_link_errors,
    )
    from unifi_mapper.analysis.port_counter_baseline import default_baseline_path

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot or record:
        try:
            devices = asyncio.run(fetch_devices())
        except Exception as e:  # noqa: BLE001 - any read failure ends the command cleanly
            from .core.utils.redact import redact_text

            _fail(f'Error: {redact_text(e)}')
        if snapshot:
            console.print('📸 [bold]Link Error Baseline Snapshot[/bold]\n')
            target = Path(baseline) if baseline else default_link_error_baseline_path()
            result = asyncio.run(snapshot_link_errors(target, devices=devices))
            dev_count = len(result['devices'])
            port_count = sum(len(d['ports']) for d in result['devices'])
            console.print(f'Captured: {dev_count} devices, {port_count} ports')
            console.print(f'Saved to: [green]{escape(str(target))}[/green]')
            console.print(
                f'Port-counter baseline: [green]{escape(str(default_baseline_path()))}[/green]'
            )
            console.print('\n💡 Run again without --snapshot to compare against this baseline')
        if record:
            epoch = time.time()
            taken_at = datetime.fromtimestamp(epoch).astimezone().isoformat()
            records = build_history_records(devices, taken_at=taken_at, epoch=epoch)
            written = append_history(
                records,
                path=Path(history) if history else None,
                retention_days=retention_days,
                now=epoch,
            )
            held = f', holds {written.span_days:g} days' if written.span_days is not None else ''
            console.print(
                f'🗂️ Recorded {written.records_written} switch(es) to '
                f'[green]{escape(written.path)}[/green] '
                f'(retention {written.retention_days} days, {written.bytes} bytes{held})'
            )
            if written.compacted:
                console.print(
                    f'[dim]   Compacted: dropped {written.dropped_by_age} by age, '
                    f'{written.dropped_by_size} by size, '
                    f'{written.dropped_unparsable} unparsable[/dim]'
                )
        return

    console.print('📈 [bold]Link Error Rate Analysis[/bold]\n')
    try:
        report = asyncio.run(compare_link_errors(baseline, threshold))
    except Exception as e:
        console.print(f'[red]Error:[/red] {_error_text(e)}')
        raise typer.Exit(1)

    if report.get('legacy_baseline'):
        err_console.print(
            f'[yellow]Using the legacy baseline {escape(report["baseline_path"])}; '
            f'run --snapshot to set one at {escape(str(default_link_error_baseline_path()))}'
            '[/yellow]',
            soft_wrap=True,
        )

    console.print(
        f'Baseline: {report["baseline_timestamp"]} '
        f'([dim]{escape(str(report.get("baseline_path", "")))}[/dim])',
        soft_wrap=True,
    )
    console.print(f'Elapsed: {report["elapsed_minutes"]} minutes')
    console.print(f'Ports with new errors: {report["ports_with_new_errors"]}')
    console.print(
        f'Ports flagged (>{threshold}/min): [{"red" if report["ports_flagged"] else "green"}]{report["ports_flagged"]}[/{"red" if report["ports_flagged"] else "green"}]\n'
    )

    # Surface devices that rebooted between snapshots — their counter deltas
    # are suppressed from flagging because the reset to 0 makes rates meaningless.
    rebooted = report.get('rebooted_devices', [])
    if rebooted:
        reboot_names = ', '.join(d['name'] for d in rebooted)
        console.print(
            f'[yellow]⚠️  {len(rebooted)} device(s) rebooted since baseline: {reboot_names}[/yellow]'
        )
        console.print(
            '[dim]   Their port deltas are shown but excluded from flagging (counters reset on boot).[/dim]\n'
        )

    if report['all_deltas']:
        table = Table(title='Error Rate Deltas (top 20)')
        table.add_column('Device', style='cyan')
        table.add_column('Port')
        table.add_column('Errors Δ', justify='right')
        table.add_column('Drops Δ', justify='right')
        table.add_column('Rate/min', justify='right')
        table.add_column('Status')

        for d in report['all_deltas']:
            rate = d['rate_per_min']
            if d.get('reboot_detected'):
                status = '[yellow]🔄 REBOOT[/yellow]'
            elif rate > 100:
                status = '[red]🚨 CRITICAL[/red]'
            elif rate >= threshold:
                status = '[yellow]⚠️ WARNING[/yellow]'
            else:
                status = '[green]OK[/green]'
            table.add_row(
                d['device'],
                d['port_name'],
                str(d['rx_errors_delta'] + d['tx_errors_delta']),
                str(d['rx_dropped_delta'] + d['tx_dropped_delta']),
                f'{rate:.1f}',
                status,
            )
        console.print(table)
    else:
        console.print('[green]✅ No new errors since baseline[/green]')


# ─── Client Roaming Commands ─────────────────────────────────────────────────


@analyze_app.command('roaming')
def analyze_roaming_cmd(
    snapshot: bool = typer.Option(False, '--snapshot', help='Record current client associations'),
    history: str = typer.Option(
        'reports/client-roaming-history.json', '--history', '-h', help='History file path'
    ),
):
    """📡 Analyze client roaming patterns and detect sticky clients."""
    import asyncio
    from rich.table import Table
    from unifi_mapper.analysis.roaming_analysis import (
        analyze_roaming,
        snapshot_client_associations,
    )

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot:
        console.print('📸 [bold]Client Association Snapshot[/bold]\n')
        result = asyncio.run(snapshot_client_associations(history))
        console.print(f'Clients tracked: {result["clients_tracked"]}')
        console.print(f'Snapshots stored: {result["snapshots_stored"]}')
        console.print(f'History: [green]{history}[/green]')
        console.print('\n💡 Run periodically (every 5 min) to build roaming history')
        return

    console.print('📡 [bold]Client Roaming Analysis[/bold]\n')
    try:
        report = asyncio.run(analyze_roaming(history))
    except Exception as e:
        console.print(f'[red]Error:[/red] {_error_text(e)}')
        raise typer.Exit(1)

    console.print(f'Snapshots analyzed: {report["snapshots_analyzed"]}')
    console.print(f'Time span: {report["time_span"]}')
    console.print(f'Clients tracked: {report["clients_tracked"]}')
    console.print(f'Roaming clients: {report["roaming_clients"]}')
    console.print(f'Sticky clients: {report["sticky_clients"]}\n')

    if report['roamers']:
        table = Table(title='Roaming Clients')
        table.add_column('Client', style='cyan')
        table.add_column('Transitions', justify='right')
        table.add_column('APs Used')
        table.add_column('Avg RSSI', justify='right')

        for r in report['roamers'][:15]:
            table.add_row(
                r['client'], str(r['transitions']), ', '.join(r['aps_used']), str(r['avg_rssi'])
            )
        console.print(table)

    if report['sticky']:
        console.print()
        table = Table(title='Sticky Clients (low RSSI, not roaming)')
        table.add_column('Client', style='cyan')
        table.add_column('Stuck On')
        table.add_column('Avg RSSI', justify='right')
        table.add_column('Min RSSI', justify='right')

        for s in report['sticky']:
            table.add_row(
                s['client'], s['stuck_on'], str(s['avg_rssi']), f'[red]{s["min_rssi"]}[/red]'
            )
        console.print(table)


# ─── Configuration Drift Commands ────────────────────────────────────────────


@analyze_app.command('config-drift')
def analyze_config_drift(
    snapshot: bool = typer.Option(False, '--snapshot', help='Take a config baseline snapshot'),
    baseline: str = typer.Option(
        'reports/config-baseline.json', '--baseline', '-b', help='Baseline file path'
    ),
):
    """🔍 Detect configuration drift from baseline (catches manual UI changes)."""
    import asyncio
    from rich.table import Table
    from unifi_mapper.analysis.config_drift import detect_drift, snapshot_config

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if snapshot:
        console.print('📸 [bold]Configuration Baseline Snapshot[/bold]\n')
        result = asyncio.run(snapshot_config(baseline))
        console.print(f'Devices captured: {len(result["devices"])}')
        console.print(f'Saved to: [green]{baseline}[/green]')
        console.print('\n💡 Run without --snapshot to detect drift from this baseline')
        return

    console.print('🔍 [bold]Configuration Drift Detection[/bold]\n')
    try:
        report = asyncio.run(detect_drift(baseline))
    except Exception as e:
        console.print(f'[red]Error:[/red] {_error_text(e)}')
        raise typer.Exit(1)

    console.print(f'Baseline: {report["baseline_timestamp"]}')
    console.print(f'Devices checked: {report["devices_checked"]}')
    console.print(
        f'Drifts detected: [{"red" if report["drifts_detected"] else "green"}]{report["drifts_detected"]}[/{"red" if report["drifts_detected"] else "green"}]\n'
    )

    if report['drifts']:
        table = Table(title='Configuration Drifts')
        table.add_column('Device', style='cyan')
        table.add_column('Field')
        table.add_column('Type')
        table.add_column('Details')

        for drift in report['drifts']:
            dtype = drift['type']
            style = '[red]' if dtype == 'REMOVED' else '[yellow]'
            if dtype == 'CHANGED':
                details = 'changed'
            elif dtype == 'REMOVED':
                details = 'field removed'
            else:
                details = drift.get('details', '')
            table.add_row(drift['device'], drift.get('field', '—'), f'{style}{dtype}[/]', details)
        console.print(table)
    else:
        console.print('[green]✅ No configuration drift detected[/green]')


# ─── Neighbour AP Scan Commands ──────────────────────────────────────────────


@analyze_app.command('neighbours')
def analyze_neighbours(
    ap_name: Optional[str] = typer.Option(
        None, '--ap', '-a', help='Specific AP to scan (default: all)'
    ),
    cached: bool = typer.Option(False, '--cached', help='DEPRECATED: no-op, data is always fresh'),
    snapshot: bool = typer.Option(
        False, '--snapshot', help='Capture current neighbour landscape as a baseline'
    ),
    diff: bool = typer.Option(
        False, '--diff', help='Compare current landscape against the baseline snapshot'
    ),
    baseline: str = typer.Option(
        'reports/neighbour-baseline.json', '--baseline', '-b', help='Baseline snapshot file path'
    ),
    signal_delta: int = typer.Option(
        10, '--signal-delta', help='dB change threshold for signal-change flagging'
    ),
):
    """📡 Scan for neighbouring APs and external interference sources."""
    import asyncio
    from rich.table import Table
    from unifi_mapper.analysis.neighbour_scan import scan_neighbours
    from unifi_mapper.analysis.neighbour_trend import (
        detect_neighbour_trend,
        snapshot_neighbours,
    )

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    if cached:
        console.print(
            '[yellow]⚠️  --cached is deprecated (neighbour data is now always fresh). Flag will be removed in a future release.[/yellow]'
        )

    # ── Snapshot mode ────────────────────────────────────────────────────
    if snapshot:
        console.print('📸 [bold]Neighbour Baseline Snapshot[/bold]\n')
        result = asyncio.run(snapshot_neighbours(baseline))
        console.print(f'Captured: {result["entry_count"]} neighbour entries')
        console.print(f'Saved to: [green]{baseline}[/green]')
        console.print('\n💡 Run again with --diff to compare future scans against this baseline')
        return

    # ── Diff mode ────────────────────────────────────────────────────────
    if diff:
        console.print('📊 [bold]Neighbour Landscape Trend[/bold]\n')
        try:
            report = asyncio.run(detect_neighbour_trend(baseline, signal_delta))
        except Exception as e:
            console.print(f'[red]Error:[/red] {_error_text(e)}')
            raise typer.Exit(1)

        console.print(f'Baseline: {report["baseline_timestamp"]}')
        console.print(f'Current:  {report["current_timestamp"]}\n')

        summary = (
            f'[green]New: {report["new_count"]}[/green]   '
            f'[red]Disappeared: {report["disappeared_count"]}[/red]   '
            f'[yellow]Channel-moved: {report["moved_count"]}[/yellow]   '
            f'[cyan]Signal-changed (≥{signal_delta} dB): {report["signal_changed_count"]}[/cyan]'
        )
        console.print(summary + '\n')

        # New neighbours
        if report['new']:
            table = Table(show_header=True, title='🆕 New Neighbours')
            table.add_column('SSID')
            table.add_column('Channel', justify='right')
            table.add_column('Signal (dBm)', justify='right')
            table.add_column('Detecting AP (MAC)', style='dim')
            table.add_column('BSSID', style='dim')
            for n in report['new'][:15]:
                sig = n.get('signal', -100)
                style = 'red' if sig > -50 else 'yellow' if sig > -70 else 'green'
                table.add_row(
                    n.get('essid') or '<hidden>',
                    str(n.get('channel', '?')),
                    f'[{style}]{sig}[/{style}]',
                    n.get('ap_mac', ''),
                    n.get('bssid', ''),
                )
            console.print(table)

        # Disappeared neighbours
        if report['disappeared']:
            table = Table(show_header=True, title='👋 Disappeared Neighbours')
            table.add_column('SSID')
            table.add_column('Channel', justify='right')
            table.add_column('Signal (dBm)', justify='right')
            table.add_column('BSSID', style='dim')
            for n in report['disappeared'][:15]:
                table.add_row(
                    n.get('essid') or '<hidden>',
                    str(n.get('channel', '?')),
                    str(n.get('signal', -100)),
                    n.get('bssid', ''),
                )
            console.print(table)

        # Channel moves
        if report['moved']:
            table = Table(show_header=True, title='🔀 Channel Moves')
            table.add_column('SSID')
            table.add_column('From', justify='right')
            table.add_column('To', justify='right')
            table.add_column('Signal (dBm)', justify='right')
            table.add_column('BSSID', style='dim')
            for m in report['moved'][:15]:
                table.add_row(
                    m.get('essid') or '<hidden>',
                    str(m.get('from_channel', '?')),
                    str(m.get('to_channel', '?')),
                    str(m.get('signal', -100)),
                    m.get('bssid', ''),
                )
            console.print(table)

        # Signal changes
        if report['signal_changes']:
            table = Table(show_header=True, title=f'📶 Signal Changes (≥{signal_delta} dB)')
            table.add_column('SSID')
            table.add_column('Channel', justify='right')
            table.add_column('Before', justify='right')
            table.add_column('After', justify='right')
            table.add_column('Δ dB', justify='right')
            table.add_column('BSSID', style='dim')
            for s in report['signal_changes'][:15]:
                delta = s.get('delta_db', 0)
                style = 'green' if delta > 0 else 'red'
                table.add_row(
                    s.get('essid') or '<hidden>',
                    str(s.get('channel', '?')),
                    str(s.get('signal_before', -100)),
                    str(s.get('signal_after', -100)),
                    f'[{style}]{delta:+d}[/{style}]',
                    s.get('bssid', ''),
                )
            console.print(table)

        if (
            report['new_count'] == 0
            and report['disappeared_count'] == 0
            and report['moved_count'] == 0
            and report['signal_changed_count'] == 0
        ):
            console.print(
                '[green]✅ No significant neighbour landscape changes since baseline[/green]'
            )
        return

    # ── Default: live scan ───────────────────────────────────────────────
    console.print('📡 [bold]Neighbour AP Scan[/bold]\n')

    report = asyncio.run(scan_neighbours(ap_name=ap_name))

    if not report['aps']:
        console.print('[yellow]No neighbour data available.[/yellow]')
        return

    for ap_entry in report['aps']:
        ap_display = ap_entry['ap_name']
        total = ap_entry['total_neighbours']
        console.print(f'\n[bold]{ap_display}[/bold] — {total} neighbours')

        # Channel summary
        ch_summary = ap_entry.get('channel_summary', {})
        if ch_summary:
            ch_str = ', '.join(f'ch{ch}:{count}' for ch, count in sorted(ch_summary.items()))
            console.print(f'  Channels: {ch_str}')

        # Strongest neighbours (by signal dBm)
        strongest = ap_entry.get('strongest', [])
        if strongest:
            table = Table(show_header=True, title=f'Strongest Neighbours ({ap_display})')
            table.add_column('SSID')
            table.add_column('Channel', justify='right')
            table.add_column('Signal (dBm)', justify='right')
            table.add_column('BSSID', style='dim')

            for n in strongest[:10]:
                signal = n.get('signal', -100)
                style = 'red' if signal > -50 else 'yellow' if signal > -70 else 'green'
                table.add_row(
                    n.get('essid', '<hidden>') or '<hidden>',
                    str(n.get('channel', '?')),
                    f'[{style}]{signal}[/{style}]',
                    n.get('bssid', ''),
                )
            console.print(table)


# ─── Bandwidth Test Commands ─────────────────────────────────────────────────


GATEWAY_SSH_NOTICE = (
    "⚠ This command runs on the gateway over SSH as the SSH user, and the gateway's host key "
    'is not verified (issue 038).'
)


def _run_gateway_ssh[T](run: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run one gateway SSH diagnostic; report a failure on stderr as text, never a traceback.

    Its controller reads run behind the read-only transport (``_guarded``). The host-key
    notice goes to stderr first, once per invocation. Typer's traceback prints every frame's
    local variables, which here include the SSH password. A ``ToolError`` prints with its
    code and suggestion; anything else, redacted.
    """
    import asyncio
    from .core.utils.errors import ToolError
    from .core.utils.redact import redact_text

    if not state.ssh_notice_shown:
        state.ssh_notice_shown = True
        err_console.print(GATEWAY_SSH_NOTICE, style='yellow', markup=False, soft_wrap=True)
    try:
        return asyncio.run(_guarded(run))
    except ToolError as e:
        _fail(e)
    except Exception as e:  # noqa: BLE001 - every failure ends the command cleanly
        if state.debug:
            _print_debug_traceback(err_console)
        _fail(f'Error: {redact_text(e)}')


@diagnose_app.command('bandwidth')
def diagnose_bandwidth(
    target: str = typer.Argument(..., help='Target IP running iperf3 -s'),
    duration: int = typer.Option(10, '--duration', '-d', help='Test duration in seconds'),
    reverse: bool = typer.Option(
        False, '--reverse', '-R', help='Test download (target→UDM) instead of upload'
    ),
    bidirectional: bool = typer.Option(False, '--bidir', help='Test both directions'),
    parallel: int = typer.Option(1, '--parallel', '-P', help='Number of parallel streams'),
):
    """⚡ Run iperf3 bandwidth test from UDM to a target device."""
    from unifi_mapper.analysis.bandwidth_test import check_bandwidth_args, run_bandwidth_test
    from unifi_mapper.core.utils.errors import ToolError

    try:  # refuse a bad TARGET or number before reading config or connecting
        target, duration, parallel = check_bandwidth_args(target, duration, parallel)
    except ToolError as e:
        _fail(e)

    load_env_from_config(str(state.config_path))
    if not state.debug:
        setup_logging(debug=False)

    def run_test(reverse: bool) -> dict:
        return _run_gateway_ssh(
            lambda: run_bandwidth_test(target, duration, reverse=reverse, parallel=parallel)
        )

    console.print('⚡ [bold]Bandwidth Test (iperf3 via SSH)[/bold]\n')
    console.print(f'Target: [cyan]{target}[/cyan]')
    console.print(f'Duration: {duration}s | Streams: {parallel}\n')

    if bidirectional:
        # Upload
        console.print('▶ Upload (UDM → target)...')
        up = run_test(False)
        if up['status'] == 'OK':
            console.print(
                f'  [green]{up["throughput_mbps"]} Mbps[/green] ({up["throughput_gbps"]} Gbps)'
            )
            if 'retransmits' in up:
                console.print(f'  Retransmits: {up["retransmits"]}')
        else:
            console.print(f'  [red]FAILED: {up.get("error", "unknown")}[/red]')

        # Download
        console.print('\n▼ Download (target → UDM)...')
        down = run_test(True)
        if down['status'] == 'OK':
            console.print(
                f'  [green]{down["throughput_mbps"]} Mbps[/green] ({down["throughput_gbps"]} Gbps)'
            )
            if 'retransmits' in down:
                console.print(f'  Retransmits: {down["retransmits"]}')
        else:
            console.print(f'  [red]FAILED: {down.get("error", "unknown")}[/red]')
    else:
        direction = 'download' if reverse else 'upload'
        console.print(f'{"▼" if reverse else "▶"} Testing {direction}...')
        result = run_test(reverse)

        if result['status'] == 'OK':
            console.print(
                f'\n  [green]{result["throughput_mbps"]} Mbps[/green] ({result["throughput_gbps"]} Gbps)'
            )
            console.print(f'  Direction: {result["direction"]}')
            if 'retransmits' in result:
                console.print(f'  Retransmits: {result["retransmits"]}')
            if 'bytes_transferred' in result:
                gb = result['bytes_transferred'] / 1_073_741_824
                console.print(f'  Transferred: {gb:.2f} GB')
        else:
            console.print(f'\n  [red]FAILED: {result.get("error", "unknown")}[/red]')


# ─── Device stats, AP retries and controller config (read-only) ─────────────


class _Radio(StrEnum):
    """A radio band, as the controller names it."""

    NG = 'ng'
    NA = 'na'
    SIX_E = '6e'


class _ConfigKind(StrEnum):
    """A kind of legacy controller config object."""

    WLANCONF = 'wlanconf'
    NETWORKCONF = 'networkconf'
    SETTING = 'setting'
    APGROUP = 'apgroup'


def _cell(value: Any) -> str:
    """A table cell: the value, or an em dash when it is missing, markup-escaped."""
    return '—' if value is None or value == '' else escape(str(value))


def _print_dim_notes(notes: list[str]) -> None:
    """Print a result's notes, dimmed."""
    for note in notes:
        console.print(f'[dim]{escape(note)}[/dim]')


@diagnose_app.command('device-stats')
def diagnose_device_stats(
    device: str = typer.Argument(..., help='Device name, MAC or IP (any adopted device)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📟 One device's CPU, memory, load, uptime, radios and per-VAP TX counters.

    An exact name or MAC wins over a partial match; an ambiguous name lists the
    candidates. The retry percentage per VAP is cumulative since the AP booted; for an
    interval measurement use diagnose ap-retries. Read-only.
    """
    from .diagnostics.observability import get_device_stats

    stats = _run_analysis(lambda: get_device_stats(device))
    if as_json:
        _emit_json(stats)
        return
    system = stats['system']
    table = Table(title=f'📟 {escape(str(stats["name"] or "?"))}', show_header=False)
    table.add_column('Metric', style='cyan')
    table.add_column('Value')
    table.add_row('Model / type', f'{_cell(stats["model"])} / {_cell(stats["type"])}')
    table.add_row('Online', 'yes' if stats['online'] else '[red]no[/red]')
    table.add_row('IP', _cell(stats['ip']))
    table.add_row('Firmware', _cell(stats['firmware']))
    table.add_row('Uptime (s)', _cell(stats['uptime_seconds']))
    table.add_row('CPU / memory %', f'{_cell(system["cpu_pct"])} / {_cell(system["mem_pct"])}')
    table.add_row('Load (1 min)', _cell(system['loadavg_1']))
    console.print(table)
    if stats['radios']:
        radios = Table(title='Radios', show_header=True)
        for column in ('Radio', 'Channel', 'Utilisation %', 'TX power', 'Clients'):
            radios.add_column(column)
        for r in stats['radios']:
            radios.add_row(
                _cell(r['radio']),
                _cell(r['channel']),
                _cell(r['cu_total']),
                _cell(r['tx_power']),
                _cell(r['num_sta']),
            )
        console.print(radios)
    if stats['vaps']:
        vaps = Table(title='VAPs', show_header=True)
        for column in ('SSID', 'Radio', 'Channel', 'Clients', 'TX packets', 'Retry %'):
            vaps.add_column(column)
        for v in stats['vaps']:
            vaps.add_row(
                _cell(v['essid']),
                _cell(v['radio']),
                _cell(v['channel']),
                str(v['num_sta']),
                str(v['tx_packets']),
                _cell(v['retry_pct_cumulative']),
            )
        console.print(vaps)
    _print_dim_notes(stats['notes'])


@diagnose_app.command('ap-retries')
def diagnose_ap_retries(
    essid: Optional[str] = typer.Option(
        None, '--essid', help='Only this SSID (default every SSID)'
    ),
    radio: _Radio = typer.Option(
        _Radio.NG, '--radio', case_sensitive=False, help='ng (2.4 GHz), na (5 GHz) or 6e (6 GHz)'
    ),
    interval: int = typer.Option(
        30, '--interval', min=10, max=240, help='Seconds between the two device reads (10-240)'
    ),
    threshold: float = typer.Option(
        10.0, '--threshold', min=0, max=100, help='Flag a VAP above this retry % (0-100)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📶 Every AP's per-VAP TX retry rate over an interval, from two device reads.

    Waits --interval seconds between the reads (default 30, at most 240) and computes the
    reset-aware retry percentage per VAP: an AP that rebooted in between counts from
    zero. A VAP above --threshold is flagged; healthy VAPs run below 5 to 10%. Read-only.
    """
    from .diagnostics.observability import get_ap_retry_rates

    err_console.print(f'⏳ Reading every AP twice, {interval}s apart…')
    result = _run_analysis(
        lambda: get_ap_retry_rates(
            essid=essid,
            radio=cast(Any, radio.value),
            interval_seconds=interval,
            threshold_pct=threshold,
        )
    )
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f'📶 Retry rates ({result["radio"]}, {interval}s)', show_header=True)
    for column in ('AP', 'SSID', 'Channel', 'Clients', 'Δ TX packets', 'Retry %'):
        table.add_column(column)
    for ap in result['aps']:
        for vap in ap['vaps']:
            pct = _cell(vap['retry_pct'])
            table.add_row(
                _cell(ap['ap']),
                _cell(vap['essid']),
                _cell(vap['channel']),
                _cell(vap['num_sta']),
                str(vap['delta_tx_packets']),
                f'[red]{pct}[/red]' if vap['unhealthy'] else pct,
            )
    console.print(table)
    if result['healthy']:
        console.print(f'✅ No VAP above {threshold:g}% retries.')
    else:
        console.print(f'[red]⚠ {len(result["flagged"])} VAP(s) above {threshold:g}%[/red]')
    _print_dim_notes(result['notes'])


@diagnose_app.command('wan')
def diagnose_wan(
    record: bool = typer.Option(
        False, '--record', help="Append the controller's last speedtest result to the history"
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🌐 WAN and internet health, and the controller's last scheduled speedtest.

    One read of the controller's health summary: ISP, WAN IP, gateway version, latency,
    drops and the result of the controller's own scheduled speedtest. Never starts a
    speedtest. --record appends that result to a history file under the XDG state
    directory (skipped when the run is already recorded); diagnose wan-history lists it.
    Read-only towards the controller.
    """
    from .diagnostics.wan_health import get_wan_health

    report = _run_analysis(get_wan_health)
    if as_json:
        _emit_json(report)
    else:
        wan, www, speedtest = report['wan'], report['www'], report['last_speedtest']
        table = Table(title='🌐 WAN health', show_header=False)
        table.add_column('Metric', style='cyan')
        table.add_column('Value')
        style = 'green' if report['healthy'] else 'red'
        table.add_row('Healthy', f'[{style}]{"yes" if report["healthy"] else "no"}[/]')
        table.add_row('WAN / internet', f'{_cell(wan["status"])} / {_cell(www["status"])}')
        table.add_row('ISP', _cell(wan['isp_name']))
        table.add_row('WAN IP', _cell(wan['wan_ip']))
        table.add_row('Gateway version', _cell(wan['gw_version']))
        table.add_row(
            'Latency (ms) / drops', f'{_cell(www["latency_ms"])} / {_cell(www["drops"])}'
        )
        if speedtest:
            table.add_row(
                'Last speedtest',
                f'↓ {_cell(speedtest["down_mbps"])} / ↑ {_cell(speedtest["up_mbps"])} Mbps, '
                f'{_cell(speedtest["ping_ms"])} ms ({_cell(speedtest["status"])})',
            )
        else:
            table.add_row('Last speedtest', '—')
        console.print(table)
        _print_dim_notes(report['notes'])
    if record:
        _record_speedtest(report['last_speedtest'])


def _record_speedtest(speedtest: Optional[JsonDict]) -> None:
    """Append the last speedtest to the history; report the outcome on stderr only."""
    from .diagnostics.wan_history import append_speedtest, default_speedtest_history_path

    if not speedtest:
        err_console.print('Nothing to record: the controller reports no speedtest result.')
        return
    path = default_speedtest_history_path()
    try:
        written = append_speedtest(speedtest, path)
    except OSError as e:
        reason = e.strerror or type(e).__name__
        err_console.print(
            f'[yellow]⚠ Not recorded: {escape(str(path))}: {escape(reason)}[/yellow]',
            soft_wrap=True,
        )
        return
    if written is None:
        err_console.print('Nothing to record: the last speedtest has no run time.')
    elif written.lines_written == 0:
        err_console.print('Already recorded: that speedtest run is in the history.')
    else:
        err_console.print(f'Recorded the speedtest in {escape(str(path))}', soft_wrap=True)


@diagnose_app.command('wan-history')
def diagnose_wan_history(
    limit: int = typer.Option(
        20, '--limit', min=1, max=1000, help='Show at most this many results (1-1000)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """📈 The WAN speedtest results recorded by diagnose wan --record, newest first.

    Reads the history file under the XDG state directory; contacts nothing. Read-only.
    """
    from .diagnostics.wan_history import read_speedtest_history

    with _offline_errors():
        history = read_speedtest_history(limit=limit)
    if as_json:
        _emit_json(history)
        return
    if not history['entries']:
        err_console.print(escape(history['note']), soft_wrap=True)
        return
    from datetime import UTC, datetime

    table = Table(title=f'📈 WAN speedtests ({history["returned"]} of {history["total"]})')
    for column in ('Run (UTC)', 'Down Mbps', 'Up Mbps', 'Ping ms', 'Status'):
        table.add_column(column)
    for entry in history['entries']:
        run = datetime.fromtimestamp(entry['epoch'], tz=UTC).isoformat(timespec='minutes')
        table.add_row(
            run,
            _cell(entry.get('down_mbps')),
            _cell(entry.get('up_mbps')),
            _cell(entry.get('ping_ms')),
            _cell(entry.get('status')),
        )
    console.print(table)


@backup_app.command('verify')
def backup_verify(
    path: str = typer.Argument(..., help='The .unf backup file (relative paths and ~ work)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """💾 Check a downloaded config backup (.unf) offline: structure only.

    Decrypts the backup with the controller's fixed backup key, extracts and decompresses
    the database (each capped at 1 GiB, the database at 64 gzip members) and counts the
    documents in each collection; a truncated or corrupt database is not valid. Prints no
    document contents and contacts no controller. The file must end in .unf, be a regular
    file and be at most 512 MiB. Exits 0 when the backup is valid, 1 when it is not.
    Read-only.
    """
    from .backup.verify import BACKUP_SUFFIX, check_backup_path, verify_backup_file
    from .core.utils.errors import ErrorCodes, ToolError

    with _offline_errors():
        if Path(path).suffix.lower() != BACKUP_SUFFIX:  # before any filesystem call
            raise ToolError(
                message='the backup must be a .unf file', error_code=ErrorCodes.CONFIG_INVALID
            )
        checked = check_backup_path(Path(path).expanduser().resolve(), require_absolute=True)
        result = verify_backup_file(checked)
    if as_json:
        _emit_json(result)
    else:
        style = 'green' if result['valid'] else 'red'
        verdict = 'valid' if result['valid'] else 'NOT valid'
        console.print(f'💾 {escape(result["path"])}: [{style}]{verdict}[/]', soft_wrap=True)
        table = Table(title='Collections', show_header=True)
        table.add_column('Collection', style='cyan')
        table.add_column('Documents', justify='right')
        for name, count in result['collections'].items():
            table.add_row(escape(name), str(count))
        console.print(table)
        missing = [k for k, present in result['key_sections_present'].items() if not present]
        if missing and result['valid']:
            console.print(f'[yellow]⚠ Missing key sections: {escape(", ".join(missing))}[/]')
        for error in result['errors']:
            err_console.print(f'[red]{escape(error["stage"])}: {escape(error["error"])}[/red]')
    if not result['valid']:
        raise typer.Exit(1)


@controller_app.command('config')
def controller_config(
    kind: _ConfigKind = typer.Argument(
        ..., case_sensitive=False, help='wlanconf, networkconf, setting or apgroup'
    ),
    name: Optional[str] = typer.Option(
        None, '--name', help='Only objects whose name (key for settings) contains this'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print the objects as JSON'),
):
    """🗂️ The controller's raw config objects of one kind, with every secret removed.

    Secret keys (passphrases, PSKs, SNMP communities, syslog keys and the rest) are
    removed, never shown; --json lists their paths in sanitised_paths. Each object gains
    created_utc, the creation time its ID records. Read-only.
    """
    from .diagnostics.observability import get_config_object

    result = _run_analysis(lambda: get_config_object(kind=cast(Any, kind.value), name=name))
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f'🗂️ {result["kind"]} ({result["count"]})', show_header=True)
    for column in ('Name', 'ID', 'Created (UTC)', 'Fields'):
        table.add_column(column)
    name_key = 'key' if result['kind'] == 'setting' else 'name'
    for obj in result['objects']:
        table.add_row(
            _cell(obj.get(name_key) or obj.get('name')),
            _cell(obj.get('_id')),
            _cell(obj.get('created_utc')),
            str(len(obj)),
        )
    console.print(table)
    removed = len(result['sanitised_paths'])
    console.print(f'{removed} secret key(s) removed; --json lists them by path.')
    _print_dim_notes(result['notes'])


@controller_app.command('events')
def controller_events(
    since_hours: int = typer.Option(24, '--since-hours', help='Hours back from now (1-8760)'),
    category: Optional[str] = typer.Option(
        None, '--category', help='Only this category (system-log category or event subsystem)'
    ),
    severity: Optional[str] = typer.Option(
        None, '--severity', help='Only this system-log severity'
    ),
    contains: Optional[str] = typer.Option(
        None, '--contains', help='Only entries whose key, message or record contains this'
    ),
    max_events: int = typer.Option(
        100, '--max-events', help='Keep at most this many entries, newest first (1-1000)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of tables'),
):
    """📜 Site-wide events, alarms and system-log entries from the last --since-hours.

    Reads stat/event, list/alarm and the v2 system-log classes (device-alert,
    admin-activity, update-alert, client-alert) for the whole site, newest first, with
    every secret key removed. Admin edits are in admin-activity. For one device, port
    or client, use ports events. Read-only: the POSTs are query endpoints on an
    allowlist.
    """
    from .port_diagnostics_render import render_recent_events
    from .port_history import collect_recent_events, validate_recent_window

    with _diagnostic_errors():
        validate_recent_window(since_hours, max_events)  # exit 2 before connecting
        with _readonly_client() as (client, site):
            recent = collect_recent_events(
                client,
                site,
                since_hours=since_hours,
                category=category,
                severity=severity,
                contains=contains,
                max_events=max_events,
            )
    if as_json:
        _emit_json(recent.to_json_dict())
    else:
        render_recent_events(console, recent)


@controller_app.command('config-changes')
def controller_config_changes(
    since_hours: int = typer.Option(
        24, '--since-hours', min=1, max=8760, help='Hours back from now (1-8760)'
    ),
    kinds: Optional[list[_ConfigKind]] = typer.Option(
        None,
        '--kind',
        case_sensitive=False,
        help='A config kind to search; repeat for more (default all four)',
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🕑 Config objects created in the last --since-hours, newest first.

    Reads the WLAN, network, setting and AP-group objects and decodes the creation time
    each ID records. Creation only: an edit to an older object does not appear here.
    Read-only.
    """
    from .diagnostics.observability import find_recent_config_changes

    chosen = None if kinds is None else [cast(Any, k.value) for k in kinds]
    result = _run_analysis(
        lambda: find_recent_config_changes(since_hours=since_hours, kinds=chosen)
    )
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f'🕑 Created in the last {since_hours}h ({result["count"]})')
    for column in ('Created (UTC)', 'Age (h)', 'Kind', 'Name', 'ID'):
        table.add_column(column)
    for change in result['changes']:
        table.add_row(
            _cell(change['created_utc']),
            _cell(change['age_hours']),
            _cell(change['kind']),
            _cell(change['name']),
            _cell(change['id']),
        )
    console.print(table)
    _print_dim_notes(result['notes'])


# ─── Gateway probes (class B: SSH, CLI only) ─────────────────────────────────


class _FlowState(StrEnum):
    """A conntrack state or flag ``gateway flows --state`` filters on."""

    ESTABLISHED = 'ESTABLISHED'
    SYN_SENT = 'SYN_SENT'
    SYN_RECV = 'SYN_RECV'
    FIN_WAIT = 'FIN_WAIT'
    CLOSE_WAIT = 'CLOSE_WAIT'
    LAST_ACK = 'LAST_ACK'
    TIME_WAIT = 'TIME_WAIT'
    CLOSE = 'CLOSE'
    UNREPLIED = 'UNREPLIED'
    ASSURED = 'ASSURED'


def _probe[T](run: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Load the config, then run one gateway probe through ``_run_gateway_ssh``."""
    load_env_from_config(str(state.config_path or get_default_config_path()))
    return _run_gateway_ssh(run)


@gateway_app.command('ping')
def gateway_ping_command(
    target: str = typer.Argument(
        ..., help='An IP, or a device or client name, hostname or MAC (or a unique part of a name)'
    ),
    count: int = typer.Option(10, '--count', min=1, max=100, help='Echo requests (1-100)'),
    interval: float = typer.Option(
        0.3, '--interval', min=0.2, max=5.0, help='Seconds between requests (0.2-5.0)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """📡 Ping one target from the gateway over SSH: loss and round trips.

    A name is resolved to its address through the read-only controller client. Prints the
    expected duration first (count x interval: up to 500 s). Runs ping on the gateway as
    the SSH user; the gateway's host key is not verified.
    """
    from .connectivity.gateway_probe import gateway_ping

    err_console.print(f'Expected duration: about {_duration_text(count * interval)}', style='dim')
    result = _probe(lambda: gateway_ping(target, count=count, interval=interval))
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f'📡 Ping {escape(target)} from the gateway', show_header=False)
    rtts = ' / '.join(_cell(result[k]) for k in ('rtt_min_ms', 'rtt_avg_ms', 'rtt_max_ms'))
    for label, value in (
        ('Address', _cell(result['probe_ip'])),
        ('Resolved from', _cell(result['resolved_name'])),
        ('Sent / received', f'{result["transmitted"]} / {result["received"]}'),
        ('Loss %', _cell(result['loss_pct'])),
        ('RTT min / avg / max ms', rtts),
        ('Reachable', _cell(result['reachable'])),
    ):
        table.add_row(label, value)
    console.print(table)


@gateway_app.command('traceroute')
def gateway_traceroute_command(
    target: str = typer.Argument(
        ..., help='An IP, or a device or client name, hostname or MAC (or a unique part of a name)'
    ),
    max_hops: int = typer.Option(20, '--max-hops', min=1, max=30, help='Hops to probe (1-30)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🧭 Trace the gateway's real forwarding path to a target over SSH.

    Runs traceroute on the gateway as the SSH user; the gateway's host key is not verified.
    "Reached the target" only when the last hop is the target itself and answered without an
    ICMP unreachable; the table marks a hop that answered with one "(unreachable)". With
    --json each hop also has "timeout" (no reply) and "unreachable":
    the hop answered with traceroute's !H (host), !N (network), !P (protocol), !S (source
    route), !F (fragmentation needed), !X, !V or !C (prohibited) or !<code> annotation.
    """
    from .connectivity.gateway_probe import gateway_traceroute

    result = _probe(lambda: gateway_traceroute(target, max_hops=max_hops))
    if as_json:
        _emit_json(result)
        return
    table = Table(title=f'🧭 Path to {escape(result["probe_ip"])}')
    for column in ('Hop', 'Host', 'Address', 'RTT ms'):
        table.add_column(column)
    for hop in result['hops']:
        rtts = ', '.join(f'{rtt:g}' for rtt in hop['rtt_ms']) or '*'
        if hop['unreachable']:
            rtts += ' (unreachable)'
        table.add_row(str(hop['hop']), _cell(hop['host']), _cell(hop['ip']), escape(rtts))
    console.print(table)
    last = result['hops'][-1] if result['hops'] else None
    if result['reached']:
        console.print('Reached the target.')
    elif last is not None and last['unreachable']:
        console.print(
            f'[yellow]Not reached: hop {last["hop"]} answered with an ICMP unreachable.[/]'
        )
    else:
        console.print('[yellow]Not reached.[/]')


@gateway_app.command('dns')
def gateway_dns_command(
    hostname: str = typer.Argument(..., help='The hostname to resolve'),
    server: Optional[str] = typer.Option(None, '--server', help='Ask this DNS server (an IP)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🔤 Resolve a hostname on the gateway over SSH (nslookup).

    Runs nslookup on the gateway as the SSH user; the gateway's host key is not verified.
    """
    from .connectivity.gateway_probe import gateway_dns_check

    result = _probe(lambda: gateway_dns_check(hostname, server=server))
    if as_json:
        _emit_json(result)
        return
    verdict = '[green]resolved[/]' if result['resolved'] else '[red]not resolved[/]'
    console.print(f'🔤 {escape(hostname)}: {verdict} (server {_cell(result["server"])})')
    for address in result['addresses']:
        console.print(f'  {escape(address)}')
    if result['error']:
        console.print(f'[yellow]{escape(result["error"])}[/]')


@gateway_app.command('http')
def gateway_http_command(
    url: str = typer.Argument(
        ...,
        help=(
            'The http(s) URL to fetch: no user name or password, and no secret in its query '
            "(it is run as given, on the gateway's command line)"
        ),
    ),
    vlan: Optional[int] = typer.Option(
        None, '--vlan', min=1, max=4094, help="Fetch from this VLAN's gateway interface"
    ),
    interface: Optional[str] = typer.Option(
        None, '--interface', help='Fetch from this interface (not with --vlan)'
    ),
    timeout: int = typer.Option(
        10, '--timeout', min=1, max=60, help="curl's --max-time in seconds (1-60)"
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🌐 Fetch a URL from the gateway over SSH (curl), from a VLAN if asked.

    --vlan resolves to the interface whose address is in that VLAN's subnet, from the
    controller's network list. Runs curl on the gateway as the SSH user; the gateway's host
    key is not verified.
    """
    from .connectivity.gateway_probe import gateway_http_check

    result = _probe(
        lambda: gateway_http_check(url, vlan=vlan, interface=interface, timeout_seconds=timeout)
    )
    if as_json:
        _emit_json(result)
        return
    style = 'green' if result['ok'] else 'red'
    via = f' via {escape(result["interface"])}' if result['interface'] else ''
    console.print(
        f'🌐 HTTP [{style}]{result["http_status"]}[/] in {_cell(result["time_total_s"])} s'
        f' from {_cell(result["remote_ip"])}{via}',
        soft_wrap=True,
    )
    if result.get('error'):
        console.print(f'[yellow]{escape(result["error"])}[/]', soft_wrap=True)


@gateway_app.command('flows')
def gateway_flows_command(
    ip: Optional[str] = typer.Option(None, '--ip', help='Only flows to or from this address'),
    flow_state: Optional[_FlowState] = typer.Option(
        None, '--state', case_sensitive=False, help='Only this state or flag, e.g. UNREPLIED'
    ),
    limit: int = typer.Option(200, '--limit', min=1, max=5000, help='Flows to show (1-5000)'),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🔁 The gateway's connection-tracking flows over SSH (conntrack), filtered here.

    UNREPLIED flows are traffic that left with nothing back. Runs conntrack -L on the gateway
    as the SSH user; the gateway's host key is not verified.
    """
    from .connectivity.gateway_probe import get_active_flows

    chosen = None if flow_state is None else flow_state.value
    result = _probe(lambda: get_active_flows(ip=ip, state=chosen, limit=limit))
    if as_json:
        _emit_json(result)
        return
    table = Table(
        title=f'🔁 Flows ({result["total_matching"]}, {result["unreplied_count"]} unreplied)'
    )
    for column in ('Proto', 'State', 'Source', 'Destination', 'Port'):
        table.add_column(column)
    for flow in result['flows']:
        table.add_row(
            _cell(flow['protocol']),
            _cell(flow['state']),
            _cell(flow['orig_src']),
            _cell(flow['orig_dst']),
            _cell(flow['orig_dport']),
        )
    console.print(table)
    if result['truncated']:
        console.print(f'[dim]Showing the first {limit}.[/dim]')


# ─── Composites (CLI only: lookup, AP counters and gateway probes) ──────────


def _duration_text(seconds: float) -> str:
    """A rough duration: seconds under a minute, minutes under an hour, else hours."""
    if seconds < 60:
        return f'{seconds:g} s'
    if seconds < 3600:
        return f'{round(seconds / 60)} min'
    hours, minutes = divmod(round(seconds / 60), 60)
    return f'{hours} h' + (f' {minutes} min' if minutes else '')


@diagnose_app.command('client-connectivity')
def diagnose_client_connectivity_command(
    client: str = typer.Argument(..., help="The client's name, hostname, MAC or IP"),
    probe_url: Optional[str] = typer.Option(
        None,
        '--probe-url',
        help=(
            "The http(s) URL to fetch from the client's VLAN (default a captive-portal check): "
            'no user name or password, and no secret in its query'
        ),
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of text'),
):
    """🩺 Diagnose one client's connectivity, layer by layer, in one run (SSH).

    Finds the client on the controller (read-only) and reads its AP's VAP counters, then,
    from the gateway over SSH, pings it, resolves the probe URL's host, fetches the URL from
    the client's VLAN and lists the client's conntrack flows. Each layer is bounded and the
    whole run capped at 120 s; a failing layer is reported and the others still run. Exits 1
    when a fault is found or a layer did not complete. Needs SSH enabled on the gateway and
    UNIFI_SSH_PASSWORD (and UNIFI_SSH_USERNAME if not root) in the config; runs on the
    gateway as the SSH user; the gateway's host key is not verified.
    """
    from .diagnostics.client_connectivity import (
        CAPTIVE_PROBE_URL,
        diagnose_client_connectivity,
    )

    url = probe_url or CAPTIVE_PROBE_URL
    result = _probe(lambda: diagnose_client_connectivity(client, probe_url=url))
    if as_json:
        _emit_json(result)
    else:
        where = ', '.join(
            part
            for part in (
                result.get('client_ip'),
                f'VLAN {result["vlan"]}' if result.get('vlan') else None,
                f'via {result["ap"]}' if result.get('ap') else None,
            )
            if part
        )
        console.print(
            f'🩺 [bold]{escape(str(result.get("client")))}[/bold]'
            + (f' ({escape(where)})' if where else ''),
            soft_wrap=True,
        )
        for finding in result['findings']:
            console.print(f'  • {escape(finding)}', soft_wrap=True)
        style = 'green' if result['ok'] else 'red'
        console.print(f'[{style}]{escape(result["verdict"])}[/{style}]', soft_wrap=True)
    if not result['ok']:
        raise typer.Exit(1)


def _file_option(path: Optional[Path], option: str) -> Optional[Path]:
    """Expand a file option's ``~`` and refuse an existing directory (design 6.1: exit 2)."""
    if path is None:
        return None
    expanded = path.expanduser()
    if expanded.is_dir():
        _fail(f'{option} names a directory, not a file: {expanded}', code=2)
    return expanded


def _prepare_output(path: Path, option: str) -> None:
    """Before a long run: create the output's directory (``0o700``) and check it is writable.

    A missing directory is created private; an existing one keeps its mode. Exits 2 naming
    the path when the directory can't be made or the file can't be written.
    """
    import os

    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        _fail(f'cannot write {option} {path}: {e.strerror or type(e).__name__}', code=2)
    if not os.access(path if path.exists() else path.parent, os.W_OK):
        _fail(f'cannot write {option} {path}: permission denied', code=2)


def _write_report(path: Path, text: str, option: str) -> bool:
    """Write a report that was already printed; a failure is one redacted line (False)."""
    from .core.utils.redact import redact_text

    try:
        path.write_text(text + '\n', encoding='utf-8')
    except OSError as e:
        reason = redact_text(e.strerror or type(e).__name__)
        err_console.print(
            f'❌ cannot write {option} {path}: {reason}', style='red', markup=False, soft_wrap=True
        )
        return False
    err_console.print(f'💾 Report written to {path}', markup=False)
    return True


@diagnose_app.command('ap-health')
def diagnose_ap_health(
    target: str = typer.Argument(..., help='The AP to sample: its name, MAC or IP'),
    reference: Optional[str] = typer.Option(
        None, '--reference', help='A known-good AP to sample alongside it'
    ),
    essid: Optional[str] = typer.Option(
        None, '--essid', help='The SSID whose 2.4 GHz VAP to track (default the busiest)'
    ),
    samples: int = typer.Option(6, '--samples', min=1, max=60, help='Samples to take (1-60)'),
    interval: int = typer.Option(
        60, '--interval', min=30, max=600, help='Seconds between samples (30-600)'
    ),
    ping_clients: bool = typer.Option(
        False,
        '--ping-clients',
        help=(
            "Also ping up to 4 of each AP's wireless clients on 2.4 GHz (or with no radio "
            'reported) from the gateway over SSH'
        ),
    ),
    output: Optional[Path] = typer.Option(
        None, '--output', help='Also write the markdown report to this file (checked first)'
    ),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of markdown'),
):
    """📶 Sample an AP's 2.4 GHz radio, retry and load counters over time, for a ticket.

    Takes --samples reads --interval seconds apart (60 reads 600 s apart take about 10 h; the
    expected duration is printed first) and reports each sample and the mean interval retry
    rate, beside a --reference AP when given. A sample whose read times out or fails is recorded
    as missing. Read-only, with no power-cycle step. --ping-clients also pings up to 4 of each
    AP's wireless clients from the gateway over SSH: those on 2.4 GHz, the radio the report
    measures, and those whose radio the controller doesn't report (5 and 6 GHz clients are
    left out), as the SSH user (the gateway's host key is not verified). --output is checked
    before the first sample and written after the report is printed. Ctrl-C prints the
    samples taken so far as a partial report (and writes it to --output) and exits 130; a
    failure that ends the run does the same and exits 1.
    """
    import asyncio
    from .analysis.ap_health import (
        MAX_PINGED_CLIENTS,
        PING_COUNT,
        PING_INTERVAL,
        ApHealthCapture,
        build_report,
        expected_duration_seconds,
        render_markdown,
        run_ap_health_capture,
    )

    output = _file_option(output, '--output')
    if output is not None:
        _prepare_output(output, '--output')
    expected = _duration_text(expected_duration_seconds(samples, interval))
    if ping_clients:  # each ping adds its own time to the pauses
        expected += (
            f', plus up to {MAX_PINGED_CLIENTS} pings per AP per sample, '
            f'about {PING_COUNT * PING_INTERVAL:g} s each'
        )
    err_console.print(f'Expected duration: about {expected}', style='dim')
    capture = ApHealthCapture()

    def progress(info: dict) -> None:
        note = ' (missing)' if info['missing'] else ''
        err_console.print(f'Sample {info["sample"]} of {info["of"]}{note}', style='dim')

    def run() -> Coroutine[Any, Any, dict]:
        return run_ap_health_capture(
            target, reference, essid, samples, interval, ping_clients, progress, sink=capture
        )

    failure_code = 0
    try:
        report = _probe(run) if ping_clients else _run_analysis(run)
    except (KeyboardInterrupt, asyncio.CancelledError):
        report = build_report(capture, partial=True)
    except typer.Exit as e:  # the error line is printed; keep the samples taken so far
        if not capture.samples:
            raise
        failure_code = e.exit_code or 1
        report = build_report(capture, partial=True)
    markdown = render_markdown(report)
    if as_json:
        _emit_json(report)
    else:
        console.print(markdown, markup=False, soft_wrap=True)
    written = output is None or _write_report(output, markdown, '--output')
    if report['partial']:
        rounds = sum(1 for s in capture.samples if s.role == 'target')
        err_console.print(f'Partial run: {rounds} of {samples} samples taken.', markup=False)
        raise typer.Exit(failure_code or 130)
    if not written:
        raise typer.Exit(2)


# ─── VLAN traffic (sample over SSH; rollup, report and coverage offline) ────


class _VlanPeriod(StrEnum):
    """A VLAN traffic report period."""

    NOW = 'now'
    DAY = '1d'
    WEEK = '1w'
    MONTH = '1m'
    YEAR = '1y'


_DB_HELP = 'The VLAN traffic store (default vlan-traffic.sqlite3 under the XDG state directory)'


def _bps(value: float) -> str:
    """A bit rate for a table: bps, kbps, Mbps or Gbps."""
    for unit, scale in (('Gbps', 1e9), ('Mbps', 1e6), ('kbps', 1e3)):
        if value >= scale:
            return f'{value / scale:.1f} {unit}'
    return f'{value:.0f} bps'


@vlan_traffic_app.command('sample')
def vlan_traffic_sample(
    db: Optional[Path] = typer.Option(None, '--db', help=_DB_HELP),
):
    """📥 Sample every VLAN's bridge byte counters from the gateway over SSH into the store.

    Reads the controller's network list (read-only), runs one fixed script on the gateway
    (each br* interface's byte counters and addresses, 30 s bound), matches each VLAN to the
    interface whose address is in its subnet and stores a row per VLAN. Run it by hand (or
    from your own schedule) every minute or so; no schedule is published until the gateway's
    host key can be verified. Exits 1 when the script fails or nothing was stored, so a
    schedule notices. Runs on the gateway as the SSH user; the gateway's host key is not
    verified.
    """
    from .analysis.vlan_traffic import sample_vlan_traffic
    from datetime import UTC, datetime

    store = _file_option(db, '--db')
    result = _probe(lambda: sample_vlan_traffic(store))
    when = datetime.fromtimestamp(result['ts'], tz=UTC).isoformat(timespec='seconds')
    extra = f', {len(result["skipped"])} without counters' if result['skipped'] else ''
    console.print(
        f'Sampled {len(result["sampled"])} VLAN(s) at {when}, '
        f'{len(result["unresolved"])} unresolved{extra}.',
        markup=False,
        soft_wrap=True,
    )
    if not result['sampled']:
        _fail('Nothing was stored: no VLAN matched a gateway interface with byte counters')


@vlan_traffic_app.command('rollup')
def vlan_traffic_rollup(
    db: Optional[Path] = typer.Option(None, '--db', help=_DB_HELP),
):
    """🧮 Roll complete hours and days of samples into rollup rows (offline; also recovers).

    Every complete hour of raw samples becomes an hourly row and every complete day a daily
    row; a bucket is complete once it ended twice the sampling interval ago, and at least 5
    minutes. Each run also recomputes the newest two hours and the newest day, so two runs
    give the same rows, and a sample written late still counts if a run comes less than two
    hours after its hour became complete; a later one stays in the raw samples (now, 1d,
    1w) but never reaches 1m or 1y. Raw samples are kept 8 days and hourly rows 60 days, and
    none is pruned before its hour or day is rolled. Run it hourly, say, to keep the 1m and
    1y reports current. Opening the store to write also rolls back what a crashed sample
    left, so this is the fix a report's "store needs recovery" asks for. Contacts nothing.
    """
    from .analysis.vlan_traffic_store import run_rollups

    store = _file_option(db, '--db')
    with _offline_errors():
        result = run_rollups(store)
    console.print(
        f'Rolled {result["raw_rows_rolled"]} raw row(s) into {result["hourly_rows_written"]} '
        f'hourly and {result["hourly_rows_rolled"]} hourly into {result["daily_rows_written"]} '
        f'daily; pruned {result["raw_rows_pruned"]} raw and {result["hourly_rows_pruned"]} '
        'hourly.',
        markup=False,
        soft_wrap=True,
    )


@vlan_traffic_app.command('report')
def vlan_traffic_report(
    period: _VlanPeriod = typer.Argument(..., help='now, 1d, 1w, 1m or 1y'),
    db: Optional[Path] = typer.Option(None, '--db', help=_DB_HELP),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """📊 Per-VLAN average and peak throughput over a period, from the store (offline).

    now, 1d and 1w read raw samples (kept 8 days); 1m reads hourly rollups and 1y daily
    rollups (smoothed peaks), each up to the newest complete hour or day `vlan-traffic
    rollup` has rolled. Valid samples is the share of the window's samples that gave a
    rate, not time coverage: `vlan-traffic coverage` shows the time each tier covers. A
    missing store exits 1 with a hint to sample first. Contacts nothing.
    """
    from .analysis.vlan_traffic_store import read_vlan_traffic_report

    store = _file_option(db, '--db')
    with _offline_errors():
        report = read_vlan_traffic_report(period.value, store)
    if as_json:
        _emit_json(report)
        return
    table = Table(title=f'📊 VLAN traffic, {period.value} ({report["methodology"]["tier_used"]})')
    columns = ('VLAN', 'Network', 'Avg rx', 'Avg tx', 'Peak rx', 'Peak tx', 'Valid samples')
    for column in columns:
        table.add_column(column)
    for vlan in report['vlans']:
        table.add_row(
            str(vlan['vlan_id']),
            escape(vlan['network_name']),
            _bps(vlan['avg_rx_bps']),
            _bps(vlan['avg_tx_bps']),
            _bps(vlan['peak_rx_bps']),
            _bps(vlan['peak_tx_bps']),
            f'{vlan["valid_sample_pct"]}%',
        )
    console.print(table)
    _print_dim_notes(report['methodology']['caveats'])


@vlan_traffic_app.command('coverage')
def vlan_traffic_coverage(
    db: Optional[Path] = typer.Option(None, '--db', help=_DB_HELP),
    as_json: bool = typer.Option(False, '--json', help='Print JSON instead of a table'),
):
    """🗓️ What each tier of the store holds, and its gaps (offline).

    Tells an idle VLAN (0 bps) from a window with no samples. Contacts nothing.
    """
    from .analysis.vlan_traffic_store import read_vlan_traffic_periods
    from datetime import UTC, datetime

    store = _file_option(db, '--db')
    with _offline_errors():
        periods = read_vlan_traffic_periods(store)
    if as_json:
        _emit_json(periods)
        return

    def when(ts: Optional[int]) -> str:
        return '—' if ts is None else datetime.fromtimestamp(ts, tz=UTC).isoformat()

    table = Table(title='🗓️ VLAN traffic store coverage')
    for column in ('Tier', 'Rows', 'Earliest', 'Latest', 'Gaps > 5 min'):
        table.add_column(column)
    for tier, info in periods.items():
        table.add_row(
            tier,
            str(info['count']),
            when(info['earliest']),
            when(info['latest']),
            str(info['gaps_over_5min']),
        )
    console.print(table)


if __name__ == '__main__':
    app()
