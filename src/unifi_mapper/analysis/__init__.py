"""Network analysis tools for UniFi MCP server.

P1 Priority Tools (High):
- detect_ip_conflicts: Find IP address conflicts between devices
- detect_storms: Detect broadcast/multicast storms
- diagnose_vlans: Comprehensive VLAN diagnostics

P2 Priority Tools (Medium):
- analyze_link_quality: Port health and error analysis
- get_capacity_report: Network capacity planning
- monitor_lags: LAG health monitoring
- validate_qos: QoS configuration validation

P3 Priority Tools (Lower):
- analyze_mac_table: MAC address table analysis and flapping detection
- get_firmware_report: Firmware security assessment and update recommendations

STP Optimization Tools:
- discover_stp_topology: Discover current STP topology from all switches
- calculate_optimal_priorities: Calculate optimal bridge priorities based on hierarchy
- generate_stp_report: Generate comprehensive STP optimization report
- apply_stp_changes: Apply priority changes via API (supports dry-run mode)
- format_stp_report_markdown: Format STP report as markdown with mermaid diagrams
- validate_10g_expansion_readiness: Validate STP, link speed, and errors before 10G expansion
"""

from unifi_mapper.analysis.capacity_planning import get_capacity_report
from unifi_mapper.analysis.firmware_advisor import get_firmware_report
from unifi_mapper.analysis.ip_conflicts import detect_ip_conflicts
from unifi_mapper.analysis.lag_monitoring import find_lag_candidates, monitor_lags
from unifi_mapper.analysis.link_quality import analyze_link_quality
from unifi_mapper.analysis.mac_analyzer import analyze_mac_table
from unifi_mapper.analysis.mtu_audit import audit_mtu_consistency
from unifi_mapper.analysis.port_counter_baseline import (
    PortCounterBaselineStore,
    PortCounterSnapshot,
    default_baseline_path,
    diff_snapshots,
    port_counter_key,
    snapshot_from_port,
    snapshots_from_switches,
)
from unifi_mapper.analysis.port_profile_validation import (
    PortProfileFinding,
    PortProfileValidationReport,
    validate_port_profiles,
    validate_port_profiles_from_data,
)
from unifi_mapper.analysis.qos_validation import validate_qos
from unifi_mapper.analysis.radio_optimization import analyze_radio_optimization
from unifi_mapper.analysis.sfp_diagnostics import audit_sfp_diagnostics
from unifi_mapper.analysis.storm_detection import detect_storms
from unifi_mapper.analysis.stp_drift import detect_stp_config_drift, load_stp_intent
from unifi_mapper.analysis.stp_guard import audit_stp_guard_recommendations
from unifi_mapper.analysis.stp_optimizer import (
    apply_stp_changes,
    build_10g_expansion_validation_report,
    audit_stp_path_costs,
    calculate_optimal_priorities,
    discover_stp_topology,
    expected_long_path_cost,
    format_10g_validation_report_markdown,
    format_stp_report_markdown,
    generate_stp_report,
    validate_10g_expansion_readiness,
)
from unifi_mapper.analysis.stp_change_plan import create_stp_change_plan
from unifi_mapper.analysis.stp_preflight import stp_preflight_simulate_add
from unifi_mapper.analysis.stp_snapshot import diff_stp_snapshots, snapshot_stp_topology
from unifi_mapper.analysis.traffic_matrix import (
    TrafficEndpoint,
    TrafficFlow,
    TrafficMatrixRecommendation,
    TrafficMatrixReport,
    TrafficTalker,
    analyze_traffic_matrix,
    analyze_traffic_matrix_from_payloads,
)
from unifi_mapper.analysis.vlan_diagnostics import diagnose_vlans
from unifi_mapper.analysis.vlan_coverage import (
    VLANCoverageFinding,
    VLANCoverageReport,
    audit_vlan_coverage,
    audit_vlan_coverage_from_data,
)


__all__ = [
    # P1 tools
    'detect_ip_conflicts',
    'detect_storms',
    'diagnose_vlans',
    'VLANCoverageFinding',
    'VLANCoverageReport',
    'audit_vlan_coverage',
    'audit_vlan_coverage_from_data',
    # P2 tools
    'analyze_link_quality',
    'analyze_radio_optimization',
    'audit_mtu_consistency',
    'audit_sfp_diagnostics',
    'find_lag_candidates',
    'get_capacity_report',
    'monitor_lags',
    'validate_qos',
    # P3 tools
    'analyze_mac_table',
    'get_firmware_report',
    'PortCounterBaselineStore',
    'PortCounterSnapshot',
    'default_baseline_path',
    'diff_snapshots',
    'port_counter_key',
    'snapshot_from_port',
    'snapshots_from_switches',
    'PortProfileFinding',
    'PortProfileValidationReport',
    'validate_port_profiles',
    'validate_port_profiles_from_data',
    # STP tools
    'apply_stp_changes',
    'build_10g_expansion_validation_report',
    'audit_stp_path_costs',
    'calculate_optimal_priorities',
    'discover_stp_topology',
    'expected_long_path_cost',
    'format_10g_validation_report_markdown',
    'format_stp_report_markdown',
    'generate_stp_report',
    'validate_10g_expansion_readiness',
    'create_stp_change_plan',
    'audit_stp_guard_recommendations',
    'detect_stp_config_drift',
    'diff_stp_snapshots',
    'load_stp_intent',
    'snapshot_stp_topology',
    'stp_preflight_simulate_add',
    # Traffic matrix analysis
    'TrafficEndpoint',
    'TrafficFlow',
    'TrafficMatrixRecommendation',
    'TrafficMatrixReport',
    'TrafficTalker',
    'analyze_traffic_matrix',
    'analyze_traffic_matrix_from_payloads',
]
