"""One-shot client connectivity diagnosis: ``unifi-mapper diagnose client-connectivity``.

Class B, CLI only (no MCP tool: exposing an SSH probe over MCP is decision D1 in issue 060, and
long-running MCP work waits for D4). It chains the checks of the "my phone says No Internet"
workflow, each a layer: find the client on the controller, its AP's VAP counters, a ping from
the gateway, DNS on the gateway, an HTTP probe from the client's VLAN, and the client's
conntrack flows, then a layered verdict (:func:`build_verdict`).

Bounds: the controller lookup runs under ``asyncio.timeout(45)``; each SSH probe keeps its own
bounds (``connectivity/gateway_probe.py``); and the whole chain has a 120 s budget
(:data:`CHAIN_BUDGET_SECONDS`). A layer that fails or times out becomes that layer's finding,
so one failing layer never hides the others, and a layer the budget leaves no time for is
reported ``not_run: budget``. The controller reads borrow the read-only holder the CLI
installs, so none of them can write; the probes run on the gateway as the SSH user, whose
host key is not verified (issue 038).

Ported from the July work (a local archive, not in the repo): the verdict's layers and wording
are July's. Adapted: the HTTP probe takes the client's VLAN, resolved to the gateway interface
whose address is in its subnet (July passed a VLAN ID as an interface name), an untagged LAN
counts as VLAN 1, a lookup that matches more than one client is an error naming them, and the
DNS check asks for the probe URL's own host.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unifi_mapper.analysis.gateway_ssh import require_http_url, ssh_login
from unifi_mapper.analysis.vlan_interfaces import network_vlan_id
from unifi_mapper.connectivity.gateway_probe import (
    describe_matches,
    gateway_dns_check,
    gateway_http_check,
    gateway_ping,
    get_active_flows,
    match_identities,
)
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.redact import redact_text, strip_secrets
from unifi_mapper.diagnostic_reads import is_ip_address, normalise_mac
from unifi_mapper.diagnostics.observability import (
    MAX_QUERY_LENGTH,
    RETRY_PCT_UNHEALTHY,
    device_stats_from_data,
)
from urllib.parse import urlsplit


CAPTIVE_PROBE_URL = 'http://captive.apple.com/hotspot-detect.html'
CHAIN_BUDGET_SECONDS = 120
LOOKUP_TIMEOUT = 45  # the controller reads (httpx bounds each request at 30 s)
PING_COUNT = 4
HTTP_TIMEOUT = 10  # curl's --max-time
# The probe layers in the order they run, and how a finding names each.
LAYERS = ('ping', 'dns', 'http', 'flows')
LAYER_LABELS = {
    'ping': 'gateway ping',
    'dns': 'DNS',
    'http': 'HTTP probe',
    'flows': 'conntrack flows',
}
NO_ADDRESS = 'no IP address'
BUDGET = 'budget'
# The HTTP probe runs from the client's VLAN; with the client's network unresolved, the
# gateway's default path would test some other VLAN, so the layer is not run.
NETWORK_UNKNOWN = 'client network unknown'
# A probe URL whose host is an address needs no lookup, so DNS has nothing to test.
HOST_IS_ADDRESS = 'probe URL host is an address'

OK_VERDICT = (
    'No connectivity fault found: path, DNS, and captive probe all pass. '
    "If the client still shows 'No Internet', the banner is likely a stale "
    'captive-probe result from join time — it clears on rejoin. Conntrack '
    'evidence above outranks the banner.'
)
FAULT_VERDICT = 'Connectivity fault found — see findings (first failing layer is the lead).'


def _ping_findings(ping: dict[str, Any]) -> tuple[bool, str]:
    loss = ping.get('loss_pct')
    if not ping.get('reachable'):
        return False, (
            f'Gateway cannot ping the client ({loss}% loss) — the client is unreachable at L3 '
            '(asleep, blocked, or air-path dead).'
        )
    if (loss or 0) > 20:
        return False, f'High packet loss to the client ({loss}%) — degraded path.'
    return True, f'Client reachable: {loss}% loss, avg RTT {ping.get("rtt_avg_ms")}ms.'


def _ap_finding(ap_stats: dict[str, Any]) -> str:
    unhealthy = [
        v
        for v in ap_stats.get('vaps', [])
        if (v.get('retry_pct_cumulative') or 0) > RETRY_PCT_UNHEALTHY
    ]
    if not unhealthy:
        return f'AP {ap_stats.get("name")} VAP counters look healthy.'
    names = ', '.join(f'{v["essid"]} ({v["retry_pct_cumulative"]}%)' for v in unhealthy)
    return (
        f'AP {ap_stats.get("name")} shows elevated cumulative TX retries on: {names}. '
        'Confirm with diagnose ap-retries (an interval measurement): cumulative can be stale.'
    )


def _flows_finding(flows: dict[str, Any]) -> tuple[bool, str]:
    unreplied = flows.get('unreplied_count', 0)
    total = flows.get('total_matching', 0)
    if total and unreplied and unreplied / max(total, 1) > 0.5:
        return False, (
            f'{unreplied}/{total} conntrack flows for the client are UNREPLIED — '
            'traffic leaves but nothing returns (firewall drop or blackhole).'
        )
    if total:
        return True, (
            f'Conntrack shows {total} live flows ({unreplied} unreplied) — '
            'the client is actively passing traffic.'
        )
    return True, 'No live conntrack flows for the client right now.'


def build_verdict(
    *,
    client_found: bool,
    ping: dict[str, Any] | None,
    ap_stats: dict[str, Any] | None,
    dns: dict[str, Any] | None,
    http: dict[str, Any] | None,
    flows: dict[str, Any] | None,
    failed: dict[str, str] | None = None,
    not_run: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Combine the layers' results into a layered verdict. Pure.

    Args:
        client_found: Whether the client was found on the controller.
        ping: The gateway ping result, or None when it has none.
        ap_stats: ``device_stats_from_data`` of the client's AP (wireless clients only).
        dns: The gateway DNS check result.
        http: The HTTP probe result (from the client's VLAN).
        flows: The conntrack flows for the client's address.
        failed: Layer name (:data:`LAYERS`) to the error text of a layer that ran and failed.
        not_run: Layer name to why it did not run (``budget``, ``no IP address``, ``client
            network unknown``, ``probe URL host is an address``).

    Returns:
        ``ok`` (every layer that was given ran and passed), ``verdict`` and ``findings``.
        A failing check makes the verdict a fault; otherwise a layer that failed or did not
        run makes it inconclusive.
    """
    if not client_found:
        return {
            'ok': False,
            'verdict': 'Client not found on the controller — it is offline or never joined.',
            'findings': ['Client not present in the controller client table.'],
        }
    failed, not_run = failed or {}, not_run or {}
    findings: list[str] = []
    healthy = True
    if ping is not None:
        passed, text = _ping_findings(ping)
        healthy = healthy and passed
        findings.append(text)
    if ap_stats is not None:
        findings.append(_ap_finding(ap_stats))
    if dns is not None:
        if dns.get('resolved'):
            findings.append('Gateway DNS resolution working.')
        else:
            healthy = False
            findings.append(
                f'DNS resolution failed on the gateway ({dns.get("error") or "no answers"}) — '
                'clients cannot resolve either. Check DNS/upstream first.'
            )
    if http is not None:
        where = http.get('interface')
        if http.get('ok'):
            findings.append(
                f'HTTP captive probe OK from {where or "gateway default"} '
                f'(status {http.get("http_status")}).'
            )
        else:
            healthy = False
            findings.append(
                f'HTTP captive probe FAILED from interface {where or "default"} '
                f'(status {http.get("http_status")}) — clients on this VLAN genuinely '
                'have no working internet path; check firewall/NAT/routing for the VLAN.'
            )
    if flows is not None:
        passed, text = _flows_finding(flows)
        healthy = healthy and passed
        findings.append(text)
    for layer in LAYERS:
        if layer in failed:
            findings.append(f'{LAYER_LABELS[layer]} could not run: {failed[layer]}')
        elif layer in not_run:
            findings.append(f'{LAYER_LABELS[layer]} not run: {not_run[layer]}')
    if not healthy:
        verdict = FAULT_VERDICT
    elif failed or not_run:
        missing = [LAYER_LABELS[layer] for layer in LAYERS if layer in failed or layer in not_run]
        reasons = sorted(set(not_run.values()) | ({'failed'} if failed else set()))
        verdict = (
            'Inconclusive: no fault found in the layers that ran, but '
            f'{", ".join(missing)} did not complete ({", ".join(reasons)}).'
        )
    else:
        verdict = OK_VERDICT
    return {'ok': healthy and not failed and not not_run, 'verdict': verdict, 'findings': findings}


