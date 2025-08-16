#!/usr/bin/env python3
"""
Models for the UniFi Port Mapper.
Contains data classes for port and device information.
"""

from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from enum import Enum
import statistics


class PortInfo:
    """Data class to store port information."""
    
    def __init__(self, idx: int, name: str, media: str = "RJ45", 
                 is_uplink: bool = False, up: bool = True, enabled: bool = True,
                 speed: int = 1000, full_duplex: bool = True, has_lldp_info: bool = False,
                 lldp_info: Dict[str, Any] = None, connected_device_name: Optional[str] = None,
                 connected_port_name: Optional[str] = None, poe: bool = False):
        """
        Initialize a PortInfo object.
        
        Args:
            idx: Port index
            name: Port name
            media: Port media type (e.g., RJ45, SFP+)
            is_uplink: Whether this is an uplink port
            up: Whether the port is up
            enabled: Whether the port is enabled
            speed: Port speed in Mbps
            full_duplex: Whether the port is full duplex
            has_lldp_info: Whether the port has LLDP/CDP information
            lldp_info: LLDP/CDP information
            connected_device_name: Name of the connected device
            connected_port_name: Name of the connected port
        """
        self.id = f"port_{idx}"
        self.name = name
        self.idx = idx
        self.media = media
        self.is_uplink = is_uplink
        self.up = up
        self.enabled = enabled
        self.speed = speed
        self.full_duplex = full_duplex
        self.has_lldp_info = has_lldp_info or (lldp_info is not None and len(lldp_info) > 0)
        self.lldp_info = lldp_info or {}
        self.modified = False
        self.new_name = ""
        self.connected_device_id = None
        self.connected_port_id = None
        self.proposed_name = ""
        self.connected_device_name = connected_device_name
        self.connected_port_name = connected_port_name
        self.poe = poe

    def get_display_name(self) -> str:
        """
        Get a display name for the port that includes media type and speed.
        """
        speed_str = f"{self.speed/1000}G" if self.speed >= 1000 else f"{self.speed}M"
        return f"{self.name} ({self.media} {speed_str})"

    def get_lldp_display_name(self) -> str:
        """
        Get a display name based on LLDP/CDP information.
        """
        if not self.has_lldp_info:
            return self.name
        
        chassis_name = self.lldp_info.get('chassis_name', '')
        port_id = self.lldp_info.get('port_id', '')
        
        if chassis_name and port_id:
            return f"{chassis_name} ({port_id})"
        elif chassis_name:
            return chassis_name
        elif port_id:
            return port_id
        else:
            return self.name

    def update_lldp_info(self, lldp_info: Dict[str, Any]) -> None:
        """
        Update LLDP/CDP information for the port and set proposed name.
        
        Args:
            lldp_info: LLDP/CDP information
        """
        if not lldp_info:
            return
        
        self.lldp_info = lldp_info
        self.has_lldp_info = True
        
        # Set proposed name based on LLDP/CDP information
        chassis_name = lldp_info.get('chassis_name', '')
        port_id = lldp_info.get('port_id', '')
        
        if chassis_name and port_id:
            self.proposed_name = f"{chassis_name} ({port_id})"
        elif chassis_name:
            self.proposed_name = chassis_name
        elif port_id:
            self.proposed_name = port_id


class DeviceInfo:
    """Data class to store device information."""
    
    def __init__(self, id: str, name: str, model: str, ip: str, mac: str, ports: List[PortInfo] = None, device_type: str = None, lldp_info: Dict[str, Any] = None):
        """
        Initialize a DeviceInfo object.
        
        Args:
            id: Device ID
            name: Device name
            model: Device model
            ip: Device IP address
            mac: Device MAC address
            ports: List of ports
            device_type: Device type (router, switch, ap, or unknown)
            lldp_info: LLDP/CDP information
        """
        self.id = id
        self.name = name
        self.model = model
        self.ip = ip
        self.mac = mac
        self.ports = ports or []
        self.device_type = device_type if device_type else self.get_device_type()
        self.lldp_info = lldp_info or {}

    def get_device_type(self) -> str:
        """
        Determine the device type based on the model name.
        
        Returns:
            str: Device type
        """
        model_lower = self.model.lower()
        
        if 'udm' in model_lower or 'usg' in model_lower or 'ugw' in model_lower or 'gateway' in model_lower or 'router' in model_lower:
            return "router"
        elif 'usw' in model_lower or 'switch' in model_lower:
            return "switch"
        elif 'uap' in model_lower or 'ap' in model_lower or 'access point' in model_lower or 'u6' in model_lower or 'u7' in model_lower or 'ac' in model_lower or 'nanostation' in model_lower or 'litebeam' in model_lower:
            return "ap"
        elif 'server' in model_lower or 'nas' in model_lower:
            return "server"
        else:
            return "other"

    def get_color(self) -> str:
        """
        Get a color for the device based on its type.
        
        Returns:
            str: Color in hex format
        """
        if self.device_type == "router":
            return "#3498db"  # Blue
        elif self.device_type == "switch":
            return "#2ecc71"  # Green
        elif self.device_type == "ap":
            return "#e74c3c"  # Red
        elif self.device_type == "server":
            return "#9b59b6"  # Purple
        else:
            return "#95a5a6"  # Gray


