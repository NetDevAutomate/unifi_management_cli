"""Path analysis tool for detailed network path examination."""

from pydantic import Field
from typing import Annotated, Any
from unifi_mcp.models import NetworkPath
from unifi_mcp.utils.errors import ToolError


async def path_analysis(
    path: Annotated[NetworkPath, Field(description='Network path to analyze in detail')],
) -> dict[str, Any]:
    """Perform detailed analysis of a network path.

    When to use this tool:
    - After traceroute() to get deeper insights into the path
    - Identifying potential performance bottlenecks or issues
    - Understanding path characteristics and quality
    - Diagnosing complex routing or switching issues

    Common workflow:
    1. Run traceroute() to get the basic path
    2. Use path_analysis() on the result for detailed breakdown
    3. Use link_quality() on any hops showing high latency
    4. Use system_load() on devices showing performance issues

    What to do next:
    - For high latency hops: Use link_quality() and system_load()
    - For VLAN crossing issues: Use vlan_info() and firewall_check()
    - For duplex problems: Use get_port_map() to check port settings
    - For routing issues: Use best_practice_check() for configuration review

    Args:
        path: NetworkPath object from traceroute() containing path details

    Returns:
        Dictionary containing:
        - path_summary: High-level path characteristics
        - hop_analysis: Detailed analysis of each hop
        - performance_metrics: Latency, bandwidth, error analysis
        - vlan_analysis: VLAN crossing and routing details
        - bottleneck_identification: Potential performance issues
        - recommendations: Suggestions for optimization

    Raises:
        ToolError: PATH_INCOMPLETE if path data is insufficient for analysis
    """
    if not path.hops:
        raise ToolError(
            message='Cannot analyze empty path',
            error_code='PATH_INCOMPLETE',
            suggestion='Run traceroute() first to generate path data',
            related_tools=['traceroute', 'find_device'],
        )

    # Analyze path characteristics
    path_summary = _analyze_path_summary(path)

    # Analyze each hop in detail
    hop_analysis = _analyze_hops(path.hops)

    # Performance analysis
    performance_metrics = _analyze_performance(path)

    # VLAN analysis
    vlan_analysis = _analyze_vlans(path)

    # Identify potential bottlenecks
    bottlenecks = _identify_bottlenecks(path.hops)

    # Generate recommendations
    recommendations = _generate_path_recommendations(
        path, hop_analysis, performance_metrics, bottlenecks
    )

    return {
        'path_summary': path_summary,
        'hop_analysis': hop_analysis,
        'performance_metrics': performance_metrics,
        'vlan_analysis': vlan_analysis,
        'bottleneck_identification': bottlenecks,
        'recommendations': recommendations,
    }


def _analyze_path_summary(path: NetworkPath) -> dict[str, Any]:
    """Analyze high-level path characteristics."""
    return {
        'total_hops': len(path.hops),
        'path_type': 'L3 routed' if path.is_l3_routed else 'L2 switched',
        'crosses_vlans': path.crosses_vlans,
        'vlan_crossings': path.vlan_crossing_count,
        'firewall_verdict': path.firewall_verdict,
        'is_blocked': path.is_blocked,
        'total_latency_ms': path.total_latency_ms,
        'complexity': 'high'
        if len(path.hops) > 5
        else 'medium'
        if len(path.hops) > 3
        else 'simple',
    }


def _analyze_hops(hops: list) -> list[dict[str, Any]]:
    """Analyze each hop in the path."""
    hop_analysis = []

    for i, hop in enumerate(hops):
        analysis = {
            'hop_number': hop.hop_number,
            'device_name': hop.device_name,
            'device_type': hop.device_type,
            'interface': hop.interface,
            'vlan': hop.vlan,
            'latency_ms': hop.latency_ms,
            'is_bottleneck': False,  # Will be determined by bottleneck analysis
            'issues': [],
        }

        # Check for issues at this hop
        if hop.latency_ms and hop.latency_ms > 50:
            analysis['issues'].append('High latency (>50ms)')

        if hop.firewall_result == 'deny':
            analysis['issues'].append(f'Blocked by firewall rule: {hop.blocking_rule}')

        # Check for VLAN transitions
        if i > 0:
            prev_hop = hops[i - 1]
            if prev_hop.vlan != hop.vlan:
                analysis['vlan_transition'] = {
                    'from': prev_hop.vlan,
                    'to': hop.vlan,
                    'type': 'inter_vlan_routing',
                }

        hop_analysis.append(analysis)

    return hop_analysis


