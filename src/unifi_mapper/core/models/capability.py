"""Capability class enum shared across core models and analysis.

Kept here (rather than in ``analysis/model_capabilities.py``) so that
``core.models.stp`` can reference it without creating a circular
import between ``core`` and ``analysis``.
"""

from __future__ import annotations

from enum import Enum


class SwitchCapabilityClass(str, Enum):
    """Capability class for UniFi devices.

    Ordered roughly by "suitability as STP root" - GATEWAY is a special
    case (UDM acts as gateway, not switch root).
    """

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
    """Return True if a switch of this class may act as STP root."""
    return capability in _ROOT_ELIGIBLE_CLASSES


def is_access_class(capability: SwitchCapabilityClass) -> bool:
    """Return True if a switch of this class should never be STP root."""
    return capability in (
        SwitchCapabilityClass.ACCESS,
        SwitchCapabilityClass.ACCESS_POE,
    )
