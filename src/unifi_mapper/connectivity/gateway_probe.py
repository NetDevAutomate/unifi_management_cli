"""Live probes run on the gateway over SSH: ping, traceroute, DNS, HTTP and conntrack flows.

Class B (CLI only, ``unifi-mapper gateway ...``; no MCP tool, decision D1 in issue 060): each
probe opens one session through ``analysis/gateway_ssh.py`` and runs one argv with its own
bound, every value checked by that module's validators first, so nothing a user types or the
controller reports can add a command or an option. The gateway's host key is not verified
(issue 038). A device or client name is resolved to its address through ``UniFiClient()``,
which borrows the read-only holder the CLI installs, so those reads can't write.

Ported from the July work (a local archive, not in the repo): the pure parsers are July's,
logic unchanged; the handlers are rebuilt on argv lists (July built shell strings and piped
conntrack through ``grep``), ``--globoff`` keeps curl from expanding ``[]`` and ``{}`` in a
URL, and a VLAN resolves to the interface whose address is in its subnet. July's spectrum
scan (a controller command) is not ported.
"""

import json
import re
from typing import Any
from unifi_mapper.analysis.gateway_ssh import (
    gateway_session,
    require_bounded_float,
    require_bounded_int,
    require_hostname,
    require_http_url,
    require_interface_name,
    require_ip,
    run_gateway_command,
    ssh_login,
)
from unifi_mapper.analysis.vlan_interfaces import resolve_vlan_interfaces
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.ping_parse import parse_ping_output
from unifi_mapper.core.utils.redact import redact_text
from unifi_mapper.diagnostic_reads import is_ip_address, normalise_mac


# curl's -w template: the status, the total time and the address it reached.
WRITE_OUT = '%{http_code} %{time_total} %{remote_ip}'
# The conntrack states and flags ``gateway flows --state`` accepts (upper case).
FLOW_STATES = (
    'ESTABLISHED',
    'SYN_SENT',
    'SYN_RECV',
    'FIN_WAIT',
    'CLOSE_WAIT',
    'LAST_ACK',
    'TIME_WAIT',
    'CLOSE',
    'UNREPLIED',
    'ASSURED',
)
DNS_TIMEOUT = 20
FLOWS_TIMEOUT = 60  # July's 30 s, raised for busy tables
INTERFACES_TIMEOUT = 15

_TRACEROUTE_HOP_RE = re.compile(r'^\s*(\d+)\s+(.*)$')
_HOP_HOST_RE = re.compile(r'([A-Za-z0-9._\-]+)\s+\(([\d.]+)\)|^([\d.]+)')
_HOP_TIME_RE = re.compile(r'([\d.]+)\s*ms')
_CONNTRACK_KV_RE = re.compile(r'(\w+)=(\S+)')
_CONNTRACK_FLAG_RE = re.compile(r'\[(\w+)\]')
_NSLOOKUP_ADDR_RE = re.compile(r'^Address(?:\s+\d+)?:\s*(\S+)', re.M)
_NSLOOKUP_NAME_RE = re.compile(r'^Name:\s*(\S+)', re.M)
_DNS_FAILURE_MARKERS = ("can't resolve", "server can't find", 'NXDOMAIN', 'no servers could')


# --- pure parsers (July's, unchanged in logic) ---------------------------------------------


def parse_traceroute_output(output: str) -> list[dict[str, Any]]:
    """Parse traceroute output (GNU or BusyBox) into hops.

    Args:
        output: Raw traceroute stdout.

    Returns:
        One ``{hop, host, ip, rtt_ms, timeout}`` dict per hop line.
    """
    hops: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = _TRACEROUTE_HOP_RE.match(line)
        if not match:
            continue
        hop_no, rest = int(match.group(1)), match.group(2)
        if rest.strip().replace('*', '').strip() == '':
            hops.append({'hop': hop_no, 'host': None, 'ip': None, 'rtt_ms': [], 'timeout': True})
            continue
        host: str | None = None
        ip: str | None = None
        host_match = _HOP_HOST_RE.search(rest)
        if host_match:
            if host_match.group(3):
                host = ip = host_match.group(3)
            else:
                host, ip = host_match.group(1), host_match.group(2)
        times = [float(t) for t in _HOP_TIME_RE.findall(rest)]
        hops.append({'hop': hop_no, 'host': host, 'ip': ip, 'rtt_ms': times, 'timeout': not times})
    return hops


