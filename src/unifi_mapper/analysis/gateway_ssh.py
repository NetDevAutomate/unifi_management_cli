"""Checks for values that go on a command line run on the gateway over SSH.

``diagnose latency-matrix`` and ``diagnose bandwidth`` run ``ping`` and ``iperf3`` on the
gateway, normally as root, with addresses the controller reports or the user types. Every
value is checked here before it is interpolated, and the command line is shell-quoted as
well (``shlex.join``), so no value can add a shell command of its own.
"""

import ipaddress
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError


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
