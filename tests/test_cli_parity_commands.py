"""CLI commands for the MCP tools that had none (issue 078, the MCP-only side).

Each command runs its tool through ``_run_analysis`` (guarded, read-only), prints JSON equal
to the tool's ``model_dump`` with ``--json`` and a Rich rendering otherwise, and forwards its
options to the handler by keyword. The handlers are faked in their modules; no controller.
"""

from __future__ import annotations

import importlib
import json
import pytest
from datetime import datetime
from typer.testing import CliRunner
from types import SimpleNamespace
from typing import Any
from unifi_mapper import typer_cli
from unifi_mapper.core.models import (
    CapacityReport,
    ConflictingClient,
    IPConflict,
    IPConflictReport,
    LAGHealthReport,
    MACAnalysisReport,
    QoSValidationReport,
    StormDetectionReport,
    VLANDiagnosticReport,
)
from unifi_mapper.core.models.network_path import NetworkPath
from unifi_mapper.core.utils.errors import ErrorCodes, ToolError
from unifi_mapper.diagnostics.security_audit import SecurityAuditReport, SecurityDevice
from unifi_mapper.mcp.parity import cli_commands
from unifi_mapper.mcp.registry import ToolRegistry, default_manifests_dir
from unifi_mapper.typer_cli import app


device_freshness = importlib.import_module('unifi_mapper.analysis.device_freshness')
foreign_bridges = importlib.import_module('unifi_mapper.analysis.foreign_bridges')


pytestmark = pytest.mark.usefixtures('block_network')
runner = CliRunner()
REGISTRY = ToolRegistry(default_manifests_dir(), strict=True)

IP_CONFLICTS = IPConflictReport(
    timestamp='2026-10-13T10:00:00',
    total_clients_scanned=42,
    conflicts_found=1,
    conflicts=[
        IPConflict(
            ip_address='192.0.2.50',
            clients=[
                ConflictingClient(
                    mac_address='02:00:00:00:00:50',
                    hostname='printer',
                    name='Printer',
                    is_wired=True,
                    is_guest=False,
                    connected_device='Rack Switch',
                    connected_port='7',
                    last_seen=datetime(2026, 10, 13, 9, 59),
                    vlan=10,
                ),
                ConflictingClient(
                    mac_address='02:00:00:00:00:51',
                    hostname='laptop',
                    name=None,
                    is_wired=False,
                    is_guest=False,
                    connected_device='Hall AP',
                    connected_port=None,
                    last_seen=None,
                    vlan=20,
                ),
            ],
            conflict_count=2,
            severity='CRITICAL',
            vlan_mismatch=True,
        )
    ],
    healthy=False,
    recommendations=['Reserve 192.0.2.50 for one client'],
)
SECURITY = SecurityAuditReport(
    timestamp='2026-10-13T10:00:00',
    total_devices=42,
    authorized_devices=40,
    unauthorized_devices=1,
    anomalous_devices=1,
    unknown_devices=0,
    critical_risks=[
        SecurityDevice(
            mac='02:00:00:00:00:99',
            name='mystery-box',
            ip='192.0.2.99',
            type='client',
            vendor=None,
            first_seen=None,
            last_seen=None,
            is_authorized=False,
            is_anomalous=True,
            security_flags=['unknown vendor', 'new device'],
            risk_level='critical',
        )
    ],
    high_risks=[],
    medium_risks=[],
    mac_anomalies=['02:00:00:00:00:99 seen on two switches'],
    new_devices=[],
    rogue_aps=[],
    guest_violations=[],
    vlan_analysis=[],
    immediate_actions=['Isolate mystery-box'],
    security_recommendations=['Enable 802.1X on access ports'],
)

