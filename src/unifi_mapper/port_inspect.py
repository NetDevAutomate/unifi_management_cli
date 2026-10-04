"""Port inspection — answer 'what is (or was last) on this port?'.

Core, UI-free logic. Pulls every relevant fact the UniFi controller has for a
single switch port and resolves the associated MAC against both adopted UniFi
gear and the historical client table.

Example:
    from unifi_mapper.port_inspect import inspect_port, resolve_switch

    switch = resolve_switch(client, site, "Switch B Flex 8")
    result = inspect_port(client, site, switch, port_idx=7)
    result.render(console)
"""

from __future__ import annotations

import logging
from .analysis.link_settings import effective_port_settings
from .api_client import UnifiApiClient
from .core.utils.redact import strip_secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typing import Any, Optional


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class IdentityMatch:
    """Who a MAC belongs to, if we can tell."""

    kind: str  # "device" | "client" | "unknown"
    name: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    ip: Optional[str] = None

    @property
    def label(self) -> str:
        """Render a one-line human description of this identity."""
        if self.kind == 'device':
            bits = [f'[bold]UniFi device[/bold] {self.name or "?"}']
            if self.model:
                bits.append(f'({self.model})')
            if self.ip:
                bits.append(f'@ {self.ip}')
            return ' '.join(bits)
        if self.kind == 'client':
            bits = [f'[bold]Client[/bold] {self.name or "(no name)"}']
            if self.vendor:
                bits.append(f'— {self.vendor}')
            if self.ip:
                bits.append(f'@ {self.ip}')
            return ' '.join(bits)
        return '[dim]unknown — MAC not in any known table[/dim]'


@dataclass
class FreshnessReport:
    """Cache-staleness / consistency signal for a port snapshot.

    The UniFi controller pushes ``stat/device`` on a cycle. A single read of
    ``port_table`` can therefore lag reality: the port's ``up`` flag may show
    ``false`` while the device-side ``last_connection`` block already records
    a heartbeat from seconds ago. This object collects the disagreement
    signals so the caller can warn the user.
    """

    is_suspicious: bool
    reasons: list[str] = field(default_factory=list)
    last_seen_age_seconds: Optional[int] = None

    @property
    def label(self) -> str:
        """Return a one-line human summary of the freshness status."""
        if not self.is_suspicious:
            return 'consistent'
        return 'possibly stale: ' + '; '.join(self.reasons)


def _compute_freshness(
    port_table: dict[str, Any],
    active_client: Optional[dict[str, Any]],
    now_epoch: Optional[int] = None,
    recent_threshold_seconds: int = 120,
) -> FreshnessReport:
    """Detect when port_table and the device-side signals disagree.

    Rules:
      1. ``port_table.up == False`` but ``last_connection.connected == True``
         → almost certainly stale cache.
      2. ``port_table.up == False`` but ``last_connection.last_seen`` is within
         ``recent_threshold_seconds`` → same symptom, written slightly later.
      3. ``port_table.up == False`` but PoE power draw > 0 → the PD is alive,
         the link flag lies.
      4. ``port_table.up == False`` but an active DHCP client is reporting on
         this port in ``stat/sta`` → link must be up somewhere.

    Any single match flips ``is_suspicious`` to True.
    """
    now = now_epoch if now_epoch is not None else int(datetime.now(timezone.utc).timestamp())
    reasons: list[str] = []
    up = bool(port_table.get('up'))
    lc = port_table.get('last_connection') or {}

    last_seen = lc.get('last_seen')
    age: Optional[int] = None
    try:
        if last_seen is not None:
            age = max(0, now - int(last_seen))
    except (TypeError, ValueError):
        age = None

    if not up and lc.get('connected') is True:
        reasons.append('last_connection.connected=true while port.up=false')

    if not up and age is not None and age <= recent_threshold_seconds:
        reasons.append(
            f'last_connection.last_seen is {age}s old (<= {recent_threshold_seconds}s) while port.up=false'
        )

    # PoE power draw > 0 implies an attached PD that is at least powered.
    # Treat the stringly-typed numeric fields defensively.
    poe_power_raw = port_table.get('poe_power')
    try:
        poe_power = float(poe_power_raw) if poe_power_raw not in (None, '') else 0.0
    except (TypeError, ValueError):
        poe_power = 0.0
    if not up and poe_power > 0.0 and port_table.get('port_poe'):
        reasons.append(f'PoE draw={poe_power}W > 0 while port.up=false')

    if not up and active_client:
        reasons.append('stat/sta reports a client on this port while port.up=false')

    return FreshnessReport(
        is_suspicious=bool(reasons),
        reasons=reasons,
        last_seen_age_seconds=age,
    )


