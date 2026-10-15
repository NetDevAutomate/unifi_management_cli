"""Live probes run on the gateway over SSH: ping, traceroute, DNS, HTTP and conntrack flows.

Class B (``unifi-mapper gateway ...``; ``gateway_ping``, ``gateway_traceroute`` and
``gateway_dns_check`` are also MCP tools, held back unless the server starts with
``UNIFI_MCP_ALLOW_ACTIVE_PROBES=1``, issue 092; ``http`` and ``flows`` stay CLI only): each
probe opens one session through ``analysis/gateway_ssh.py`` and runs one argv with its own
bound (``gateway http --vlan`` runs two: ``ip -j addr show`` to find the VLAN's interface,
then ``curl``), every value checked by that module's validators first, so nothing a user
or an agent types, or the controller reports, can add a command or an option. The gateway's
host key is verified before the password is sent (issue 038). A device or client name is
resolved to its address through ``UniFiClient()``, which borrows the read-only holder the CLI
(or the MCP server) installs, so those reads can't write.

Ported from the prototype (a local archive, not in the repo): the conntrack, nslookup and
curl parsers are the prototype's, logic unchanged; the traceroute parser reads each hop line token by
token (the prototype's pattern took a time from any digits or dots before ``ms``, host names
included). The handlers are rebuilt on argv lists (the prototype built shell strings and piped
conntrack through ``grep``), ``--globoff`` keeps curl from expanding ``[]`` and ``{}`` in a
URL, and a VLAN resolves to the interface whose address is in its subnet. The prototype's spectrum
scan (a controller command) is not ported.
"""

