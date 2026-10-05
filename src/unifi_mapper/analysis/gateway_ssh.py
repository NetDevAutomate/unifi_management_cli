"""The only door to the gateway over SSH: sessions, commands and checks on their values.

``diagnose latency-matrix`` and ``diagnose bandwidth`` run ``ping`` and ``iperf3`` on the
gateway, normally as root, with addresses the controller reports or the user types. Every SSH
session opens here (``gateway_session``) and every command runs here
(``run_gateway_command``): an argv list, shell-quoted with ``shlex.join``, bounded by a timeout
the caller must state. Every value is checked here before it goes on a command line, so no
value can add a shell command, or an option, of its own. The SSH login (``ssh_login``) comes
only from ``UNIFI_SSH_USERNAME`` and ``UNIFI_SSH_PASSWORD``.

The gateway's host key is not verified: ``GATEWAY_KNOWN_HOSTS`` is the one constant issue 038
changes. ``asyncssh.connect`` is called nowhere else in ``src/`` (a test scans for it).
"""

import asyncio
import asyncssh
import ipaddress
import math
import os
import re
import shlex
from collections.abc import AsyncIterator, Container, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unifi_mapper.core.utils.auth import Credentials
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.core.utils.redact import redact_text
from urllib.parse import urlsplit


DEFAULT_SSH_USERNAME = 'root'
SSH_PASSWORD_MISSING = (
    'UNIFI_SSH_PASSWORD is not set. The gateway SSH login has its own password; '
    'UNIFI_PASSWORD (the UniFi OS login) is never sent over SSH'
)
SSH_PASSWORD_SUGGESTION = (
    'Enable SSH in UniFi OS (Settings > Control Plane > Console) and set UNIFI_SSH_PASSWORD '
    'to the SSH password set there; set UNIFI_SSH_USERNAME as well if the SSH user is not root'
)
SSH_CONNECT_SUGGESTION = (
    'Set UNIFI_SSH_USERNAME (default: root) and UNIFI_SSH_PASSWORD in config. '
    'Ensure SSH is enabled in UniFi OS (Settings > Control Plane > Console).'
)
# The gateway's host key is not checked (issue 038 changes this one line).
GATEWAY_KNOWN_HOSTS: None = None
# Seconds allowed for the TCP connect, the SSH handshake and the login together.
SSH_CONNECT_TIMEOUT = 30

MAX_HOSTNAME_LENGTH = 253
MAX_URL_LENGTH = 2048
_HOSTNAME_LABEL_RE = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')
_INTERFACE_RE = re.compile(r'[a-z][a-z0-9.-]{0,14}')


@dataclass(frozen=True)
class GatewayResult:
    """What one command run on the gateway returned.

    Attributes:
        stdout: Standard output, as text.
        stderr: Standard error, as text.
        exit_status: The exit status; ``-1`` when the command ended without one (asyncssh's
            own value for a command ended by a signal), so a caller that treats non-zero as a
            failure does so here too.
    """

    stdout: str
    stderr: str
    exit_status: int


def as_text(value: object) -> str:
    """Coerce asyncssh process output to str.

    ``SSHCompletedProcess.stdout``/``stderr`` are typed ``BytesOrStr`` because the channel
    encoding is configurable, so string operations on them fail type checking.

    Args:
        value: The output, as bytes, str or None.

    Returns:
        The output as text; bytes that are not UTF-8 are replaced.
    """
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return '' if value is None else str(value)


def ssh_login() -> tuple[str, str]:
    """Return the username and password for SSH to the gateway.

    The password comes only from ``UNIFI_SSH_PASSWORD``. ``UNIFI_PASSWORD`` is the UniFi OS
    login, not the console's SSH password, so sending it to root SSH only fails and leaves
    failed root logins on the gateway. The username is ``UNIFI_SSH_USERNAME``, default
    ``root``. Empty values count as unset.

    Returns:
        ``(username, password)``.

    Raises:
        ToolError: ``CONFIG_MISSING`` if ``UNIFI_SSH_PASSWORD`` is unset or empty. Call this
            before connecting to anything.
    """
    password = os.environ.get('UNIFI_SSH_PASSWORD')
    if not password:
        raise ToolError(
            message=SSH_PASSWORD_MISSING,
            error_code=ErrorCodes.CONFIG_MISSING,
            suggestion=SSH_PASSWORD_SUGGESTION,
        )
    return os.environ.get('UNIFI_SSH_USERNAME') or DEFAULT_SSH_USERNAME, password