# --- the chain ----------------------------------------------------------------------------


def _not_found(message: str) -> ToolError:
    return ToolError(
        message=message,
        error_code=ErrorCodes.DEVICE_NOT_FOUND,
        suggestion='Give the exact name, hostname, MAC or IP of a client; find_device searches.',
        related_tools=['find_device', 'client_trace'],
    )


def find_client(clients: list[Any], query: str) -> dict[str, Any] | None:
    """The client a query names: exact name, hostname, MAC or IP first, then a unique part.

    Pure. The same rule as ``gateway ping``'s target (``gateway_probe.match_identities``,
    over the clients only). Returns None when nothing matches.

    Raises:
        ToolError: ``DEVICE_NOT_FOUND`` naming the candidates when more than one matches.
    """
    matches = match_identities([], clients, query)
    if len(matches) > 1:
        raise _not_found(f'{query!r} matches more than one client: {describe_matches(matches)}')
    return matches[0][0] if matches else None


def client_network(entry: dict[str, Any], networks: list[Any]) -> tuple[str | None, int | None]:
    """The client's network name and VLAN ID, from networkconf. Pure.

    An untagged LAN the controller lists is VLAN 1, so its HTTP probe runs from that LAN's
    interface; the VLAN is None only when the client's network can't be resolved.
    """
    rows = [n for n in networks if isinstance(n, dict)]
    network_id, name = entry.get('network_id'), entry.get('network')
    net = next((n for n in rows if network_id and n.get('_id') == network_id), None)
    if net is None and name:
        net = next((n for n in rows if n.get('name') == name), None)
    if net is None:
        return name, None
    vlan = network_vlan_id(net)
    return name or net.get('name'), vlan if vlan is not None and 1 <= vlan <= 4094 else None


