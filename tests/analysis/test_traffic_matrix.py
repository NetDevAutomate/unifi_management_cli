"""Tests for traffic matrix analysis."""

from __future__ import annotations

from unifi_mapper.analysis.traffic_matrix import (
    analyze_traffic_matrix,
    analyze_traffic_matrix_from_payloads,
)


def test_aggregates_bidirectional_flows_by_endpoint_pair() -> None:
    """Bidirectional records for the same endpoints become one pair flow."""
    payloads = [
        {
            'data': [
                {
                    'src_ip': '192.0.2.10',
                    'dst_ip': '192.0.2.20',
                    'bytes': 600,
                },
                {
                    'source_ip': '192.0.2.20',
                    'destination_ip': '192.0.2.10',
                    'total_bytes': 400,
                },
            ]
        }
    ]

    report = analyze_traffic_matrix_from_payloads(payloads)

    assert report.records_analyzed == 2
    assert report.flow_count == 1
    assert report.total_bytes == 1000
    assert report.top_flows[0].total_bytes == 1000
    assert {report.top_flows[0].endpoint_a.identifier, report.top_flows[0].endpoint_b.identifier} == {
        '192.0.2.10',
        '192.0.2.20',
    }


def test_extracts_nested_endpoint_shapes_and_tx_rx_byte_fields() -> None:
    """Nested endpoint objects and split byte counters are supported."""
    payloads = [
        [
            {
                'source': {
                    'ip': '10.0.0.5',
                    'mac': 'aa:bb:cc:dd:ee:ff',
                    'hostname': 'nas',
                },
                'destination': {'ip_address': '10.0.0.50', 'name': 'workstation'},
                'tx_bytes': '1500',
                'rx_bytes': 500,
            }
        ]
    ]

    report = analyze_traffic_matrix_from_payloads(payloads)

    assert report.records_analyzed == 1
    assert report.top_flows[0].total_bytes == 2000
    assert report.top_talkers[0].total_bytes == 2000
    assert report.top_talkers[0].endpoint.name in {'nas', 'workstation'}


def test_ignores_records_without_two_endpoints_or_traffic_metrics() -> None:
    """Partial records are ignored instead of producing ambiguous flows."""
    payloads = [
        {'src_ip': '192.0.2.10', 'bytes': 100},
        {'src_ip': '192.0.2.10', 'dst_ip': '192.0.2.20'},
        {'dst_ip': '192.0.2.20', 'bytes': 100},
    ]

    report = analyze_traffic_matrix_from_payloads(payloads)

    assert report.records_analyzed == 0
    assert report.flow_count == 0
    assert report.top_flows == []
    assert report.top_talkers == []


def test_recommends_10g_placement_for_high_bandwidth_pairs() -> None:
    """High byte or rate observations produce 10G placement recommendations."""
    payloads = [
        {
            'src_mac': 'aa:aa:aa:aa:aa:aa',
            'dst_mac': 'bb:bb:bb:bb:bb:bb',
            'byte_count': 5_000,
            'rate_bps': 2_500_000_000,
        }
    ]

    report = analyze_traffic_matrix_from_payloads(
        payloads,
        high_bandwidth_threshold_bytes=10_000,
        high_bandwidth_threshold_bps=1_000_000_000,
    )

    assert len(report.recommendations) == 1
    recommendation = report.recommendations[0]
    assert recommendation.observed_bytes == 5_000
    assert recommendation.observed_bps == 2_500_000_000
    assert '10G-capable' in recommendation.recommendation


async def test_async_wrapper_analyzes_supplied_payloads_without_controller() -> None:
    """Supplying payloads to the async wrapper avoids controller collection."""
    report = await analyze_traffic_matrix(
        [
            {
                'src': '10.1.1.10',
                'dst': '10.1.1.11',
                'usage_bytes': 1234,
            }
        ]
    )

    assert report.records_analyzed == 1
    assert report.top_flows[0].total_bytes == 1234