@dataclass
class NetworkContext:
    """The L2/L3 network a port's untagged traffic lands in."""

    network_id: Optional[str] = None
    name: Optional[str] = None
    vlan: Optional[int] = None
    subnet: Optional[str] = None
    gateway_ip: Optional[str] = None
    dhcp_enabled: Optional[bool] = None
    dhcp_start: Optional[str] = None
    dhcp_stop: Optional[str] = None
    dhcp_relay_enabled: Optional[bool] = None
    enabled: Optional[bool] = None
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Return a one-line summary of the network this port belongs to."""
        if not self.name:
            return 'unresolved — port has no native network assigned'
        vlan = f'VLAN {self.vlan}' if self.vlan is not None else 'untagged / default VLAN'
        return f'{self.name} ({vlan})'


@dataclass
class PortProfile:
    """The effective port profile (portconf) applied to a port."""

    profile_id: Optional[str] = None
    name: Optional[str] = None
    forward: Optional[str] = None
    native_network_id: Optional[str] = None
    tagged_vlans: Optional[list[int]] = None
    poe_mode: Optional[str] = None
    source: str = 'unknown'  # "override" | "port_table" | "unknown"

    @property
    def carries(self) -> str:
        """Describe which VLANs this port actually forwards."""
        if self.forward == 'all':
            return 'all VLANs (trunk)'
        if self.forward == 'native':
            return 'untagged native VLAN only (access)'
        if self.forward == 'customize' and self.tagged_vlans is not None:
            return f'native + tagged {sorted(self.tagged_vlans)}'
        if self.forward == 'disabled':
            return 'nothing — port forwarding disabled'
        return f'forward={self.forward}'


@dataclass
class DhcpStatus:
    """Whether the attached client has working L3 addressing.

    Separates "no address at all", "statically addressed" and "holding a DHCP
    lease". A port that is up with an active client but no lease is the
    signature of a VLAN or DHCP path fault rather than a cabling fault.
    """

    verdict: str = 'no_client'  # no_client | no_address | static | leased | unknown
    ip: Optional[str] = None
    lease_expires_at: Optional[int] = None
    fixed_ip: Optional[str] = None
    uses_fixed_ip: Optional[bool] = None
    in_dhcp_pool: Optional[bool] = None
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        """Return a one-line human summary of the addressing state."""
        return {
            'no_client': 'no client on this port',
            'no_address': 'client present but has NO IP address',
            'static': f'statically addressed {self.ip}',
            'leased': f'holding DHCP lease {self.ip}',
            'unknown': 'addressing state could not be determined',
        }.get(self.verdict, self.verdict)


@dataclass
class ConnectedDevice:
    """The thing plugged into the port, network device or not.

    ``is_unifi_device`` distinguishes adopted UniFi gear from third-party
    hosts. For third-party hosts the controller's fingerprint engine supplies
    a guessed ``model_name``; ``fingerprint_confidence`` is carried alongside
    because that guess is regularly wrong and should not be trusted blindly.
    """

    mac: Optional[str] = None
    is_unifi_device: bool = False
    name: Optional[str] = None
    hostname: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    fingerprint_confidence: Optional[int] = None
    ip: Optional[str] = None
    ipv6: list[str] = field(default_factory=list)
    network_name: Optional[str] = None
    vlan: Optional[int] = None
    wired_rate_mbps: Optional[int] = None
    uptime: Optional[int] = None
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None

    @property
    def label(self) -> str:
        """Return a one-line description of the attached device."""
        if not self.mac:
            return 'nothing detected on this port'
        kind = 'UniFi device' if self.is_unifi_device else 'third-party host'
        name = self.name or self.hostname or self.mac
        vendor = f' — {self.vendor}' if self.vendor else ''
        return f'[bold]{name}[/bold] ({kind}{vendor})'


@dataclass
class PortInspectionResult:
    """All facts gathered about a single switch port."""

    switch_name: str
    switch_model: str
    switch_mac: str
    port_idx: int
    port_table: dict[str, Any] = field(default_factory=dict)
    lldp: Optional[dict[str, Any]] = None
    active_client: Optional[dict[str, Any]] = None
    identity: Optional[IdentityMatch] = None
    freshness: FreshnessReport = field(
        default_factory=lambda: FreshnessReport(is_suspicious=False)
    )
    network: NetworkContext = field(default_factory=NetworkContext)
    profile: PortProfile = field(default_factory=PortProfile)
    dhcp: DhcpStatus = field(default_factory=DhcpStatus)
    connected: ConnectedDevice = field(default_factory=ConnectedDevice)
    lldp_identity: Optional[IdentityMatch] = None
    switch_uplink: dict[str, Any] = field(default_factory=dict)
    port_override: dict[str, Any] = field(default_factory=dict)

    # --- Convenience views -------------------------------------------------
    @property
    def up(self) -> bool:
        """Return True if the port is currently carrying link."""
        return bool(self.port_table.get('up'))

    @property
    def last_connection(self) -> dict[str, Any]:
        """Return the switch's persisted last_connection dict (may be empty)."""
        return self.port_table.get('last_connection') or {}

    # --- Serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view for API and MCP consumers.

        Rich markup is stripped from label strings so the output is safe for
        non-terminal consumers. ``override`` is the port's full
        ``port_overrides`` entry with secret keys removed. ``link.speed_caps``
        is the controller's raw, undocumented value and is never decoded.
        """
        pt = self.port_table
        override, _ = strip_secrets(self.port_override)
        return {
            'switch': {
                'name': self.switch_name,
                'model': self.switch_model,
                'mac': self.switch_mac,
                'uplink': self.switch_uplink or None,
            },
            'port_idx': self.port_idx,
            'override': override or None,
            'link': {
                'up': self.up,
                'enabled': pt.get('enable'),
                'media': pt.get('media'),
                'speed_mbps': pt.get('speed'),
                'full_duplex': pt.get('full_duplex'),
                'autoneg': pt.get('autoneg'),
                'speed_caps': pt.get('speed_caps'),
                'op_mode': pt.get('op_mode'),
                'forward': pt.get('forward'),
                'flowctrl_rx': pt.get('flowctrl_rx'),
                'flowctrl_tx': pt.get('flowctrl_tx'),
                'jumbo': pt.get('jumbo'),
                'is_uplink': pt.get('is_uplink'),
                'stp_state': pt.get('stp_state'),
                'link_down_count': pt.get('link_down_count'),
                'name': pt.get('name'),
            },
            'profile': {
                'id': self.profile.profile_id,
                'name': self.profile.name,
                'forward': self.profile.forward,
                'carries': self.profile.carries,
                'tagged_vlans': self.profile.tagged_vlans,
                'poe_mode': self.profile.poe_mode,
                'source': self.profile.source,
            },
            'network': {
                'id': self.network.network_id,
                'name': self.network.name,
                'vlan': self.network.vlan,
                'subnet': self.network.subnet,
                'gateway_ip': self.network.gateway_ip,
                'enabled': self.network.enabled,
                'dhcp_enabled': self.network.dhcp_enabled,
                'dhcp_start': self.network.dhcp_start,
                'dhcp_stop': self.network.dhcp_stop,
                'dhcp_relay_enabled': self.network.dhcp_relay_enabled,
                'warnings': self.network.warnings,
                'summary': self.network.label,
            },
            'connected_device': {
                'mac': self.connected.mac,
                'is_unifi_device': self.connected.is_unifi_device,
                'name': self.connected.name,
                'hostname': self.connected.hostname,
                'model': self.connected.model,
                'vendor': self.connected.vendor,
                'fingerprint_confidence': self.connected.fingerprint_confidence,
                'ip': self.connected.ip,
                'ipv6': self.connected.ipv6,
                'network_name': self.connected.network_name,
                'vlan': self.connected.vlan,
                'wired_rate_mbps': self.connected.wired_rate_mbps,
                'uptime_seconds': self.connected.uptime,
                'first_seen': self.connected.first_seen,
                'last_seen': self.connected.last_seen,
            },
            'addressing': {
                'verdict': self.dhcp.verdict,
                'summary': _strip_markup(self.dhcp.label),
                'ip': self.dhcp.ip,
                'lease_expires_at': self.dhcp.lease_expires_at,
                'fixed_ip': self.dhcp.fixed_ip,
                'uses_fixed_ip': self.dhcp.uses_fixed_ip,
                'in_dhcp_pool': self.dhcp.in_dhcp_pool,
                'notes': self.dhcp.notes,
            },
            'lldp': {
                'neighbour': self.lldp,
                'resolved': (
                    {
                        'kind': self.lldp_identity.kind,
                        'name': self.lldp_identity.name,
                        'model': self.lldp_identity.model,
                        'ip': self.lldp_identity.ip,
                    }
                    if self.lldp_identity
                    else None
                ),
            },
            'last_connection': self.last_connection or None,
            'counters': {
                'tx': {
                    'bytes': pt.get('tx_bytes'),
                    'packets': pt.get('tx_packets'),
                    'errors': pt.get('tx_errors'),
                    'dropped': pt.get('tx_dropped'),
                    'broadcast': pt.get('tx_broadcast'),
                    'multicast': pt.get('tx_multicast'),
                },
                'rx': {
                    'bytes': pt.get('rx_bytes'),
                    'packets': pt.get('rx_packets'),
                    'errors': pt.get('rx_errors'),
                    'dropped': pt.get('rx_dropped'),
                    'broadcast': pt.get('rx_broadcast'),
                    'multicast': pt.get('rx_multicast'),
                    'crc_errors': _rx_crc_errors(pt),
                },
            },
            'poe': (
                {
                    'capable': True,
                    'enabled': self.port_table.get('poe_enable'),
                    'mode': self.port_table.get('poe_mode'),
                    'good': self.port_table.get('poe_good'),
                    'class': self.port_table.get('poe_class'),
                    'power_w': self.port_table.get('poe_power'),
                    'voltage_v': self.port_table.get('poe_voltage'),
                    'current_ma': self.port_table.get('poe_current'),
                }
                if self.port_table.get('port_poe')
                else {'capable': False}
            ),
            'freshness': {
                'is_suspicious': self.freshness.is_suspicious,
                'reasons': self.freshness.reasons,
                'last_seen_age_seconds': self.freshness.last_seen_age_seconds,
            },
        }

    # --- Rendering ---------------------------------------------------------
    def render(self, console: Console) -> None:
        """Render the full inspection result to the given Rich console."""
        header = (
            f'🔌 [bold]{self.switch_name}[/bold] — port [cyan]{self.port_idx}[/cyan]  '
            f'[dim]({self.switch_model} / {self.switch_mac})[/dim]'
        )
        console.print(Panel(header, border_style='cyan'))

        self._render_freshness_warning(console)
        self._render_link_state(console)
        self._render_vlan_context(console)
        self._render_connected_device(console)
        self._render_addressing(console)
        self._render_lldp(console)
        self._render_last_connection(console)
        self._render_active_client(console)
        self._render_port_config(console)
        self._render_counters(console)
        self._render_poe(console)

    def _render_vlan_context(self, console: Console) -> None:
        """Render the effective port profile and the network it maps to."""
        t = Table(title='VLAN / profile', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('port profile', str(self.profile.name or '—'))
        t.add_row('forward mode', str(self.profile.forward or '—'))
        t.add_row('carries', self.profile.carries)
        t.add_row('native network', self.network.label)
        if self.network.subnet:
            t.add_row('subnet', f'{self.network.subnet} (gateway {self.network.gateway_ip})')
        if self.network.dhcp_enabled is not None:
            pool = (
                f'{self.network.dhcp_start} – {self.network.dhcp_stop}'
                if self.network.dhcp_start
                else '—'
            )
            t.add_row('DHCP server', f'{self.network.dhcp_enabled} (pool {pool})')
        console.print(t)
        for w in self.network.warnings:
            console.print(f'  [yellow]⚠ {w}[/yellow]')

    def _render_connected_device(self, console: Console) -> None:
        """Render what is plugged in, whether or not it is UniFi gear."""
        d = self.connected
        if not d.mac:
            return
        t = Table(title='Connected device', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('identity', d.label)
        t.add_row('mac', str(d.mac))
        if d.hostname:
            t.add_row('hostname', str(d.hostname))
        if d.model:
            conf = (
                f'  [dim](fingerprint guess, {d.fingerprint_confidence}% confidence)[/dim]'
                if not d.is_unifi_device and d.fingerprint_confidence is not None
                else ''
            )
            t.add_row('model', f'{d.model}{conf}')
        if d.vendor:
            t.add_row('vendor (OUI)', str(d.vendor))
        if d.ip:
            t.add_row('ip', str(d.ip))
        for addr in d.ipv6:
            t.add_row('ipv6', str(addr))
        if d.network_name:
            t.add_row('network', f'{d.network_name} (VLAN {d.vlan})')
        if d.wired_rate_mbps:
            t.add_row('negotiated rate', f'{d.wired_rate_mbps} Mbps')
        if d.uptime is not None:
            t.add_row('uptime', f'{d.uptime}s')
        t.add_row('first seen', _fmt_ts(d.first_seen))
        t.add_row('last seen', _fmt_ts(d.last_seen))
        console.print(t)

    def _render_addressing(self, console: Console) -> None:
        """Render the L3 addressing verdict, highlighting a missing address."""
        s = self.dhcp
        if s.verdict == 'no_client':
            return
        colour = {'leased': 'green', 'static': 'cyan', 'no_address': 'red'}.get(
            s.verdict, 'yellow'
        )
        console.print(f'[{colour}]Addressing:[/] {s.label}')
        if s.lease_expires_at:
            console.print(f'  lease expires: {_fmt_ts(s.lease_expires_at)}')
        for n in s.notes:
            console.print(f'  [yellow]• {n}[/yellow]')

    # --- internal renderers ------------------------------------------------
    def _render_freshness_warning(self, console: Console) -> None:
        """Render a top-of-output warning when controller signals disagree."""
        f = self.freshness
        if not f.is_suspicious:
            return
        lines = [
            '⚠️  [bold yellow]Cached controller state may be stale[/bold yellow]',
            '',
            'The UniFi controller pushes [cyan]stat/device[/cyan] on a cycle, so '
            '[cyan]port_table[/cyan] can lag reality by up to ~60 seconds.',
            'Treat [cyan]last_connection[/cyan] + [cyan]stat/sta[/cyan] as ground truth.',
            '',
            'Signals that disagree with port_table.up=false:',
        ]
        for r in f.reasons:
            lines.append(f'  • {r}')
        lines.append('')
        lines.append(
            '[dim]Tip: re-run in ~30-60s, or pair with `unifi-mapper --verify-updates` '
            'for multi-read consistency checking.[/dim]'
        )
        console.print(Panel('\n'.join(lines), border_style='yellow', title='Freshness check'))

    def _render_link_state(self, console: Console) -> None:
        pt = self.port_table
        t = Table(title='Link state', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        up = pt.get('up')
        colour = 'green' if up else 'red'
        t.add_row('status', f'[{colour}]{"up" if up else "down"}[/]')
        t.add_row('enable', str(pt.get('enable')))
        t.add_row('media', str(pt.get('media')))
        t.add_row('speed (Mbps)', str(pt.get('speed')))
        t.add_row('full-duplex', str(pt.get('full_duplex')))
        t.add_row('autoneg', str(pt.get('autoneg')))
        t.add_row('jumbo', str(pt.get('jumbo')))
        t.add_row('is_uplink', str(pt.get('is_uplink')))
        t.add_row('STP state', str(pt.get('stp_state')))
        t.add_row('link-down count', str(pt.get('link_down_count')))
        console.print(t)

    def _render_lldp(self, console: Console) -> None:
        if not self.lldp:
            console.print(
                '[yellow]LLDP:[/] no neighbour visible (port down, or device does not speak LLDP)'
            )
            return
        peer = self.lldp
        t = Table(title='LLDP neighbour (live)', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row(
            'remote device',
            str(peer.get('remote_device_name') or peer.get('system_name') or '—'),
        )
        t.add_row('chassis id', str(peer.get('chassis_id')))
        t.add_row('remote port', str(peer.get('remote_port_name') or peer.get('port_id')))
        t.add_row('is_wired', str(peer.get('is_wired')))
        console.print(t)
        if self.lldp_identity and self.lldp_identity.kind != 'unknown':
            console.print(f'    ↳ resolved to: {self.lldp_identity.label}')

    def _render_last_connection(self, console: Console) -> None:
        lc = self.last_connection
        if not lc:
            console.print('[yellow]last_connection:[/] none recorded')
            return
        t = Table(
            title='last_connection (switch memory)', show_header=False, box=None, pad_edge=False
        )
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('currently connected', str(lc.get('connected')))
        t.add_row('mac', str(lc.get('mac') or '—'))
        t.add_row('ip', str(lc.get('ip') or '—'))
        t.add_row('connected_at', _fmt_ts(lc.get('connected_at')))
        t.add_row('last_seen', _fmt_ts(lc.get('last_seen')))
        console.print(t)

        if self.identity:
            console.print(f'    ↳ resolved to: {self.identity.label}')

    def _render_active_client(self, console: Console) -> None:
        c = self.active_client
        if not c:
            if self.up:
                console.print(
                    '[yellow]Active client:[/] none reported by controller '
                    '(device may not have sent DHCP/traffic yet)'
                )
            return
        t = Table(title='Active client on this port', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        for k in (
            'hostname',
            'name',
            'mac',
            'ip',
            'oui',
            'network',
            'vlan',
            'is_wired',
            'is_guest',
            'uptime',
            'tx_bytes',
            'rx_bytes',
            'tx_packets',
            'rx_packets',
            'dev_cat',
            'dev_family',
            'dev_vendor',
            'os_name',
            'os_class',
            'fingerprint_source',
        ):
            if k in c:
                t.add_row(k, str(c.get(k)))
        t.add_row('first_seen', _fmt_ts(c.get('first_seen')))
        t.add_row('last_seen', _fmt_ts(c.get('last_seen')))
        console.print(t)

    def _render_port_config(self, console: Console) -> None:
        pt = self.port_table
        t = Table(title='Port config', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('port name', str(pt.get('name')))
        t.add_row('native VLAN id', str(pt.get('native_networkconf_id')))
        t.add_row('tagged-VLAN mode', str(pt.get('tagged_vlan_mgmt')))
        t.add_row('port security', str(pt.get('port_security_enabled')))
        t.add_row('isolation', str(pt.get('isolation')))
        t.add_row('LLDP-MED enabled', str(pt.get('lldpmed_enabled')))
        t.add_row('port profile pref', str(pt.get('setting_preference')))
        t.add_row('egress rate-limit', str(pt.get('egress_rate_limit_kbps_enabled')))
        t.add_row('aggregated by', str(pt.get('aggregated_by')))
        console.print(t)

    def _render_counters(self, console: Console) -> None:
        pt = self.port_table
        t = Table(title='Counters', show_header=True, box=None, pad_edge=False)
        t.add_column('direction', style='cyan')
        t.add_column('bytes', justify='right')
        t.add_column('packets', justify='right')
        t.add_column('errors', justify='right')
        t.add_column('dropped', justify='right')
        t.add_column('broadcast', justify='right')
        t.add_column('multicast', justify='right')
        t.add_row(
            'tx',
            str(pt.get('tx_bytes', 0)),
            str(pt.get('tx_packets', 0)),
            str(pt.get('tx_errors', 0)),
            str(pt.get('tx_dropped', 0)),
            str(pt.get('tx_broadcast', 0)),
            str(pt.get('tx_multicast', 0)),
        )
        t.add_row(
            'rx',
            str(pt.get('rx_bytes', 0)),
            str(pt.get('rx_packets', 0)),
            str(pt.get('rx_errors', 0)),
            str(pt.get('rx_dropped', 0)),
            str(pt.get('rx_broadcast', 0)),
            str(pt.get('rx_multicast', 0)),
        )
        t.add_row(
            'rate B/s',
            str(pt.get('tx_bytes-r', 0)),
            '',
            '',
            '',
            str(pt.get('rx_bytes-r', 0)),
            '',
        )
        console.print(t)

    def _render_poe(self, console: Console) -> None:
        pt = self.port_table
        if not pt.get('port_poe'):
            return
        t = Table(title='PoE', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('enabled', str(pt.get('poe_enable')))
        t.add_row('mode', str(pt.get('poe_mode')))
        t.add_row('good', str(pt.get('poe_good')))
        t.add_row('class', str(pt.get('poe_class')))
        t.add_row('draw (W)', str(pt.get('poe_power')))
        t.add_row('voltage (V)', str(pt.get('poe_voltage')))
        t.add_row('current (mA)', str(pt.get('poe_current')))
        t.add_row('budget max (W)', str(pt.get('max_poe_power')))
        console.print(t)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def _normalise_mac(value: Any) -> Optional[str]:
    """Return a MAC as lower-case colon-separated hex, or None if it is not a full MAC.

    Accepts ``aa:bb:cc:dd:ee:ff``, ``AA-BB-CC-DD-EE-FF``, ``aabb.ccdd.eeff`` and
    ``aabbccddeeff``. Partial MACs return None so they fall through to the
    substring match.
    """
    if not isinstance(value, str):
        return None
    digits = ''.join(ch for ch in value.strip().lower() if ch not in ':-.')
    if len(digits) != 12 or any(ch not in '0123456789abcdef' for ch in digits):
        return None
    return ':'.join(digits[i : i + 2] for i in range(0, 12, 2))


def _describe_candidates(devices: list[dict[str, Any]]) -> str:
    """Render candidate devices as ``'name' (mac, model)`` for error messages."""
    return ', '.join(
        f'{d.get("name")!r} ({d.get("mac") or "?"}, {d.get("model") or "?"})' for d in devices
    )


def match_switch(
    devices: list[dict[str, Any]],
    query: str,
    *,
    device_types: Optional[tuple[str, ...]] = ('usw',),
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Pick one device from an already-fetched device list and report how it matched.

    Tiers are tried in order and the first non-empty tier wins:

      1. ``exact_name``: the whole query equals the device name (case-insensitive).
      2. ``mac``: the query is a full MAC equal to the device MAC, in any notation.
      3. ``ip``: the query equals the device IP.
      4. ``tokens``: every whitespace-separated token appears in the name
         (multi-token queries only), so 'Switch B Flex 8' finds
         'Switch B USW Flex 2.5G 8 PoE'.
      5. ``substring``: the query appears in name, model, IP or MAC.

    An exact name therefore beats a token match: 'USW Flex XG' resolves to the
    switch named exactly that even when 'Core USW Flex XG 10G' also exists.

    Args:
        devices: ``stat/device`` records (non-dict entries are ignored).
        query: Device name, MAC, IP, or a partial name.
        device_types: Device ``type`` values to consider. None considers every
            adopted device. Defaults to switches only.

    Returns:
        ``(device, matched_by, candidates)`` where ``candidates`` is the winning
        tier's match list (a single entry on success).

    Raises:
        LookupError: Nothing matched, or the winning tier matched more than one
            device. The message lists the name, MAC and model of every candidate.
    """
    pool = [
        d
        for d in devices
        if isinstance(d, dict) and (device_types is None or d.get('type') in device_types)
    ]
    raw_query = query.strip()
    q = raw_query.lower()
    tokens = [t for t in q.split() if t]
    query_mac = _normalise_mac(raw_query)

    def _all_tokens_in_name(d: dict) -> bool:
        name = (d.get('name') or '').lower()
        return len(tokens) > 1 and all(t in name for t in tokens)

    def _substring_hit(d: dict) -> bool:
        return bool(q) and any(
            q in (str(d.get(k) or '')).lower() for k in ('name', 'model', 'ip', 'mac')
        )

    tiers: list[tuple[str, Any]] = [
        ('exact_name', lambda d: bool(q) and (d.get('name') or '').strip().lower() == q),
        ('mac', lambda d: query_mac is not None and _normalise_mac(d.get('mac')) == query_mac),
        ('ip', lambda d: bool(raw_query) and str(d.get('ip') or '').strip() == raw_query),
        ('tokens', _all_tokens_in_name),
        ('substring', _substring_hit),
    ]
    for matched_by, predicate in tiers:
        matches = [d for d in pool if predicate(d)]
        if len(matches) == 1:
            return matches[0], matched_by, matches
        if len(matches) > 1:
            raise LookupError(
                f'Ambiguous match for {query!r} ({matched_by}): {_describe_candidates(matches)}. '
                'Pass the exact name or the MAC address.'
            )

    kind, plural = ('switch', 'switches') if device_types == ('usw',) else ('device', 'devices')
    available = ', '.join(sorted({(d.get('name') or '?') for d in pool}))
    raise LookupError(f'No {kind} matched {query!r}. Known {plural}: {available}')


