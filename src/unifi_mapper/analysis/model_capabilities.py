"""Capability classification for UniFi switch / gateway hardware.

Used by the STP optimizer to decide which switches may act as the STP
root bridge. Topology-only classification (is the device gateway-
connected?) is insufficient: a small 1G access switch may be cabled to
the gateway without being architecturally suitable as root.

Classification rules (model substring, case-insensitive):

* ``GATEWAY``        - UDM / USG / UGW appliances (never a switch root).
* ``AGGREGATION``    - 10G+ aggregation switches (USFXG, USXG, USAGGPRO,
                       US24XG, US48XG, US-XG-*).  Root-eligible.
* ``CORE_DISTRIBUTION`` - Enterprise 1G+ distribution switches
                       (USW-Pro-*, USW-Enterprise-*).  Root-eligible.
* ``ACCESS_POE``     - Access switches with PoE budget (USW-Lite-*-PoE,
                       USW-Flex-*-PoE, US-*-60W, US-8-*, USM-*).
* ``ACCESS``         - Access switches without PoE (USW-Flex-*,
                       USW-Lite-*, basic USC-*).
* ``UNKNOWN``        - Not recognised; treated as non-root-eligible by
                       default.

The optimizer applies a root-guard policy: an ``ACCESS`` or
``ACCESS_POE`` class switch will never be assigned STP priority below
:data:`unifi_mapper.core.models.stp.STP_PRIORITY_DISTRIBUTION` (8192),
even if it is gateway-adjacent or listed in ``root_eligible_macs``
override.  Only ``AGGREGATION`` and ``CORE_DISTRIBUTION`` are allowed
at the core tier.
"""

from __future__ import annotations

from unifi_mapper.core.models.capability import (
    SwitchCapabilityClass,
    is_access_class,
    is_root_eligible,
)


__all__ = [
    'SwitchCapabilityClass',
    'classify_model',
    'is_access_class',
    'is_root_eligible',
]


def _normalise(model: str) -> str:
    return model.upper().replace('-', '').replace('_', '').strip()


_AGGREGATION_TOKENS: tuple[str, ...] = (
    'USFXG',
    'USXG',
    'USAGGPRO',
    'USAGG',
    'US24XG',
    'US48XG',
    'USWXG',
    'USWPROXG',
    'USWENTERPRISEXG',
    'USWEA',
)

_CORE_DISTRIBUTION_TOKENS: tuple[str, ...] = (
    'USWPRO',
    'USWENTERPRISE',
    'USPROHD',
    'US24PRO',
    'US48PRO',
)

_GATEWAY_TOKENS: tuple[str, ...] = (
    'UDM',
    'USG',
    'UGW',
    'UXG',
    'UCG',
)

_ACCESS_POE_TOKENS: tuple[str, ...] = (
    'USL8LP',
    'USL16LPB',
    'USL16LP',
    'USL24LP',
    'USWED37',
    'USWED35P',
    'US8P60',
    'US8P150',
    'US16P150',
    'US24P250',
    'US24P500',
    'US48P500',
    'US48P750',
    'USM8P210',
    'USMPRO',
    'USWULTRA',
)

_ACCESS_TOKENS: tuple[str, ...] = (
    'USWED35',
    'USC8',
    'USC5',
    'USS5',
    'USWLITE8',
    'USWLITE16',
    'USWFLEX',
    'USFLEX',
    'USWFLEXMINI',
    'USWFLEXUTILITY',
)


def classify_model(model: str) -> SwitchCapabilityClass:
    """Return the capability class for a UniFi device model string.

    Matching is substring-based against an upper-cased, hyphen/underscore-
    stripped form of ``model``.  The order of checks matters: gateway
    first, then aggregation (most specific hardware), then
    core-distribution, then access-PoE, then access.
    """
    if not model:
        return SwitchCapabilityClass.UNKNOWN

    key = _normalise(model)

    for token in _GATEWAY_TOKENS:
        if token in key:
            return SwitchCapabilityClass.GATEWAY

    for token in _AGGREGATION_TOKENS:
        if token in key:
            return SwitchCapabilityClass.AGGREGATION

    for token in _CORE_DISTRIBUTION_TOKENS:
        if token in key:
            return SwitchCapabilityClass.CORE_DISTRIBUTION

    for token in _ACCESS_POE_TOKENS:
        if token in key:
            return SwitchCapabilityClass.ACCESS_POE

    for token in _ACCESS_TOKENS:
        if token in key:
            return SwitchCapabilityClass.ACCESS

    return SwitchCapabilityClass.UNKNOWN
