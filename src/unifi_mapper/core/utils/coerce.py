"""Numeric coercion for controller fields whose JSON type varies by model and firmware.

The controller sends the same field as a number on one device and a string on
another (``system-stats.cpu`` is ``"7.1"`` on a USW Flex XG, for example), and
some fields are simply absent. Compare such a field only after passing it
through one of these helpers.

Import-cycle rule: this module imports only the standard library and
``typing``, so any module (including ``diagnostic_reads`` and the diagnostics
tools) can import it.
"""

from typing import Any, Optional


def int_or_none(value: Any) -> Optional[int]:
    """Return ``value`` as an int, or None when it is absent or not numeric.

    Args:
        value: Any controller value. Bools are rejected, because ``True`` is not a count.

    Returns:
        The truncated int, or None.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> Optional[float]:
    """Return ``value`` as a float, or None when it is absent or not numeric.

    Args:
        value: Any controller value. Bools are rejected, because ``True`` is not a reading.

    Returns:
        The float, or None.
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