def resolve_switch_match(
    client: UnifiApiClient,
    site: str,
    query: str,
    *,
    device_types: Optional[tuple[str, ...]] = ('usw',),
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Find one device and report how it matched.

    Reads the site's device list once, then applies :func:`match_switch` (same
    tiers, same messages).

    Args:
        client: Authenticated API client.
        site: Site name.
        query: Device name, MAC, IP, or a partial name.
        device_types: Device ``type`` values to consider. None considers every
            adopted device. Defaults to switches only.

    Returns:
        ``(device, matched_by, candidates)`` where ``candidates`` is the winning
        tier's match list (a single entry on success).

    Raises:
        LookupError: The controller returned no devices, nothing matched, or the
            winning tier matched more than one device. The message lists the
            name, MAC and model of every candidate.
    """
    resp = client.get_devices(site)
    devices = (resp or {}).get('data', []) if isinstance(resp, dict) else []
    if not devices:
        raise LookupError(
            f'The controller returned no devices for site {site!r}: check the site name and '
            'that the account can read devices'
        )
    return match_switch(devices, query, device_types=device_types)


def resolve_switch(
    client: UnifiApiClient,
    site: str,
    query: str,
) -> dict[str, Any]:
    """Find a switch by name, MAC, IP or a partial name.

    Prefers an exact name, then an exact MAC, then an exact IP, then a
    match on every token, then a substring of name / model / ip / mac. See
    :func:`resolve_switch_match` for the full rules.

    Raises LookupError if nothing matches or the match is ambiguous.
    """
    switch, _, _ = resolve_switch_match(client, site, query)
    return switch


def _build_mac_index(client: UnifiApiClient, site: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (mac_to_adopted_device, mac_to_historical_client) maps."""
    devs = (client.get_devices(site) or {}).get('data', [])
    mac_to_dev = {(d.get('mac') or '').lower(): d for d in devs if d.get('mac')}

    prefix = (
        f'/proxy/network/api/s/{site}'
        if getattr(client, 'is_unifi_os', False)
        else f'/api/s/{site}'
    )
    mac_to_user: dict[str, dict] = {}
    try:
        r = client.session.get(f'{client.base_url}{prefix}/rest/user', timeout=client.timeout)
        r.raise_for_status()
        for u in r.json().get('data', []):
            m = (u.get('mac') or '').lower()
            if m:
                mac_to_user[m] = u
    except Exception as e:
        log.debug(f'historical client lookup failed: {e}')
    return mac_to_dev, mac_to_user