class NetworkHealthStatus(Enum):
    """Enum for network health status levels."""
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class PortHealthMetrics:
    """Advanced health metrics for network ports."""
    
    def __init__(self, port_idx: int, device_id: str):
        """Initialize port health metrics."""
        self.port_idx = port_idx
        self.device_id = device_id
        self.timestamp = datetime.now()
        
        # Traffic metrics
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.rx_packets = 0
        self.tx_packets = 0
        self.rx_errors = 0
        self.tx_errors = 0
        self.rx_dropped = 0
        self.tx_dropped = 0
        
        # Performance metrics
        self.utilization_percent = 0.0
        self.latency_ms = 0.0
        self.jitter_ms = 0.0
        self.packet_loss_percent = 0.0
        
        # Link stability
        self.link_flap_count = 0
        self.uptime_seconds = 0
        self.last_state_change = None
        
        # Historical data (last 24 hours)
        self.utilization_history: List[Tuple[datetime, float]] = []
        self.error_history: List[Tuple[datetime, int]] = []
        
    def calculate_health_score(self) -> float:
        """Calculate overall health score (0-100)."""
        scores = []
        
        # Utilization score (healthy below 80%)
        if self.utilization_percent <= 50:
            scores.append(100)
        elif self.utilization_percent <= 80:
            scores.append(80 - (self.utilization_percent - 50))
        else:
            scores.append(max(0, 60 - (self.utilization_percent - 80) * 2))
            
        # Error rate score
        total_packets = self.rx_packets + self.tx_packets
        if total_packets > 0:
            error_rate = (self.rx_errors + self.tx_errors) / total_packets
            error_score = max(0, 100 - error_rate * 10000)  # Heavily penalize errors
            scores.append(error_score)
        else:
            scores.append(100)
            
        # Link stability score
        if self.link_flap_count == 0:
            scores.append(100)
        elif self.link_flap_count <= 5:
            scores.append(80)
        else:
            scores.append(max(0, 60 - (self.link_flap_count - 5) * 5))
            
        return sum(scores) / len(scores) if scores else 0.0
        
    def get_health_status(self) -> NetworkHealthStatus:
        """Get health status based on score."""
        score = self.calculate_health_score()
        
        if score >= 90:
            return NetworkHealthStatus.EXCELLENT
        elif score >= 75:
            return NetworkHealthStatus.GOOD
        elif score >= 50:
            return NetworkHealthStatus.WARNING
        else:
            return NetworkHealthStatus.CRITICAL
            
    def add_utilization_sample(self, utilization: float):
        """Add utilization sample to history."""
        now = datetime.now()
        self.utilization_history.append((now, utilization))
        
        # Keep only last 24 hours
        cutoff = now - timedelta(hours=24)
        self.utilization_history = [
            (ts, util) for ts, util in self.utilization_history 
            if ts > cutoff
        ]
        
    def get_peak_utilization(self) -> float:
        """Get peak utilization in the last 24 hours."""
        if not self.utilization_history:
            return self.utilization_percent
            
        return max(util for _, util in self.utilization_history)
        
    def get_average_utilization(self) -> float:
        """Get average utilization in the last 24 hours."""
        if not self.utilization_history:
            return self.utilization_percent
            
        return statistics.mean(util for _, util in self.utilization_history)


