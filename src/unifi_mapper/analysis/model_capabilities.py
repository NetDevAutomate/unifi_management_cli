"""Capability classification for UniFi switch and gateway hardware."""

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
    return model.upper().replace('-', '').replace('_', '').replace(' ', '').strip()


_GATEWAY_TOKENS: tuple[str, ...] = (
    'UDM',
    'USG',
    'UGW',
    'UXG',
    'UCG',
)

_AGGREGATION_TOKENS: tuple[str, ...] = (
    'USFXG',
    'USWFLEXXG',
    'FLEXXG',
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
    """Classify a UniFi model string into an STP capability class."""
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
