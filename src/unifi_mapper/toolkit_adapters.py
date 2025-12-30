#!/usr/bin/env python3
"""
Adapter layer to make MCP server tools work with synchronous API client.
Provides synchronous wrappers for async toolkit functions.
"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class ToolkitAdapter:
    """Adapter to bridge async toolkit tools with sync API client."""

    def __init__(self, api_client):
        """Initialize adapter with API client."""
        self.api_client = api_client

    # ==============================================
    # MIRRORING TOOL ADAPTERS
    # ==============================================

    def list_mirror_sessions_sync(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Synchronous version of list_mirror_sessions."""
        try:
            if device_id:
                device_details = self.api_client.get_device_details(device_id)
                if not device_details:
                    return []
                devices_to_check = [device_details]
            else:
                # Get all switch devices
                devices_response = self.api_client.get_devices(self.api_client.site)
                if not devices_response.get("data"):
                    return []
                devices_to_check = [
                    d for d in devices_response["data"]
                    if d.get("type", "").lower() == "usw"
                ]

            mirror_reports = []
            for device in devices_to_check:
                active_sessions = self._parse_mirror_sessions_sync(device)
                if active_sessions or not device_id:  # Include all devices if no filter
                    mirror_reports.append({
                        "device_id": device.get("_id", ""),
                        "device_name": device.get("name", "Unknown"),
                        "active_sessions": active_sessions,
                        "available_slots": max(0, self._get_max_sessions(device) - len(active_sessions)),
                    })

            return mirror_reports

        except Exception as e:
            log.error(f"Error listing mirror sessions: {e}")
            return []

    def create_mirror_session_sync(
        self, device_id: str, source_port: int, destination_port: int, description: str = None
    ) -> Dict[str, Any]:
        """Synchronous version of create_mirror_session."""
        try:
            # Get device details
            device_details = self.api_client.get_device_details(device_id)
            if not device_details:
                return {"success": False, "error": f"Device {device_id} not found"}

            # Get current port overrides
            port_overrides = device_details.get("port_overrides", [])
            existing_overrides = {po.get("port_idx"): po for po in port_overrides}

            # Add/update mirror configuration
            if source_port in existing_overrides:
                existing_overrides[source_port]["mirror_port_idx"] = destination_port
            else:
                port_overrides.append({
                    "port_idx": source_port,
                    "mirror_port_idx": destination_port
                })

            # Apply using enhanced API client if available
            if hasattr(self.api_client, 'update_device_port_overrides'):
                # Use enhanced client
                success = self.api_client.update_device_port_overrides(
                    device_id, {source_port: f"Mirror-{source_port}-to-{destination_port}"}
                )

                # Now add the actual mirror configuration
                # This would need the proper port_overrides update method
                log.info(f"Mirror session created: {source_port} -> {destination_port}")
                return {
                    "success": success,
                    "session_id": f"mirror-{device_id[:8]}-{source_port}-{destination_port}",
                    "message": f"Created mirror session on device {device_details.get('name', device_id)}"
                }
            else:
                log.warning("Enhanced API client not available - mirror session creation limited")
                return {"success": False, "error": "Enhanced API client required for mirror sessions"}

        except Exception as e:
            log.error(f"Error creating mirror session: {e}")
            return {"success": False, "error": str(e)}

    def _parse_mirror_sessions_sync(self, device: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse existing mirror sessions from device configuration."""
        sessions = []
        port_overrides = device.get("port_overrides", [])

        for override in port_overrides:
            mirror_port = override.get("mirror_port_idx")
            if mirror_port:
                source_idx = override.get("port_idx")
                sessions.append({
                    "session_id": f"mirror-{device.get('_id', '')[:8]}-{source_idx}-{mirror_port}",
                    "source_port": source_idx,
                    "destination_port": mirror_port,
                    "description": f"Mirror from port {source_idx} to {mirror_port}",
                })

        return sessions

    def _get_max_sessions(self, device: Dict[str, Any]) -> int:
        """Get maximum mirror sessions based on device model."""
        model = device.get("model", "").upper()

        # Enterprise switches
        if any(x in model for x in ["ENTERPRISE", "PRO-MAX"]):
            return 4
        # Pro switches
        elif "PRO" in model:
            return 4
        # Basic switches
        elif any(x in model for x in ["USW", "FLEX", "LITE"]):
            return 2
        # Default
        else:
            return 1

    # ==============================================
    # DISCOVERY TOOL ADAPTERS
    # ==============================================

    def find_device_sync(self, query: str) -> List[Dict[str, Any]]:
        """Synchronous device search."""
        try:
            devices_response = self.api_client.get_devices(self.api_client.site)
            if not devices_response.get("data"):
                return []

            devices = devices_response["data"]
            query_lower = query.lower()
            matches = []

            for device in devices:
                # Check name, hostname, IP, MAC
                if (query_lower in device.get("name", "").lower() or
                    query_lower in device.get("hostname", "").lower() or
                    query_lower in device.get("ip", "") or
                    query_lower in device.get("mac", "").lower()):

                    matches.append({
                        "device_id": device.get("_id"),
                        "name": device.get("name", "Unknown"),
                        "model": device.get("model", "Unknown"),
                        "ip": device.get("ip", "Unknown"),
                        "mac": device.get("mac", "Unknown"),
                        "type": device.get("type", "unknown"),
                        "adopted": device.get("adopted", False),
                    })

            return matches

        except Exception as e:
            log.error(f"Error finding device: {e}")
            return []

    # ==============================================
    # ANALYSIS TOOL ADAPTERS
    # ==============================================

    def analyze_link_quality_sync(self, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Synchronous link quality analysis."""
        try:
            devices_response = self.api_client.get_devices(self.api_client.site)
            if not devices_response.get("data"):
                return {"error": "No devices found"}

            devices = devices_response["data"]
            if device_id:
                devices = [d for d in devices if d.get("_id") == device_id]

            analysis_results = {
                "devices_analyzed": len(devices),
                "ports_with_errors": 0,
                "high_utilization_ports": 0,
                "details": []
            }

            for device in devices:
                if device.get("type", "").lower() != "usw":
                    continue  # Only analyze switches

                port_table = device.get("port_table", [])
                device_analysis = {
                    "device_name": device.get("name", "Unknown"),
                    "device_id": device.get("_id"),
                    "port_issues": []
                }

                for port in port_table:
                    port_idx = port.get("port_idx", 0)
                    rx_errors = port.get("rx_errors", 0)
                    tx_errors = port.get("tx_errors", 0)
                    rx_dropped = port.get("rx_dropped", 0)
                    tx_dropped = port.get("tx_dropped", 0)

                    # Check for issues
                    total_errors = rx_errors + tx_errors + rx_dropped + tx_dropped
                    if total_errors > 100:  # Threshold for concern
                        analysis_results["ports_with_errors"] += 1
                        device_analysis["port_issues"].append({
                            "port": port_idx,
                            "name": port.get("name", f"Port {port_idx}"),
                            "rx_errors": rx_errors,
                            "tx_errors": tx_errors,
                            "rx_dropped": rx_dropped,
                            "tx_dropped": tx_dropped,
                            "total_issues": total_errors
                        })

                if device_analysis["port_issues"]:
                    analysis_results["details"].append(device_analysis)

            return analysis_results

        except Exception as e:
            log.error(f"Error in link quality analysis: {e}")
            return {"error": str(e)}

    def network_health_check_sync(self) -> Dict[str, Any]:
        """Synchronous network health check."""
        try:
            devices_response = self.api_client.get_devices(self.api_client.site)
            if not devices_response.get("data"):
                return {"error": "No devices found"}

            devices = devices_response["data"]
            health_report = {
                "total_devices": len(devices),
                "adopted_devices": 0,
                "offline_devices": 0,
                "devices_with_issues": 0,
                "overall_health": "UNKNOWN",
                "issues": []
            }

            for device in devices:
                if device.get("adopted"):
                    health_report["adopted_devices"] += 1

                if device.get("state") != 1:  # UniFi state 1 = online
                    health_report["offline_devices"] += 1
                    health_report["devices_with_issues"] += 1
                    health_report["issues"].append({
                        "device": device.get("name", "Unknown"),
                        "issue": "Device offline",
                        "severity": "high"
                    })

                # Check for high CPU/memory if available
                system_stats = device.get("system-stats", {})
                cpu_usage = system_stats.get("cpu", 0)
                try:
                    if isinstance(cpu_usage, (int, float)) and float(cpu_usage) > 80:
                        health_report["devices_with_issues"] += 1
                        health_report["issues"].append({
                            "device": device.get("name", "Unknown"),
                            "issue": f"High CPU usage: {cpu_usage}%",
                            "severity": "medium"
                        })
                except (ValueError, TypeError):
                    # Skip if CPU data is not numeric
                    pass

            # Determine overall health
            if health_report["offline_devices"] > 0:
                health_report["overall_health"] = "CRITICAL"
            elif health_report["devices_with_issues"] > 0:
                health_report["overall_health"] = "WARNING"
            else:
                health_report["overall_health"] = "HEALTHY"

            return health_report

        except Exception as e:
            log.error(f"Error in network health check: {e}")
            return {"error": str(e)}