@asynccontextmanager
async def gateway_session(
    host: str | None = None,
    *,
    suggestion: str = SSH_CONNECT_SUGGESTION,
    connect_timeout: float = SSH_CONNECT_TIMEOUT,
) -> AsyncIterator[asyncssh.SSHClientConnection]:
    """Open one SSH session to the gateway, and close it on exit.

    The login is checked first (``ssh_login``), so a missing ``UNIFI_SSH_PASSWORD`` fails
    before anything connects. The connect, handshake and login together are bounded by
    ``connect_timeout``, so a gateway that stalls never hangs the command.

    Args:
        host: The gateway's address; defaults to ``Credentials.from_env().host``.
        suggestion: What the connect error tells the user to check.
        connect_timeout: Seconds allowed to connect and log in (default 30).

    Yields:
        The open connection, for ``run_gateway_command``.

    Raises:
        ToolError: ``CONFIG_MISSING`` without ``UNIFI_SSH_PASSWORD``;
            ``CONTROLLER_UNREACHABLE`` if the connection or the login fails or takes longer
            than ``connect_timeout``, with the exception text redacted.
    """
    username, password = ssh_login()
    target = host if host is not None else Credentials.from_env().host
    try:
        async with asyncio.timeout(connect_timeout):
            conn = await asyncssh.connect(
                target,
                username=username,
                password=password,
                known_hosts=GATEWAY_KNOWN_HOSTS,
                client_keys=[],  # don't try local SSH keys
                preferred_auth='keyboard-interactive,password',
            )
    except TimeoutError:
        raise ToolError(
            message=f'SSH connection to {target} timed out after {connect_timeout:g}s',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        ) from None
    except Exception as e:
        raise ToolError(
            message=f'SSH connection to {target} failed: {redact_text(e)}',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
            suggestion=suggestion,
        ) from None
    async with conn:
        yield conn


async def run_gateway_command(
    conn: asyncssh.SSHClientConnection, argv: Sequence[str], *, timeout: float
) -> GatewayResult:
    """Run one command on the gateway, never a raw string.

    Args:
        conn: A connection from ``gateway_session``.
        argv: The program and its arguments, each one checked by the caller; joined with
            ``shlex.join``, so every element reaches the program as one argument.
        timeout: Seconds to wait for the command (required: every caller states its bound).

    Returns:
        The command's output and exit status.

    Raises:
        ToolError: ``TIMEOUT`` naming the program and the bound only, never the full line.
        TypeError: If ``argv`` is a ``str`` or ``bytes``: ``shlex.join`` would run its first
            character with the rest as one-letter arguments.
        ValueError: If ``argv`` is empty.
    """
    if isinstance(argv, str | bytes):
        raise TypeError('argv must be a list of arguments, not a string')
    if not argv:
        raise ValueError('argv must name a program')
    command = shlex.join(argv)
    try:
        async with asyncio.timeout(timeout):
            result = await conn.run(command, check=False)
    except TimeoutError:
        raise ToolError(
            message=f'{argv[0]} timed out after {timeout:g}s on the gateway',
            error_code=ErrorCodes.TIMEOUT,
        ) from None
    exit_status = result.exit_status
    return GatewayResult(
        stdout=as_text(result.stdout),
        stderr=as_text(result.stderr),
        exit_status=-1 if exit_status is None else exit_status,
    )


