"""Rich renderers for the read-only port diagnostic reports.

Pure presentation: each function takes a report model and a Console and prints
tables. Nothing here talks to the controller. ``--json`` output bypasses these
entirely and prints the model's sanitised JSON instead.
"""

from pathlib import Path
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from typing import Any, Iterable, Optional
from unifi_mapper.analysis.counter_history import PortCounterHistoryView
from unifi_mapper.diagnostic_reads import SectionError
from unifi_mapper.port_diagnostics import (
    ClientHistory,
    DeviceIdentity,
    PortDiagnosticBundle,
    ProfileDiff,
    SwitchPortsReport,
)
from unifi_mapper.port_history import CounterTrend, EventHistory


def _text(value: Any) -> str:
    """Render a verbatim controller value safely ('—' for absent)."""
    if value is None or value == '':
        return '—'
    return escape(str(value))


def _flag(value: Optional[bool]) -> str:
    if value is True:
        return '[green]yes[/green]'
    if value is False:
        return '[red]no[/red]'
    return '[dim]unknown[/dim]'


def _dotted_get(record: dict[str, Any], dotted: str) -> Any:
    """Read a flattened ``a.b.c`` key back out of a nested record."""
    value: Any = record
    for part in dotted.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def render_errors(console: Console, errors: Iterable[SectionError]) -> None:
    """Print collection failures, if any, as a dim footer."""
    errors = list(errors)
    if not errors:
        return
    console.print(f'\n[yellow]⚠ {len(errors)} source(s) could not be read:[/yellow]')
    for error in errors:
        console.print(f'  [dim]• {escape(error.section)}: {escape(error.error)}[/dim]')


def render_identity(console: Console, device: DeviceIdentity) -> None:
    """Print a one-panel summary of the device identity."""
    model = device.model or '?'
    if device.display_model:
        model = f'{device.display_model} ({model})'
    firmware = escape(device.firmware_version or '?')
    if device.upgradable:
        firmware += (
            f'  [yellow](upgrade available, not applied: '
            f'{escape(device.upgrade_to_firmware or "?")})[/yellow]'
        )
    age = f'{device.data_age_seconds:.0f}s ago' if device.data_age_seconds is not None else '?'
    lines = [
        f'[bold]{escape(device.name or "?")}[/bold]  [dim]{escape(model)}[/dim]',
        f'MAC {_text(device.mac)}   IP {_text(device.ip)}   serial {_text(device.serial)}',
        f'firmware {firmware}',
        f'uptime {_text(device.uptime_seconds)}s   state {_text(device.state)} '
        f'(informing: {_flag(device.informing)})   last seen {age}',
    ]
    if device.system_stats:
        lines.append(f'system-stats {escape(str(device.system_stats))}')
    if device.thermal_fields:
        lines.append(f'thermal {escape(str(device.thermal_fields))}')
    console.print(Panel('\n'.join(lines), border_style='cyan', title='Device'))


def render_switch_ports(console: Console, report: SwitchPortsReport) -> None:
    """Print the all-ports table."""
    render_identity(console, report.device)
    table = Table(title='Ports', show_lines=False)
    for column in ('Port', 'Name', 'Media', 'Speed', 'Duplex', 'Autoneg', 'Up', 'STP'):
        table.add_column(column, justify='right' if column in ('Port', 'Speed') else 'left')
    table.add_column('Profile')
    table.add_column('LLDP / clients')
    table.add_column('Err rx/tx', justify='right')
    table.add_column('CRC', justify='right')
    table.add_column('Flaps', justify='right')
    for port in report.ports:
        neighbour = ''
        if port.lldp:
            neighbour = f'LLDP {port.lldp.resolved_name or port.lldp.name or port.lldp.chassis_id}'
        elif port.clients:
            first = port.clients[0]
            neighbour = str(first.name or first.mac)
            if port.client_count > 1:
                neighbour += f' +{port.client_count - 1}'
        profile = (port.profile_name or port.portconf_id or '—') + (
            ' *' if port.has_override else ''
        )
        table.add_row(
            _text(port.port_idx),
            _text(port.name),
            _text(port.media),
            _text(port.speed),
            'full' if port.full_duplex else ('half' if port.full_duplex is False else '—'),
            _text(port.autoneg),
            '[green]up[/green]' if port.up else '[red]down[/red]',
            _text(port.stp_state),
            escape(profile),
            escape(neighbour) or '—',
            f'{_text(port.rx_errors)}/{_text(port.tx_errors)}',
            _text(port.rx_crc_errors),
            _text(port.link_down_count),
        )
    console.print(table)
    console.print('[dim]* profile set by a per-port override[/dim]')
    render_errors(console, report.errors)


