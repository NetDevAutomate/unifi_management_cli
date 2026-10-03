"""Checks for values that go on a command line run on the gateway over SSH.

``diagnose latency-matrix`` and ``diagnose bandwidth`` run ``ping`` and ``iperf3`` on the
gateway, normally as root, with addresses the controller reports or the user types. Every
value is checked here before it is interpolated, and the command line is shell-quoted as
well (``shlex.join``), so no value can add a shell command of its own. The SSH login
(``ssh_login``) comes only from ``UNIFI_SSH_USERNAME`` and ``UNIFI_SSH_PASSWORD``.
"""

import ipaddress
import os
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


DEFAULT_SSH_USERNAME = 'root'
SSH_PASSWORD_MISSING = (
    'UNIFI_SSH_PASSWORD is not set. The gateway SSH login has its own password; '
    'UNIFI_PASSWORD (the UniFi OS login) is never sent over SSH'
)
SSH_PASSWORD_SUGGESTION = (
    'Enable SSH in UniFi OS (Settings > Control Plane > Console) and set UNIFI_SSH_PASSWORD '
    'to the SSH password set there; set UNIFI_SSH_USERNAME as well if the SSH user is not root'
)


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
        message=f'{label} must be a whole number from {low} to {high}, not {value!r}',
        error_code=ErrorCodes.CONFIG_INVALID,
    )