STORMS = StormDetectionReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'devices_analyzed': 2,
        'ports_analyzed': 48,
        'storms_detected': 1,
        'active_storms': [
            {
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'port_idx': 7,
                'storm_type': 'broadcast',
                'severity': 'critical',
                'broadcast_percent': 61.5,
                'multicast_percent': 2.0,
                'affected_ports': [7],
                'is_active': True,
                'recommendation': 'Enable storm control on port 7',
            }
        ],
        'high_risk_ports': [
            {
                'port_idx': 9,
                'port_name': 'Port 9',
                'rx_packets': 1000,
                'broadcast_percent': 22.0,
                'multicast_percent': 1.0,
            }
        ],
        'network_healthy': False,
        'thresholds': {'broadcast_percent': 20.0},
    }
)
MAC_TABLE = MACAnalysisReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'devices_analyzed': 2,
        'total_mac_entries': 90,
        'unique_mac_addresses': 88,
        'static_mac_count': 3,
        'flapping_events': [
            {
                'mac_address': '02:00:00:00:00:77',
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'ports_involved': [3, 4],
                'flap_count': 6,
                'window_seconds': 300,
                'first_seen': '2026-10-13T09:50:00',
                'last_seen': '2026-10-13T09:55:00',
                'severity': 'high',
                'recommendation': 'Check for a loop between ports 3 and 4',
            }
        ],
        'alerts': [
            {
                'alert_type': 'excessive_macs',
                'severity': 'warning',
                'message': 'Port 12 learns 41 MACs',
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'port_idx': 12,
                'recommendation': 'Mark port 12 as a trunk or limit MAC learning',
            }
        ],
        'port_mac_counts': [
            {
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'port_idx': 12,
                'port_name': 'Port 12',
                'mac_count': 41,
                'is_trunk': False,
                'exceeds_threshold': True,
            }
        ],
        'ports_exceeding_threshold': 1,
        'critical_alerts': 0,
        'warning_alerts': 1,
        'network_healthy': False,
        'recommendations': ['Review the flapping MAC'],
    }
)
QOS = QoSValidationReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'devices_analyzed': 2,
        'ports_analyzed': 48,
        'findings': [
            {
                'severity': 'error',
                'category': 'dscp',
                'message': 'DSCP trust disabled on the voice port',
                'device_name': 'Rack Switch',
                'port_idx': 5,
                'current_value': 'off',
                'expected_value': 'on',
                'recommendation': 'Enable DSCP trust on port 5',
            }
        ],
        'critical_count': 0,
        'error_count': 1,
        'warning_count': 0,
        'info_count': 0,
        'port_configs': [
            {
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'port_idx': 5,
                'port_name': 'Phone',
                'dscp_trust': False,
                'voice_vlan': 40,
            }
        ],
        'voice_vlan_configured': True,
        'dscp_trust_enabled_count': 0,
        'overall_health': 'DEGRADED',
        'recommendations': ['Trust DSCP on voice ports'],
    }
)
CAPACITY = CapacityReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'total_devices': 2,
        'total_ports': 48,
        'used_ports': 40,
        'available_ports': 8,
        'overall_utilization': 83.3,
        'total_poe_budget': 400.0,
        'total_poe_used': 310.0,
        'devices': [
            {
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'model': 'USW-Pro-24-PoE',
                'total_ports': 24,
                'used_ports': 23,
                'available_ports': 1,
                'utilization_percent': 95.8,
                'poe_budget_watts': 400.0,
                'poe_used_watts': 310.0,
                'poe_available_watts': 90.0,
                'poe_utilization_percent': 77.5,
                'uplink_capacity_gbps': 10.0,
                'recommendation': 'Plan a second switch',
            }
        ],
        'bottlenecks': ['Rack Switch: 1 port left'],
        'expansion_needed': True,
        'recommendations': ['Add a switch before the next device'],
    }
)
LAGS = LAGHealthReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'devices_analyzed': 2,
        'total_lags': 1,
        'healthy_lags': 0,
        'degraded_lags': 1,
        'critical_lags': 0,
        'lag_groups': [
            {
                'lag_id': 'lag-1',
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'lag_name': 'Uplink LAG',
                'members': [
                    {
                        'port_idx': 25,
                        'port_name': 'SFP+ 1',
                        'is_active': True,
                        'link_up': True,
                        'speed_mbps': 10000,
                        'lacp_state': 'distributing',
                    },
                    {
                        'port_idx': 26,
                        'port_name': 'SFP+ 2',
                        'is_active': False,
                        'link_up': False,
                        'speed_mbps': 0,
                        'lacp_state': 'defaulted',
                    },
                ],
                'expected_members': 2,
                'active_members': 1,
                'total_bandwidth_mbps': 20000,
                'active_bandwidth_mbps': 10000,
                'partner_device_name': 'Desk Switch',
                'status': 'degraded',
                'efficiency_percent': 50.0,
                'issues': ['SFP+ 2 down'],
            }
        ],
        'total_lag_bandwidth_gbps': 20.0,
        'active_lag_bandwidth_gbps': 10.0,
        'issues': [
            {
                'severity': 'warning',
                'message': 'Uplink LAG runs on one member',
                'lag_id': 'lag-1',
                'device_name': 'Rack Switch',
            }
        ],
        'recommendations': ['Check the SFP+ 2 cable'],
        'network_healthy': False,
    }
)
VLANS = VLANDiagnosticReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'vlans_configured': 2,
        'vlans': [
            {
                'vlan_id': 1,
                'name': 'Default',
                'subnet': '192.0.2.0/24',
                'gateway': '192.0.2.1',
                'enabled': True,
                'dhcp_enabled': True,
                'client_count': 30,
            },
            {
                'vlan_id': 40,
                'name': 'Voice',
                'subnet': '198.51.100.0/24',
                'gateway': '198.51.100.1',
                'enabled': True,
                'dhcp_enabled': False,
                'client_count': 4,
            },
        ],
        'port_configs': [
            {
                'device_id': 'sw-1',
                'device_name': 'Rack Switch',
                'port_idx': 25,
                'port_name': 'Uplink',
                'native_vlan': 1,
                'tagged_vlans': [40],
                'profile_name': 'All',
                'is_trunk': True,
            }
        ],
        'diagnostic_checks': [
            {
                'check_name': 'DHCP on Voice',
                'status': 'WARNING',
                'message': 'VLAN 40 has no DHCP',
                'recommendations': ['Enable DHCP or use static addressing'],
            }
        ],
        'issues_found': 0,
        'warnings_found': 1,
        'overall_health': 'DEGRADED',
    }
)
FRESHNESS_SUMMARY = device_freshness.FreshnessSummary.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'devices': [
            {
                'device': 'Rack Switch',
                'mac': '02:00:00:00:00:10',
                'state': 1,
                'data_age_seconds': 12.0,
                'trustworthy': True,
                'reason': 'fresh',
            },
            {
                'device': 'Garage Switch',
                'mac': '02:00:00:00:00:12',
                'state': 1,
                'data_age_seconds': 900.0,
                'trustworthy': False,
                'reason': 'last_seen is 15 minutes old',
            },
        ],
        'not_informing': ['Garage Switch'],
        'stale_data': ['Garage Switch'],
        'validation_passed': False,
    }
)
FRESHNESS_REPORT = device_freshness.FreshnessReport.model_validate(
    {
        'timestamp': '2026-10-13T10:05:00',
        'devices_compared': 2,
        'fresh_count': 1,
        'stale_count': 1,
        'no_peer_advanced': False,
        'disappeared': [],
        'rebooted': [],
        'findings_count': 1,
        'validation_passed': False,
        'findings': [
            {
                'severity': 'WARNING',
                'device': 'Garage Switch',
                'mac': '02:00:00:00:00:12',
                'last_seen_delta': 0,
                'uptime_delta': 0,
                'rx_bytes_delta': 0,
                'peers_advancing': True,
                'message': 'counters did not move',
                'recommendation': 'Check the uplink',
            }
        ],
        'message': '1 of 2 devices stale',
    }
)
FOREIGN = foreign_bridges.ForeignBridgeReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'clients_analyzed': 60,
        'adopted_devices': 5,
        'bridges_found': 1,
        'bridges': [
            {
                'mac': '02:00:00:00:00:88',
                'oui': 'Netgear',
                'ip': '192.0.2.88',
                'hostname': 'gs108',
                'downstream_clients': 4,
                'attached_to': [['Rack Switch', 3]],
                'trunk_ports': [],
                'behind_another_bridge': False,
            }
        ],
        'findings_count': 1,
        'validation_passed': False,
        'findings': [
            {
                'severity': 'WARNING',
                'bridge_mac': '02:00:00:00:00:88',
                'loop_risk': False,
                'message': 'Unmanaged switch with 4 clients behind it',
                'recommendation': 'Replace with a managed switch or mark the port',
            }
        ],
    }
)