def render_profile_diff(console: Console, diff: ProfileDiff) -> None:
    """Print a profile diff: settings, metadata, networks and usage."""
    console.print(
        f'[bold]A[/bold] {escape(diff.a.name or "?")} [dim]({diff.a.id})[/dim]\n'
        f'[bold]B[/bold] {escape(diff.b.name or "?")} [dim]({diff.b.id})[/dim]'
    )
    table = Table(title=f'Settings that differ ({len(diff.differences)})')
    table.add_column('Key', style='cyan')
    table.add_column('A')
    table.add_column('B')
    for item in diff.differences:
        table.add_row(escape(item.key), _text(item.a), _text(item.b))
    for key in diff.only_in_a:
        table.add_row(escape(key), _text(_dotted_get(diff.a.raw, key)), '[dim]absent[/dim]')
    for key in diff.only_in_b:
        table.add_row(escape(key), '[dim]absent[/dim]', _text(_dotted_get(diff.b.raw, key)))
    console.print(table)
    console.print(f'[dim]{diff.identical_key_count} other setting(s) are identical.[/dim]')
    if diff.metadata_differences:
        keys = ', '.join(item.key for item in diff.metadata_differences)
        console.print(f'[dim]Metadata that differs (expected): {escape(keys)}[/dim]')
    if diff.network_refs:
        networks = Table(title='Networks referenced')
        networks.add_column('Network id', style='dim')
        networks.add_column('Name')
        networks.add_column('VLAN', justify='right')
        networks.add_column('Referenced by')
        for network_id, ref in diff.network_refs.items():
            networks.add_row(
                escape(network_id),
                _text(ref.get('name')),
                _text(ref.get('vlan')),
                escape(', '.join(ref.get('referenced_by') or [])),
            )
        console.print(networks)
    for side, label in (('a', diff.a.name), ('b', diff.b.name)):
        usage = diff.used_by.get(side, [])
        table = Table(title=f'Ports using {escape(label or side)} ({len(usage)})')
        for column in ('Switch', 'Port', 'Up', 'Speed', 'Media', 'Source'):
            table.add_column(column)
        for use in usage:
            table.add_row(
                _text(use.switch),
                _text(use.port_idx),
                _text(use.up),
                _text(use.speed),
                _text(use.media),
                _text(use.source),
            )
        console.print(table)
    render_errors(console, diff.errors)


def render_client_history(console: Console, history: ClientHistory) -> None:
    """Print where the controller places each resolved client."""
    if not history.records:
        console.print(f'[yellow]No client matched {escape(history.query)!r}.[/yellow]')
        render_errors(console, history.errors)
        return
    if history.target:
        console.print(
            f'Target: {escape(str(history.target.get("switch_name")))} '
            f'port {_text(history.target.get("port"))}'
        )
    table = Table(title=f'Client records for {escape(history.query)!r} ({history.resolution})')
    for column in ('MAC', 'Location', 'Source', 'On target', 'Rate', 'Network', 'IP', 'Last seen'):
        table.add_column(column)
    for record in history.records:
        location = record.location
        where = (
            f'{location.sw_name or location.sw_mac} port {location.sw_port}' if location else '—'
        )
        table.add_row(
            escape(record.mac),
            escape(where),
            _text(location.source if location else None),
            _flag(record.matches_target),
            _text(record.link.get('wired_rate_mbps')),
            _text(f'{record.network} (VLAN {record.vlan})' if record.network else None),
            _text(record.ip),
            _text(record.last_seen),
        )
    console.print(table)
    if history.resolved_truncated:
        console.print('[yellow]More clients matched; narrow the query.[/yellow]')
    render_errors(console, history.errors)


