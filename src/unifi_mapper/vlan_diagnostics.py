#!/usr/bin/env python3
"""
VLAN Diagnostics module for UniFi Network Mapper.
Provides comprehensive VLAN troubleshooting and analysis capabilities.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from .api_client import UnifiApiClient

logger = logging.getLogger(__name__)

@dataclass
class VLANInfo:
    """Information about a VLAN."""
    id: int
    name: str
    subnet: str
    gateway: str
    enabled: bool
    dhcp_enabled: bool
    firewall_group: Optional[str] = None

@dataclass
class PortVLANConfig:
    """VLAN configuration for a switch port."""
    port_idx: int
    device_id: str
    device_name: str
    native_vlan: int
    tagged_vlans: List[int]
    profile_name: str
    is_trunk: bool

@dataclass
class VLANDiagnosticResult:
    """Result of VLAN diagnostic check."""
    check_name: str
    status: str  # "PASS", "FAIL", "WARNING"
    message: str
    details: Dict[str, Any]
    recommendations: List[str]

class VLANDiagnostics:
    """VLAN diagnostic and troubleshooting utilities."""
    
    def __init__(self, api_client: UnifiApiClient, site: str = "default"):
        self.api_client = api_client
        self.site = site
        self.vlans: Dict[int, VLANInfo] = {}
        self.port_configs: List[PortVLANConfig] = []
        self.firewall_rules: List[Dict[str, Any]] = []
        
    def get_vlan_configuration(self) -> Dict[int, VLANInfo]:
        """Retrieve VLAN configuration from UniFi Controller."""
        try:
            # Get network configuration
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/networkconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/networkconf"
            
            def _try_get_networks():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            
            response = self.api_client._retry_request(_try_get_networks)
            
            vlans = {}
            if response and response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    for network in data['data']:
                        if network.get('purpose') == 'vlan-only' or 'vlan' in network:
                            vlan_id = network.get('vlan', 1)
                            vlans[vlan_id] = VLANInfo(
                                id=vlan_id,
                                name=network.get('name', f'VLAN {vlan_id}'),
                                subnet=network.get('ip_subnet', ''),
                                gateway=network.get('gateway_ip', ''),
                                enabled=network.get('enabled', True),
                                dhcp_enabled=network.get('dhcpd_enabled', False),
                                firewall_group=network.get('firewall_group')
                            )
            
            self.vlans = vlans
            logger.info(f"Retrieved {len(vlans)} VLAN configurations")
            return vlans
            
        except Exception as e:
            logger.error(f"Failed to get VLAN configuration: {e}")
            return {}
    
    def get_port_vlan_configs(self) -> List[PortVLANConfig]:
        """Get VLAN configuration for all switch ports."""
        try:
            devices = self.api_client.get_devices(self.site)
            port_configs = []
            
            if not devices or 'data' not in devices:
                return port_configs
                
            for device in devices['data']:
                if device.get('type') != 'usw':  # Only switches
                    continue
                    
                device_id = device['_id']
                device_name = device.get('name', device.get('model', 'Unknown'))
                
                # Get port overrides
                port_overrides = device.get('port_overrides', [])
                
                for port_override in port_overrides:
                    port_idx = port_override.get('port_idx')
                    if port_idx is None:
                        continue
                        
                    # Get VLAN configuration
                    native_vlan = port_override.get('native_networkconf_id', 1)
                    profile_name = port_override.get('portconf_id', 'Default')
                    
                    # Parse tagged VLANs
                    tagged_vlans = []
                    if 'networkconf_id' in port_override:
                        tagged_vlans = [port_override['networkconf_id']]
                    
                    is_trunk = len(tagged_vlans) > 0 or 'trunk' in profile_name.lower()
                    
                    port_configs.append(PortVLANConfig(
                        port_idx=port_idx,
                        device_id=device_id,
                        device_name=device_name,
                        native_vlan=native_vlan,
                        tagged_vlans=tagged_vlans,
                        profile_name=profile_name,
                        is_trunk=is_trunk
                    ))
            
            self.port_configs = port_configs
            logger.info(f"Retrieved VLAN config for {len(port_configs)} ports")
            return port_configs
            
        except Exception as e:
            logger.error(f"Failed to get port VLAN configs: {e}")
            return []
    
    def get_firewall_rules(self) -> List[Dict[str, Any]]:
        """Get firewall rules that might affect inter-VLAN traffic."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/firewallrule"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/firewallrule"
            
            def _try_get_firewall():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            
            response = self.api_client._retry_request(_try_get_firewall)
            
            rules = []
            if response and response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    rules = data['data']
            
            self.firewall_rules = rules
            logger.info(f"Retrieved {len(rules)} firewall rules")
            return rules
            
        except Exception as e:
            logger.error(f"Failed to get firewall rules: {e}")
            return []
    
    def diagnose_inter_vlan_connectivity(self, source_vlan: int, dest_vlan: int) -> List[VLANDiagnosticResult]:
        """Comprehensive diagnosis of inter-VLAN connectivity issues."""
        results = []
        
        # Refresh data
        self.get_vlan_configuration()
        self.get_port_vlan_configs()
        self.get_firewall_rules()
        
        # Check 1: VLAN existence and configuration
        results.append(self._check_vlan_existence(source_vlan, dest_vlan))
        
        # Check 2: Gateway configuration
        results.append(self._check_gateway_configuration(source_vlan, dest_vlan))
        
        # Check 3: Trunk configuration
        results.append(self._check_trunk_configuration(source_vlan, dest_vlan))
        
        # Check 4: Firewall rules
        results.append(self._check_firewall_rules(source_vlan, dest_vlan))
        
        # Check 5: Port configuration consistency
        results.append(self._check_port_configuration())
        
        return results
    
    def _check_vlan_existence(self, source_vlan: int, dest_vlan: int) -> VLANDiagnosticResult:
        """Check if VLANs exist and are properly configured."""
        missing_vlans = []
        disabled_vlans = []
        
        for vlan_id in [source_vlan, dest_vlan]:
            if vlan_id not in self.vlans:
                missing_vlans.append(vlan_id)
            elif not self.vlans[vlan_id].enabled:
                disabled_vlans.append(vlan_id)
        
        if missing_vlans:
            return VLANDiagnosticResult(
                check_name="VLAN Existence",
                status="FAIL",
                message=f"Missing VLANs: {missing_vlans}",
                details={"missing_vlans": missing_vlans},
                recommendations=[
                    f"Create missing VLANs: {missing_vlans}",
                    "Verify VLAN configuration in UniFi Network settings"
                ]
            )
        
        if disabled_vlans:
            return VLANDiagnosticResult(
                check_name="VLAN Existence",
                status="FAIL",
                message=f"Disabled VLANs: {disabled_vlans}",
                details={"disabled_vlans": disabled_vlans},
                recommendations=[f"Enable VLANs: {disabled_vlans}"]
            )
        
        return VLANDiagnosticResult(
            check_name="VLAN Existence",
            status="PASS",
            message="All VLANs exist and are enabled",
            details={"vlans": {vlan_id: self.vlans[vlan_id] for vlan_id in [source_vlan, dest_vlan]}},
            recommendations=[]
        )
    
    def _check_gateway_configuration(self, source_vlan: int, dest_vlan: int) -> VLANDiagnosticResult:
        """Check gateway configuration for inter-VLAN routing."""
        issues = []
        
        for vlan_id in [source_vlan, dest_vlan]:
            if vlan_id in self.vlans:
                vlan = self.vlans[vlan_id]
                if not vlan.gateway:
                    issues.append(f"VLAN {vlan_id} has no gateway configured")
                elif not vlan.subnet:
                    issues.append(f"VLAN {vlan_id} has no subnet configured")
        
        if issues:
            return VLANDiagnosticResult(
                check_name="Gateway Configuration",
                status="FAIL",
                message="; ".join(issues),
                details={"issues": issues},
                recommendations=[
                    "Configure gateway IP for each VLAN",
                    "Ensure subnet is properly defined",
                    "Verify router/gateway device supports inter-VLAN routing"
                ]
            )
        
        return VLANDiagnosticResult(
            check_name="Gateway Configuration",
            status="PASS",
            message="Gateway configuration looks correct",
            details={},
            recommendations=[]
        )
    
    def _check_trunk_configuration(self, source_vlan: int, dest_vlan: int) -> VLANDiagnosticResult:
        """Check trunk port configuration for VLAN connectivity."""
        trunk_ports = [p for p in self.port_configs if p.is_trunk]
        vlan_coverage = {source_vlan: [], dest_vlan: []}
        
        for port in trunk_ports:
            for vlan_id in [source_vlan, dest_vlan]:
                if vlan_id in port.tagged_vlans or vlan_id == port.native_vlan:
                    vlan_coverage[vlan_id].append(f"{port.device_name}:{port.port_idx}")
        
        issues = []
        for vlan_id, ports in vlan_coverage.items():
            if not ports:
                issues.append(f"VLAN {vlan_id} not found on any trunk ports")
        
        if issues:
            return VLANDiagnosticResult(
                check_name="Trunk Configuration",
                status="FAIL",
                message="; ".join(issues),
                details={"vlan_coverage": vlan_coverage, "trunk_ports": len(trunk_ports)},
                recommendations=[
                    "Verify VLAN is tagged on trunk ports between switches",
                    "Check switch port profiles include required VLANs",
                    "Ensure trunk ports are properly configured on all switches in path"
                ]
            )
        
        return VLANDiagnosticResult(
            check_name="Trunk Configuration",
            status="PASS",
            message="VLANs found on trunk ports",
            details={"vlan_coverage": vlan_coverage},
            recommendations=[]
        )
    
    def _check_firewall_rules(self, source_vlan: int, dest_vlan: int) -> VLANDiagnosticResult:
        """Check firewall rules that might block inter-VLAN traffic."""
        blocking_rules = []
        
        for rule in self.firewall_rules:
            if not rule.get('enabled', True):
                continue
                
            action = rule.get('action', 'allow')
            if action == 'drop' or action == 'reject':
                # Check if rule affects our VLANs
                src_group = rule.get('src_firewallgroup_ids', [])
                dst_group = rule.get('dst_firewallgroup_ids', [])
                
                # This is a simplified check - in reality, you'd need to resolve
                # firewall group memberships
                if src_group or dst_group:
                    blocking_rules.append({
                        'name': rule.get('name', 'Unnamed Rule'),
                        'action': action,
                        'src_groups': src_group,
                        'dst_groups': dst_group
                    })
        
        if blocking_rules:
            return VLANDiagnosticResult(
                check_name="Firewall Rules",
                status="WARNING",
                message=f"Found {len(blocking_rules)} potentially blocking firewall rules",
                details={"blocking_rules": blocking_rules},
                recommendations=[
                    "Review firewall rules for inter-VLAN blocking",
                    "Check if VLAN firewall groups have restrictive rules",
                    "Consider creating specific allow rules for required inter-VLAN traffic"
                ]
            )
        
        return VLANDiagnosticResult(
            check_name="Firewall Rules",
            status="PASS",
            message="No obvious blocking firewall rules found",
            details={},
            recommendations=[]
        )
    
    def _check_port_configuration(self) -> VLANDiagnosticResult:
        """Check for port configuration inconsistencies."""
        issues = []
        profile_usage = {}
        
        for port in self.port_configs:
            profile = port.profile_name
            if profile not in profile_usage:
                profile_usage[profile] = []
            profile_usage[profile].append(port)
        
        # Check for inconsistent trunk configurations
        for profile, ports in profile_usage.items():
            if len(ports) > 1:
                # Check if all ports with same profile have same VLAN config
                first_port = ports[0]
                for port in ports[1:]:
                    if (port.native_vlan != first_port.native_vlan or 
                        set(port.tagged_vlans) != set(first_port.tagged_vlans)):
                        issues.append(f"Inconsistent VLAN config for profile '{profile}'")
                        break
        
        if issues:
            return VLANDiagnosticResult(
                check_name="Port Configuration",
                status="WARNING",
                message="; ".join(issues),
                details={"profile_usage": {k: len(v) for k, v in profile_usage.items()}},
                recommendations=[
                    "Review port profiles for consistency",
                    "Ensure all ports with same profile have same VLAN configuration"
                ]
            )
        
        return VLANDiagnosticResult(
            check_name="Port Configuration",
            status="PASS",
            message="Port configurations appear consistent",
            details={"profiles_found": len(profile_usage)},
            recommendations=[]
        )
    
    def generate_diagnostic_report(self, source_vlan: int, dest_vlan: int) -> str:
        """Generate a comprehensive diagnostic report."""
        results = self.diagnose_inter_vlan_connectivity(source_vlan, dest_vlan)
        
        report = f"""
# VLAN Connectivity Diagnostic Report
## Source: VLAN {source_vlan} → Destination: VLAN {dest_vlan}

"""
        
        # Summary
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        warnings = sum(1 for r in results if r.status == "WARNING")
        
        report += f"**Summary:** {passed} passed, {failed} failed, {warnings} warnings\n\n"
        
        # Detailed results
        for result in results:
            status_emoji = {"PASS": "✅", "FAIL": "❌", "WARNING": "⚠️"}
            report += f"## {status_emoji[result.status]} {result.check_name}\n"
            report += f"**Status:** {result.status}\n"
            report += f"**Message:** {result.message}\n"
            
            if result.recommendations:
                report += "**Recommendations:**\n"
                for rec in result.recommendations:
                    report += f"- {rec}\n"
            
            report += "\n"
        
        # VLAN Information
        if self.vlans:
            report += "## VLAN Configuration\n"
            for vlan_id in [source_vlan, dest_vlan]:
                if vlan_id in self.vlans:
                    vlan = self.vlans[vlan_id]
                    report += f"- **VLAN {vlan_id}** ({vlan.name}): {vlan.subnet} → {vlan.gateway}\n"
        
        return report