PATH = NetworkPath.model_validate(
    {
        'source': 'laptop',
        'source_resolved': '192.0.2.50',
        'source_name': 'Laptop',
        'destination': 'nas',
        'destination_resolved': '198.51.100.20',
        'destination_name': 'NAS',
        'hops': [
            {'hop_number': 1, 'device_mac': '02:00:00:00:00:20', 'device_name': 'Hall AP', 'device_type': 'ap', 'interface': 'wifi0', 'vlan': 20, 'latency_ms': 2.5},
            {'hop_number': 2, 'device_mac': '02:00:00:00:00:01', 'device_name': 'Gateway', 'device_type': 'gateway', 'interface': 'br20', 'vlan': 20, 'firewall_checked': True, 'firewall_result': 'deny', 'blocking_rule': 'Block IoT to LAN'},
            {'hop_number': 3, 'device_mac': '02:00:00:00:00:10', 'device_name': 'Rack Switch', 'device_type': 'switch', 'interface': 'port 7', 'vlan': 10, 'latency_ms': 0.4},
        ],
        'total_latency_ms': 2.9,
        'firewall_verdict': 'deny',
        'blocking_rules': [
            {'id': 'r1', 'name': 'Block IoT to LAN', 'action': 'deny', 'source': '198.51.100.0/24', 'destination': '192.0.2.0/24', 'protocol': 'all', 'order': 2000, 'rule_set': 'LAN_IN'}
        ],
        'crosses_vlans': True,
        'vlans_traversed': [20, 10],
        'is_l2_only': False,
        'is_l3_routed': True,
    }
)  # fmt: skip
PATH_ANALYSIS: dict[str, Any] = {
    'path_summary': {'total_hops': 3, 'path_type': 'L3 routed', 'crosses_vlans': True, 'firewall_verdict': 'deny', 'is_blocked': True, 'total_latency_ms': 2.9, 'complexity': 'medium'},
    'hop_analysis': [{'hop_number': 2, 'device_name': 'Gateway', 'device_type': 'gateway', 'interface': 'br20', 'vlan': 20, 'latency_ms': None, 'is_bottleneck': True, 'issues': ['firewall deny']}],
    'performance_metrics': {'total_latency_ms': 2.9, 'average_latency_ms': 1.45, 'max_latency_ms': 2.5, 'performance_rating': 'good'},
    'vlan_analysis': {'crossings': 1},
    'bottleneck_identification': ['Gateway: firewall deny'],
    'recommendations': ['Allow the NAS from the IoT VLAN or move the laptop'],
}  # fmt: skip
FIREWALL: dict[str, Any] = {
    'verdict': 'deny',
    'source_resolved': {'type': 'vlan', 'vlan_id': 20, 'vlan_name': 'IoT', 'network': '198.51.100.0/24'},
    'destination_resolved': {'type': 'ip', 'address': '192.0.2.20', 'network': '192.0.2.20/32'},
    'matching_rules': [
        {'id': 'r1', 'name': 'Block IoT to LAN', 'action': 'deny', 'enabled': True, 'source': '198.51.100.0/24', 'destination': '192.0.2.0/24', 'protocol': 'all', 'order': 2000, 'rule_set': 'LAN_IN'}
    ],
    'rule_evaluation_order': [2000],
    'recommendations': ['Add an allow rule above 2000 for the NAS'],
    'vlan_matrix': {'vlans': [], 'connectivity_matrix': {}},
}  # fmt: skip
PERFORMANCE = importlib.import_module(
    'unifi_mapper.diagnostics.performance_analysis'
).NetworkPerformanceReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'total_devices_analyzed': 2,
        'average_cpu': 31.0,
        'average_memory': 55.0,
        'average_load': 0.8,
        'high_performers': [],
        'average_performers': [],
        'poor_performers': [
            {'name': 'Garage Switch', 'mac': '02:00:00:00:00:12', 'model': 'USW-Pro-24-PoE', 'type': 'usw', 'cpu_percent': 92.0, 'memory_percent': 88.0, 'load_average': 3.1, 'uptime_days': 12.0, 'tx_bytes': 1, 'rx_bytes': 1, 'tx_packets': 1, 'rx_packets': 1, 'tx_dropped': 500, 'rx_dropped': 0, 'performance_score': 35, 'bottleneck_indicators': ['CPU above 90%'], 'recommendations': ['Reboot in a maintenance window']}
        ],
        'network_bottlenecks': ['Garage Switch CPU'],
        'capacity_warnings': ['Garage Switch memory at 88%'],
        'critical_alerts': [],
        'optimization_recommendations': ['Spread the IoT clients across two switches'],
    }
)  # fmt: skip
CONNECTIVITY = importlib.import_module(
    'unifi_mapper.diagnostics.connectivity_analysis'
).ConnectivityAnalysisReport.model_validate(
    {
        'timestamp': '2026-10-13T10:00:00',
        'network_connectivity_score': 72,
        'total_paths_analyzed': 5,
        'healthy_paths': 3,
        'degraded_paths': 2,
        'broken_paths': 0,
        'network_segments': [
            {'segment_id': 'core', 'segment_type': 'distribution', 'device_count': 3, 'uplink_quality': 'good', 'congestion_level': 'low', 'redundancy': False, 'single_points_of_failure': ['Rack Switch']}
        ],
        'critical_paths': [
            {'source_device': 'Garage Switch', 'source_mac': '02:00:00:00:00:12', 'destination_device': 'Gateway', 'destination_mac': '02:00:00:00:00:01', 'path_hops': ['Rack Switch'], 'path_quality': 'degraded', 'bandwidth_usage': 81.0, 'latency_ms': 1.2, 'issues': ['uplink at 81%']}
        ],
        'redundant_paths': [],
        'connectivity_issues': [
            {'issue_type': 'single_point_of_failure', 'severity': 'high', 'affected_devices': ['Rack Switch'], 'description': 'Every path crosses Rack Switch', 'root_cause': 'one distribution switch', 'resolution_steps': ['Add a second uplink']}
        ],
        'bandwidth_bottlenecks': ['Garage Switch uplink'],
        'latency_issues': [],
        'optimization_opportunities': ['Enable LACP on the two Garage links'],
        'reliability_improvements': ['Second uplink for Rack Switch'],
        'capacity_planning': [],
    }
)  # fmt: skip
FOUND_IP: dict[str, Any] = {
    'device_mac': '02:00:00:00:00:50',
    'device_name': 'Printer',
    'device_type': 'client',
    'device_model': 'Brother',
    'vlan_id': 10,
    'vlan_name': 'LAN',
    'subnet': 'net-lan',
    'dhcp_assigned': True,
    'connection_info': {
        'type': 'wired',
        'connected_to_mac': '02:00:00:00:00:10',
        'port_number': 7,
    },
    'first_seen': 1700000000,
    'last_seen': 1760000000,
    'is_online': True,
}
FOUND_MAC: dict[str, Any] = {
    'device_type': 'client',
    'device_name': 'Laptop',
    'device_model': 'Apple',
    'connection_type': 'wireless',
    'connected_to': 'Hall AP',
    'port_number': None,
    'vlan': 20,
    'ip_address': '198.51.100.50',
    'first_seen': 1700000000,
    'last_seen': 1760000000,
    'is_online': True,
    'signal_strength': -58,
    'channel': 44,
}