def parse_conntrack_output(
    output: str, ip: str | None = None, state: str | None = None
) -> list[dict[str, Any]]:
    """Parse ``conntrack -L`` output into flows, optionally filtered.

    Each line holds the original direction first, then the reply; the first src/dst pair is
    the originator.

    Args:
        output: Raw ``conntrack -L`` stdout.
        ip: Keep only flows where this address is any src or dst.
        state: Keep only flows in this TCP state or with this flag (any case), such as
            ``ESTABLISHED`` or ``UNREPLIED``.

    Returns:
        Flow dicts: protocol, state, flags, orig and reply tuples, unreplied.
    """
    flows: list[dict[str, Any]] = []
    state_upper = state.upper() if state else None
    for raw in output.splitlines():
        line = raw.strip()
        if not line or '=' not in line:
            continue
        parts = line.split()
        flags = [f.upper() for f in _CONNTRACK_FLAG_RE.findall(line)]
        tcp_state = next(
            (t for t in parts[1:5] if t.isupper() and not t.isdigit() and '=' not in t), None
        )
        kvs = _CONNTRACK_KV_RE.findall(line)
        srcs = [v for k, v in kvs if k == 'src']
        dsts = [v for k, v in kvs if k == 'dst']
        sports = [v for k, v in kvs if k == 'sport']
        dports = [v for k, v in kvs if k == 'dport']
        flow = {
            'protocol': parts[0],
            'state': tcp_state or ('UNREPLIED' if 'UNREPLIED' in flags else 'ASSURED'),
            'flags': flags,
            'orig_src': srcs[0] if srcs else None,
            'orig_dst': dsts[0] if dsts else None,
            'orig_sport': int(sports[0]) if sports and sports[0].isdigit() else None,
            'orig_dport': int(dports[0]) if dports and dports[0].isdigit() else None,
            'reply_src': srcs[1] if len(srcs) > 1 else None,
            'reply_dst': dsts[1] if len(dsts) > 1 else None,
            'unreplied': 'UNREPLIED' in flags,
        }
        if ip and ip not in srcs + dsts:
            continue
        if state_upper and state_upper != flow['state'] and state_upper not in flags:
            continue
        flows.append(flow)
    return flows


def parse_nslookup_output(output: str) -> dict[str, Any]:
    """Parse nslookup output (BusyBox or GNU) into the answers.

    Args:
        output: Raw nslookup stdout and stderr.

    Returns:
        ``resolved``, ``addresses`` (the answers), ``names``, ``server`` (the first Address
        line, its ``:53`` dropped) and ``error`` (the failure marker found, or None).
    """
    lower = output.lower()
    error = next((m for m in _DNS_FAILURE_MARKERS if m.lower() in lower), None)
    addresses = [a.rstrip('.') for a in _NSLOOKUP_ADDR_RE.findall(output)]
    names = [n.rstrip('.') for n in _NSLOOKUP_NAME_RE.findall(output)]
    server = addresses[0] if addresses else None
    if server and server.endswith(':53'):
        server = server[:-3]
    if server and server.endswith('#53'):
        server = server[:-3]
    answers = addresses[1:]
    return {
        'resolved': bool(answers) and error is None,
        'addresses': answers,
        'names': names,
        'server': server,
        'error': error,
    }


def parse_curl_writeout(output: str) -> dict[str, Any]:
    """Parse curl's ``WRITE_OUT`` line.

    Args:
        output: The last line curl printed for ``-w WRITE_OUT``.

    Returns:
        ``http_status`` (0 when absent), ``time_total_s``, ``remote_ip`` and ``ok`` (2xx or
        3xx).
    """
    parts = output.strip().split()
    try:
        http_status = int(parts[0]) if parts else 0
    except ValueError:
        http_status = 0
    try:
        time_total = float(parts[1]) if len(parts) > 1 else None
    except ValueError:
        time_total = None
    remote_ip = parts[2] if len(parts) > 2 and parts[2] not in ('', '-') else None
    return {
        'http_status': http_status,
        'time_total_s': time_total,
        'remote_ip': remote_ip,
        'ok': 200 <= http_status < 400,
    }


