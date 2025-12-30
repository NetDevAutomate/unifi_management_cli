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

    def _resolve_device_name_to_id(self, device_name_or_id: str) -> str:
        """
        Resolve device name to device ID.

        Args:
            device_name_or_id: Either a device name or device ID

        Returns:
            Device ID if found, None if not found
        """
        try:
            # Get all devices
            devices_response = self.api_client.get_devices(self.api_client.site)
            if not devices_response.get("data"):
                return None

            devices = devices_response["data"]

            # First try exact ID match (if already an ID)
            for device in devices:
                if device.get("_id") == device_name_or_id:
                    return device_name_or_id

            # Then try name matching (case insensitive, partial match)
            device_name_lower = device_name_or_id.lower()
            for device in devices:
                device_name = device.get("name", "").lower()
                if device_name == device_name_lower:
                    return device.get("_id")

            # Try partial name matching
            for device in devices:
                device_name = device.get("name", "").lower()
                if device_name_lower in device_name or device_name in device_name_lower:
                    return device.get("_id")

            # Try MAC address matching
            for device in devices:
                if device.get("mac", "").lower() == device_name_or_id.lower():
                    return device.get("_id")

            # Try IP address matching
            for device in devices:
                if device.get("ip", "") == device_name_or_id:
                    return device.get("_id")

            log.error(f"Could not find device matching '{device_name_or_id}'")
            return None

        except Exception as e:
            log.error(f"Error resolving device name: {e}")
            return None