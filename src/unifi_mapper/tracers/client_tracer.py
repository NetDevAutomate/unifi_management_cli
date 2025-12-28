#!/usr/bin/env python3
"""
Client Path Tracer for UniFi Networks.

Provides end-to-end path tracing for network clients:
- Trace client MAC through switch fabric (port-by-port path)
- Identify all intermediate devices between client and gateway
- VLAN path verification (ensure correct tagging throughout)
- Identify asymmetric routing paths
- Path latency estimation
- Troubleshoot connectivity issues
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class PathStatus(Enum):
    """Path health status."""

    COMPLETE = "complete"  # Full path traced successfully
    PARTIAL = "partial"  # Path traced but incomplete
    BROKEN = "broken"  # Path has issues
    UNKNOWN = "unknown"  # Could not determine path


class HopType(Enum):
    """Type of network hop."""

    CLIENT = "client"  # Source client
    ACCESS_SWITCH = "access_switch"
    DISTRIBUTION_SWITCH = "distribution_switch"
    CORE_SWITCH = "core_switch"
    ROUTER = "router"
    GATEWAY = "gateway"
    ACCESS_POINT = "access_point"
    UNKNOWN = "unknown"


@dataclass
class PathHop:
    """Represents a single hop in the network path."""

    hop_number: int
    device_id: str
    device_name: str
    device_type: HopType
    device_model: str = ""
    device_ip: str = ""

    # Ingress (where traffic enters)
    ingress_port: Optional[int] = None
    ingress_port_name: str = ""
    ingress_vlan: Optional[int] = None

    # Egress (where traffic exits)
    egress_port: Optional[int] = None
    egress_port_name: str = ""
    egress_vlan: Optional[int] = None

    # Connection details
    connected_via: str = ""  # LLDP, MAC table, etc.
    link_speed_mbps: int = 0

    # Issues detected at this hop
    issues: List[str] = field(default_factory=list)

    # Latency estimation (if available)
    estimated_latency_ms: float = 0.0

    @property
    def has_vlan_mismatch(self) -> bool:
        """Check for VLAN tagging mismatch between ingress and egress."""
        if self.ingress_vlan and self.egress_vlan:
            return self.ingress_vlan != self.egress_vlan
        return False

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0


@dataclass
class ClientPath:
    """Complete path from client to destination."""

    client_mac: str
    client_ip: str = ""
    client_hostname: str = ""
    destination: str = ""  # Gateway, server, etc.

    # Path details
    hops: List[PathHop] = field(default_factory=list)
    total_hops: int = 0
    path_status: PathStatus = PathStatus.UNKNOWN

    # VLAN information
    client_vlan: Optional[int] = None
    vlan_consistent: bool = True
    vlans_traversed: Set[int] = field(default_factory=set)

    # Path metrics
    total_estimated_latency_ms: float = 0.0
    path_bandwidth_mbps: int = 0  # Minimum link speed in path

    # Issues
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Timestamps
    trace_time: datetime = field(default_factory=datetime.now)

    def add_hop(self, hop: PathHop) -> None:
        """Add a hop to the path."""
        self.hops.append(hop)
        self.total_hops = len(self.hops)
        self.total_estimated_latency_ms += hop.estimated_latency_ms

        # Update minimum bandwidth
        if hop.link_speed_mbps > 0:
            if self.path_bandwidth_mbps == 0:
                self.path_bandwidth_mbps = hop.link_speed_mbps
            else:
                self.path_bandwidth_mbps = min(
                    self.path_bandwidth_mbps, hop.link_speed_mbps
                )

        # Track VLANs
        if hop.ingress_vlan:
            self.vlans_traversed.add(hop.ingress_vlan)
        if hop.egress_vlan:
            self.vlans_traversed.add(hop.egress_vlan)

        # Check VLAN consistency
        if len(self.vlans_traversed) > 1 and self.client_vlan:
            if hop.egress_vlan and hop.egress_vlan != self.client_vlan:
                self.vlan_consistent = False

        # Inherit hop issues
        self.issues.extend(hop.issues)

    def get_path_string(self) -> str:
        """Get a simple string representation of the path."""
        if not self.hops:
            return "No path found"

        path_parts = []
        for hop in self.hops:
            port_info = ""
            if hop.egress_port:
                port_info = f":{hop.egress_port}"
            path_parts.append(f"{hop.device_name}{port_info}")

        return " → ".join(path_parts)


@dataclass
class PathTraceResult:
    """Complete path trace results."""

    timestamp: datetime = field(default_factory=datetime.now)
    query_mac: str = ""
    query_ip: str = ""

    # Traced paths
    paths: List[ClientPath] = field(default_factory=list)

    # Client information
    client_found: bool = False
    client_device: str = ""
    client_port: int = 0
    client_vlan: Optional[int] = None

    # Analysis
    path_complete: bool = False
    issues: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def add_issue(
        self,
        severity: str,
        message: str,
        location: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add an issue to the trace result."""
        self.issues.append({
            "severity": severity,
            "message": message,
            "location": location,
            "details": details or {},
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self) -> Dict[str, Any]:
        """Get summary of trace results."""
        primary_path = self.paths[0] if self.paths else None
        return {
            "timestamp": self.timestamp.isoformat(),
            "client_mac": self.query_mac,
            "client_ip": self.query_ip,
            "client_found": self.client_found,
            "path_complete": self.path_complete,
            "total_hops": primary_path.total_hops if primary_path else 0,
            "path_status": primary_path.path_status.value if primary_path else "unknown",
            "vlans_traversed": list(primary_path.vlans_traversed) if primary_path else [],
            "estimated_latency_ms": primary_path.total_estimated_latency_ms if primary_path else 0,
            "min_bandwidth_mbps": primary_path.path_bandwidth_mbps if primary_path else 0,
            "issues_count": len(self.issues),
        }


class ClientPathTracer:
    """
    End-to-end client path tracer for UniFi networks.

    Traces the network path from a client device through all intermediate
    switches to the gateway/router, identifying potential issues along the way.
    """

    # Latency estimates per device type (ms)
    LATENCY_ESTIMATES = {
        HopType.ACCESS_SWITCH: 0.1,
        HopType.DISTRIBUTION_SWITCH: 0.15,
        HopType.CORE_SWITCH: 0.1,
        HopType.ROUTER: 0.5,
        HopType.GATEWAY: 0.5,
        HopType.ACCESS_POINT: 2.0,  # Wireless adds latency
    }

    def __init__(self, api_client, site: str = "default"):
        """Initialize Client Path Tracer."""
        self.api_client = api_client
        self.site = site

        # Caches
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._client_cache: Dict[str, Dict[str, Any]] = {}
        self._mac_table_cache: Dict[str, Dict[str, Tuple[str, int]]] = {}  # mac -> (device_id, port)
        self._lldp_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}  # device_id -> port -> lldp_info
        self._topology_cache: Dict[str, List[Tuple[str, int]]] = {}  # device_id -> [(connected_device, port)]

    def _load_caches(self) -> None:
        """Load all necessary caches for path tracing."""
        logger.info("Loading network topology caches...")

        # Get all devices
        try:
            result = self.api_client.get_devices(self.site)
            if result and "data" in result:
                for device in result["data"]:
                    self._device_cache[device["_id"]] = device

                    # Cache LLDP info
                    device_id = device["_id"]
                    lldp_table = device.get("lldp_table", [])
                    self._lldp_cache[device_id] = {}
                    for entry in lldp_table:
                        port_idx = entry.get("port_idx", entry.get("local_port_idx"))
                        if port_idx is not None:
                            self._lldp_cache[device_id][port_idx] = entry

                    # Build topology from port table
                    self._topology_cache[device_id] = []
                    port_table = device.get("port_table", [])
                    for port in port_table:
                        if port.get("is_uplink"):
                            # Find connected device via LLDP
                            port_idx = port.get("port_idx")
                            if port_idx in self._lldp_cache.get(device_id, {}):
                                lldp = self._lldp_cache[device_id][port_idx]
                                chassis_id = lldp.get("chassis_id", "")
                                # Find device by MAC
                                for other_id, other_dev in self._device_cache.items():
                                    if other_dev.get("mac", "").lower() == chassis_id.lower():
                                        self._topology_cache[device_id].append((other_id, port_idx))
                                        break
        except Exception as e:
            logger.error(f"Failed to load device cache: {e}")

        # Get all clients
        try:
            if self.api_client.is_unifi_os:
                endpoint = f"{self.api_client.base_url}/proxy/network/api/s/{self.site}/stat/sta"
            else:
                endpoint = f"{self.api_client.base_url}/api/s/{self.site}/stat/sta"

            def _fetch():
                return self.api_client.session.get(endpoint, timeout=self.api_client.timeout)

            response = self.api_client._retry_request(_fetch)

            if response and response.status_code == 200:
                data = response.json()
                for client in data.get("data", []):
                    mac = client.get("mac", "").upper().replace("-", ":")
                    if mac:
                        self._client_cache[mac] = client

                        # Also cache by IP
                        ip = client.get("ip")
                        if ip:
                            self._client_cache[ip] = client
        except Exception as e:
            logger.error(f"Failed to load client cache: {e}")

        logger.info(
            f"Caches loaded: {len(self._device_cache)} devices, "
            f"{len(self._client_cache)} clients"
        )

    def _get_device_type(self, device: Dict[str, Any]) -> HopType:
        """Determine the device type for path classification."""
        device_type = device.get("type", "")
        model = device.get("model", "").lower()
        name = device.get("name", "").lower()

        if device_type in ["udm", "ugw", "uxg"]:
            return HopType.GATEWAY
        elif device_type in ["uap", "u6", "u7"]:
            return HopType.ACCESS_POINT
        elif device_type == "usw":
            # Classify switch type based on model/name
            if "core" in name or "agg" in name:
                return HopType.CORE_SWITCH
            elif "dist" in name:
                return HopType.DISTRIBUTION_SWITCH
            elif "pro" in model or "enterprise" in model:
                return HopType.DISTRIBUTION_SWITCH
            else:
                return HopType.ACCESS_SWITCH
        return HopType.UNKNOWN

    def _find_client_location(
        self, mac: str
    ) -> Optional[Tuple[str, int, Optional[int]]]:
        """
        Find where a client is connected.

        Returns:
            Tuple of (device_id, port_idx, vlan_id) or None
        """
        mac = mac.upper().replace("-", ":")

        # Check client cache first
        if mac in self._client_cache:
            client = self._client_cache[mac]
            # Get switch port info
            sw_mac = client.get("sw_mac", "")
            sw_port = client.get("sw_port")

            if sw_mac and sw_port is not None:
                # Find device by MAC
                for device_id, device in self._device_cache.items():
                    if device.get("mac", "").upper() == sw_mac.upper():
                        vlan = client.get("vlan")
                        return (device_id, sw_port, vlan)

            # Check for AP connection (wireless)
            ap_mac = client.get("ap_mac", "")
            if ap_mac:
                for device_id, device in self._device_cache.items():
                    if device.get("mac", "").upper() == ap_mac.upper():
                        vlan = client.get("vlan")
                        return (device_id, 0, vlan)  # Port 0 for wireless

        # Fall back to MAC table search
        for device_id, device in self._device_cache.items():
            if device.get("type") != "usw":
                continue

            mac_table = device.get("mac_table", [])
            for entry in mac_table:
                if entry.get("mac", "").upper() == mac:
                    port = entry.get("port_idx", entry.get("port"))
                    vlan = entry.get("vlan")
                    return (device_id, port, vlan)

        return None

    def _find_uplink_path(
        self, device_id: str, visited: Set[str]
    ) -> List[Tuple[str, int, int]]:
        """
        Find the uplink path from a device to the gateway.

        Returns:
            List of (device_id, egress_port, ingress_port) tuples
        """
        path = []
        current_device = device_id
        visited = visited.copy()

        max_hops = 20  # Prevent infinite loops

        while current_device and len(path) < max_hops:
            if current_device in visited:
                logger.warning(f"Loop detected at device {current_device}")
                break
            visited.add(current_device)

            device = self._device_cache.get(current_device)
            if not device:
                break

            # Check if we've reached a gateway
            if device.get("type") in ["udm", "ugw", "uxg"]:
                break

            # Find uplink port
            port_table = device.get("port_table", [])
            uplink_port = None
            uplink_device = None

            for port in port_table:
                if port.get("is_uplink"):
                    uplink_port = port.get("port_idx")
                    port_idx = port.get("port_idx")

                    # Get LLDP info for this port
                    lldp_info = self._lldp_cache.get(current_device, {}).get(port_idx, {})
                    chassis_id = lldp_info.get("chassis_id", "")

                    # Find the connected device
                    for other_id, other_dev in self._device_cache.items():
                        if other_dev.get("mac", "").lower() == chassis_id.lower():
                            uplink_device = other_id
                            break

                    if uplink_device:
                        # Find the ingress port on the uplink device
                        ingress_port = 0
                        remote_port_id = lldp_info.get("port_id", "")
                        if remote_port_id:
                            # Try to match port ID
                            other_ports = self._device_cache.get(uplink_device, {}).get("port_table", [])
                            for op in other_ports:
                                if str(op.get("port_idx")) in remote_port_id:
                                    ingress_port = op.get("port_idx")
                                    break

                        path.append((current_device, uplink_port, ingress_port))
                        current_device = uplink_device
                        break

            if not uplink_device:
                # No more uplinks found
                break

        return path

    def trace(
        self,
        mac_or_ip: str,
        destination: str = "gateway",
    ) -> PathTraceResult:
        """
        Trace the network path for a client.

        Args:
            mac_or_ip: Client MAC address or IP address
            destination: Trace destination ("gateway" or specific IP)

        Returns:
            PathTraceResult with complete path information
        """
        logger.info(f"Starting path trace for {mac_or_ip}")

        # Ensure caches are loaded
        if not self._device_cache:
            self._load_caches()

        result = PathTraceResult()

        # Normalize input
        mac_or_ip = mac_or_ip.upper().replace("-", ":")
        result.query_mac = mac_or_ip if ":" in mac_or_ip else ""
        result.query_ip = mac_or_ip if "." in mac_or_ip else ""

        # Look up client
        client_info = self._client_cache.get(mac_or_ip)
        if client_info:
            result.query_mac = client_info.get("mac", "").upper()
            result.query_ip = client_info.get("ip", "")
            result.client_found = True

        # Find client location
        location = self._find_client_location(mac_or_ip)
        if not location:
            result.add_issue(
                "critical",
                f"Could not locate client {mac_or_ip} in the network",
                "client_lookup",
            )
            result.recommendations.append(
                "Verify the client is connected and has recent network activity"
            )
            return result

        device_id, port_idx, vlan = location
        device = self._device_cache.get(device_id, {})
        result.client_device = device.get("name", device.get("model", device_id))
        result.client_port = port_idx
        result.client_vlan = vlan
        result.client_found = True

        # Create the path
        path = ClientPath(
            client_mac=result.query_mac,
            client_ip=result.query_ip,
            client_hostname=client_info.get("hostname", "") if client_info else "",
            destination=destination,
            client_vlan=vlan,
        )

        # Add first hop (where client connects)
        first_hop = PathHop(
            hop_number=1,
            device_id=device_id,
            device_name=device.get("name", device.get("model", "Unknown")),
            device_type=self._get_device_type(device),
            device_model=device.get("model", ""),
            device_ip=device.get("ip", ""),
            ingress_port=port_idx,
            ingress_vlan=vlan,
        )

        # Get port details
        port_table = device.get("port_table", [])
        for port in port_table:
            if port.get("port_idx") == port_idx:
                first_hop.ingress_port_name = port.get("name", f"Port {port_idx}")
                first_hop.link_speed_mbps = port.get("speed", 0)
                break

        first_hop.estimated_latency_ms = self.LATENCY_ESTIMATES.get(
            first_hop.device_type, 0.1
        )
        path.add_hop(first_hop)

        # Trace uplink path
        visited = {device_id}
        uplink_path = self._find_uplink_path(device_id, visited)

        hop_number = 2
        for dev_id, egress_port, ingress_port in uplink_path:
            dev = self._device_cache.get(dev_id, {})
            if not dev:
                continue

            hop = PathHop(
                hop_number=hop_number,
                device_id=dev_id,
                device_name=dev.get("name", dev.get("model", "Unknown")),
                device_type=self._get_device_type(dev),
                device_model=dev.get("model", ""),
                device_ip=dev.get("ip", ""),
                egress_port=egress_port,
                connected_via="LLDP",
            )

            # Get port details
            for port in dev.get("port_table", []):
                if port.get("port_idx") == egress_port:
                    hop.egress_port_name = port.get("name", f"Port {egress_port}")
                    hop.link_speed_mbps = port.get("speed", 0)

                    # Check for VLAN tagging
                    for po in dev.get("port_overrides", []):
                        if po.get("port_idx") == egress_port:
                            hop.egress_vlan = po.get("native_vlan")
                    break

            hop.estimated_latency_ms = self.LATENCY_ESTIMATES.get(
                hop.device_type, 0.1
            )
            path.add_hop(hop)
            hop_number += 1

        # Add final hop to gateway if we found one
        if uplink_path:
            last_device_id = uplink_path[-1][0] if uplink_path else device_id
            last_device = self._device_cache.get(last_device_id, {})

            # Look for gateway in topology
            for dev_id, dev in self._device_cache.items():
                if dev.get("type") in ["udm", "ugw", "uxg"]:
                    gateway_hop = PathHop(
                        hop_number=hop_number,
                        device_id=dev_id,
                        device_name=dev.get("name", dev.get("model", "Gateway")),
                        device_type=HopType.GATEWAY,
                        device_model=dev.get("model", ""),
                        device_ip=dev.get("ip", ""),
                        connected_via="L3 Gateway",
                    )
                    gateway_hop.estimated_latency_ms = self.LATENCY_ESTIMATES.get(
                        HopType.GATEWAY, 0.5
                    )
                    path.add_hop(gateway_hop)
                    path.path_status = PathStatus.COMPLETE
                    break

        if path.path_status != PathStatus.COMPLETE:
            path.path_status = PathStatus.PARTIAL
            result.add_issue(
                "warning",
                "Could not trace complete path to gateway",
                "path_trace",
            )

        # Check for VLAN consistency
        if not path.vlan_consistent:
            result.add_issue(
                "warning",
                f"VLAN mismatch detected in path. Client VLAN: {path.client_vlan}, "
                f"VLANs traversed: {path.vlans_traversed}",
                "vlan_consistency",
            )
            result.recommendations.append(
                "Verify trunk port VLAN tagging configuration along the path"
            )

        # Add path to result
        result.paths.append(path)
        result.path_complete = path.path_status == PathStatus.COMPLETE

        logger.info(
            f"Path trace complete: {path.total_hops} hops, "
            f"status: {path.path_status.value}"
        )

        return result

    def generate_report(self, result: PathTraceResult) -> str:
        """Generate human-readable path trace report."""
        report = [
            "# Client Path Trace Report",
            "",
            f"**Generated**: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Client Information",
            "",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| MAC Address | {result.query_mac or 'N/A'} |",
            f"| IP Address | {result.query_ip or 'N/A'} |",
            f"| Client Found | {'✅ Yes' if result.client_found else '❌ No'} |",
            f"| Connected To | {result.client_device or 'Unknown'} |",
            f"| Port | {result.client_port or 'Unknown'} |",
            f"| VLAN | {result.client_vlan or 'Unknown'} |",
            "",
        ]

        if not result.paths:
            report.extend([
                "## ❌ Path Trace Failed",
                "",
                "Could not trace path for this client.",
                "",
            ])
        else:
            path = result.paths[0]

            # Status banner
            status_emoji = {
                PathStatus.COMPLETE: "✅",
                PathStatus.PARTIAL: "⚠️",
                PathStatus.BROKEN: "❌",
                PathStatus.UNKNOWN: "❓",
            }
            emoji = status_emoji.get(path.path_status, "❓")

            report.extend([
                f"## {emoji} Path Status: {path.path_status.value.upper()}",
                "",
                f"**Path**: {path.get_path_string()}",
                "",
                "## Path Summary",
                "",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Total Hops | {path.total_hops} |",
                f"| Estimated Latency | {path.total_estimated_latency_ms:.1f} ms |",
                f"| Minimum Bandwidth | {path.path_bandwidth_mbps} Mbps |",
                f"| VLANs Traversed | {', '.join(map(str, path.vlans_traversed)) or 'N/A'} |",
                f"| VLAN Consistent | {'✅ Yes' if path.vlan_consistent else '⚠️ No'} |",
                "",
                "## Path Details",
                "",
                "| Hop | Device | Type | Port | Speed | Latency |",
                "|-----|--------|------|------|-------|---------|",
            ])

            for hop in path.hops:
                port_info = ""
                if hop.ingress_port is not None and hop.egress_port is not None:
                    port_info = f"→{hop.ingress_port} →{hop.egress_port}→"
                elif hop.ingress_port is not None:
                    port_info = f"→{hop.ingress_port}"
                elif hop.egress_port is not None:
                    port_info = f"{hop.egress_port}→"

                speed = f"{hop.link_speed_mbps} Mbps" if hop.link_speed_mbps else "N/A"
                report.append(
                    f"| {hop.hop_number} | {hop.device_name} | {hop.device_type.value} | "
                    f"{port_info} | {speed} | {hop.estimated_latency_ms:.1f}ms |"
                )
            report.append("")

        # Issues
        if result.issues:
            report.extend([
                "## Issues Detected",
                "",
            ])
            for issue in result.issues:
                severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(
                    issue["severity"], "⚪"
                )
                report.append(f"- {severity_emoji} **{issue['severity'].upper()}**: {issue['message']}")
            report.append("")

        # Recommendations
        if result.recommendations:
            report.extend([
                "## Recommendations",
                "",
            ])
            for rec in result.recommendations:
                report.append(f"- {rec}")
            report.append("")

        return "\n".join(report)
