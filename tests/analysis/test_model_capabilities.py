"""Tests for UniFi hardware capability classification."""

from __future__ import annotations

import pytest
from unifi_mapper.analysis.model_capabilities import (
    SwitchCapabilityClass,
    classify_model,
    is_access_class,
    is_root_eligible,
)


@pytest.mark.parametrize(
    ('model', 'expected'),
    [
        ('USFXG', SwitchCapabilityClass.AGGREGATION),
        ('USF-XG', SwitchCapabilityClass.AGGREGATION),
        ('USW-EnterpriseXG-24', SwitchCapabilityClass.AGGREGATION),
        ('US24XG', SwitchCapabilityClass.AGGREGATION),
        ('USAGGPRO', SwitchCapabilityClass.AGGREGATION),
        ('USW-Pro-48-PoE', SwitchCapabilityClass.CORE_DISTRIBUTION),
        ('USW-Enterprise-24-PoE', SwitchCapabilityClass.CORE_DISTRIBUTION),
        ('UDM-Pro', SwitchCapabilityClass.GATEWAY),
        ('USG-3P', SwitchCapabilityClass.GATEWAY),
        ('USL16LPB', SwitchCapabilityClass.ACCESS_POE),
        ('US8P60', SwitchCapabilityClass.ACCESS_POE),
        ('USW-Lite-16-PoE', SwitchCapabilityClass.ACCESS),
        ('USW-Flex-Mini', SwitchCapabilityClass.ACCESS),
        ('', SwitchCapabilityClass.UNKNOWN),
        ('MYSTERY-9000', SwitchCapabilityClass.UNKNOWN),
    ],
)
def test_classify_model(model: str, expected: SwitchCapabilityClass) -> None:
    """Classify known UniFi model strings."""
    assert classify_model(model) == expected


def test_root_eligible_classes() -> None:
    """Only aggregation and core/distribution switch classes are root-eligible by default."""
    assert is_root_eligible(SwitchCapabilityClass.AGGREGATION)
    assert is_root_eligible(SwitchCapabilityClass.CORE_DISTRIBUTION)
    assert not is_root_eligible(SwitchCapabilityClass.ACCESS)
    assert not is_root_eligible(SwitchCapabilityClass.ACCESS_POE)
    assert not is_root_eligible(SwitchCapabilityClass.GATEWAY)
    assert not is_root_eligible(SwitchCapabilityClass.UNKNOWN)


def test_access_class_helper() -> None:
    """Access classes are root-guarded."""
    assert is_access_class(SwitchCapabilityClass.ACCESS)
    assert is_access_class(SwitchCapabilityClass.ACCESS_POE)
    assert not is_access_class(SwitchCapabilityClass.AGGREGATION)
    assert not is_access_class(SwitchCapabilityClass.CORE_DISTRIBUTION)
