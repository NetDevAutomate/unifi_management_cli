"""Gateway-centric latency matrix tool for UniFi networks.

SSHs to the UDM Pro Max and pings all known device/client IPs to build
a connectivity and latency report from the gateway's vantage point.
Every target IP and both numbers are checked (``gateway_ssh``) before they
go on the ping command line; a target whose IP fails the check is not
pinged and is listed in the report's ``skipped_targets``.
"""

import asyncio
import asyncssh
import shlex
from datetime import datetime
from unifi_mapper.analysis.gateway_ssh import (
    check_exit_status,
    gateway_session,
    require_bounded_int,
    require_ip,
    run_gateway_command,
    ssh_login,
)
from unifi_mapper.core.models import LatencyMatrixReport, LatencyResult, LatencySkippedTarget
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.ping_parse import parse_ping_output


# Each target waits up to count * timeout + 5 s, and targets are pinged ten at a time.
PING_COUNT_RANGE = (1, 100)
PING_TIMEOUT_RANGE = (1, 60)  # seconds


async def run_latency_matrix(
    ping_count: int = 3,
    timeout: int = 2,
    include_clients: bool = True,
) -> LatencyMatrixReport:
    """SSH to UDM and ping all device/client IPs to build a latency matrix.

    Args:
        ping_count: Number of pings per target (default 3, from 1 to 100)
        timeout: Ping timeout in seconds per target (default 2, from 1 to 60)
        include_clients: Include wireless/wired clients (default True)

    Returns:
        LatencyMatrixReport with per-target latency results. Targets whose IP is
        not a plain IPv4 or IPv6 address are not pinged; they are listed in
        ``skipped_targets``. A target whose ping could not run (``ping`` missing or
        refused for the SSH user: an exit status other than 0 or 1) carries that
        error and no loss figure, counted in ``targets_failed``, never among the
        unreachable.

    Raises:
        ToolError: If an argument is out of range or UNIFI_SSH_PASSWORD is unset
            (both before any request), no target has a valid IP, or SSH or API
            connection fails
    """
    ping_count = require_bounded_int('ping count', ping_count, *PING_COUNT_RANGE)
    timeout = require_bounded_int('ping timeout (seconds)', timeout, *PING_TIMEOUT_RANGE)
    creds = Credentials.from_env()
    ssh_login()  # before any request: without UNIFI_SSH_PASSWORD nothing connects

    # Gather target IPs from API
    async with UniFiClient() as client:
        try:
            devices = await client.get_devices()
            clients = await client.get_clients() if include_clients else []
        except Exception as e:
            raise ToolError(
                message=f'Failed to fetch device list: {e}',
                error_code=ErrorCodes.API_ERROR,
            )

    targets, skipped = _split_targets(_build_target_list(devices, clients, include_clients))

    if not targets:
        message = 'No targets found with IP addresses'
        if skipped:
            names = ', '.join(s.name for s in skipped[:5]) + (', ...' if len(skipped) > 5 else '')
            message = f'No targets with a valid IP address ({len(skipped)} skipped: {names})'
        raise ToolError(
            message=message,
            error_code=ErrorCodes.NO_DATA,
            suggestion='Ensure devices are online and have IP addresses assigned',
        )

    # SSH to UDM and ping all targets
    results = await _ping_targets_via_ssh(creds.host, targets, ping_count, timeout)

    reachable = [r for r in results if r.reachable]
    failed = [r for r in results if r.error is not None]
    unreachable = [r for r in results if not r.reachable and r.error is None]

    return LatencyMatrixReport(
        timestamp=datetime.now().isoformat(),
        gateway_host=creds.host,
        targets_total=len(results),
        targets_reachable=len(reachable),
        targets_unreachable=len(unreachable),
        targets_failed=len(failed),
        ping_count=ping_count,
        results=results,
        unreachable_devices=[r.name for r in unreachable],
        skipped_targets=skipped,
    )