class DeviceHealthMetrics:
    """Advanced health metrics for network devices."""
    
    def __init__(self, device_id: str):
        """Initialize device health metrics."""
        self.device_id = device_id
        self.timestamp = datetime.now()
        
        # System metrics
        self.cpu_usage_percent = 0.0
        self.memory_usage_percent = 0.0
        self.temperature_celsius = 0.0
        self.uptime_seconds = 0
        
        # Network metrics
        self.total_ports = 0
        self.active_ports = 0
        self.error_ports = 0
        self.port_metrics: Dict[int, PortHealthMetrics] = {}
        
        # Device-specific metrics
        self.firmware_version = ""
        self.config_version = 0
        self.last_seen = datetime.now()
        self.reboot_count = 0
        
        # Alerts and issues
        self.active_alerts: List[Dict[str, Any]] = []
        self.resolved_alerts_24h = 0
        
    def add_port_metrics(self, port_metrics: PortHealthMetrics):
        """Add port metrics."""
        self.port_metrics[port_metrics.port_idx] = port_metrics
        
    def calculate_overall_health_score(self) -> float:
        """Calculate overall device health score."""
        scores = []
        
        # System health
        cpu_score = max(0, 100 - self.cpu_usage_percent)
        memory_score = max(0, 100 - self.memory_usage_percent)
        scores.extend([cpu_score, memory_score])
        
        # Temperature score (assuming 70C is warning threshold)
        if self.temperature_celsius <= 50:
            temp_score = 100
        elif self.temperature_celsius <= 70:
            temp_score = 100 - (self.temperature_celsius - 50) * 2
        else:
            temp_score = max(0, 60 - (self.temperature_celsius - 70) * 3)
        scores.append(temp_score)
        
        # Port health average
        if self.port_metrics:
            port_scores = [metrics.calculate_health_score() for metrics in self.port_metrics.values()]
            avg_port_score = sum(port_scores) / len(port_scores)
            scores.append(avg_port_score)
            
        # Alert penalty
        alert_penalty = min(50, len(self.active_alerts) * 10)
        
        base_score = sum(scores) / len(scores) if scores else 100
        return max(0, base_score - alert_penalty)
        
    def get_health_status(self) -> NetworkHealthStatus:
        """Get overall device health status."""
        score = self.calculate_overall_health_score()
        
        if score >= 90:
            return NetworkHealthStatus.EXCELLENT
        elif score >= 75:
            return NetworkHealthStatus.GOOD
        elif score >= 50:
            return NetworkHealthStatus.WARNING
        else:
            return NetworkHealthStatus.CRITICAL
            
    def get_critical_ports(self) -> List[int]:
        """Get list of ports with critical health status."""
        return [
            port_idx for port_idx, metrics in self.port_metrics.items()
            if metrics.get_health_status() == NetworkHealthStatus.CRITICAL
        ]
        
    def get_warning_ports(self) -> List[int]:
        """Get list of ports with warning health status."""
        return [
            port_idx for port_idx, metrics in self.port_metrics.items()
            if metrics.get_health_status() == NetworkHealthStatus.WARNING
        ]


class NetworkTopologyChange:
    """Track changes in network topology."""
    
    def __init__(self, change_type: str, device_id: str, details: Dict[str, Any]):
        """Initialize topology change record."""
        self.timestamp = datetime.now()
        self.change_type = change_type  # 'device_added', 'device_removed', 'port_connected', 'port_disconnected'
        self.device_id = device_id
        self.details = details
        self.severity = self._calculate_severity()
        
    def _calculate_severity(self) -> str:
        """Calculate change severity."""
        if self.change_type in ['device_removed', 'critical_port_down']:
            return 'critical'
        elif self.change_type in ['device_added', 'port_disconnected']:
            return 'warning'
        else:
            return 'info'


