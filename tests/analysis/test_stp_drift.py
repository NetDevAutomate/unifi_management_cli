"""Tests for STP intent drift detection."""

from __future__ import annotations

from unifi_mapper.analysis.stp_drift import detect_stp_config_drift
from unifi_mapper.core.models.stp import STPTopology, SwitchSTPConfig


def test_stp_drift_reports_priority_mismatch() -> None:
    """Priority drift should be reported for a matching switch."""
    topology = STPTopology(
        switches=[
            SwitchSTPConfig(
                device_id='core-1',
                name='Core Switch',
                mac='aa:bb:cc:dd:ee:ff',
                current_priority=32768,
            )
        ]
    )

    report = detect_stp_config_drift(
        topology,
        {'Core Switch': {'priority': 4096}},
    )

    assert report.drift_detected is True
    assert report.findings_count == 1
    finding = report.findings[0]
    assert finding.finding_type == 'priority_mismatch'
    assert finding.device_name == 'Core Switch'
    assert finding.expected == 4096
    assert finding.actual == 32768


def test_stp_drift_reports_missing_device() -> None:
    """Intent entries that match no live switch should be reported."""
    topology = STPTopology(switches=[])

    report = detect_stp_config_drift(
        topology,
        {'missing-switch-id': {'priority': 8192}},
    )

    assert report.drift_detected is True
    assert report.findings_count == 1
    finding = report.findings[0]
    assert finding.finding_type == 'missing_device'
    assert finding.identifier == 'missing-switch-id'
    assert finding.expected == {'priority': 8192}
    assert finding.actual is None


def test_stp_drift_reports_expected_root_mismatch() -> None:
    """Root expectation drift should compare against the live root bridge."""
    topology = STPTopology(
        root_bridge_id='core-1',
        root_bridge_name='Core Switch',
        switches=[
            SwitchSTPConfig(
                device_id='core-1',
                name='Core Switch',
                mac='aa:bb:cc:dd:ee:ff',
                current_priority=4096,
                is_root_bridge=True,
            ),
            SwitchSTPConfig(
                device_id='dist-1',
                name='Distribution Switch',
                mac='11:22:33:44:55:66',
                current_priority=8192,
                is_root_bridge=False,
            ),
        ],
    )

    report = detect_stp_config_drift(
        topology,
        {'Distribution Switch': {'priority': 8192, 'root_expected': True}},
    )

    assert report.drift_detected is True
    assert report.findings_count == 1
    finding = report.findings[0]
    assert finding.finding_type == 'root_expected_mismatch'
    assert finding.device_name == 'Distribution Switch'
    assert finding.expected is True
    assert finding.actual is False
