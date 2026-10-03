"""Bandwidth testing via iperf3 over SSH to UDM.

Runs iperf3 between the UDM Pro Max and a target device (e.g., NAS)
to measure actual throughput on network paths. The target and both numbers
are checked (``gateway_ssh``) before the iperf3 command line is built, so an
invalid target is refused before anything connects.
"""

import asyncio
import asyncssh
import json
import re
import shlex
from datetime import datetime
from unifi_mapper.analysis.gateway_ssh import require_bounded_int, require_ip, ssh_login
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


# iperf3's own limits: -t up to 86400 seconds, -P up to 128 streams.
DURATION_RANGE = (1, 86400)
PARALLEL_RANGE = (1, 128)


def _as_text(value: object) -> str:
    """Coerce asyncssh process output to str.

    `SSHCompletedProcess.stdout/stderr` are typed `BytesOrStr` because the channel
    encoding is configurable, so string operations on them fail type checking.
    """
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return '' if value is None else str(value)


def check_bandwidth_args(
    target_ip: object, duration: object, parallel: object
) -> tuple[str, int, int]:
    """Check the iperf3 arguments, before anything connects.

    Args:
        target_ip: The target's IPv4 or IPv6 address.
        duration: Test duration in seconds.
        parallel: Number of parallel streams.

    Returns:
        ``(target_ip, duration, parallel)``, unchanged.

    Raises:
        ToolError: ``INVALID_IP`` for a bad target, ``CONFIG_INVALID`` for a number
            out of range.
    """
    return (
        require_ip(target_ip),
        require_bounded_int('duration (seconds)', duration, *DURATION_RANGE),
        require_bounded_int('parallel streams', parallel, *PARALLEL_RANGE),
    )


def _iperf3_command(target_ip: str, duration: int, parallel: int, reverse: bool) -> str:
    """Return the iperf3 command line for checked arguments, every argument shell-quoted."""
    args = ['iperf3', '-c', target_ip, '-t', str(duration), '-P', str(parallel), '-J']
    if reverse:
        args.append('-R')
    return shlex.join(args)


async def run_bandwidth_test(
    target_ip: str,
    duration: int = 10,
    reverse: bool = False,
    parallel: int = 1,
) -> dict:
    """Run iperf3 from UDM to a target device.

    Requires iperf3 installed on UDM (available by default on UniFi OS),
    an iperf3 server running on the target, and ``UNIFI_SSH_PASSWORD``
    (``UNIFI_SSH_USERNAME`` defaults to root).

    Args:
        target_ip: IPv4 or IPv6 address of the device running iperf3 -s
        duration: Test duration in seconds (default 10, from 1 to 86400)
        reverse: If True, test download (target→UDM) instead of upload
        parallel: Number of parallel streams (default 1, from 1 to 128)

    Returns:
        Bandwidth test results with throughput metrics

    Raises:
        ToolError: If an argument is invalid or UNIFI_SSH_PASSWORD is unset (both
            before anything connects), or SSH, iperf3 or the route to the target fails
    """
    target_ip, duration, parallel = check_bandwidth_args(target_ip, duration, parallel)
    creds = Credentials.from_env()
    ssh_user, ssh_pass = ssh_login()  # before connecting: UNIFI_PASSWORD is never tried

    cmd = _iperf3_command(target_ip, duration, parallel, reverse)

    try:
        conn = await asyncssh.connect(
            creds.host,
            username=ssh_user,
            password=ssh_pass,
            known_hosts=None,
            client_keys=[],
            preferred_auth='keyboard-interactive,password',
        )
    except Exception as e:
        raise ToolError(
            message=f'SSH connection failed: {e}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion='Check UNIFI_SSH_USERNAME/UNIFI_SSH_PASSWORD in config',
        )

    async with conn:
        try:
            result = await asyncio.wait_for(
                conn.run(cmd, check=False),
                timeout=duration + 15,
            )
        except asyncio.TimeoutError:
            raise ToolError(
                message=f'iperf3 timed out after {duration + 15}s',
                error_code=ErrorCodes.API_ERROR,
                suggestion=f'Ensure iperf3 server is running on {target_ip} (iperf3 -s)',
            )

    stdout = _as_text(result.stdout)
    stderr = _as_text(result.stderr)

    if result.exit_status != 0:
        # Try to parse common errors
        if 'Connection refused' in stderr or 'Connection refused' in stdout:
            raise ToolError(
                message=f'iperf3 connection refused by {target_ip}',
                error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
                suggestion=f"Start iperf3 server on target: ssh {target_ip} 'iperf3 -s -D'",
            )
        if 'No route to host' in stderr:
            raise ToolError(
                message=f'No route to {target_ip} from UDM',
                error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            )
        # Return raw error
        return {
            'timestamp': datetime.now().isoformat(),
            'target': target_ip,
            'status': 'FAILED',
            'error': stderr or stdout,
        }

    # Parse JSON output
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        # Fallback: parse text output
        return _parse_text_output(stdout, target_ip, reverse, duration)

    return _parse_json_output(data, target_ip, reverse, duration)


def _parse_json_output(data: dict, target_ip: str, reverse: bool, duration: int) -> dict:
    """Parse iperf3 JSON output."""
    end = data.get('end', {})
    sum_sent = end.get('sum_sent', {})
    sum_received = end.get('sum_received', {})

    # Use received for actual throughput (accounts for loss)
    bits_per_second = sum_received.get('bits_per_second', 0)
    mbps = bits_per_second / 1_000_000
    gbps = bits_per_second / 1_000_000_000

    return {
        'timestamp': datetime.now().isoformat(),
        'target': target_ip,
        'direction': 'download (target→UDM)' if reverse else 'upload (UDM→target)',
        'duration_seconds': duration,
        'status': 'OK',
        'throughput_mbps': round(mbps, 1),
        'throughput_gbps': round(gbps, 3),
        'bytes_transferred': sum_received.get('bytes', 0),
        'retransmits': sum_sent.get('retransmits', 0),
        'streams': data.get('start', {}).get('test_start', {}).get('num_streams', 1),
    }


def _parse_text_output(stdout: str, target_ip: str, reverse: bool, duration: int) -> dict:
    """Fallback: parse iperf3 text output."""
    # Look for summary line like: [SUM]   0.00-10.00  sec  1.09 GBytes   937 Mbits/sec
    match = re.search(r'\[SUM\].*?([\d.]+)\s+(G|M)bits/sec', stdout)
    if not match:
        match = re.search(r'([\d.]+)\s+(G|M)bits/sec.*?receiver', stdout)
    if not match:
        match = re.search(r'([\d.]+)\s+(G|M)bits/sec', stdout)

    if match:
        value = float(match.group(1))
        unit = match.group(2)
        mbps = value * 1000 if unit == 'G' else value
    else:
        mbps = 0

    return {
        'timestamp': datetime.now().isoformat(),
        'target': target_ip,
        'direction': 'download (target→UDM)' if reverse else 'upload (UDM→target)',
        'duration_seconds': duration,
        'status': 'OK' if mbps > 0 else 'PARSE_ERROR',
        'throughput_mbps': round(mbps, 1),
        'throughput_gbps': round(mbps / 1000, 3),
    }