# --- target resolution --------------------------------------------------------------------


def _not_found(message: str) -> ToolError:
    return ToolError(
        message=message,
        error_code=ErrorCodes.DEVICE_NOT_FOUND,
        suggestion='Give an IP address, or the exact name, hostname or MAC of a device or client',
        related_tools=['find_device'],
    )


def _names(record: dict[str, Any], kind: str) -> list[str]:
    """What a record is called, folded: a device's name; a client's name and hostname."""
    keys = ('name',) if kind == 'device' else ('name', 'hostname')
    return [str(record[key]).strip().casefold() for key in keys if record.get(key)]


def match_identities(
    devices: list[Any], clients: list[Any], query: str
) -> list[tuple[dict[str, Any], str]]:
    """The devices and clients a query names, from the first tier with a match. Pure.

    Tier 1 is an exact identity in either pool: a device's name or a client's name or
    hostname (any case), a MAC in any notation, or an IP. Tier 2 is a partial name: the
    query, or every word of a query of several, inside one of those names. So a client named
    exactly "Hub 3" wins over an AP named "AP Hub 3", and ``phone`` finds the one client
    called "Phone A". A device the controller also lists as a client (one MAC) counts once.
    Shared by ``gateway ping`` and ``traceroute`` (both pools) and ``diagnose
    client-connectivity`` (clients only).

    Args:
        devices: ``stat/device`` records (non-dict entries are ignored).
        clients: ``stat/sta`` records.
        query: A name, hostname, MAC, IP or part of a name.

    Returns:
        The winning tier's ``(record, kind)`` pairs, ``kind`` being ``device`` or ``client``:
        none when nothing matched, more than one when that tier is ambiguous.
    """
    text = query.strip()
    folded, mac = text.casefold(), normalise_mac(text)
    words = folded.split()
    pool = [(r, 'device') for r in devices if isinstance(r, dict)]
    pool += [(r, 'client') for r in clients if isinstance(r, dict)]

    def exact(record: dict[str, Any], kind: str) -> bool:
        return (
            (bool(folded) and folded in _names(record, kind))
            or (mac is not None and normalise_mac(record.get('mac')) == mac)
            or (bool(text) and str(record.get('ip') or '').strip() == text)
        )

    def partial(record: dict[str, Any], kind: str) -> bool:
        return bool(words) and any(
            all(word in name for word in words) for name in _names(record, kind)
        )

    for tier in (exact, partial):
        matches = [(record, kind) for record, kind in pool if tier(record, kind)]
        macs = {normalise_mac(record.get('mac')) for record, _ in matches}
        if len(matches) > 1 and len(macs) == 1 and None not in macs:
            return matches[:1]  # one MAC: a device the controller also lists as a client
        if matches:
            return matches
    return []


def describe_matches(matches: list[tuple[dict[str, Any], str]]) -> str:
    """Name each candidate of an ambiguous match: its name (or hostname) and MAC."""
    return '; '.join(
        f'{record.get("name") or record.get("hostname") or "?"} ({record.get("mac")})'
        for record, _ in matches
    )


async def resolve_probe_target(target: str) -> tuple[str, str | None]:
    """Return the address to probe and the name it resolved from (None for an address).

    An IP address is used as given. Anything else is looked up through the controller, in
    the adopted devices and the clients together (:func:`match_identities`: exact identities
    first, then a unique partial name). The address found goes through ``require_ip``.

    Raises:
        ToolError: ``DEVICE_NOT_FOUND`` for no match or one naming the candidates,
            ``DEVICE_OFFLINE`` for a match with no address, ``INVALID_IP`` for an address
            that is not one.
    """
    if is_ip_address(target):
        return require_ip(target.strip()), None
    async with UniFiClient() as client:
        devices = await client.get_devices()
        clients = await client.get_clients()
    matches = match_identities(devices, clients, target)
    if len(matches) > 1:
        raise _not_found(
            f'{target!r} matches more than one device or client: {describe_matches(matches)}'
        )
    if not matches:
        raise _not_found(f'No device or client matched {target!r}')
    record, _ = matches[0]
    found, name = record.get('ip'), record.get('name') or record.get('hostname') or target
    if not found:
        raise ToolError(
            message=f'{name} has no IP address',
            error_code=ErrorCodes.DEVICE_OFFLINE,
            suggestion='It may be offline or without a DHCP lease',
        )
    return require_ip(str(found)), str(name)


