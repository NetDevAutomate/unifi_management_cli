#!/usr/bin/env python3
"""
Automated port profile application and connectivity testing.
"""

import logging
import subprocess
import re
import statistics
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from .api_client import UnifiApiClient

logger = logging.getLogger(__name__)

@dataclass
class ConnectivityTest:
    """Results of a connectivity test."""
    source_ip: str
    target_ip: str
    success: bool
    packet_loss: float
    avg_latency: Optional[float]
    min_latency: Optional[float]
    max_latency: Optional[float]
    packets_sent: int
    packets_received: int

@dataclass
class PortApplication:
    """Result of applying a port profile."""
    device_id: str
    device_name: str
    port_idx: int
    profile_name: str
    success: bool
    message: str

class NetworkAutomation:
    """Automated network configuration and testing."""
    
    def __init__(self, api_client: UnifiApiClient, site: str = "default"):
        self.api_client = api_client
        self.site = site
    
    def find_uplink_ports(self) -> List[Dict[str, Any]]:
        """Identify uplink ports between switches using LLDP data."""
        uplink_ports = []
        
        try:
            devices = self.api_client.get_devices(self.site)
            if not devices or 'data' not in devices:
                return uplink_ports
            
            switches = [d for d in devices['data'] if d.get('type') == 'usw']
            
            for switch in switches:
                device_id = switch['_id']
                device_name = switch.get('name', switch.get('model', 'Unknown'))
                
                # Get LLDP info to identify uplinks
                lldp_info = self.api_client.get_lldp_info(self.site, device_id)
                
                for port_idx, lldp_data in lldp_info.items():
                    if lldp_data and 'system_name' in lldp_data:
                        # This port connects to another device
                        uplink_ports.append({
                            'device_id': device_id,
                            'device_name': device_name,
                            'port_idx': int(port_idx),
                            'connected_to': lldp_data.get('system_name', 'Unknown'),
                            'port_name': f"Port {port_idx}"
                        })
            
            logger.info(f"Found {len(uplink_ports)} potential uplink ports")
            return uplink_ports
            
        except Exception as e:
            logger.error(f"Error finding uplink ports: {e}")
            return []
    
    def apply_port_profile(self, device_id: str, port_idx: int, profile_id: str) -> PortApplication:
        """Apply a port profile to a specific switch port."""
        try:
            # Get device info for logging
            devices = self.api_client.get_devices(self.site)
            device_name = "Unknown"
            if devices and 'data' in devices:
                for device in devices['data']:
                    if device['_id'] == device_id:
                        device_name = device.get('name', device.get('model', 'Unknown'))
                        break
            
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/device/{device_id}"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/device/{device_id}"
            
            # Get current device configuration
            def _get_device():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            
            response = self.api_client._retry_request(_get_device)
            if response.status_code != 200:
                return PortApplication(
                    device_id=device_id,
                    device_name=device_name,
                    port_idx=port_idx,
                    profile_name="Unknown",
                    success=False,
                    message=f"Failed to get device config: {response.status_code}"
                )
            
            device_config = response.json()['data'][0]
            
            # Update port overrides
            port_overrides = device_config.get('port_overrides', [])
            
            # Remove existing override for this port
            port_overrides = [po for po in port_overrides if po.get('port_idx') != port_idx]
            
            # Add new override
            port_overrides.append({
                'port_idx': port_idx,
                'portconf_id': profile_id
            })
            
            update_config = {'port_overrides': port_overrides}
            
            def _update_device():
                return self.api_client.session.put(
                    endpoint,
                    json=update_config,
                    timeout=self.api_client.timeout
                )
            
            response = self.api_client._retry_request(_update_device)
            
            if response.status_code == 200:
                logger.info(f"Applied profile to {device_name} port {port_idx}")
                return PortApplication(
                    device_id=device_id,
                    device_name=device_name,
                    port_idx=port_idx,
                    profile_name="Applied",
                    success=True,
                    message="Successfully applied port profile"
                )
            else:
                return PortApplication(
                    device_id=device_id,
                    device_name=device_name,
                    port_idx=port_idx,
                    profile_name="Failed",
                    success=False,
                    message=f"API error: {response.status_code} - {response.text}"
                )
                
        except Exception as e:
            return PortApplication(
                device_id=device_id,
                device_name=device_name,
                port_idx=port_idx,
                profile_name="Error",
                success=False,
                message=f"Exception: {e}"
            )
    
    def get_port_profiles(self) -> Dict[str, str]:
        """Get available port profiles."""
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/rest/portconf"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/rest/portconf"
            
            def _get_profiles():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)
            
            response = self.api_client._retry_request(_get_profiles)
            
            if response.status_code == 200:
                profiles = {}
                for profile in response.json()['data']:
                    profiles[profile['name']] = profile['_id']
                return profiles
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting port profiles: {e}")
            return {}
    
    def apply_trunk_profile_to_uplinks(self, profile_name: str = "Trunk Default+VLAN10") -> List[PortApplication]:
        """Automatically apply trunk profile to identified uplink ports."""
        results = []
        
        # Get available profiles
        profiles = self.get_port_profiles()
        if profile_name not in profiles:
            logger.error(f"Profile '{profile_name}' not found")
            return results
        
        profile_id = profiles[profile_name]
        
        # Find uplink ports
        uplink_ports = self.find_uplink_ports()
        
        for uplink in uplink_ports:
            result = self.apply_port_profile(
                uplink['device_id'],
                uplink['port_idx'],
                profile_id
            )
            results.append(result)
            
            # Small delay between applications
            time.sleep(1)
        
        return results
    
    def ping_test(self, target_ip: str, count: int = 5, timeout: int = 10) -> ConnectivityTest:
        """Perform ping connectivity test with detailed metrics."""
        try:
            cmd = ['ping', '-c', str(count), '-W', str(timeout), target_ip]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            
            success = result.returncode == 0
            packets_sent = count
            packets_received = 0
            packet_loss = 100.0
            latencies = []
            
            if success and result.stdout:
                # Parse ping output
                lines = result.stdout.split('\n')
                
                # Extract latency values
                for line in lines:
                    if 'time=' in line:
                        match = re.search(r'time=([0-9.]+)', line)
                        if match:
                            latencies.append(float(match.group(1)))
                
                # Extract packet loss
                for line in lines:
                    if 'packet loss' in line:
                        match = re.search(r'(\d+)% packet loss', line)
                        if match:
                            packet_loss = float(match.group(1))
                            packets_received = int(count * (100 - packet_loss) / 100)
                            break
            
            return ConnectivityTest(
                source_ip="local",
                target_ip=target_ip,
                success=success,
                packet_loss=packet_loss,
                avg_latency=statistics.mean(latencies) if latencies else None,
                min_latency=min(latencies) if latencies else None,
                max_latency=max(latencies) if latencies else None,
                packets_sent=packets_sent,
                packets_received=packets_received
            )
            
        except subprocess.TimeoutExpired:
            return ConnectivityTest(
                source_ip="local",
                target_ip=target_ip,
                success=False,
                packet_loss=100.0,
                avg_latency=None,
                min_latency=None,
                max_latency=None,
                packets_sent=count,
                packets_received=0
            )
        except Exception as e:
            logger.error(f"Ping test error: {e}")
            return ConnectivityTest(
                source_ip="local",
                target_ip=target_ip,
                success=False,
                packet_loss=100.0,
                avg_latency=None,
                min_latency=None,
                max_latency=None,
                packets_sent=count,
                packets_received=0
            )
    
    def comprehensive_connectivity_test(self, test_targets: List[str]) -> Dict[str, ConnectivityTest]:
        """Run comprehensive connectivity tests against multiple targets."""
        results = {}
        
        for target in test_targets:
            logger.info(f"Testing connectivity to {target}")
            results[target] = self.ping_test(target)
            time.sleep(1)  # Small delay between tests
        
        return results
    
    def generate_test_report(self, connectivity_results: Dict[str, ConnectivityTest], 
                           port_results: List[PortApplication]) -> str:
        """Generate comprehensive test report."""
        report = "# Network Automation Test Report\n\n"
        
        # Port Profile Application Results
        report += "## Port Profile Application Results\n\n"
        successful_ports = sum(1 for r in port_results if r.success)
        total_ports = len(port_results)
        
        report += f"**Summary**: {successful_ports}/{total_ports} ports configured successfully\n\n"
        
        for result in port_results:
            status = "✅" if result.success else "❌"
            report += f"- {status} **{result.device_name}** Port {result.port_idx}: {result.message}\n"
        
        report += "\n"
        
        # Connectivity Test Results
        report += "## Connectivity Test Results\n\n"
        successful_tests = sum(1 for r in connectivity_results.values() if r.success)
        total_tests = len(connectivity_results)
        
        report += f"**Summary**: {successful_tests}/{total_tests} connectivity tests passed\n\n"
        
        for target, result in connectivity_results.items():
            status = "✅" if result.success else "❌"
            report += f"### {status} {target}\n"
            report += f"- **Success**: {result.success}\n"
            report += f"- **Packet Loss**: {result.packet_loss}%\n"
            
            if result.avg_latency:
                report += f"- **Average Latency**: {result.avg_latency:.2f}ms\n"
                report += f"- **Min/Max Latency**: {result.min_latency:.2f}ms / {result.max_latency:.2f}ms\n"
            
            report += f"- **Packets**: {result.packets_received}/{result.packets_sent}\n\n"
        
        # Overall Assessment
        report += "## Overall Assessment\n\n"
        
        if successful_ports == total_ports and successful_tests == total_tests:
            report += "🎉 **All tests passed!** Network automation completed successfully.\n"
        elif successful_ports == total_ports:
            report += "⚠️ **Port configuration successful, but connectivity issues remain.**\n"
        elif successful_tests == total_tests:
            report += "⚠️ **Connectivity working, but port configuration had issues.**\n"
        else:
            report += "❌ **Multiple issues detected.** Review individual test results.\n"
        
        return report
