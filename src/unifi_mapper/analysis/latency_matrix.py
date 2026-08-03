"""Gateway-centric latency matrix tool for UniFi networks.

SSHs to the UDM Pro Max and pings all known device/client IPs to build
a connectivity and latency report from the gateway's vantage point.
"""

import asyncio
import asyncssh
import re
from datetime import datetime
from unifi_mapper.core.models import LatencyMatrixReport, LatencyResult
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.client import UniFiClient
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


def _as_text(value: object) -> str:
    """Coerce asyncssh process output to str.

    `SSHCompletedProcess.stdout/stderr` are typed `BytesOrStr` because the channel
    encoding is configurable, so string operations on them fail type checking.
    """
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return '' if value is None else str(value)


async def run_latency_matrix(
    ping_count: int = 3,
    timeout: int = 2,
    include_clients: bool = True,
) -> LatencyMatrixReport:
    """SSH to UDM and ping all device/client IPs to build a latency matrix.

    Args:
        ping_count: Number of pings per target (default 3)
        timeout: Ping timeout in seconds per target (default 2)
        include_clients: Include wireless/wired clients (default True)

    Returns:
        LatencyMatrixReport with per-target latency results

    Raises:
        ToolError: If SSH or API connection fails
    """
    creds = Credentials.from_env()

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

    targets = _build_target_list(devices, clients, include_clients)

    if not targets:
        raise ToolError(
            message='No targets found with IP addresses',
            error_code=ErrorCodes.NO_DATA,
            suggestion='Ensure devices are online and have IP addresses assigned',
        )

    # SSH to UDM and ping all targets
    results = await _ping_targets_via_ssh(creds, targets, ping_count, timeout)

    reachable = [r for r in results if r.reachable]
    unreachable = [r for r in results if not r.reachable]

    return LatencyMatrixReport(
        timestamp=datetime.now().isoformat(),
        gateway_host=creds.host,
        targets_total=len(results),
        targets_reachable=len(reachable),
        targets_unreachable=len(unreachable),
        ping_count=ping_count,
        results=results,
        unreachable_devices=[r.name for r in unreachable],
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


async def _ping_targets_via_ssh(
    creds: Credentials,
    targets: list[dict],
    ping_count: int,
    timeout: int,
) -> list[LatencyResult]:
    """SSH to UDM and run ping commands for all targets."""
    import os

    # UDM SSH uses 'root' with the UniFi OS password (may differ from API creds)
    ssh_user = os.environ.get('UNIFI_SSH_USERNAME', 'root')
    ssh_pass = os.environ.get('UNIFI_SSH_PASSWORD') or creds.password

    try:
        conn = await asyncssh.connect(
            creds.host,
            username=ssh_user,
            password=ssh_pass,
            known_hosts=None,
            client_keys=[],  # Don't try local SSH keys
            preferred_auth='keyboard-interactive,password',
        )
    except Exception as e:
        raise ToolError(
            message=f'SSH connection to {creds.host} failed: {e}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=(
                'Set UNIFI_SSH_USERNAME (default: root) and UNIFI_SSH_PASSWORD in config. '
                'Ensure SSH is enabled in UniFi OS Settings > System > Advanced.'
            ),
        )

    results: list[LatencyResult] = []

    async with conn:
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
    """Run a single ping command and parse results."""
    ip = target['ip']
    cmd = f'ping -c {count} -W {timeout} {ip}'

    try:
        result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=count * timeout + 5)
        return _parse_ping_output(target, _as_text(result.stdout))
    except asyncio.TimeoutError:
        return LatencyResult(
            ip=ip,
            name=target['name'],
            target_type=target['type'],
            reachable=False,
            packet_loss=100.0,
        )
    except Exception:
        return LatencyResult(
            ip=ip,
            name=target['name'],
            target_type=target['type'],
            reachable=False,
            packet_loss=100.0,
        )


def _parse_ping_output(target: dict, output: str) -> LatencyResult:
    """Parse ping output for RTT stats and packet loss."""
    # Parse packet loss: "3 packets transmitted, 3 received, 0% packet loss"
    loss_match = re.search(r'(\d+)% packet loss', output)
    packet_loss = float(loss_match.group(1)) if loss_match else 100.0

    # Parse RTT: "rtt min/avg/max/mdev = 0.123/0.456/0.789/0.012 ms"
    rtt_match = re.search(
        r'(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)',
        output,
    )

    if rtt_match and packet_loss < 100:
        return LatencyResult(
            ip=target['ip'],
            name=target['name'],
            target_type=target['type'],
            reachable=True,
            rtt_min=float(rtt_match.group(1)),
            rtt_avg=float(rtt_match.group(2)),
            rtt_max=float(rtt_match.group(3)),
            rtt_mdev=float(rtt_match.group(4)),
            packet_loss=packet_loss,
        )

    return LatencyResult(
        ip=target['ip'],
        name=target['name'],
        target_type=target['type'],
        reachable=packet_loss < 100,
        packet_loss=packet_loss,
    )