# --- the probes (each one SSH session, one argv per command, its own bound) ---------------


async def gateway_ping(target: str, count: int = 10, interval: float = 0.3) -> dict[str, Any]:
    """Ping one target from the gateway: loss and round trips through the real path.

    Args:
        target: An IP address, or a device or client name, hostname or MAC.
        count: Echo requests, 1-100.
        interval: Seconds between them, 0.2-5.0.

    Returns:
        ``target``, ``probe_ip``, ``resolved_name``, the counts, loss, round trips and
        ``reachable``.
    """
    count = require_bounded_int('ping count', count, 1, 100)
    interval = require_bounded_float('ping interval', interval, 0.2, 5.0)
    ssh_login()  # a missing SSH password fails before the controller is asked for a name
    probe_ip, resolved = await resolve_probe_target(target)
    argv = ['ping', '-c', str(count), '-i', f'{interval:g}', '-W', '2', probe_ip]
    async with gateway_session() as conn:
        result = await run_gateway_command(conn, argv, timeout=count * interval + 12)
    stats = parse_ping_output(result.stdout)
    return {
        'target': target,
        'probe_ip': probe_ip,
        'resolved_name': resolved,
        'transmitted': stats.transmitted,
        'received': stats.received,
        'loss_pct': stats.loss_pct,
        'rtt_min_ms': stats.rtt_min,
        'rtt_avg_ms': stats.rtt_avg,
        'rtt_max_ms': stats.rtt_max,
        'rtt_mdev_ms': stats.rtt_mdev,
        'reachable': stats.reachable,
    }


async def gateway_traceroute(target: str, max_hops: int = 20) -> dict[str, Any]:
    """Trace the gateway's real forwarding path to a target.

    Args:
        target: An IP address, or a device or client name, hostname or MAC.
        max_hops: Hops to probe, 1-30.

    Returns:
        ``target``, ``probe_ip``, ``resolved_name``, ``hops`` and ``reached``.
    """
    max_hops = require_bounded_int('traceroute hops', max_hops, 1, 30)
    ssh_login()  # a missing SSH password fails before the controller is asked for a name
    probe_ip, resolved = await resolve_probe_target(target)
    argv = ['traceroute', '-m', str(max_hops), '-w', '2', probe_ip]
    async with gateway_session() as conn:
        result = await run_gateway_command(conn, argv, timeout=max_hops * 6 + 15)
    hops = parse_traceroute_output(result.stdout)
    return {
        'target': target,
        'probe_ip': probe_ip,
        'resolved_name': resolved,
        'hops': hops,
        'reached': bool(hops) and not hops[-1]['timeout'],
    }


async def gateway_dns_check(hostname: str, server: str | None = None) -> dict[str, Any]:
    """Resolve a hostname on the gateway, optionally against one DNS server.

    Args:
        hostname: The name to resolve (``require_hostname``).
        server: A DNS server's IP address to ask instead of the gateway's own.

    Returns:
        ``resolved``, ``addresses``, ``names``, ``server``, ``error``, ``hostname`` and
        ``requested_server``.
    """
    hostname = require_hostname(hostname)
    if server is not None:
        server = require_ip(server)
    argv = ['nslookup', hostname, *([server] if server else [])]
    async with gateway_session() as conn:
        result = await run_gateway_command(conn, argv, timeout=DNS_TIMEOUT)
    parsed = parse_nslookup_output(result.stdout + result.stderr)
    return {**parsed, 'hostname': hostname, 'requested_server': server}


async def _gateway_interfaces(conn: Any) -> list[dict[str, Any]]:
    """The gateway's interfaces and addresses (``ip -j addr show``), parsed."""
    result = await run_gateway_command(
        conn, ['ip', '-j', 'addr', 'show'], timeout=INTERFACES_TIMEOUT
    )
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        raise ToolError(
            message='ip -j addr show on the gateway did not return JSON',
            error_code=ErrorCodes.API_ERROR,
        ) from None
    return (
        [entry for entry in parsed if isinstance(entry, dict)] if isinstance(parsed, list) else []
    )