def render_event_history(console: Console, history: EventHistory, limit: int = 50) -> None:
    """Print per-source retention and the newest matched entries."""
    console.print(
        f'Window: {escape(history.window.since)} → {escape(history.window.until)} '
        f'({history.window.since_days} days requested)'
    )
    sources = Table(title='Sources (earliest = observed retention)')
    for column in ('Source', 'Status', 'HTTP', 'Records', 'Pages', 'Truncated', 'Earliest'):
        sources.add_column(column)
    sources.add_column('Latest')
    sources.add_column('Matched', justify='right')
    rows = [('stat/event', history.sources.stat_event), ('list/alarm', history.sources.alarms)]
    rows += [(f'system-log/{k}', v) for k, v in history.sources.system_log.items()]
    for name, result in rows:
        colour = {'ok': 'green', 'unavailable': 'yellow'}.get(result.status, 'red')
        sources.add_row(
            escape(name),
            f'[{colour}]{result.status}[/{colour}]',
            _text(result.http_status),
            str(result.records_returned),
            str(result.pages),
            _flag(result.truncated) if result.truncated else 'no',
            _text(result.earliest),
            _text(result.latest),
            str(result.matched),
        )
    console.print(sources)
    matched = Table(title=f'Matched entries ({history.returned} of {history.matched_total})')
    for column in ('Time (UTC)', 'Source', 'Key', 'Matched on', 'Message'):
        matched.add_column(column)
    for event in history.matched[:limit]:
        on = ', '.join(event.matched_on)
        if event.switch_matched_by == 'name':
            on += ' (by name)'
        matched.add_row(
            _text(event.time),
            escape(event.source),
            _text(event.key),
            escape(on),
            _text(event.message),
        )
    console.print(matched)
    if history.returned > limit:
        console.print(f'[dim]Showing {limit}; use --json for all {history.returned}.[/dim]')
    render_errors(console, history.errors)


def history_line(history: Optional[PortCounterHistoryView]) -> str:
    """Return one line describing the recorded counter history for a port."""
    if history is None:
        return 'counter history: not read'
    where = f'counter history {escape(history.path)}: '
    if history.error:
        return where + f'unreadable ({escape(history.error)})'
    if not history.found:
        return where + 'not found (record with `analyze link-errors --record`)'
    if not history.records:
        return where + 'no records for this port'
    started = [
        f'{key} since {first.taken_at or first.epoch}'
        for key, first in history.first_increase.items()
        if first is not None and not key.endswith('_bytes')
    ]
    return where + (
        f'{history.records} records {escape(str(history.earliest))} → '
        f'{escape(str(history.latest))}; '
        + (f'increasing: {escape(", ".join(started))}' if started else 'no error increase')
        + (f'; {len(history.resets)} reset(s)' if history.resets else '')
    )


