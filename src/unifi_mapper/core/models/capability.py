"""Capability class enum shared across core models and analysis."""

from __future__ import annotations

from enum import Enum


class SwitchCapabilityClass(str, Enum):
    """UniFi hardware capability class for STP root selection."""

    GATEWAY = 'gateway'
    AGGREGATION = 'aggregation'
    CORE_DISTRIBUTION = 'core_distribution'
    ACCESS_POE = 'access_poe'
    ACCESS = 'access'
    UNKNOWN = 'unknown'


_ROOT_ELIGIBLE_CLASSES: frozenset[SwitchCapabilityClass] = frozenset(
    {SwitchCapabilityClass.AGGREGATION, SwitchCapabilityClass.CORE_DISTRIBUTION}
)


def is_root_eligible(capability: SwitchCapabilityClass) -> bool:
    """Return True if this hardware class may act as STP root."""
    return capability in _ROOT_ELIGIBLE_CLASSES


def is_access_class(capability: SwitchCapabilityClass) -> bool:
    """Return True if this hardware class should never be preferred as STP root."""
    return capability in (
        SwitchCapabilityClass.ACCESS,
        SwitchCapabilityClass.ACCESS_POE,
    )