async def _vlan_interface(conn: Any, vlan: int) -> str:
    async with UniFiClient() as client:
        networks = await client.get_networks()
    mapping = resolve_vlan_interfaces(networks, await _gateway_interfaces(conn))
    for entry in mapping['resolved']:
        if entry['vlan_id'] == vlan:
            return entry['iface']
    raise ToolError(
        message=f'VLAN {vlan} has no live interface on the gateway whose address is in its subnet',
        error_code=ErrorCodes.NO_DATA,
        suggestion='Check the VLAN ID, or give the interface itself with --interface',
    )


async def gateway_http_check(
    url: str,
    vlan: int | None = None,
    interface: str | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """Fetch an http(s) URL from the gateway, optionally from one VLAN's interface.

    Args:
        url: The URL (``require_http_url``: no user name or password in it).
        vlan: Fetch from the interface whose address is in this VLAN's subnet (1-4094).
        interface: Or from this interface (``require_interface_name``); not both.
        timeout_seconds: curl's ``--max-time``, 1-60.

    Returns:
        ``http_status``, ``time_total_s``, ``remote_ip``, ``ok``, ``url``, ``interface``,
        ``vlan`` and, on failure, curl's last error line (redacted).
    """
    url = require_http_url(url)
    timeout_seconds = require_bounded_int('HTTP timeout', timeout_seconds, 1, 60)
    if vlan is not None and interface is not None:
        raise ToolError(
            message='give a VLAN or an interface, not both',
            error_code=ErrorCodes.CONFIG_INVALID,
        )
    if vlan is not None:
        vlan = require_bounded_int('VLAN', vlan, 1, 4094)
    if interface is not None:
        interface = require_interface_name(interface)
    async with gateway_session() as conn:
        iface = interface if vlan is None else await _vlan_interface(conn, vlan)
        argv = [
            'curl', '-sS', '--globoff', '-o', '/dev/null', '--max-time', str(timeout_seconds),
            '-w', WRITE_OUT, *(['--interface', iface] if iface else []), '--', url,
        ]  # fmt: skip
        result = await run_gateway_command(conn, argv, timeout=timeout_seconds + 10)
    parsed = parse_curl_writeout(result.stdout)
    out = {**parsed, 'url': url, 'interface': iface, 'vlan': vlan}
    if not parsed['ok'] and result.stderr.strip():
        out['error'] = redact_text(result.stderr.strip().splitlines()[-1])
    return out


async def get_active_flows(
    ip: str | None = None, state: str | None = None, limit: int = 200
) -> dict[str, Any]:
    """The gateway's connection-tracking flows, filtered in Python.

    UNREPLIED flows are traffic that left with nothing back (a firewall drop, a dead route
    or upstream).

    Args:
        ip: Keep only flows where this address is a source or destination.
        state: Keep only this state or flag (:data:`FLOW_STATES`, any case).
        limit: Flows to return, 1-5000.

    Returns:
        ``ip_filter``, ``state_filter``, ``total_matching``, ``unreplied_count``,
        ``truncated`` and ``flows``.
    """
    if ip is not None:
        ip = require_ip(ip)
    state_filter = state.upper() if state is not None else None
    if state_filter is not None and state_filter not in FLOW_STATES:
        raise ToolError(
            message=f'state must be one of {", ".join(FLOW_STATES)}',
            error_code=ErrorCodes.CONFIG_INVALID,
        )
    limit = require_bounded_int('flow limit', limit, 1, 5000)
    async with gateway_session() as conn:
        result = await run_gateway_command(conn, ['conntrack', '-L'], timeout=FLOWS_TIMEOUT)
    flows = parse_conntrack_output(result.stdout, ip=ip, state=state_filter)
    return {
        'ip_filter': ip,
        'state_filter': state_filter,
        'total_matching': len(flows),
        'unreplied_count': sum(1 for f in flows if f['unreplied']),
        'truncated': len(flows) > limit,
        'flows': flows[:limit],
    }