def render_counter_trend(console: Console, trend: CounterTrend) -> None:
    """Print counter samples, rates, the verdict and baseline comparisons."""
    samples = Table(title=f'Port {trend.port_idx} counter samples')
    for column in ('Taken at', 'Device last_seen', 'Uptime', 'rx_err', 'tx_err', 'CRC', 'Flaps'):
        samples.add_column(column)
    for sample in trend.samples:
        c = sample.counters
        samples.add_row(
            escape(sample.taken_at),
            _text(sample.device_last_seen),
            _text(sample.device_uptime),
            _text(c.get('rx_errors')),
            _text(c.get('tx_errors')),
            _text(c.get('rx_crc_errors')),
            _text(c.get('link_down_count')),
        )
    console.print(samples)
    colour = {'ok': 'green', 'single_sample': 'cyan'}.get(trend.verdict, 'yellow')
    console.print(
        f'Verdict: [{colour}]{trend.verdict}[/{colour}] — {escape(trend.verdict_reason)}'
    )
    if any(v is not None for v in trend.rates_per_minute.values()):
        rates = Table(title=f'Rates per minute (basis: {trend.rate_basis})')
        rates.add_column('Counter', style='cyan')
        rates.add_column('Per minute', justify='right')
        for key, value in trend.rates_per_minute.items():
            rates.add_row(escape(key), _text(value))
        console.print(rates)
    if trend.baselines:
        link = trend.baselines.link_error_tracking
        store = trend.baselines.port_counter_baseline
        console.print(
            f'link-error baseline {escape(link.path)}'
            + (' (legacy reports/ path)' if link.legacy else '')
            + ': '
            + (
                f'device {"present" if link.device_present else "absent"}, '
                f'port {"present" if link.port_present else "absent"}, deltas {link.deltas}'
                if link.found
                else 'not found'
            )
        )
        console.print(
            f'port-counter store {escape(store.path)}: '
            + (f'delta {store.delta}' if store.found else 'not found')
        )
        console.print(history_line(trend.baselines.history), soft_wrap=True)
    render_errors(console, trend.errors)


def render_bundle_summary(console: Console, bundle: PortDiagnosticBundle, path: Path) -> None:
    """Print a short summary of a diagnostic bundle and where it was written."""
    if bundle.device:
        render_identity(console, bundle.device)
    if bundle.port:
        fields = bundle.port.key_fields
        caps = bundle.port.speed_caps
        console.print(
            f'Port {bundle.port.port_idx}: up={_text(fields.get("up"))} '
            f'speed={_text(fields.get("speed"))} autoneg={_text(fields.get("autoneg"))} '
            f'media={_text(fields.get("media"))} speed_caps={_text(caps.raw)} '
            f'(same as ports {caps.same_value_ports or "none"})'
        )
        if bundle.port.integration_port:
            ip = bundle.port.integration_port
            console.print(
                f'Integration API: maxSpeedMbps={_text(ip.get("maxSpeedMbps"))} '
                f'speedMbps={_text(ip.get("speedMbps"))} connector={_text(ip.get("connector"))}'
            )
    if bundle.override:
        assigned = bundle.override.profile_assigned
        note = (
            '  [yellow](configured but not yet applied)[/yellow]' if assigned.ids_disagree else ''
        )
        console.print(f'Profile: {_text(assigned.name)} [dim]via {assigned.source}[/dim]{note}')
    for history in bundle.clients:
        for record in history.records:
            console.print(
                f'Client {escape(record.mac)}: on target port {_flag(record.matches_target)}, '
                f'rate {_text(record.link.get("wired_rate_mbps"))} Mbps'
            )
    if bundle.events:
        console.print(
            f'Events: {bundle.events.matched_total} matched '
            f'(stat/event earliest {_text(bundle.events.sources.stat_event.earliest)})'
        )
    if bundle.counters:
        console.print(f'Counters: {bundle.counters.verdict}')
        if bundle.counters.baselines:
            console.print(history_line(bundle.counters.baselines.history), soft_wrap=True)
    gets = sum(1 for r in bundle.request_audit if r['method'] == 'GET')
    posts = len(bundle.request_audit) - gets
    console.print(
        f'Requests: {gets} GET + {posts} read-only POST queries; '
        f'{len(bundle.sanitised_paths)} secret field(s) stripped'
    )
    render_errors(console, bundle.errors)
    console.print(f'\n💾 Evidence bundle written to [cyan]{escape(str(path))}[/cyan]')
