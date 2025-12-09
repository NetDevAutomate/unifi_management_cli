#!/usr/bin/env python3
"""
Advanced Network Analysis Module for UniFi Port Mapper.
Provides comprehensive network health monitoring, topology analysis, and configuration comparison.
Implemented based on DeepSeek-R1 recommendations for enhanced network visibility.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .api_client import UnifiApiClient
from .models import (
    DeviceHealthMetrics,
    DeviceInfo,
    NetworkAnalysisResult,
    NetworkConfiguration,
    NetworkHealthStatus,
    NetworkTopologyChange,
    PortHealthMetrics,
)

log = logging.getLogger(__name__)


class NetworkAnalyzer:
    """Advanced network analysis and monitoring engine."""

    def __init__(self, api_client: UnifiApiClient):
        """Initialize network analyzer."""
        self.api_client = api_client
        self.configuration_history: List[NetworkConfiguration] = []
        self.analysis_cache: Dict[str, NetworkAnalysisResult] = {}
        self.baseline_config: Optional[NetworkConfiguration] = None

    def perform_comprehensive_analysis(
        self, devices: List[DeviceInfo]
    ) -> NetworkAnalysisResult:
        """
        Perform comprehensive network analysis including health monitoring,
        topology analysis, and configuration drift detection.

        Args:
            devices: List of discovered devices

        Returns:
            NetworkAnalysisResult: Complete analysis results
        """
        log.info("Starting comprehensive network analysis...")
        result = NetworkAnalysisResult()

        try:
            # Collect health metrics for all devices
            for device in devices:
                device_health = self._analyze_device_health(device)
                if device_health:
                    result.add_device_health(device_health)

            # Analyze topology changes
            current_topology = self._build_topology_snapshot(devices)
            if self.baseline_config:
                topology_changes = self._detect_topology_changes(current_topology)
                result.topology_changes.extend(topology_changes)
            else:
                # Set first topology as baseline
                self.baseline_config = current_topology
                log.info("Set baseline network configuration")

            # Detect configuration drift
            if len(self.configuration_history) > 0:
                drift_analysis = self._analyze_configuration_drift(current_topology)
                result.configuration_drift = drift_analysis

            # Store current configuration for future comparisons
            self.configuration_history.append(current_topology)

            # Keep only last 7 days of history
            cutoff = datetime.now() - timedelta(days=7)
            self.configuration_history = [
                config
                for config in self.configuration_history
                if config.timestamp > cutoff
            ]

            # Identify performance bottlenecks
            bottlenecks = self._identify_performance_bottlenecks(result.device_health)
            result.performance_bottlenecks.extend(bottlenecks)

            # Security analysis
            security_issues = self._analyze_security_posture(
                devices, result.device_health
            )
            result.security_issues.extend(security_issues)

            # Generate recommendations
            recommendations = self._generate_recommendations(result)
            result.recommendations.extend(recommendations)

            # Calculate summary statistics
            result.calculate_summary_stats()

            log.info(
                f"Analysis completed: {result.total_devices} devices analyzed, "
                f"overall health score: {result.overall_health_score:.1f}"
            )

            return result

        except Exception as e:
            log.error(f"Error during comprehensive analysis: {e}")
            return result

    def _analyze_device_health(
        self, device: DeviceInfo
    ) -> Optional[DeviceHealthMetrics]:
        """Analyze health metrics for a single device."""
        try:
            # Get detailed device information including system metrics
            device_details = self.api_client.get_device_details(
                self.api_client.site, device.id
            )
            if not device_details:
                log.debug(f"Could not get device details for {device.id}")
                return None

            health = DeviceHealthMetrics(device.id)

            # Extract system metrics if available
            system_stats = device_details.get("system-stats", {})
            if system_stats:
                health.cpu_usage_percent = system_stats.get("cpu", 0.0)
                health.memory_usage_percent = system_stats.get("mem", 0.0)
                health.temperature_celsius = system_stats.get("temps", {}).get(
                    "Board", 0.0
                )

            # Extract uptime
            health.uptime_seconds = device_details.get("uptime", 0)
            health.firmware_version = device_details.get("version", "unknown")
            health.last_seen = datetime.fromtimestamp(
                device_details.get("last_seen", 0)
            )

            # Analyze port health
            port_table = device_details.get("port_table", [])
            health.total_ports = len(port_table)

            for port_data in port_table:
                port_idx = port_data.get("port_idx")
                if port_idx is None:
                    continue

                port_metrics = self._analyze_port_health(device.id, port_idx, port_data)
                if port_metrics:
                    health.add_port_metrics(port_metrics)

                    # Count active and error ports
                    if port_data.get("up", False):
                        health.active_ports += 1

                    if (port_metrics.rx_errors + port_metrics.tx_errors) > 0:
                        health.error_ports += 1

            # Check for active alerts
            if "anomalies" in device_details:
                health.active_alerts = device_details["anomalies"]

            return health

        except Exception as e:
            log.debug(f"Error analyzing device health for {device.id}: {e}")
            return None

    def _analyze_port_health(
        self, device_id: str, port_idx: int, port_data: Dict[str, Any]
    ) -> Optional[PortHealthMetrics]:
        """Analyze health metrics for a single port."""
        try:
            metrics = PortHealthMetrics(port_idx, device_id)

            # Extract traffic statistics
            metrics.rx_bytes = port_data.get("rx_bytes", 0)
            metrics.tx_bytes = port_data.get("tx_bytes", 0)
            metrics.rx_packets = port_data.get("rx_packets", 0)
            metrics.tx_packets = port_data.get("tx_packets", 0)
            metrics.rx_errors = port_data.get("rx_errors", 0)
            metrics.tx_errors = port_data.get("tx_errors", 0)
            metrics.rx_dropped = port_data.get("rx_dropped", 0)
            metrics.tx_dropped = port_data.get("tx_dropped", 0)

            # Calculate utilization (simplified estimation)
            speed_bps = port_data.get("speed", 1000) * 1000000  # Convert Mbps to bps
            total_bytes = metrics.rx_bytes + metrics.tx_bytes

            if speed_bps > 0 and metrics.uptime_seconds > 0:
                # Rough utilization calculation
                max_theoretical_bytes = (speed_bps / 8) * metrics.uptime_seconds
                metrics.utilization_percent = min(
                    100.0, (total_bytes / max_theoretical_bytes) * 100
                )

            # Link stability indicators
            metrics.uptime_seconds = port_data.get("uptime", 0)
            if port_data.get("up", False):
                metrics.last_state_change = datetime.now() - timedelta(
                    seconds=metrics.uptime_seconds
                )

            # Estimate link flaps from uptime patterns (heuristic)
            if (
                metrics.uptime_seconds < 86400
            ):  # Less than 24 hours uptime suggests recent changes
                metrics.link_flap_count = 1

            return metrics

        except Exception as e:
            log.debug(
                f"Error analyzing port health for device {device_id}, port {port_idx}: {e}"
            )
            return None

    def _build_topology_snapshot(
        self, devices: List[DeviceInfo]
    ) -> NetworkConfiguration:
        """Build current network topology snapshot."""
        config = NetworkConfiguration()

        for device in devices:
            # Get device configuration
            device_details = self.api_client.get_device_details(
                self.api_client.site, device.id
            )
            if device_details:
                config.add_device_config(
                    device.id,
                    {
                        "name": device.name,
                        "model": device.model,
                        "version": device_details.get("version", ""),
                        "mac": device.mac,
                        "ip": device.ip,
                        "uptime": device_details.get("uptime", 0),
                        "port_count": len(device.ports),
                    },
                )

            # Add topology connections from LLDP/CDP data
            for port in device.ports:
                if port.has_lldp_info and port.connected_device_name:
                    # Find connected device
                    connected_device = None
                    for other_device in devices:
                        if other_device.name == port.connected_device_name:
                            connected_device = other_device
                            break

                    if connected_device:
                        # Find connected port
                        connected_port_idx = None
                        if port.connected_port_name:
                            for other_port in connected_device.ports:
                                if port.connected_port_name in other_port.name:
                                    connected_port_idx = other_port.idx
                                    break

                        if connected_port_idx:
                            config.add_connection(
                                device.id,
                                port.idx,
                                connected_device.id,
                                connected_port_idx,
                            )

        return config

    def _detect_topology_changes(
        self, current_config: NetworkConfiguration
    ) -> List[NetworkTopologyChange]:
        """Detect changes in network topology."""
        changes = []

        if not self.baseline_config:
            return changes

        # Compare with baseline configuration
        comparison = self.baseline_config.compare_with(current_config)

        # Convert comparison results to topology changes
        for device_info in comparison["devices_added"]:
            changes.append(
                NetworkTopologyChange(
                    "device_added",
                    device_info["device_id"],
                    {"device_config": device_info["config"]},
                )
            )

        for device_info in comparison["devices_removed"]:
            changes.append(
                NetworkTopologyChange(
                    "device_removed",
                    device_info["device_id"],
                    {"device_config": device_info["config"]},
                )
            )

        for conn_info in comparison["connections_added"]:
            changes.append(
                NetworkTopologyChange(
                    "port_connected",
                    conn_info["device1_id"],
                    {
                        "local_port": conn_info["port1"],
                        "remote_device": conn_info["device2_id"],
                        "remote_port": conn_info["port2"],
                    },
                )
            )

        for conn_info in comparison["connections_removed"]:
            changes.append(
                NetworkTopologyChange(
                    "port_disconnected",
                    conn_info["device1_id"],
                    {
                        "local_port": conn_info["port1"],
                        "remote_device": conn_info["device2_id"],
                        "remote_port": conn_info["port2"],
                    },
                )
            )

        return changes

    def _analyze_configuration_drift(
        self, current_config: NetworkConfiguration
    ) -> Dict[str, Any]:
        """Analyze configuration drift over time."""
        if len(self.configuration_history) < 2:
            return {}

        # Compare with configuration from 24 hours ago
        day_ago = datetime.now() - timedelta(hours=24)
        baseline = None

        for config in reversed(self.configuration_history):
            if config.timestamp <= day_ago:
                baseline = config
                break

        if not baseline:
            baseline = self.configuration_history[0]

        comparison = baseline.compare_with(current_config)

        # Calculate drift metrics
        drift_analysis = {
            "devices_changed": len(comparison["devices_added"])
            + len(comparison["devices_removed"]),
            "topology_changes": len(comparison["connections_added"])
            + len(comparison["connections_removed"]),
            "configuration_stability_score": self._calculate_stability_score(
                comparison
            ),
            "period_analyzed_hours": (
                current_config.timestamp - baseline.timestamp
            ).total_seconds()
            / 3600,
            "changes_detail": comparison,
        }

        return drift_analysis

    def _calculate_stability_score(self, comparison: Dict[str, List]) -> float:
        """Calculate configuration stability score (0-100)."""
        total_changes = sum(len(changes) for changes in comparison.values())

        if total_changes == 0:
            return 100.0

        # Penalize changes, but not too harshly for small networks
        penalty = min(50, total_changes * 5)
        return max(0, 100 - penalty)

    def _identify_performance_bottlenecks(
        self, device_health: Dict[str, DeviceHealthMetrics]
    ) -> List[Dict[str, Any]]:
        """Identify network performance bottlenecks."""
        bottlenecks = []

        for device_id, health in device_health.items():
            # High CPU usage
            if health.cpu_usage_percent > 80:
                bottlenecks.append(
                    {
                        "type": "high_cpu_usage",
                        "device_id": device_id,
                        "severity": "critical"
                        if health.cpu_usage_percent > 95
                        else "warning",
                        "description": f"Device {device_id} has high CPU usage: {health.cpu_usage_percent:.1f}%",
                        "metric_value": health.cpu_usage_percent,
                    }
                )

            # High memory usage
            if health.memory_usage_percent > 85:
                bottlenecks.append(
                    {
                        "type": "high_memory_usage",
                        "device_id": device_id,
                        "severity": "critical"
                        if health.memory_usage_percent > 95
                        else "warning",
                        "description": f"Device {device_id} has high memory usage: {health.memory_usage_percent:.1f}%",
                        "metric_value": health.memory_usage_percent,
                    }
                )

            # High temperature
            if health.temperature_celsius > 70:
                bottlenecks.append(
                    {
                        "type": "high_temperature",
                        "device_id": device_id,
                        "severity": "critical"
                        if health.temperature_celsius > 80
                        else "warning",
                        "description": f"Device {device_id} is running hot: {health.temperature_celsius:.1f}°C",
                        "metric_value": health.temperature_celsius,
                    }
                )

            # Port utilization issues
            for port_idx, port_metrics in health.port_metrics.items():
                if port_metrics.utilization_percent > 85:
                    bottlenecks.append(
                        {
                            "type": "high_port_utilization",
                            "device_id": device_id,
                            "port_idx": port_idx,
                            "severity": "critical"
                            if port_metrics.utilization_percent > 95
                            else "warning",
                            "description": f"Port {port_idx} on device {device_id} has high utilization: {port_metrics.utilization_percent:.1f}%",
                            "metric_value": port_metrics.utilization_percent,
                        }
                    )

                # Port errors
                if port_metrics.rx_errors + port_metrics.tx_errors > 1000:
                    bottlenecks.append(
                        {
                            "type": "port_errors",
                            "device_id": device_id,
                            "port_idx": port_idx,
                            "severity": "warning",
                            "description": f"Port {port_idx} on device {device_id} has high error count: {port_metrics.rx_errors + port_metrics.tx_errors}",
                            "metric_value": port_metrics.rx_errors
                            + port_metrics.tx_errors,
                        }
                    )

        return bottlenecks

    def _analyze_security_posture(
        self, devices: List[DeviceInfo], device_health: Dict[str, DeviceHealthMetrics]
    ) -> List[Dict[str, Any]]:
        """Analyze network security posture."""
        security_issues = []

        for device in devices:
            device_health_metrics = device_health.get(device.id)
            if not device_health_metrics:
                continue

            # Check firmware versions
            if device_health_metrics.firmware_version:
                # This is a simplified check - in reality, you'd compare against known vulnerability databases
                version = device_health_metrics.firmware_version
                if "6.0" in version or "6.1" in version:  # Example: older versions
                    security_issues.append(
                        {
                            "type": "outdated_firmware",
                            "device_id": device.id,
                            "severity": "warning",
                            "description": f"Device {device.id} may be running outdated firmware: {version}",
                            "recommendation": "Consider updating to the latest stable firmware version",
                        }
                    )

            # Check for devices with excessive uptime (might miss security updates)
            if device_health_metrics.uptime_seconds > 86400 * 90:  # 90 days
                uptime_days = device_health_metrics.uptime_seconds / 86400
                security_issues.append(
                    {
                        "type": "long_uptime",
                        "device_id": device.id,
                        "severity": "info",
                        "description": f"Device {device.id} has been running for {uptime_days:.0f} days without reboot",
                        "recommendation": "Consider scheduled maintenance window for updates and reboot",
                    }
                )

            # Check for devices not seen recently
            if device_health_metrics.last_seen:
                hours_since_seen = (
                    datetime.now() - device_health_metrics.last_seen
                ).total_seconds() / 3600
                if hours_since_seen > 24:
                    security_issues.append(
                        {
                            "type": "device_offline",
                            "device_id": device.id,
                            "severity": "critical"
                            if hours_since_seen > 72
                            else "warning",
                            "description": f"Device {device.id} not seen for {hours_since_seen:.1f} hours",
                            "recommendation": "Investigate device connectivity and health",
                        }
                    )

        return security_issues

    def _generate_recommendations(
        self, analysis_result: NetworkAnalysisResult
    ) -> List[Dict[str, Any]]:
        """Generate improvement recommendations based on analysis."""
        recommendations = []

        # Health-based recommendations
        critical_devices = [
            device_id
            for device_id, health in analysis_result.device_health.items()
            if health.get_health_status() == NetworkHealthStatus.CRITICAL
        ]

        if critical_devices:
            recommendations.append(
                {
                    "category": "health",
                    "priority": "high",
                    "description": f"Immediate attention required for {len(critical_devices)} critical devices",
                    "details": critical_devices,
                }
            )

        # Performance recommendations
        if analysis_result.performance_bottlenecks:
            high_priority_bottlenecks = [
                b
                for b in analysis_result.performance_bottlenecks
                if b.get("severity") == "critical"
            ]

            if high_priority_bottlenecks:
                recommendations.append(
                    {
                        "category": "performance",
                        "priority": "high",
                        "description": f"Address {len(high_priority_bottlenecks)} critical performance issues",
                        "details": [
                            b["description"] for b in high_priority_bottlenecks
                        ],
                    }
                )

        # Configuration drift recommendations
        if analysis_result.configuration_drift:
            stability_score = analysis_result.configuration_drift.get(
                "configuration_stability_score", 100
            )
            if stability_score < 75:
                recommendations.append(
                    {
                        "category": "configuration",
                        "priority": "medium",
                        "description": f"Network configuration shows instability (score: {stability_score:.0f}/100)",
                        "recommendation": "Review recent configuration changes and consider configuration backup",
                    }
                )

        # Security recommendations
        critical_security_issues = [
            issue
            for issue in analysis_result.security_issues
            if issue.get("severity") == "critical"
        ]

        if critical_security_issues:
            recommendations.append(
                {
                    "category": "security",
                    "priority": "high",
                    "description": f"Address {len(critical_security_issues)} critical security issues",
                    "details": [
                        issue["description"] for issue in critical_security_issues
                    ],
                }
            )

        # Overall health recommendations
        if analysis_result.overall_health_score < 70:
            recommendations.append(
                {
                    "category": "general",
                    "priority": "medium",
                    "description": f"Overall network health is below optimal (score: {analysis_result.overall_health_score:.0f}/100)",
                    "recommendation": "Consider comprehensive network audit and optimization",
                }
            )

        return recommendations

    def save_analysis_result(self, result: NetworkAnalysisResult, output_dir: Path):
        """Save analysis result to JSON file."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)

            # Convert result to serializable format
            serializable_result = {
                "timestamp": result.timestamp.isoformat(),
                "summary": {
                    "total_devices": result.total_devices,
                    "healthy_devices": result.healthy_devices,
                    "warning_devices": result.warning_devices,
                    "critical_devices": result.critical_devices,
                    "overall_health_score": result.overall_health_score,
                },
                "device_health": {
                    device_id: {
                        "health_score": health.calculate_overall_health_score(),
                        "health_status": health.get_health_status().value,
                        "cpu_usage": health.cpu_usage_percent,
                        "memory_usage": health.memory_usage_percent,
                        "temperature": health.temperature_celsius,
                        "critical_ports": health.get_critical_ports(),
                        "warning_ports": health.get_warning_ports(),
                        "active_alerts": len(health.active_alerts),
                    }
                    for device_id, health in result.device_health.items()
                },
                "topology_changes": [
                    {
                        "timestamp": change.timestamp.isoformat(),
                        "type": change.change_type,
                        "device_id": change.device_id,
                        "severity": change.severity,
                        "details": change.details,
                    }
                    for change in result.topology_changes
                ],
                "performance_bottlenecks": result.performance_bottlenecks,
                "security_issues": result.security_issues,
                "recommendations": result.recommendations,
                "configuration_drift": result.configuration_drift,
            }

            output_file = (
                output_dir
                / f"network_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

            with open(output_file, "w") as f:
                json.dump(serializable_result, f, indent=2, default=str)

            log.info(f"Analysis result saved to {output_file}")

        except Exception as e:
            log.error(f"Error saving analysis result: {e}")