def _resolve_mac(
    mac: Optional[str],
    mac_to_dev: dict[str, dict],
    mac_to_user: dict[str, dict],
) -> IdentityMatch:
    if not mac:
        return IdentityMatch(kind='unknown')
    key = mac.lower()
    if key in mac_to_dev:
        d = mac_to_dev[key]
        return IdentityMatch(
            kind='device',
            name=d.get('name'),
            model=d.get('model'),
            ip=d.get('ip'),
        )
    if key in mac_to_user:
        u = mac_to_user[key]
        return IdentityMatch(
            kind='client',
            name=u.get('name') or u.get('hostname'),
            vendor=u.get('oui'),
            ip=u.get('fixed_ip') or u.get('ip'),
        )
    return IdentityMatch(kind='unknown')


def _active_client_on_port(
    client: UnifiApiClient,
    site: str,
    switch_mac: str,
    port_idx: int,
) -> Optional[dict[str, Any]]:
    prefix = (
        f'/proxy/network/api/s/{site}'
        if getattr(client, 'is_unifi_os', False)
        else f'/api/s/{site}'
    )
    try:
        r = client.session.get(f'{client.base_url}{prefix}/stat/sta', timeout=client.timeout)
        r.raise_for_status()
        sw = switch_mac.lower()
        hits = [
            c
            for c in r.json().get('data', [])
            if (c.get('sw_mac') or '').lower() == sw and c.get('sw_port') == port_idx
        ]
        return hits[0] if hits else None
    except Exception as e:
        log.debug(f'active client lookup failed: {e}')
        return None