import ipaddress
import json
import re
from typing import Any
from unifi_mapper.analysis.gateway_ssh import (
    check_exit_status,
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
from unifi_mapper.core.utils.ping_parse import PingStats, parse_ping_output
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
# The exit statuses that carry each program's result; any other means it could not run
# (``check_exit_status``). ping and nslookup exit 1 for no reply or no answer; curl's own
# codes (6 could not resolve, 7 could not connect, 28 timed out, ...) are the HTTP check's
# result, while 126 and 127 mean the shell could not run it.
PING_RESULT_CODES = (0, 1)
NSLOOKUP_RESULT_CODES = (0, 1)
# Some traceroute builds exit 1 when the trace did not reach the target: a result, but only
# when it printed hops (a traceroute that could not run prints none).
TRACEROUTE_RESULT_CODES = (0, 1)
CURL_RESULT_CODES = range(126)
FLOWS_TIMEOUT = 60  # The prototype's 30 s, raised for busy tables
INTERFACES_TIMEOUT = 15

# A hop line's first token is its number (traceroute probes at most 255 hops).
_HOP_NUMBER_RE = re.compile(r'[0-9]{1,3}')
# A probe's time is this token followed by the token "ms" (traceroute prints "0.512 ms").
_HOP_TIME_RE = re.compile(r'[0-9]+(?:\.[0-9]+)?')
# Or one token with the unit glued on, as GNU inetutils' traceroute prints it ("0.351ms").
_HOP_GLUED_TIME_RE = re.compile(r'[0-9]+(?:\.[0-9]+)?ms')
# traceroute's annotation for an ICMP unreachable reply, one token: !H host, !N network, !P
# protocol, !S source route, !F (or !F-<mtu>) fragmentation needed, !X, !V, !C prohibited or
# precedence, !<n> (or !n) another code.
_HOP_UNREACHABLE_RE = re.compile(r'!(?:[HNPSFXVC]|F-[0-9]+|<[0-9]+>|[0-9]+)')
_CONNTRACK_KV_RE = re.compile(r'(\w+)=(\S+)')
_CONNTRACK_FLAG_RE = re.compile(r'\[(\w+)\]')
_NSLOOKUP_ADDR_RE = re.compile(r'^Address(?:\s+\d+)?:\s*(\S+)', re.M)
_NSLOOKUP_NAME_RE = re.compile(r'^Name:\s*(\S+)', re.M)
_DNS_FAILURE_MARKERS = ("can't resolve", "server can't find", 'NXDOMAIN', 'no servers could')


# --- pure parsers (the prototype's, but traceroute's: it reads each hop line token by token) -------


def _paren_address(token: str) -> str | None:
    """The address in a ``(address)`` token, or None for any other token."""
    if token.startswith('(') and token.endswith(')') and is_ip_address(token[1:-1]):
        return token[1:-1]
    return None


def _read_hop(tokens: list[str]) -> tuple[str | None, str | None, list[float], bool]:
    """Read one hop line's tokens after its number. Pure.

    ``*`` is a lost probe; an annotation token (:data:`_HOP_UNREACHABLE_RE`) marks the hop
    unreachable; ``name (address)`` and a bare address are responders, each taken whole and
    never read for a time, so a name such as ``r1.ms.example.net`` or ``edge-100ms`` adds
    none; a number token followed by an ``ms`` token is a probe's time, and so, after those
    checks, is one number token with ``ms`` glued on (GNU inetutils prints ``0.351ms``, and
    a resolved name after the address, in parentheses, which is skipped). Any other token
    is skipped.

    Args:
        tokens: The hop line's whitespace-separated tokens, its number left out.

    Returns:
        ``(host, ip, times, unreachable)``: the first responder's name and address (None
        without one), every probe's time in ms, and whether any probe was annotated.
    """
    host: str | None = None
    ip: str | None = None
    times: list[float] = []
    unreachable = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        following = tokens[i + 1] if i + 1 < len(tokens) else ''
        address = _paren_address(following)
        if token == '*':
            i += 1
        elif _HOP_UNREACHABLE_RE.fullmatch(token):
            unreachable, i = True, i + 1
        elif address is not None:  # "name (address)"
            if ip is None:
                host, ip = token, address
            i += 2
        elif is_ip_address(token):  # a bare address: numeric output, or no reverse name
            if ip is None:
                host = ip = token
            i += 1
        elif following == 'ms' and _HOP_TIME_RE.fullmatch(token):
            times.append(float(token))
            i += 2
        elif _HOP_GLUED_TIME_RE.fullmatch(token):
            times.append(float(token[:-2]))
            i += 1
        else:
            i += 1
    return host, ip, times, unreachable


def parse_traceroute_output(output: str) -> list[dict[str, Any]]:
    """Parse traceroute output (Linux, BusyBox or GNU inetutils; IPv4 or IPv6) into hops.

    A hop line is one whose first token is a number; the rest is read by :func:`_read_hop`.
    A hop with several responders reports the first one's name and address and every time.

    Args:
        output: Raw traceroute stdout.

    Returns:
        One ``{hop, host, ip, rtt_ms, timeout, unreachable}`` dict per hop line;
        ``unreachable`` marks a hop that answered with an ICMP unreachable (``!H``, ``!N``,
        ``!X`` and the like).
    """
    hops: list[dict[str, Any]] = []
    for line in output.splitlines():
        tokens = line.split()
        if not tokens or not _HOP_NUMBER_RE.fullmatch(tokens[0]):
            continue
        host, ip, times, unreachable = _read_hop(tokens[1:])
        hops.append(
            {
                'hop': int(tokens[0]),
                'host': host,
                'ip': ip,
                'rtt_ms': times,
                'timeout': not times,
                'unreachable': unreachable,
            }
        )
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


def _same_address(printed: str | None, target: str) -> bool:
    """Whether a hop's printed address is the target's, however either is written."""
    if printed is None:
        return False
    try:
        return ipaddress.ip_address(printed) == ipaddress.ip_address(target.strip())
    except ValueError:
        return False


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

    Args:
        target: An IP address, or a device or client name, hostname or MAC (or a unique part
            of a name).

    Returns:
        ``(address, name)``: the checked address, and the name it resolved from (None when
        ``target`` was an address).

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


async def ping_over(conn: Any, address: str, count: int, interval: float) -> PingStats:
    """Ping ``address`` from the gateway over the open SSH connection ``conn``.

    The one ping step ``gateway ping`` and AP-health's client pings share (issue 073): the
    address and the bounds are checked, the argv is ``ping -c <count> -i <interval> -W 2
    <address>``, it runs under a bound of ``count * interval + 12`` seconds, exit statuses 0
    and 1 (no reply) are a result and anything else an error, and the output is parsed.

    Args:
        conn: An open gateway connection (``gateway_session``).
        address: The IP address to ping.
        count: Echo requests, 1-100.
        interval: Seconds between them, 0.2-5.0.

    Returns:
        The parsed :class:`PingStats`.

    Raises:
        ToolError: ``CONFIG_INVALID`` for a bad address or bound; ``TIMEOUT`` past the bound;
            ``API_ERROR`` when ping could not run (its last stderr line redacted).
    """
    address = require_ip(address)
    count = require_bounded_int('ping count', count, 1, 100)
    interval = require_bounded_float('ping interval', interval, 0.2, 5.0)
    argv = ['ping', '-c', str(count), '-i', f'{interval:g}', '-W', '2', address]
    result = await run_gateway_command(conn, argv, timeout=count * interval + 12)
    return parse_ping_output(check_exit_status(result, 'ping', PING_RESULT_CODES).stdout)


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
    # Checked here too, so a bad bound fails before the SSH login and the controller read.
    count = require_bounded_int('ping count', count, 1, 100)
    interval = require_bounded_float('ping interval', interval, 0.2, 5.0)
    ssh_login()  # a missing SSH password fails before the controller is asked for a name
    probe_ip, resolved = await resolve_probe_target(target)
    async with gateway_session() as conn:
        stats = await ping_over(conn, probe_ip, count, interval)
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
        ``target``, ``probe_ip``, ``resolved_name``, ``hops`` and ``reached``: true only when
        the last hop is the target itself and answered without an unreachable annotation (not
        when the hops ran out at a router that answers).
    """
    max_hops = require_bounded_int('traceroute hops', max_hops, 1, 30)
    ssh_login()  # a missing SSH password fails before the controller is asked for a name
    probe_ip, resolved = await resolve_probe_target(target)
    argv = ['traceroute', '-m', str(max_hops), '-w', '2', probe_ip]
    async with gateway_session() as conn:
        result = await run_gateway_command(conn, argv, timeout=max_hops * 6 + 15)
    hops = parse_traceroute_output(result.stdout)
    check_exit_status(result, 'traceroute', TRACEROUTE_RESULT_CODES if hops else (0,))
    last = hops[-1] if hops else None
    reached = (
        last is not None
        and _same_address(last['ip'], probe_ip)
        and not last['timeout']
        and not last['unreachable']
    )
    return {
        'target': target,
        'probe_ip': probe_ip,
        'resolved_name': resolved,
        'hops': hops,
        'reached': reached,
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
    check_exit_status(result, 'nslookup', NSLOOKUP_RESULT_CODES)
    parsed = parse_nslookup_output(result.stdout + result.stderr)
    return {**parsed, 'hostname': hostname, 'requested_server': server}


async def _gateway_interfaces(conn: Any) -> list[dict[str, Any]]:
    """The gateway's interfaces and addresses (``ip -j addr show``), parsed."""
    result = await run_gateway_command(
        conn, ['ip', '-j', 'addr', 'show'], timeout=INTERFACES_TIMEOUT
    )
    try:
        parsed = json.loads(check_exit_status(result, 'ip').stdout)
    except ValueError:
        raise ToolError(
            message='ip -j addr show on the gateway did not return JSON',
            error_code=ErrorCodes.API_ERROR,
        ) from None
    return (
        [entry for entry in parsed if isinstance(entry, dict)] if isinstance(parsed, list) else []
    )


async def _vlan_interface(conn: Any, vlan: int) -> str:
    """The gateway interface whose address is in the VLAN's subnet, validated like --interface."""
    async with UniFiClient() as client:
        networks = await client.get_networks()
    mapping = resolve_vlan_interfaces(networks, await _gateway_interfaces(conn))
    for entry in mapping['resolved']:
        if entry['vlan_id'] == vlan:
            # The gateway reports the name; it reaches curl's argv, so check it as typed input.
            return require_interface_name(entry['iface'])
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
            'curl',
            '-sS',
            '--globoff',
            '-o',
            '/dev/null',
            '--max-time',
            str(timeout_seconds),
            '-w',
            WRITE_OUT,
            *(['--interface', iface] if iface else []),
            '--',
            url,
        ]
        result = await run_gateway_command(conn, argv, timeout=timeout_seconds + 10)
    parsed = parse_curl_writeout(check_exit_status(result, 'curl', CURL_RESULT_CODES).stdout)
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
    stdout = check_exit_status(result, 'conntrack').stdout
    flows = parse_conntrack_output(stdout, ip=ip, state=state_filter)
    return {
        'ip_filter': ip,
        'state_filter': state_filter,
        'total_matching': len(flows),
        'unreplied_count': sum(1 for f in flows if f['unreplied']),
        'truncated': len(flows) > limit,
        'flows': flows[:limit],
    }