def check_exit_status(
    result: GatewayResult, program: str, result_codes: Container[int] = (0,)
) -> GatewayResult:
    """Return ``result`` when its exit status is one of the program's result codes.

    A program that could not run (missing, not permitted for the SSH user, killed) prints
    nothing on stdout, which its parser would read as an answer: no flows, or 100% loss. So
    any other status is an error naming the program and the status, with the last line of
    its stderr redacted.

    Args:
        result: What :func:`run_gateway_command` returned.
        program: The program's name, for the message.
        result_codes: The statuses that carry a result (``ping`` 0 and 1, ``conntrack`` 0).

    Returns:
        ``result`` itself, so a call can wrap the command it checks.

    Raises:
        ToolError: ``API_ERROR`` for any other status.
    """
    if result.exit_status in result_codes:
        return result
    lines = result.stderr.strip().splitlines()
    detail = f': {redact_text(lines[-1])}' if lines else ''
    status = result.exit_status
    raise ToolError(
        message=f'{program} could not run on the gateway (exit status {status}){detail}',
        error_code=ErrorCodes.API_ERROR,
        suggestion='Check that the SSH user may run it on the gateway (UNIFI_SSH_USERNAME)',
    )


def require_ip(value: object) -> str:
    """Return ``value`` unchanged if it is an IPv4 or IPv6 address string.

    ``ipaddress`` accepts any text after ``%`` as an IPv6 zone id, so
    ``'fe80::1%eth0; reboot'`` parses; an address with a zone id is refused for that reason.

    Args:
        value: The address, from the user or the controller.

    Returns:
        ``value``, exactly as given.

    Raises:
        ToolError: ``INVALID_IP`` if ``value`` is not an address string or has a zone id.
    """
    try:
        address = ipaddress.ip_address(value) if isinstance(value, str) else None
    except ValueError:
        address = None
    if address is None:
        raise ToolError(
            message=f'{value!r} is not an IPv4 or IPv6 address',
            error_code=ErrorCodes.INVALID_IP,
            suggestion='Give an IP address such as 192.0.2.10 or 2001:db8::10',
        )
    if isinstance(address, ipaddress.IPv6Address) and address.scope_id is not None:
        raise ToolError(
            message=f'{value!r} has an IPv6 zone id, which is not supported',
            error_code=ErrorCodes.INVALID_IP,
            suggestion='Give the address without the %zone suffix',
        )
    return str(value)


def require_hostname(value: object) -> str:
    """Return ``value`` unchanged if it is a hostname (RFC 1123).

    Each dot-separated label is 1 to 63 letters, digits or hyphens and neither starts nor
    ends with a hyphen; the whole name is at most 253 characters. So a value that a program
    would read as an option (``-f``, ``--help``) is refused.

    Args:
        value: The hostname.

    Returns:
        ``value``, exactly as given.

    Raises:
        ToolError: ``CONFIG_INVALID`` for anything else; the refused value is echoed
            redacted (``redact_text``), so a pasted secret is masked.
    """
    if (
        isinstance(value, str)
        and 0 < len(value) <= MAX_HOSTNAME_LENGTH
        and all(_HOSTNAME_LABEL_RE.fullmatch(label) for label in value.split('.'))
    ):
        return value
    raise ToolError(
        message=f'{redact_text(repr(value))} is not a valid hostname',
        error_code=ErrorCodes.CONFIG_INVALID,
        suggestion='Give a hostname such as gateway.example.com',
    )


def _url_error(reason: str) -> ToolError:
    # The URL itself is never echoed: a user name, password or token in it would be.
    return ToolError(
        message=f'The URL is not valid: {reason}',
        error_code=ErrorCodes.CONFIG_INVALID,
        suggestion='Give an http or https URL such as https://www.example.com/',
    )