async def _layer(
    run: Callable[[], Awaitable[dict[str, Any]]], deadline: float
) -> tuple[dict[str, Any], bool]:
    """Run one probe within the budget; return its result and whether it produced one.

    A failure is the layer's result, ``{error, error_code}`` with the text redacted, so the
    chain goes on; only an interrupt (not an ``Exception``) stops it.
    """
    budget = asyncio.timeout(deadline - asyncio.get_running_loop().time())
    try:
        async with budget:
            return await run(), True
    except TimeoutError:
        message = (
            f'the {CHAIN_BUDGET_SECONDS:g} s budget ran out' if budget.expired() else 'timed out'
        )
        return {'error': message, 'error_code': ErrorCodes.TIMEOUT}, False
    except ToolError as e:
        return {'error': redact_text(e.message), 'error_code': e.error_code}, False
    except Exception as e:  # noqa: BLE001 - one failing layer must not hide the others
        return {'error': redact_text(e), 'error_code': ErrorCodes.API_ERROR}, False


async def _lookup() -> tuple[list[Any], list[Any], list[Any]]:
    """The controller's clients, devices and networks, bounded at :data:`LOOKUP_TIMEOUT`."""
    try:
        async with asyncio.timeout(LOOKUP_TIMEOUT), UniFiClient() as api:
            return await api.get_clients(), await api.get_devices(), await api.get_networks()
    except TimeoutError:
        raise ToolError(
            message=f'the controller lookup timed out after {LOOKUP_TIMEOUT} s',
            error_code=ErrorCodes.TIMEOUT,
        ) from None


def skipped_layers(address: str | None, host: str, vlan: int | None) -> dict[str, str]:
    """The layers that can't test the client's own path, and why. Pure.

    Ping and flows need the client's address; DNS needs a probe URL host that is a name; the
    HTTP probe needs the client's VLAN, since the gateway's default path is not it.
    """
    skip: dict[str, str] = {}
    if not address:
        skip['ping'] = skip['flows'] = NO_ADDRESS
    if is_ip_address(host):
        skip['dns'] = HOST_IS_ADDRESS
    if vlan is None:
        skip['http'] = NETWORK_UNKNOWN
    return skip


def _check_arguments(query: str, probe_url: str) -> str:
    if not query.strip() or len(query) > MAX_QUERY_LENGTH:
        raise ToolError(
            message=f'the client must be 1-{MAX_QUERY_LENGTH} characters',
            error_code=ErrorCodes.CONFIG_INVALID,
        )
    url = require_http_url(probe_url)
    host = urlsplit(url).hostname
    if not host:
        raise ToolError(
            message='the probe URL names no host', error_code=ErrorCodes.CONFIG_INVALID
        )
    return host