class NetworkConfiguration:
    """Store network configuration snapshots for comparison."""
    
    def __init__(self, timestamp: datetime = None):
        """Initialize network configuration snapshot."""
        self.timestamp = timestamp or datetime.now()
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.topology_connections: List[Tuple[str, int, str, int]] = []  # (device1, port1, device2, port2)
        self.vlans: Dict[int, Dict[str, Any]] = {}
        self.port_profiles: Dict[str, Dict[str, Any]] = {}
        self.network_settings: Dict[str, Any] = {}
        
    def add_device_config(self, device_id: str, config: Dict[str, Any]):
        """Add device configuration."""
        self.devices[device_id] = config
        
    def add_connection(self, device1_id: str, port1: int, device2_id: str, port2: int):
        """Add topology connection."""
        self.topology_connections.append((device1_id, port1, device2_id, port2))
        
    def compare_with(self, other: 'NetworkConfiguration') -> Dict[str, List[Dict[str, Any]]]:
        """Compare with another configuration snapshot."""
        changes = {
            'devices_added': [],
            'devices_removed': [],
            'devices_modified': [],
            'connections_added': [],
            'connections_removed': [],
            'vlans_changed': [],
            'port_profiles_changed': []
        }
        
        # Compare devices
        current_devices = set(self.devices.keys())
        other_devices = set(other.devices.keys())
        
        for device_id in other_devices - current_devices:
            changes['devices_added'].append({
                'device_id': device_id,
                'config': other.devices[device_id]
            })
            
        for device_id in current_devices - other_devices:
            changes['devices_removed'].append({
                'device_id': device_id,
                'config': self.devices[device_id]
            })
            
        for device_id in current_devices & other_devices:
            if self.devices[device_id] != other.devices[device_id]:
                changes['devices_modified'].append({
                    'device_id': device_id,
                    'old_config': self.devices[device_id],
                    'new_config': other.devices[device_id]
                })
                
        # Compare connections
        current_connections = set(self.topology_connections)
        other_connections = set(other.topology_connections)
        
        for conn in other_connections - current_connections:
            changes['connections_added'].append({
                'device1_id': conn[0],
                'port1': conn[1],
                'device2_id': conn[2], 
                'port2': conn[3]
            })
            
        for conn in current_connections - other_connections:
            changes['connections_removed'].append({
                'device1_id': conn[0],
                'port1': conn[1],
                'device2_id': conn[2],
                'port2': conn[3]
            })
            
        return changes


class NetworkAnalysisResult:
    """Comprehensive network analysis results."""
    
    def __init__(self):
        """Initialize analysis result."""
        self.timestamp = datetime.now()
        self.device_health: Dict[str, DeviceHealthMetrics] = {}
        self.topology_changes: List[NetworkTopologyChange] = []
        self.configuration_drift: Dict[str, Any] = {}
        self.security_issues: List[Dict[str, Any]] = []
        self.performance_bottlenecks: List[Dict[str, Any]] = []
        self.recommendations: List[Dict[str, Any]] = []
        
        # Summary statistics
        self.total_devices = 0
        self.healthy_devices = 0
        self.warning_devices = 0
        self.critical_devices = 0
        self.overall_health_score = 0.0
        
    def add_device_health(self, device_health: DeviceHealthMetrics):
        """Add device health metrics."""
        self.device_health[device_health.device_id] = device_health
        
    def calculate_summary_stats(self):
        """Calculate summary statistics."""
        self.total_devices = len(self.device_health)
        
        if not self.device_health:
            return
            
        health_scores = []
        for device_health in self.device_health.values():
            score = device_health.calculate_overall_health_score()
            health_scores.append(score)
            
            status = device_health.get_health_status()
            if status == NetworkHealthStatus.EXCELLENT or status == NetworkHealthStatus.GOOD:
                self.healthy_devices += 1
            elif status == NetworkHealthStatus.WARNING:
                self.warning_devices += 1
            elif status == NetworkHealthStatus.CRITICAL:
                self.critical_devices += 1
                
        self.overall_health_score = statistics.mean(health_scores)
        
    def add_recommendation(self, category: str, priority: str, description: str, 
                         device_id: str = None, port_idx: int = None):
        """Add improvement recommendation."""
        self.recommendations.append({
            'category': category,
            'priority': priority,
            'description': description,
            'device_id': device_id,
            'port_idx': port_idx,
            'timestamp': datetime.now()
        })
        
    def get_critical_issues(self) -> List[Dict[str, Any]]:
        """Get all critical issues requiring immediate attention."""
        issues = []
        
        # Critical device health
        for device_id, health in self.device_health.items():
            if health.get_health_status() == NetworkHealthStatus.CRITICAL:
                issues.append({
                    'type': 'device_critical',
                    'device_id': device_id,
                    'description': f"Device {device_id} has critical health issues",
                    'score': health.calculate_overall_health_score()
                })
                
        # Security issues
        for issue in self.security_issues:
            if issue.get('severity') == 'critical':
                issues.append(issue)
                
        return issues