def _api_prefix(client: UnifiApiClient, site: str) -> str:
    """Return the legacy-API path prefix, honouring the UniFi OS proxy."""
    return (
        f'/proxy/network/api/s/{site}'
        if getattr(client, 'is_unifi_os', False)
        else f'/api/s/{site}'
    )


def _v2_prefix(client: UnifiApiClient, site: str) -> str:
    """Return the v2-API path prefix, honouring the UniFi OS proxy."""
    return (
        f'/proxy/network/v2/api/site/{site}'
        if getattr(client, 'is_unifi_os', False)
        else f'/v2/api/site/{site}'
    )


def _get_json(client: UnifiApiClient, url: str) -> Any:
    """GET a URL and return parsed JSON, or None on any failure."""
    try:
        r = client.session.get(url, timeout=client.timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.debug(f'GET {url} failed: {e}')
        return None


def _rich_client_on_port(
    client: UnifiApiClient,
    site: str,
    switch_mac: str,
    port_idx: int,
) -> Optional[dict[str, Any]]:
    """Return the v2 clients/active record for this port, if available.

    The v2 endpoint carries fingerprint model guesses, DHCP lease expiry and
    negotiated wire rate, none of which ``stat/sta`` exposes. Returns None when
    the endpoint is unavailable so callers fall back to ``stat/sta``.
    """
    data = _get_json(client, f'{client.base_url}{_v2_prefix(client, site)}/clients/active')
    if data is None:
        return None
    rows = data if isinstance(data, list) else data.get('data', [])
    if not isinstance(rows, list):
        return None
    sw = (switch_mac or '').lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        uplink = (row.get('uplink_mac') or row.get('last_uplink_mac') or '').lower()
        if uplink == sw and row.get('sw_port') == port_idx:
            return row
    return None


def _fetch_networks(client: UnifiApiClient, site: str) -> dict[str, dict[str, Any]]:
    """Return networkconf entries keyed by network id."""
    data = _get_json(client, f'{client.base_url}{_api_prefix(client, site)}/rest/networkconf')
    rows = (data or {}).get('data', []) if isinstance(data, dict) else []
    return {r['_id']: r for r in rows if isinstance(r, dict) and r.get('_id')}


def _fetch_profiles(client: UnifiApiClient, site: str) -> dict[str, dict[str, Any]]:
    """Return port profile (portconf) entries keyed by profile id."""
    data = _get_json(client, f'{client.base_url}{_api_prefix(client, site)}/rest/portconf')
    rows = (data or {}).get('data', []) if isinstance(data, dict) else []
    return {r['_id']: r for r in rows if isinstance(r, dict) and r.get('_id')}


def _resolve_profile(
    switch: dict[str, Any],
    port_table: dict[str, Any],
    port_idx: int,
    profiles: dict[str, dict[str, Any]],
    networks: dict[str, dict[str, Any]],
) -> PortProfile:
    """Resolve the effective port profile, preferring a per-port override.

    A port's configuration can come from a ``port_overrides`` entry or be
    inherited from the profile referenced in ``port_table``. The override wins
    because that is what the controller pushes to the device. The rule lives in
    :func:`unifi_mapper.analysis.link_settings.effective_port_settings`.
    """
    s = effective_port_settings(switch, port_table, port_idx, profiles, networks)
    return PortProfile(
        profile_id=s.profile_id,
        name=s.name,
        forward=s.forward,
        native_network_id=s.native_network_id,
        tagged_vlans=s.tagged_vlans,
        poe_mode=s.poe_mode,
        source=s.source,
    )


def _resolve_network(
    network_id: Optional[str],
    networks: dict[str, dict[str, Any]],
) -> NetworkContext:
    """Build the network context for a port's native network.

    Also flags a DHCP pool that contains the gateway's own address, which can
    hand a duplicate address to a client.
    """
    net = networks.get(network_id or '')
    if not net:
        return NetworkContext(network_id=network_id)

    subnet = net.get('ip_subnet')
    gateway_ip = subnet.split('/')[0] if isinstance(subnet, str) and '/' in subnet else None

    ctx = NetworkContext(
        network_id=network_id,
        name=net.get('name'),
        vlan=net.get('vlan'),
        subnet=subnet,
        gateway_ip=gateway_ip,
        dhcp_enabled=net.get('dhcpd_enabled'),
        dhcp_start=net.get('dhcpd_start'),
        dhcp_stop=net.get('dhcpd_stop'),
        dhcp_relay_enabled=net.get('dhcp_relay_enabled'),
        enabled=net.get('enabled'),
    )

    if gateway_ip and _ip_in_range(gateway_ip, ctx.dhcp_start, ctx.dhcp_stop):
        ctx.warnings.append(
            f'DHCP pool {ctx.dhcp_start}–{ctx.dhcp_stop} contains the gateway address '
            f'{gateway_ip}; the server can hand out a conflicting address'
        )
    if ctx.enabled is False:
        ctx.warnings.append(f'network {ctx.name!r} is disabled')
    if ctx.dhcp_enabled is False and ctx.dhcp_relay_enabled is False:
        ctx.warnings.append(
            f'no DHCP server and no relay on {ctx.name!r}; clients must be statically addressed'
        )
    return ctx


def _ip_to_int(ip: Optional[str]) -> Optional[int]:
    """Convert a dotted-quad IPv4 string to an int, or None if unparseable."""
    if not isinstance(ip, str):
        return None
    parts = ip.strip().split('.')
    if len(parts) != 4:
        return None
    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return None
    if any(o < 0 or o > 255 for o in octets):
        return None
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def _ip_in_range(ip: Optional[str], start: Optional[str], stop: Optional[str]) -> bool:
    """Return True if ip falls inside the inclusive start–stop IPv4 range."""
    v, lo, hi = _ip_to_int(ip), _ip_to_int(start), _ip_to_int(stop)
    if v is None or lo is None or hi is None:
        return False
    return lo <= v <= hi


def _build_connected_device(
    rich: Optional[dict[str, Any]],
    basic: Optional[dict[str, Any]],
    identity: Optional[IdentityMatch],
    mac_to_dev: dict[str, dict],
    fallback_mac: Optional[str] = None,
) -> ConnectedDevice:
    """Describe the attached device from the richest source available.

    Prefers the v2 client record, falls back to ``stat/sta``, and finally to the
    switch's remembered ``last_connection`` identity so a port whose peer is an
    adopted switch or AP — which never appears in the client tables — still
    reports what is on the other end.
    """
    src = rich or basic or {}
    mac = (src.get('mac') or '').lower() or None

    if not mac and identity and identity.kind != 'unknown':
        return ConnectedDevice(
            mac=(fallback_mac or '').lower() or None,
            is_unifi_device=identity.kind == 'device',
            name=identity.name,
            model=identity.model,
            vendor=identity.vendor,
            ip=identity.ip,
        )

    is_unifi = bool(src.get('unifi_device')) or (mac in mac_to_dev if mac else False)
    fingerprint = src.get('fingerprint') or {}
    adopted = mac_to_dev.get(mac or '', {})

    ipv6 = src.get('ipv6_address') or []
    if not isinstance(ipv6, list):
        ipv6 = [str(ipv6)]

    return ConnectedDevice(
        mac=mac,
        is_unifi_device=is_unifi,
        name=(adopted.get('name') if is_unifi else None) or src.get('name') or src.get('hostname'),
        hostname=src.get('hostname'),
        model=(adopted.get('model') if is_unifi else None) or src.get('model_name'),
        vendor=src.get('oui') or None,
        fingerprint_confidence=(
            fingerprint.get('confidence') if isinstance(fingerprint, dict) else None
        ),
        ip=src.get('ip') or adopted.get('ip'),
        ipv6=[str(a) for a in ipv6],
        network_name=src.get('network_name') or src.get('network'),
        vlan=src.get('vlan'),
        wired_rate_mbps=src.get('wired_rate_mbps'),
        uptime=src.get('uptime'),
        first_seen=src.get('first_seen'),
        last_seen=src.get('last_seen'),
    )


def _build_dhcp_status(
    rich: Optional[dict[str, Any]],
    basic: Optional[dict[str, Any]],
    network: NetworkContext,
) -> DhcpStatus:
    """Classify the attached client's addressing as leased, static or absent.

    A DHCP lease expiry timestamp is the only positive proof of a working
    DHCP exchange; its absence alongside an address implies static
    configuration. No address at all on a live port points at the VLAN or
    DHCP path rather than the cable.
    """
    src = rich or basic
    if not src:
        return DhcpStatus(verdict='no_client')

    ip = src.get('ip') or None
    lease = src.get('ipv4_lease_expiration_timestamp_seconds')
    fixed_ip = src.get('fixed_ip') or None
    uses_fixed = src.get('use_fixedip')

    status = DhcpStatus(
        ip=ip,
        lease_expires_at=lease,
        fixed_ip=fixed_ip,
        uses_fixed_ip=uses_fixed,
    )

    if ip and network.dhcp_start:
        status.in_dhcp_pool = _ip_in_range(ip, network.dhcp_start, network.dhcp_stop)

    if not ip:
        status.verdict = 'no_address'
        if network.dhcp_enabled:
            status.notes.append(
                f'DHCP is enabled on {network.name!r} but this client holds no address; '
                'check that the VLAN reaches the gateway on every hop of the uplink path'
            )
        if network.dhcp_enabled is False:
            status.notes.append(
                f'no DHCP server on {network.name!r} — the client needs a static address'
            )
        return status

    if lease:
        status.verdict = 'leased'
    elif uses_fixed:
        status.verdict = 'static'
        status.notes.append('address comes from a UniFi fixed-IP reservation')
    else:
        status.verdict = 'static'
        status.notes.append(
            'no DHCP lease recorded, so this address is configured on the host itself'
        )

    if status.in_dhcp_pool is False and status.verdict == 'static':
        status.notes.append(
            f'{ip} sits outside the DHCP pool {network.dhcp_start}–{network.dhcp_stop}'
        )
    return status


def _strip_markup(text: str) -> str:
    """Remove Rich markup tags so a label is safe for JSON consumers."""
    out: list[str] = []
    depth = 0
    for ch in text:
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return ''.join(out).strip()


def inspect_port(
    client: UnifiApiClient,
    site: str,
    switch: dict[str, Any],
    port_idx: int,
) -> PortInspectionResult:
    """Build a PortInspectionResult from live controller data."""
    device_id = switch['_id']

    details = client.get_device_details(site, device_id) or {}
    port_table_entries = details.get('port_table', [])
    port_table = next((p for p in port_table_entries if p.get('port_idx') == port_idx), {})
    if not port_table:
        raise LookupError(
            f'Port {port_idx} not found on {switch.get("name")!r} '
            f'(valid ports: {sorted(p.get("port_idx") for p in port_table_entries)})'
        )

    lldp = client.get_lldp_info(site, device_id).get(str(port_idx))
    mac_to_dev, mac_to_user = _build_mac_index(client, site)

    last_mac = (port_table.get('last_connection') or {}).get('mac')
    identity = _resolve_mac(last_mac, mac_to_dev, mac_to_user)

    active = _active_client_on_port(client, site, switch.get('mac', ''), port_idx)
    rich = _rich_client_on_port(client, site, switch.get('mac', ''), port_idx)

    freshness = _compute_freshness(port_table, active or rich)

    networks = _fetch_networks(client, site)
    profiles = _fetch_profiles(client, site)
    profile = _resolve_profile(switch, port_table, port_idx, profiles, networks)
    network = _resolve_network(profile.native_network_id, networks)

    connected = _build_connected_device(rich, active, identity, mac_to_dev, last_mac)
    dhcp = _build_dhcp_status(rich, active, network)

    lldp_identity = None
    if lldp:
        peer_mac = lldp.get('chassis_id') or lldp.get('mac')
        lldp_identity = _resolve_mac(peer_mac, mac_to_dev, mac_to_user)

    overrides = details.get('port_overrides') or switch.get('port_overrides') or []
    port_override = next(
        (o for o in overrides if isinstance(o, dict) and o.get('port_idx') == port_idx),
        {},
    )

    return PortInspectionResult(
        switch_name=switch.get('name', '?'),
        switch_model=switch.get('model', '?'),
        switch_mac=switch.get('mac', '?'),
        port_idx=port_idx,
        port_table=port_table,
        lldp=lldp,
        active_client=rich or active,
        identity=identity,
        freshness=freshness,
        network=network,
        profile=profile,
        dhcp=dhcp,
        connected=connected,
        lldp_identity=lldp_identity,
        switch_uplink=switch.get('uplink') or {},
        port_override=port_override,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rx_crc_errors(port_table: dict[str, Any]) -> Any:
    """Return the receive CRC counter: ``port_stats.rx_crc_errors``, then ``rx_crc_errors``.

    Same precedence as ``analysis/link_quality``. None when neither is reported.
    """
    stats = port_table.get('port_stats')
    if isinstance(stats, dict) and 'rx_crc_errors' in stats:
        return stats['rx_crc_errors']
    return port_table.get('rx_crc_errors')


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return '—'
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (TypeError, ValueError):
        return str(ts)