def _analyze_performance(path: NetworkPath) -> dict[str, Any]:
    """Analyze path performance metrics."""
    latencies = [hop.latency_ms for hop in path.hops if hop.latency_ms is not None]

    if not latencies:
        return {
            'total_latency_ms': None,
            'average_latency_ms': None,
            'max_latency_ms': None,
            'latency_distribution': None,
            'performance_rating': 'unknown',
        }

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)

    # Performance rating based on total latency
    if path.total_latency_ms:
        if path.total_latency_ms < 5:
            rating = 'excellent'
        elif path.total_latency_ms < 20:
            rating = 'good'
        elif path.total_latency_ms < 50:
            rating = 'fair'
        else:
            rating = 'poor'
    else:
        rating = 'unknown'

    return {
        'total_latency_ms': path.total_latency_ms,
        'average_latency_ms': round(avg_latency, 2),
        'max_latency_ms': max_latency,
        'latency_distribution': latencies,
        'performance_rating': rating,
        'hops_with_latency': len(latencies),
    }


def _analyze_vlans(path: NetworkPath) -> dict[str, Any]:
    """Analyze VLAN aspects of the path."""
    return {
        'crosses_vlans': path.crosses_vlans,
        'vlans_traversed': path.vlans_traversed,
        'vlan_crossings': path.vlan_crossing_count,
        'requires_routing': path.is_l3_routed,
        'routing_complexity': (
            'complex'
            if path.vlan_crossing_count > 2
            else 'simple'
            if path.vlan_crossing_count <= 1
            else 'medium'
        ),
    }


def _identify_bottlenecks(hops: list) -> list[dict[str, str]]:
    """Identify potential bottlenecks in the path."""
    bottlenecks = []

    if not hops:
        return bottlenecks

    # Find hops with significantly higher latency
    latencies = [hop.latency_ms for hop in hops if hop.latency_ms is not None]
    if len(latencies) > 1:
        avg_latency = sum(latencies) / len(latencies)

        for hop in hops:
            if hop.latency_ms and hop.latency_ms > avg_latency * 2:
                bottlenecks.append(
                    {
                        'hop': f'{hop.device_name}:{hop.interface}',
                        'issue': 'high_latency',
                        'value': f'{hop.latency_ms}ms (avg: {avg_latency:.1f}ms)',
                        'recommendation': 'Check device load and interface errors',
                    }
                )

    # Check for firewall blocks
    for hop in hops:
        if hop.firewall_result == 'deny':
            bottlenecks.append(
                {
                    'hop': f'{hop.device_name}:{hop.interface}',
                    'issue': 'firewall_block',
                    'value': f'Blocked by: {hop.blocking_rule}',
                    'recommendation': 'Review firewall rule configuration',
                }
            )

    return bottlenecks


def _generate_path_recommendations(
    path: NetworkPath,
    hop_analysis: list[dict[str, Any]],
    performance_metrics: dict[str, Any],
    bottlenecks: list[dict[str, str]],
) -> list[str]:
    """Generate recommendations for path optimization."""
    recommendations = []

    # Performance recommendations
    if performance_metrics.get('performance_rating') == 'poor':
        recommendations.append(
            'Path shows poor performance. Use system_load() to check device health '
            'and link_quality() to check for interface errors.'
        )

    # VLAN recommendations
    if path.crosses_vlans and path.vlan_crossing_count > 2:
        recommendations.append(
            'Path crosses multiple VLANs, increasing complexity. '
            'Consider network redesign to reduce VLAN traversals.'
        )

    # Firewall recommendations
    if path.firewall_verdict == 'deny':
        recommendations.append(
            'Path is blocked by firewall rules. Use firewall_check() '
            'for detailed rule analysis and recommendations.'
        )

    # Bottleneck recommendations
    if bottlenecks:
        recommendations.append(
            f'{len(bottlenecks)} potential bottlenecks identified. '
            'Check system_load() and link_quality() on affected devices.'
        )

    # Complexity recommendations
    if len(path.hops) > 6:
        recommendations.append(
            'Path has many hops, potentially indicating network design issues. '
            'Use get_device_tree() to review network topology.'
        )

    # Default recommendation if path looks good
    if not recommendations:
        recommendations.append(
            'Path analysis looks normal. If experiencing issues, '
            'use link_quality() and system_load() for deeper diagnostics.'
        )

    return recommendations
