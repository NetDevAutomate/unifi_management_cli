#!/usr/bin/env python3
"""
Physical topology verification using CDP/LLDP data.
"""

import logging
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class PhysicalConnection:
    """Physical connection between devices."""
    local_device: str
    local_port: int
    remote_device: str
    remote_port: str
    connection_type: str  # "expected", "unexpected", "missing"
    cable_length: str = "unknown"
    link_speed: str = "unknown"
    duplex: str = "unknown"

@dataclass
class TopologyVerification:
    """Results of physical topology verification."""
    total_connections: int
    verified_connections: int
    missing_connections: int
    unexpected_connections: int
    verification_percentage: float
    issues: List[str]

class PhysicalTopologyVerifier:
    """Verify physical network topology using CDP/LLDP."""
    
    def __init__(self, api_client, site: str = "default"):
        self.api_client = api_client
        self.site = site
    
    def discover_physical_topology(self) -> List[PhysicalConnection]:
        """Discover actual physical topology using LLDP/CDP."""
        connections = []
        
        try:
            devices = self.api_client.get_devices(self.site)
            if not devices or 'data' not in devices:
                return connections
            
            switches = [d for d in devices['data'] if d.get('type') == 'usw']
            
            for switch in switches:
                device_id = switch['_id']
                device_name = switch.get('name', switch.get('model', 'Unknown'))
                
                # Get LLDP info for all ports
                lldp_info = self.api_client.get_lldp_info(self.site, device_id)
                
                # Get port details for speed/duplex info
                ports = self.api_client.get_device_ports(self.site, device_id)
                port_details = {p.get('port_idx', 0): p for p in ports}
                
                for port_idx, lldp_data in lldp_info.items():
                    if lldp_data:
                        port_info = port_details.get(int(port_idx), {})
                        
                        connection = PhysicalConnection(
                            local_device=device_name,
                            local_port=int(port_idx),
                            remote_device=lldp_data.get('system_name', 'Unknown'),
                            remote_port=lldp_data.get('port_id', 'Unknown'),
                            connection_type="discovered",
                            link_speed=f"{port_info.get('speed', 0)}Mbps",
                            duplex="full" if port_info.get('full_duplex') else "half"
                        )
                        connections.append(connection)
            
            logger.info(f"Discovered {len(connections)} physical connections")
            return connections
            
        except Exception as e:
            logger.error(f"Error discovering topology: {e}")
            return []
    
    def verify_expected_topology(self, expected_connections: List[Dict]) -> TopologyVerification:
        """Verify actual topology against expected configuration."""
        actual_connections = self.discover_physical_topology()
        
        # Create lookup for actual connections
        actual_lookup = {}
        for conn in actual_connections:
            key = f"{conn.local_device}:{conn.local_port}"
            actual_lookup[key] = conn
        
        verified = 0
        missing = []
        issues = []
        
        # Check expected connections
        for expected in expected_connections:
            key = f"{expected['local_device']}:{expected['local_port']}"
            
            if key in actual_lookup:
                actual = actual_lookup[key]
                if actual.remote_device == expected['remote_device']:
                    verified += 1
                else:
                    issues.append(f"Port {key} connected to {actual.remote_device}, expected {expected['remote_device']}")
            else:
                missing.append(key)
                issues.append(f"Missing connection: {key} → {expected['remote_device']}")
        
        # Find unexpected connections
        unexpected = []
        expected_keys = {f"{e['local_device']}:{e['local_port']}" for e in expected_connections}
        for conn in actual_connections:
            key = f"{conn.local_device}:{conn.local_port}"
            if key not in expected_keys:
                unexpected.append(key)
                issues.append(f"Unexpected connection: {key} → {conn.remote_device}")
        
        total = len(expected_connections)
        verification_percentage = (verified / total * 100) if total > 0 else 0
        
        return TopologyVerification(
            total_connections=total,
            verified_connections=verified,
            missing_connections=len(missing),
            unexpected_connections=len(unexpected),
            verification_percentage=verification_percentage,
            issues=issues
        )
    
    def generate_topology_report(self, verification: TopologyVerification) -> str:
        """Generate physical topology verification report."""
        report = "# Physical Topology Verification Report\n\n"
        
        report += f"**Verification Score**: {verification.verification_percentage:.1f}%\n\n"
        report += f"- **Total Expected**: {verification.total_connections}\n"
        report += f"- **Verified**: {verification.verified_connections}\n"
        report += f"- **Missing**: {verification.missing_connections}\n"
        report += f"- **Unexpected**: {verification.unexpected_connections}\n\n"
        
        if verification.verification_percentage >= 95:
            report += "✅ **Physical topology verified successfully**\n\n"
        elif verification.verification_percentage >= 80:
            report += "⚠️ **Minor topology discrepancies detected**\n\n"
        else:
            report += "❌ **Significant topology issues found**\n\n"
        
        if verification.issues:
            report += "## Issues Found\n\n"
            for issue in verification.issues:
                report += f"- {issue}\n"
        
        return report