async def diagnose_client_connectivity(
    client: str, probe_url: str = CAPTIVE_PROBE_URL
) -> dict[str, Any]:
    """Diagnose one client's connectivity in one run, layer by layer.

    The arguments and the SSH login are checked before anything connects. Then the client is
    looked up (name, hostname, MAC or IP) with its AP and network, and the probes run from
    the gateway in order, each bounded and the chain within :data:`CHAIN_BUDGET_SECONDS`:
    ping (4 echo requests), DNS for the probe URL's host, the HTTP probe from the client's
    VLAN, and the conntrack flows for its address. A layer that can't test the client's own
    path is not run, with the reason (:func:`skipped_layers`): no address, a probe URL host
    that is an address, or a client network that can't be resolved.

    Args:
        client: The client's name, hostname, MAC or IP (1-128 characters).
        probe_url: The http(s) URL to fetch, with no user name or password in it.

    Returns:
        ``client``, ``client_ip``, ``client_mac``, ``wired``, ``network``, ``vlan``, ``ap``,
        ``ap_stats``, ``probe_url``, ``probes`` (each layer's result, its ``{error,
        error_code}``, or ``{not_run: reason}``), ``not_run``, ``budget_seconds``, ``ok``,
        ``verdict`` and ``findings``.

    Raises:
        ToolError: ``CONFIG_INVALID`` for a bad argument, ``CONFIG_MISSING`` without the SSH
            password, ``DEVICE_NOT_FOUND`` for a query that matches more than one client, and
            the controller's errors from the lookup.
    """
    host = _check_arguments(client, probe_url)
    ssh_login()  # a missing SSH password fails before the controller is asked
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CHAIN_BUDGET_SECONDS
    clients, devices, networks = await _lookup()
    entry = find_client(clients, client)
    if entry is None:
        result = build_verdict(
            client_found=False, ping=None, ap_stats=None, dns=None, http=None, flows=None
        )
        return {'client': client, 'probe_url': probe_url, **result}

    address = entry.get('ip') or None
    wired = bool(entry.get('is_wired'))
    network, vlan = client_network(entry, networks)
    ap_stats = None
    ap_mac = normalise_mac(entry.get('ap_mac'))
    if not wired and ap_mac:
        ap = next(
            (d for d in devices if isinstance(d, dict) and normalise_mac(d.get('mac')) == ap_mac),
            None,
        )
        if ap is not None:
            ap_stats = device_stats_from_data(strip_secrets(ap, 'device')[0])

    steps: dict[str, Callable[[], Awaitable[dict[str, Any]]] | None] = {
        'ping': (lambda: gateway_ping(address, count=PING_COUNT)) if address else None,
        'dns': lambda: gateway_dns_check(host),
        'http': lambda: gateway_http_check(probe_url, vlan=vlan, timeout_seconds=HTTP_TIMEOUT),
        'flows': (lambda: get_active_flows(ip=address)) if address else None,
    }
    skip = skipped_layers(address, host, vlan)
    probes: dict[str, dict[str, Any]] = {}
    usable: dict[str, dict[str, Any] | None] = dict.fromkeys(LAYERS)
    failed: dict[str, str] = {}
    not_run: dict[str, str] = {}
    for layer in LAYERS:
        step = steps[layer]
        if step is None or layer in skip or deadline - loop.time() <= 0:
            not_run[layer] = skip.get(layer, NO_ADDRESS if step is None else BUDGET)
            probes[layer] = {'not_run': not_run[layer]}
            continue
        probes[layer], ran = await _layer(step, deadline)
        if ran:
            usable[layer] = probes[layer]
        else:
            failed[layer] = f'[{probes[layer]["error_code"]}] {probes[layer]["error"]}'

    verdict = build_verdict(
        client_found=True,
        ping=usable['ping'],
        ap_stats=ap_stats,
        dns=usable['dns'],
        http=usable['http'],
        flows=usable['flows'],
        failed=failed,
        not_run=not_run,
    )
    return {
        'client': entry.get('name') or entry.get('hostname') or entry.get('mac'),
        'client_ip': address,
        'client_mac': entry.get('mac'),
        'wired': wired,
        'network': network,
        'vlan': vlan,
        'ap': ap_stats.get('name') if ap_stats else None,
        'ap_stats': ap_stats,
        'probe_url': probe_url,
        'probes': probes,
        'not_run': [layer for layer in LAYERS if layer in not_run],
        'budget_seconds': CHAIN_BUDGET_SECONDS,
        **verdict,
    }
