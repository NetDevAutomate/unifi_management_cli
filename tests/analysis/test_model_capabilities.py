"""Tests for hardware capability classification."""

from __future__ import annotations

import pytest
from unifi_mapper.analysis.model_capabilities import (
    SwitchCapabilityClass,
    classify_model,
    is_access_class,
    is_root_eligible,
)


class TestClassifyModel:
    """Tests for classify_model()."""

    @pytest.mark.parametrize(
        'model,expected',
        [
            # Aggregation
            ('USFXG', SwitchCapabilityClass.AGGREGATION),
            ('USF-XG', SwitchCapabilityClass.AGGREGATION),
            ('USW-EnterpriseXG-24', SwitchCapabilityClass.AGGREGATION),
            ('US24XG', SwitchCapabilityClass.AGGREGATION),
            ('US48XG', SwitchCapabilityClass.AGGREGATION),
            ('USAGGPRO', SwitchCapabilityClass.AGGREGATION),
            # Core/Distribution
            ('USW-Pro-24', SwitchCapabilityClass.CORE_DISTRIBUTION),
            ('USW-Pro-48-PoE', SwitchCapabilityClass.CORE_DISTRIBUTION),
            ('USW-Enterprise-24-PoE', SwitchCapabilityClass.CORE_DISTRIBUTION),
            # Gateway
            ('UDMPROMAX', SwitchCapabilityClass.GATEWAY),
            ('UDM-Pro', SwitchCapabilityClass.GATEWAY),
            ('USG-3P', SwitchCapabilityClass.GATEWAY),
            ('UGW-4', SwitchCapabilityClass.GATEWAY),
            # Access with PoE
            ('USL16LPB', SwitchCapabilityClass.ACCESS_POE),
            ('USL8LP', SwitchCapabilityClass.ACCESS_POE),
            ('US8P60', SwitchCapabilityClass.ACCESS_POE),
            ('USM8P210', SwitchCapabilityClass.ACCESS_POE),
            ('USWED37', SwitchCapabilityClass.ACCESS_POE),
            # Access
            ('USWED35', SwitchCapabilityClass.ACCESS),
            # Unknown
            ('', SwitchCapabilityClass.UNKNOWN),
            ('MYSTERY-9000', SwitchCapabilityClass.UNKNOWN),
        ],
    )
    def test_classify_model(self, model: str, expected: SwitchCapabilityClass) -> None:
        """Classify a model string into the expected capability class."""
        assert classify_model(model) == expected


class TestRootEligibility:
    """Tests for root-eligibility classification helper."""

    def test_aggregation_root_eligible(self) -> None:
        """AGGREGATION class is root-eligible."""
        assert is_root_eligible(SwitchCapabilityClass.AGGREGATION) is True

    def test_core_distribution_root_eligible(self) -> None:
        """CORE_DISTRIBUTION class is root-eligible."""
        assert is_root_eligible(SwitchCapabilityClass.CORE_DISTRIBUTION) is True

    def test_access_not_root_eligible(self) -> None:
        """ACCESS and ACCESS_POE classes are never root-eligible."""
        assert is_root_eligible(SwitchCapabilityClass.ACCESS) is False
        assert is_root_eligible(SwitchCapabilityClass.ACCESS_POE) is False

    def test_gateway_not_root_eligible(self) -> None:
        """GATEWAY class is not a switch root."""
        assert is_root_eligible(SwitchCapabilityClass.GATEWAY) is False

    def test_unknown_not_root_eligible(self) -> None:
        """UNKNOWN class is not root-eligible by default."""
        assert is_root_eligible(SwitchCapabilityClass.UNKNOWN) is False


class TestAccessClass:
    """Tests for access-class helper used by root guard."""

    def test_access_is_access_class(self) -> None:
        """ACCESS and ACCESS_POE are access-class and subject to root guard."""
        assert is_access_class(SwitchCapabilityClass.ACCESS) is True
        assert is_access_class(SwitchCapabilityClass.ACCESS_POE) is True

    def test_aggregation_not_access_class(self) -> None:
        """AGGREGATION is not access-class."""
        assert is_access_class(SwitchCapabilityClass.AGGREGATION) is False

    def test_core_distribution_not_access_class(self) -> None:
        """CORE_DISTRIBUTION is not access-class."""
        assert is_access_class(SwitchCapabilityClass.CORE_DISTRIBUTION) is False