def _build_target_list(
    devices: list[dict], clients: list[dict], include_clients: bool
) -> list[dict]:
    """Build deduplicated target list with name and IP."""
    seen_ips: set[str] = set()
    targets: list[dict] = []

    # Infrastructure devices first
    for d in devices:
        ip = d.get('ip')
        if ip and ip not in seen_ips:
            seen_ips.add(ip)
            targets.append(
                {
                    'ip': ip,
                    'name': d.get('name', d.get('mac', 'Unknown')),
                    'type': 'device',
                    'model': d.get('model', ''),
                }
            )

    # Then clients
    if include_clients:
        for c in clients:
            ip = c.get('ip')
            if ip and ip not in seen_ips:
                seen_ips.add(ip)
                targets.append(
                    {
                        'ip': ip,
                        'name': c.get('name') or c.get('hostname') or c.get('mac', 'Unknown'),
                        'type': 'client',
                        'model': '',
                    }
                )

    return targets


def _split_targets(targets: list[dict]) -> tuple[list[dict], list[LatencySkippedTarget]]:
    """Separate the targets whose IP can go on a ping command line from the rest."""
    valid: list[dict] = []
    skipped: list[LatencySkippedTarget] = []
    for target in targets:
        try:
            require_ip(target['ip'])
        except ToolError as e:
            skipped.append(
                LatencySkippedTarget(
                    ip=str(target['ip']),
                    name=str(target['name']),
                    target_type=target['type'],
                    reason=e.message,
                )
            )
        else:
            valid.append(target)
    return valid, skipped


async def _ping_targets_via_ssh(
    host: str,
    targets: list[dict],
    ping_count: int,
    timeout: int,
) -> list[LatencyResult]:
    """Open one SSH session to the gateway at ``host`` and ping every target from it."""
    results: list[LatencyResult] = []

    async with gateway_session(host) as conn:
        # Run pings in batches of 10 to avoid overwhelming the UDM
        batch_size = 10
        for i in range(0, len(targets), batch_size):
            batch = targets[i : i + batch_size]
            tasks = [_ping_single(conn, t, ping_count, timeout) for t in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)

    return results


async def _ping_single(
    conn: asyncssh.SSHClientConnection,
    target: dict,
    count: int,
    timeout: int,
) -> LatencyResult:
    """Run a single ping command and parse results.

    The command may take ``count * timeout + 5`` seconds. A ``TIMEOUT`` past that bound, like
    any other failure to run the command, makes the target unreachable rather than failing
    the matrix. A ``ping`` that ran but could not do its job (an exit status other than 0,
    replies, or 1, no reply: missing, or refused for the SSH user) prints nothing on stdout,
    which the parser would read as 100% loss, so it is the target's ``error`` instead, with
    no loss figure (issue 076 item 4).
    """
    try:
        result = await run_gateway_command(
            conn, _ping_argv(target['ip'], count, timeout), timeout=count * timeout + 5
        )
    except Exception:  # a TIMEOUT ToolError, a dropped channel, anything: unreachable
        return LatencyResult(
            ip=target['ip'],
            name=target['name'],
            target_type=target['type'],
            reachable=False,
            packet_loss=100.0,
        )
    try:
        check_exit_status(result, 'ping', (0, 1))
    except ToolError as e:
        return LatencyResult(
            ip=target['ip'],
            name=target['name'],
            target_type=target['type'],
            reachable=False,
            packet_loss=None,
            error=e.message,
        )
    return _parse_ping_output(target, result.stdout)


def _ping_argv(ip: str, count: int, timeout: int) -> list[str]:
    """Return the ping argv for one checked target."""
    return ['ping', '-c', str(count), '-W', str(timeout), ip]


def _ping_command(ip: str, count: int, timeout: int) -> str:
    """Return the ping command line the gateway runs for one target, shell-quoted."""
    return shlex.join(_ping_argv(ip, count, timeout))


def _parse_ping_output(target: dict, output: str) -> LatencyResult:
    """Parse ping output (GNU or BusyBox, ``core/utils/ping_parse``) into a LatencyResult.

    RTT figures are kept only when some packets came back.
    """
    stats = parse_ping_output(output)
    if stats.reachable and stats.rtt_avg is not None:
        return LatencyResult(
            ip=target['ip'],
            name=target['name'],
            target_type=target['type'],
            reachable=True,
            rtt_min=stats.rtt_min,
            rtt_avg=stats.rtt_avg,
            rtt_max=stats.rtt_max,
            rtt_mdev=stats.rtt_mdev,
            packet_loss=stats.loss_pct,
        )

    return LatencyResult(
        ip=target['ip'],
        name=target['name'],
        target_type=target['type'],
        reachable=stats.reachable,
        packet_loss=stats.loss_pct,
    )
