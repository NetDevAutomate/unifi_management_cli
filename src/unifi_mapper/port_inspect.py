"""Port inspection — answer 'what is (or was last) on this port?'.

Core, UI-free logic. Pulls every relevant fact the UniFi controller has for a
single switch port and resolves the associated MAC against both adopted UniFi
gear and the historical client table.

Example:
    from unifi_mapper.port_inspect import inspect_port, resolve_switch

    switch = resolve_switch(client, site, "Lounge Flex 8")
    result = inspect_port(client, site, switch, port_idx=7)
    result.render(console)
"""

from __future__ import annotations

import logging
from .api_client import UnifiApiClient
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

    # --- Convenience views -------------------------------------------------
    @property
    def up(self) -> bool:
        """Return True if the port is currently carrying link."""
        return bool(self.port_table.get('up'))

    @property
    def last_connection(self) -> dict[str, Any]:
        """Return the switch's persisted last_connection dict (may be empty)."""
        return self.port_table.get('last_connection') or {}

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
        self._render_lldp(console)
        self._render_last_connection(console)
        self._render_active_client(console)
        self._render_port_config(console)
        self._render_counters(console)
        self._render_poe(console)

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
        l = self.lldp
        t = Table(title='LLDP neighbour (live)', show_header=False, box=None, pad_edge=False)
        t.add_column('k', style='cyan', no_wrap=True)
        t.add_column('v')
        t.add_row('remote device', str(l.get('remote_device_name') or l.get('system_name') or '—'))
        t.add_row('chassis id', str(l.get('chassis_id')))
        t.add_row('remote port', str(l.get('remote_port_name') or l.get('port_id')))
        t.add_row('is_wired', str(l.get('is_wired')))
        console.print(t)

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


def resolve_switch(
    client: UnifiApiClient,
    site: str,
    query: str,
) -> dict[str, Any]:
    """Find a switch by case-insensitive match on name / model / ip / mac.

    Matches in this order of preference (first non-empty set wins):
      1. All whitespace-separated tokens in ``query`` appear in the switch name
         (e.g. 'Lounge Flex 8' finds 'Mike2 USW Flex 2.5G 8 PoE').
      2. ``query`` appears as a substring in name / model / ip / mac.

    Raises LookupError if nothing matches or the match is ambiguous.
    """
    resp = client.get_devices(site)
    devices = (resp or {}).get('data', []) if isinstance(resp, dict) else []
    switches = [d for d in devices if d.get('type') == 'usw']
    q = query.lower().strip()
    tokens = [t for t in q.split() if t]

    def _all_tokens_in_name(d: dict) -> bool:
        name = (d.get('name') or '').lower()
        return bool(tokens) and all(t in name for t in tokens)

    def _substring_hit(d: dict) -> bool:
        return any(q in (str(d.get(k) or '')).lower() for k in ('name', 'model', 'ip', 'mac'))

    matches: list[dict] = []
    if len(tokens) > 1:
        matches = [d for d in switches if _all_tokens_in_name(d)]
    if not matches:
        matches = [d for d in switches if _substring_hit(d)]

    if not matches:
        available = ', '.join(sorted({(d.get('name') or '?') for d in switches}))
        raise LookupError(f'No switch matched {query!r}. Known switches: {available}')
    if len(matches) > 1:
        names = ', '.join(f'{d.get("name")!r}' for d in matches)
        raise LookupError(f'Ambiguous match for {query!r}: {names}')
    return matches[0]


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

    freshness = _compute_freshness(port_table, active)

    return PortInspectionResult(
        switch_name=switch.get('name', '?'),
        switch_model=switch.get('model', '?'),
        switch_mac=switch.get('mac', '?'),
        port_idx=port_idx,
        port_table=port_table,
        lldp=lldp,
        active_client=active,
        identity=identity,
        freshness=freshness,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return '—'
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (TypeError, ValueError):
        return str(ts)