# command -> (handler module, handler name, fixture, text the rendering must show, cli args
# beyond the command that exercise the options, and the kwargs the handler must receive)
COMMANDS: dict[str, tuple[str, str, Any, str, list[str], dict[str, Any]]] = {
    'analyze ip-conflicts': (
        'unifi_mapper.analysis.ip_conflicts',
        'detect_ip_conflicts',
        IP_CONFLICTS,
        'IP Conflicts',
        ['--include-offline'],
        {'include_offline': True},
    ),
    'diagnose security': (
        'unifi_mapper.diagnostics.security_audit',
        'security_audit',
        SECURITY,
        'Security Audit',
        [],
        {},
    ),
    'analyze storms': (
        'unifi_mapper.analysis.storm_detection',
        'detect_storms',
        STORMS,
        'Storm Detection',
        ['--device', 'sw-1'],
        {'device_id': 'sw-1'},
    ),
    'analyze mac-table': (
        'unifi_mapper.analysis.mac_analyzer',
        'analyze_mac_table',
        MAC_TABLE,
        'MAC Table',
        ['--device', 'sw-1', '--max-macs-per-port', '8'],
        {'device_id': 'sw-1', 'max_macs_per_port': 8},
    ),
    'analyze qos': (
        'unifi_mapper.analysis.qos_validation',
        'validate_qos',
        QOS,
        'QoS Validation',
        ['--device', 'sw-1', '--no-voice-vlan'],
        {'device_id': 'sw-1', 'check_voice_vlan': False},
    ),
    'analyze capacity': (
        'unifi_mapper.analysis.capacity_planning',
        'get_capacity_report',
        CAPACITY,
        'Capacity',
        [],
        {},
    ),
    'analyze lags': (
        'unifi_mapper.analysis.lag_monitoring',
        'monitor_lags',
        LAGS,
        'LAG Health',
        ['--device', 'sw-1'],
        {'device_id': 'sw-1'},
    ),
    'analyze foreign-bridges': (
        'unifi_mapper.analysis.foreign_bridges',
        'detect_foreign_bridges',
        FOREIGN,
        'Foreign Bridges',
        [],
        {},
    ),
    'diagnose vlans': (
        'unifi_mapper.analysis.vlan_diagnostics',
        'diagnose_vlans',
        VLANS,
        'VLAN Diagnostics',
        ['--source-vlan', '1', '--dest-vlan', '40'],
        {'source_vlan': 1, 'dest_vlan': 40},
    ),
    'diagnose freshness': (
        'unifi_mapper.analysis.device_freshness',
        'summarise_freshness',
        FRESHNESS_SUMMARY,
        'Telemetry Freshness',
        [],
        {},
    ),
    'diagnose performance': (
        'unifi_mapper.diagnostics.performance_analysis',
        'performance_analysis',
        PERFORMANCE,
        'Performance Analysis',
        [],
        {},
    ),
    'diagnose connectivity': (
        'unifi_mapper.diagnostics.connectivity_analysis',
        'connectivity_analysis',
        CONNECTIVITY,
        'Connectivity Analysis',
        [],
        {},
    ),
    'diagnose firewall laptop nas': (
        'unifi_mapper.connectivity.firewall_check',
        'firewall_check',
        FIREWALL,
        'Firewall Check',
        ['--protocol', 'tcp', '--port', '445'],
        {'source': 'laptop', 'destination': 'nas', 'protocol': 'tcp', 'port': '445'},
    ),
    'diagnose path laptop nas': (
        'unifi_mapper.connectivity.traceroute',
        'traceroute',
        PATH,
        'Path',
        ['--no-firewall', '--expert'],
        {
            'source': 'laptop',
            'destination': 'nas',
            'include_firewall': False,
            'verbosity': 'expert',
        },
    ),
    'diagnose client-path laptop': (
        'unifi_mapper.discovery.client_trace',
        'client_trace',
        PATH,
        'Path',
        [],
        {'client': 'laptop'},
    ),
    'find ip 192.0.2.50': (
        'unifi_mapper.discovery.find_ip',
        'find_ip',
        FOUND_IP,
        '192.0.2.50',
        [],
        {'ip': '192.0.2.50'},
    ),
    'find mac 02:00:00:00:00:51': (
        'unifi_mapper.discovery.find_mac',
        'find_mac',
        FOUND_MAC,
        '02:00:00:00:00:51',
        [],
        {'mac': '02:00:00:00:00:51'},
    ),
}


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SimpleNamespace:
    """Every handler returns its fixture and records the keyword arguments it was given."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('COLUMNS', '240')  # Rich wraps cells at 80 columns otherwise
    monkeypatch.setattr(typer_cli, 'load_env_from_config', lambda path: None)
    calls: list[tuple[str, dict[str, Any]]] = []
    for module_name, handler, report, *_ in COMMANDS.values():

        async def _fake(_name=handler, _report=report, **kwargs: Any) -> Any:
            calls.append((_name, kwargs))
            return _report

        monkeypatch.setattr(importlib.import_module(module_name), handler, _fake)

    def run(*args: str):
        return runner.invoke(app, list(args))

    return SimpleNamespace(run=run, calls=calls)


def _dump(report: Any) -> Any:
    return report.model_dump(mode='json') if hasattr(report, 'model_dump') else report


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_json_equals_the_tool_result(cli: SimpleNamespace, command: str) -> None:
    _, handler, report, _, _, _ = COMMANDS[command]
    result = cli.run(*command.split(), '--json')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == _dump(report)
    assert [name for name, _ in cli.calls] == [handler]


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_rendering_names_the_report(cli: SimpleNamespace, command: str) -> None:
    _, _, _, shown, _, _ = COMMANDS[command]
    result = cli.run(*command.split())
    assert result.exit_code == 0, result.output
    assert shown in result.stdout


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_options_reach_the_handler_by_keyword(cli: SimpleNamespace, command: str) -> None:
    _, handler, _, _, args, expected = COMMANDS[command]
    result = cli.run(*command.split(), *args, '--json')
    assert result.exit_code == 0, result.output
    [(name, kwargs)] = cli.calls
    assert name == handler
    for key, value in expected.items():
        assert kwargs.get(key) == value, (key, kwargs)


def _command_path(invocation: str) -> str:
    """The registered command an invocation runs: its longest leading token prefix."""
    tokens = invocation.split()
    known = cli_commands()
    for n in range(len(tokens), 0, -1):
        if ' '.join(tokens[:n]) in known:
            return ' '.join(tokens[:n])
    raise AssertionError(f'{invocation!r} names no unifi-mapper command')


@pytest.mark.parametrize('command', sorted(COMMANDS))
def test_the_manifest_names_the_command(command: str) -> None:
    _, handler, *_ = COMMANDS[command]
    path = _command_path(command)
    named = [
        name
        for tools in REGISTRY.get_categories().values()
        for name in tools
        if (meta := REGISTRY.get_metadata(name)) is not None and meta.cli == path
    ]
    assert named, f'no manifest entry carries cli: {path}'
    assert handler in {REGISTRY.get_metadata(n).handler for n in named}  # type: ignore[union-attr]


def test_ip_conflicts_rendering_shows_each_client(cli: SimpleNamespace) -> None:
    result = cli.run('analyze', 'ip-conflicts')
    assert result.exit_code == 0, result.output
    text = ' '.join(result.stdout.split())
    assert '192.0.2.50' in text and 'CRITICAL' in text
    assert 'Printer' in text and 'Rack Switch' in text and 'Hall AP' in text
    assert 'VLAN mismatch' in text or 'mismatch' in text
    assert 'Reserve 192.0.2.50' in text


def test_security_rendering_shows_risks_and_actions(cli: SimpleNamespace) -> None:
    result = cli.run('diagnose', 'security')
    assert result.exit_code == 0, result.output
    text = ' '.join(result.stdout.split())
    assert 'mystery-box' in text and 'critical' in text.lower()
    assert 'Isolate mystery-box' in text
    assert 'Enable 802.1X' in text
    assert 'two switches' in text


def test_a_tool_error_prints_red_and_exits_1(cli: SimpleNamespace, monkeypatch) -> None:
    from unifi_mapper.analysis import ip_conflicts

    async def _down(**_kwargs: Any) -> Any:
        raise ToolError(
            message='Cannot connect to UniFi controller',
            error_code=ErrorCodes.CONTROLLER_UNREACHABLE,
        )

    monkeypatch.setattr(ip_conflicts, 'detect_ip_conflicts', _down)
    result = cli.run('analyze', 'ip-conflicts', '--json')
    assert result.exit_code == 1
    assert result.stdout == ''
    assert 'Cannot connect to UniFi controller' in result.stderr


def test_storms_rendering_shows_the_storm_and_the_risky_port(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'storms').stdout.split())
    assert 'Rack Switch' in text and 'broadcast' in text and '61.5' in text
    assert 'Port 9' in text and 'Enable storm control' in text


def test_mac_table_rendering_shows_flaps_alerts_and_busy_ports(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'mac-table').stdout.split())
    assert '02:00:00:00:00:77' in text and 'flap' in text.lower()
    assert 'Port 12 learns 41 MACs' in text and 'Review the flapping MAC' in text


def test_qos_rendering_shows_findings_and_health(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'qos').stdout.split())
    assert 'DEGRADED' in text and 'DSCP trust disabled' in text and 'Enable DSCP trust' in text


def test_capacity_rendering_shows_per_device_rows_and_expansion(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'capacity').stdout.split())
    assert 'USW-Pro-24-PoE' in text and '95.8' in text and 'Plan a second switch' in text
    assert 'expansion' in text.lower()


def test_lags_rendering_shows_members_and_issues(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'lags').stdout.split())
    assert 'Uplink LAG' in text and 'degraded' in text.lower() and 'Desk Switch' in text
    assert 'SFP+ 2' in text and 'Check the SFP+ 2 cable' in text


def test_foreign_bridges_rendering_shows_the_bridge_and_finding(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('analyze', 'foreign-bridges').stdout.split())
    assert 'gs108' in text and 'Netgear' in text and 'Rack Switch p3' in text
    assert 'Unmanaged switch with 4 clients' in text


def test_vlans_rendering_shows_vlans_checks_and_trunks(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'vlans').stdout.split())
    assert 'Voice' in text and '198.51.100.0/24' in text
    assert 'VLAN 40 has no DHCP' in text and 'DEGRADED' in text
    assert 'Uplink' in text


def test_freshness_summary_rendering_marks_the_stale_device(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'freshness').stdout.split())
    assert 'Garage Switch' in text and '15 minutes old' in text


def test_freshness_sample_runs_the_two_sample_check(cli: SimpleNamespace, monkeypatch) -> None:
    received: list[dict[str, Any]] = []

    async def _check(**kwargs: Any) -> Any:
        received.append(kwargs)
        return FRESHNESS_REPORT

    monkeypatch.setattr(device_freshness, 'check_device_freshness', _check)
    result = cli.run('diagnose', 'freshness', '--sample', '--gap', '30', '--json')
    assert result.exit_code == 0, result.output
    assert received == [{'sample_gap_seconds': 30}]
    assert json.loads(result.stdout) == FRESHNESS_REPORT.model_dump(mode='json')
    assert 'about 30 s' in result.stderr
    text = ' '.join(cli.run('diagnose', 'freshness', '--sample', '--gap', '30').stdout.split())
    assert 'counters did not move' in text and 'Check the uplink' in text


def test_freshness_gap_is_bounded(cli: SimpleNamespace) -> None:
    assert cli.run('diagnose', 'freshness', '--sample', '--gap', '5').exit_code == 2
    assert cli.run('diagnose', 'freshness', '--gap', '30').exit_code == 2  # --gap needs --sample


def test_stp_path_costs_discovers_then_audits(cli: SimpleNamespace, monkeypatch) -> None:
    from unifi_mapper.analysis import stp_optimizer
    from unifi_mapper.core.models.stp import STPPathCostFinding

    topology = object()
    audited: list[object] = []

    async def _discover(**_kwargs: Any) -> object:
        return topology

    def _audit(topo: object) -> list[STPPathCostFinding]:
        audited.append(topo)
        return [
            STPPathCostFinding(
                severity='WARNING',
                device_name='Rack Switch',
                port_idx=25,
                path_cost=20000,
                link_speed_mbps=10000,
                expected_long_cost=2000,
                message='10G uplink costs like 1G',
                recommendation='Set long path-cost mode',
            )
        ]

    monkeypatch.setattr(stp_optimizer, 'discover_stp_topology', _discover)
    monkeypatch.setattr(stp_optimizer, 'audit_stp_path_costs', _audit)
    result = cli.run('stp', 'path-costs', '--json')
    assert result.exit_code == 0, result.output
    assert audited == [topology]
    payload = json.loads(result.stdout)
    assert payload['findings'][0]['port_idx'] == 25 and payload['findings_count'] == 1
    text = ' '.join(cli.run('stp', 'path-costs').stdout.split())
    assert (
        'Path Cost' in text and '10G uplink costs like 1G' in text and 'Set long path-cost' in text
    )


def test_stp_path_costs_manifest_names_the_command() -> None:
    meta = REGISTRY.get_metadata('audit_stp_path_costs')
    assert meta is not None and meta.cli == 'stp path-costs'
    assert REGISTRY.get_metadata('check_device_freshness').cli == 'diagnose freshness'  # type: ignore[union-attr]


def test_path_rendering_shows_hops_verdict_and_blocking_rule(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'path', 'laptop', 'nas').stdout.split())
    assert 'Laptop' in text and 'NAS' in text and '192.0.2.50' in text
    assert 'Hall AP' in text and 'Gateway' in text and 'Rack Switch' in text
    assert 'deny' in text and 'Block IoT to LAN' in text
    assert 'L3' in text and 'VLANs' in text


def test_path_analyze_runs_the_analysis_tool(cli: SimpleNamespace, monkeypatch) -> None:
    path_analysis = importlib.import_module('unifi_mapper.connectivity.path_analysis')
    received: list[dict[str, Any]] = []

    async def _analyse(**kwargs: Any) -> dict[str, Any]:
        received.append(kwargs)
        return PATH_ANALYSIS

    monkeypatch.setattr(path_analysis, 'path_analysis_mcp', _analyse)
    result = cli.run('diagnose', 'path', 'laptop', 'nas', '--analyze', '--json')
    assert result.exit_code == 0, result.output
    assert received == [{'source': 'laptop', 'destination': 'nas'}]
    assert json.loads(result.stdout) == PATH_ANALYSIS
    assert cli.calls == []  # traceroute itself is not called in --analyze mode
    text = ' '.join(cli.run('diagnose', 'path', 'laptop', 'nas', '--analyze').stdout.split())
    assert 'Path Analysis' in text and 'L3 routed' in text and 'good' in text
    assert 'Gateway: firewall deny' in text and 'Allow the NAS' in text


def test_client_path_rendering_shows_the_hops(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'client-path', 'laptop').stdout.split())
    assert 'Hall AP' in text and 'Gateway' in text and 'deny' in text


def test_firewall_rendering_shows_verdict_rules_and_endpoints(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'firewall', 'laptop', 'nas').stdout.split())
    assert 'deny' in text and 'Block IoT to LAN' in text and 'LAN_IN' in text
    assert 'IoT' in text and '192.0.2.20' in text
    assert 'Add an allow rule' in text


def test_performance_rendering_shows_poor_performers_and_notes(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'performance').stdout.split())
    assert 'Garage Switch' in text and '92' in text and 'CPU above 90%' in text
    assert 'Garage Switch memory at 88%' in text and 'Spread the IoT clients' in text


def test_connectivity_rendering_shows_segments_paths_and_issues(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('diagnose', 'connectivity').stdout.split())
    assert '72' in text and 'core' in text and 'Rack Switch' in text
    assert 'Garage Switch' in text and 'uplink at 81%' in text
    assert 'Every path crosses Rack Switch' in text and 'Add a second uplink' in text
    assert 'Enable LACP' in text


def test_find_ip_and_mac_render_every_field(cli: SimpleNamespace) -> None:
    text = ' '.join(cli.run('find', 'ip', '192.0.2.50').stdout.split())
    assert 'Printer' in text and 'wired' in text and 'port_number' in text and '7' in text
    text = ' '.join(cli.run('find', 'mac', '02:00:00:00:00:51').stdout.split())
    assert 'Laptop' in text and 'Hall AP' in text and '-58' in text and '198.51.100.50' in text


def test_find_ip_not_found_exits_1_with_the_tool_message(
    cli: SimpleNamespace, monkeypatch
) -> None:
    module = importlib.import_module('unifi_mapper.discovery.find_ip')

    async def _missing(**_kwargs: Any) -> Any:
        raise ToolError(
            message='IP address 192.0.2.77 not found on any device', error_code='IP_NOT_FOUND'
        )

    monkeypatch.setattr(module, 'find_ip', _missing)
    result = cli.run('find', 'ip', '192.0.2.77')
    assert result.exit_code == 1
    assert 'not found' in result.stderr