def require_http_url(value: object) -> str:
    """Return ``value`` unchanged if it is an http(s) URL that is safe on a command line.

    The scheme is ``http`` or ``https``; there is no user name or password (an ``@`` in the
    host part is refused, so no credential lands in the gateway's process list); the host is
    a hostname (``require_hostname``) or an address (``require_ip``, IPv6 in brackets); a
    port, if given, is 1 to 65535; and there is no whitespace or control character, in at
    most 2048 characters. The URL is never echoed in the error.

    Args:
        value: The URL.

    Returns:
        ``value``, exactly as given.

    Raises:
        ToolError: ``CONFIG_INVALID`` for anything else.
    """
    if not isinstance(value, str) or not value:
        raise _url_error('it is empty or not text')
    if len(value) > MAX_URL_LENGTH:
        raise _url_error(f'it is longer than {MAX_URL_LENGTH} characters')
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise _url_error('it holds whitespace or a control character')
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise _url_error(
            'it does not parse, or its port is not a number from 0 to 65535'
        ) from None
    if parts.scheme not in ('http', 'https'):
        raise _url_error('the scheme is not http or https')
    if '@' in parts.netloc:
        raise _url_error('it holds a user name or password (user:password@)')
    host = parts.hostname or ''
    if not host:
        raise _url_error('it has no host')
    if parts.netloc.startswith('['):
        address = _ip_or_none(host)
        if not isinstance(address, ipaddress.IPv6Address) or address.scope_id is not None:
            raise _url_error('the bracketed host is not an IPv6 address without a zone id')
    elif _ip_or_none(host) is None:
        try:
            require_hostname(host)
        except ToolError:
            raise _url_error('the host is not a valid hostname or address') from None
    if port is not None and not 1 <= port <= 65535:
        raise _url_error('the port is not from 1 to 65535')
    return value


def _ip_or_none(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def require_interface_name(value: object) -> str:
    """Return ``value`` unchanged if it is a Linux interface name (``br0``, ``eth8.30``).

    A lower-case letter, then up to 14 lower-case letters, digits, dots or hyphens.

    Args:
        value: The interface name.

    Returns:
        ``value``, exactly as given.

    Raises:
        ToolError: ``CONFIG_INVALID`` for anything else; the refused value is echoed
            redacted (``redact_text``), so a pasted secret is masked.
    """
    if isinstance(value, str) and _INTERFACE_RE.fullmatch(value):
        return value
    raise ToolError(
        message=f'{redact_text(repr(value))} is not a valid interface name',
        error_code=ErrorCodes.CONFIG_INVALID,
        suggestion='Give an interface name such as br0 or eth8',
    )


def require_bounded_int(label: str, value: object, low: int, high: int) -> int:
    """Return ``value`` unchanged if it is a whole number from ``low`` to ``high``.

    A ``bool`` is refused although it is an ``int``: ``True`` would become ``-c True``.

    Args:
        label: What the value is, for the error message (e.g. ``'ping count'``).
        value: The value to check.
        low: The smallest value allowed.
        high: The largest value allowed.

    Returns:
        ``value``.

    Raises:
        ToolError: ``CONFIG_INVALID`` if ``value`` is not an ``int`` in the range.
    """
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    raise ToolError(
        message=f'{label} must be a whole number from {low} to {high}, '
        f'not {redact_text(repr(value))}',
        error_code=ErrorCodes.CONFIG_INVALID,
    )


def require_bounded_float(label: str, value: object, low: float, high: float) -> float:
    """Return ``value`` as a float if it is a finite number from ``low`` to ``high``.

    A ``bool`` is refused although it is an ``int``.

    Args:
        label: What the value is, for the error message (e.g. ``'ping interval'``).
        value: The value to check (an ``int`` or a ``float``).
        low: The smallest value allowed.
        high: The largest value allowed.

    Returns:
        ``float(value)``.

    Raises:
        ToolError: ``CONFIG_INVALID`` if ``value`` is not a finite number in the range.
    """
    # The range check runs first: Python compares an int with a float exactly, while
    # math.isfinite (and float) raise OverflowError on a huge int.
    if isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high:
        try:
            number = float(value)
        except OverflowError:
            number = math.inf
        if math.isfinite(number):
            return number
    raise ToolError(
        message=f'{label} must be a number from {low:g} to {high:g}, '
        f'not {redact_text(repr(value))}',
        error_code=ErrorCodes.CONFIG_INVALID,
    )
