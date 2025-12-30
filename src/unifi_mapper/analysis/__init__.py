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
"""

from unifi_mcp.tools.analysis.capacity_planning import get_capacity_report
from unifi_mcp.tools.analysis.firmware_advisor import get_firmware_report
from unifi_mcp.tools.analysis.ip_conflicts import detect_ip_conflicts
from unifi_mcp.tools.analysis.lag_monitoring import monitor_lags
from unifi_mcp.tools.analysis.link_quality import analyze_link_quality
from unifi_mcp.tools.analysis.mac_analyzer import analyze_mac_table
from unifi_mcp.tools.analysis.qos_validation import validate_qos
from unifi_mcp.tools.analysis.storm_detection import detect_storms
from unifi_mcp.tools.analysis.vlan_diagnostics import diagnose_vlans


__all__ = [
    # P1 tools
    'detect_ip_conflicts',
    'detect_storms',
    'diagnose_vlans',
    # P2 tools
    'analyze_link_quality',
    'get_capacity_report',
    'monitor_lags',
    'validate_qos',
    # P3 tools
    'analyze_mac_table',
    'get_firmware_report',
]
