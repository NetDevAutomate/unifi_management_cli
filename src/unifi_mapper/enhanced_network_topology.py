#!/usr/bin/env python3
"""
Enhanced network topology module for the UniFi Port Mapper.
Contains the NetworkTopology class for managing network topology visualization.
"""

import json
import logging
from typing import Dict

from .models import DeviceInfo, PortInfo

log = logging.getLogger(__name__)


class NetworkTopology:
    """
    Class for managing network topology visualization.
    """

    def __init__(self, devices: Dict[str, DeviceInfo] = None):
        """
        Initialize the NetworkTopology class.

        Args:
            devices: Dictionary of devices by ID
        """
        self.devices = devices or {}
        self.connections = []

    def add_device(self, device_id: str, name: str, model: str, mac: str, ip: str):
        """
        Add a device to the topology.

        Args:
            device_id: Device ID
            name: Device name
            model: Device model
            mac: Device MAC address
            ip: Device IP address
        """
        # Create a device info object
        device_info = DeviceInfo(
            id=device_id, name=name, model=model, mac=mac, ip=ip, ports=[], lldp_info={}
        )

        # Add the device to the topology
        self.devices[device_id] = device_info

    def add_connection(
        self,
        source_device_id: str,
        target_device_id: str,
        source_port_idx: int,
        target_port_idx: int,
    ) -> None:
        """
        Add a connection between two devices.

        Args:
            source_device_id: Source device ID
            target_device_id: Target device ID
            source_port_idx: Source port index
            target_port_idx: Target port index
        """
        # Skip if either device is not in the topology
        if source_device_id not in self.devices or target_device_id not in self.devices:
            return

        # Get the source and target devices
        source_device = self.devices[source_device_id]
        target_device = self.devices[target_device_id]

        # Find the source port
        source_port = None
        for port in source_device.ports:
            if port.idx == source_port_idx:
                source_port = port
                break

        # Find the target port
        target_port = None
        for port in target_device.ports:
            if port.idx == target_port_idx:
                target_port = port
                break

        # If we couldn't find the ports, create default ones
        if not source_port:
            source_port = PortInfo(
                idx=source_port_idx,
                name=f"Port {source_port_idx}",
                up=True,
                enabled=True,
                poe=False,
                media="RJ45",
                speed=1000,
                lldp_info={},
            )
            source_device.ports.append(source_port)

        if not target_port:
            target_port = PortInfo(
                idx=target_port_idx,
                name=f"Port {target_port_idx}",
                up=True,
                enabled=True,
                poe=False,
                media="RJ45",
                speed=1000,
                lldp_info={},
            )
            target_device.ports.append(target_port)

        # Add the connection
        self.connections.append(
            {
                "source_device_id": source_device_id,
                "target_device_id": target_device_id,
                "source_port_idx": source_port_idx,
                "target_port_idx": target_port_idx,
                "source_port_name": source_port.name,
                "target_port_name": target_port.name,
            }
        )

    def is_unifi_device(self, device_id):
        """
        Determine if a device is a UniFi device based on model and name.

        Args:
            device_id: Device ID

        Returns:
            bool: True if the device is a UniFi device, False otherwise
        """
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        model_lower = device.model.lower() if device.model else ""
        name_lower = device.name.lower() if device.name else ""

        # Check for UniFi device prefixes
        unifi_keywords = [
            "u6",
            "u7",
            "uap",
            "usw",
            "udm",
            "usg",
            "ugw",
            "unifi",
            "us-",
            "us8",
            "us16",
            "us24",
            "us48",
        ]

        # Check model for UniFi keywords
        for keyword in unifi_keywords:
            if keyword in model_lower:
                return True

        # Check name for UniFi keywords
        for keyword in unifi_keywords:
            if keyword in name_lower:
                return True

        return False

    def is_switch(self, device_id):
        """
        Determine if a device is a switch based on model and name.

        Args:
            device_id: Device ID

        Returns:
            bool: True if the device is a switch, False otherwise
        """
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        model_lower = device.model.lower() if device.model else ""
        name_lower = device.name.lower() if device.name else ""

        # Comprehensive check for switch identifiers
        switch_model_keywords = [
            "usw",
            "switch",
            "flex",
            "ultra",
            "us-",
            "us8",
            "us16",
            "us24",
            "us48",
            "usl",
            "enterprise",
            "lite",
            "poe",
            "2.5g",
            "aggregation",
            "sw",
            "us8-60w",
            "usw-flex",
            "usw-lite",
            "usw-pro",
            "usw-enterprise",
            "usw-aggregation",
        ]

        switch_name_keywords = ["switch", "flex", "sw", "usw"]

        # Check model for switch keywords
        for keyword in switch_model_keywords:
            if keyword in model_lower:
                return True

        # Check name for switch keywords
        for keyword in switch_name_keywords:
            if keyword in name_lower:
                return True

        return False

    def is_router(self, device_id):
        """
        Determine if a device is a router based on model and name.

        Args:
            device_id: Device ID

        Returns:
            bool: True if the device is a router, False otherwise
        """
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        model_lower = device.model.lower() if device.model else ""
        name_lower = device.name.lower() if device.name else ""

        router_keywords = ["ugw", "usg", "udm", "gateway", "router", "dream machine"]

        # Check model for router keywords
        for keyword in router_keywords:
            if keyword in model_lower:
                return True

        # Check name for router keywords
        for keyword in router_keywords:
            if keyword in name_lower:
                return True

        return False

    def is_ap(self, device_id):
        """
        Determine if a device is an access point based on model and name.

        Args:
            device_id: Device ID

        Returns:
            bool: True if the device is an access point, False otherwise
        """
        if device_id not in self.devices:
            return False

        device = self.devices[device_id]
        model_lower = device.model.lower() if device.model else ""
        name_lower = device.name.lower() if device.name else ""

        ap_keywords = [
            "uap",
            "ap",
            "u6",
            "u7",
            "ac",
            "nanostation",
            "litebeam",
            "iw",
            "access point",
        ]

        # Check model for AP keywords
        for keyword in ap_keywords:
            if keyword in model_lower:
                return True

        # Check name for AP keywords
        for keyword in ap_keywords:
            if keyword in name_lower:
                return True

        return False

    def infer_missing_connections(self):
        """
        Infer missing connections between switches and routers.
        This helps ensure all switches are connected to the network.
        """
        # First, identify all switches and routers
        switches = []
        routers = []

        for device_id in self.devices:
            if self.is_switch(device_id):
                switches.append(device_id)
            elif self.is_router(device_id):
                routers.append(device_id)

        # Find switches that are not connected to any other switch or router
        connected_switches = set()
        connected_devices = set()

        for connection in self.connections:
            source_id = connection.get("source_device_id")
            target_id = connection.get("target_device_id")

            if source_id in switches and target_id in switches + routers:
                connected_switches.add(source_id)
            if target_id in switches and source_id in switches + routers:
                connected_switches.add(target_id)

            connected_devices.add(source_id)
            connected_devices.add(target_id)

        # Find isolated switches (not connected to other switches or routers)
        isolated_switches = [
            switch_id for switch_id in switches if switch_id not in connected_switches
        ]

        # Also find completely disconnected switches (not in any connection)
        disconnected_switches = [
            switch_id for switch_id in switches if switch_id not in connected_devices
        ]

        # Combine both lists and remove duplicates
        switches_to_connect = list(set(isolated_switches + disconnected_switches))

        # For each switch that needs connection, try to infer a connection
        for switch_id in switches_to_connect:
            # First try to connect to a router
            if routers:
                # Connect to the first router
                router_id = routers[0]

                # Add an inferred connection
                self.connections.append(
                    {
                        "source_device_id": switch_id,
                        "target_device_id": router_id,
                        "source_port_idx": 1,  # Assume port 1 for simplicity
                        "target_port_idx": len(self.connections)
                        + 1,  # Use a unique port number
                        "source_port_name": "Port 1 (inferred)",
                        "target_port_name": f"Port {len(self.connections) + 1} (inferred)",
                        "inferred": True,
                    }
                )

                log.info(
                    f"Inferred connection from switch {self.devices[switch_id].name} to router {self.devices[router_id].name}"
                )
            # If no routers, connect to another switch that is already connected
            elif connected_switches:
                # Find a connected switch to connect to
                for connected_switch in connected_switches:
                    # Add an inferred connection
                    self.connections.append(
                        {
                            "source_device_id": switch_id,
                            "target_device_id": connected_switch,
                            "source_port_idx": 1,  # Assume port 1 for simplicity
                            "target_port_idx": len(self.connections)
                            + 1,  # Use a unique port number
                            "source_port_name": "Port 1 (inferred)",
                            "target_port_name": f"Port {len(self.connections) + 1} (inferred)",
                            "inferred": True,
                        }
                    )

                    log.info(
                        f"Inferred connection from switch {self.devices[switch_id].name} to switch {self.devices[connected_switch].name}"
                    )
                    break
            # If no routers or connected switches, connect to another switch
            elif len(switches) > 1:
                # Find another switch to connect to
                for other_switch in switches:
                    if other_switch != switch_id:
                        # Add an inferred connection
                        self.connections.append(
                            {
                                "source_device_id": switch_id,
                                "target_device_id": other_switch,
                                "source_port_idx": 1,  # Assume port 1 for simplicity
                                "target_port_idx": len(self.connections)
                                + 1,  # Use a unique port number
                                "source_port_name": "Port 1 (inferred)",
                                "target_port_name": f"Port {len(self.connections) + 1} (inferred)",
                                "inferred": True,
                            }
                        )

                        log.info(
                            f"Inferred connection from switch {self.devices[switch_id].name} to switch {self.devices[other_switch].name}"
                        )
                        break

    def generate_png_diagram(
        self, output_path: str, layout_style: str = "hierarchical"
    ) -> None:
        """
        Generate a PNG diagram using Graphviz with hierarchical layout.

        Args:
            output_path: Path to save the PNG file
            layout_style: 'hierarchical' (default, top-down) or 'wide' (left-right)
        """
        try:
            import graphviz

            # Generate DOT source with hierarchical layout for readability
            dot_source = self._generate_dot_source(layout_style=layout_style)

            # Render to PNG
            graph = graphviz.Source(dot_source)
            output_base = str(output_path).replace(".png", "")
            graph.render(output_base, format="png", cleanup=True, view=False)

            log.info(f"Generated PNG diagram ({layout_style} layout): {output_path}")

        except ImportError:
            log.error(
                "graphviz package not installed. Install with: uv pip install graphviz"
            )
            # Create placeholder
            with open(output_path, "w") as f:
                f.write(
                    "PNG generation requires 'graphviz' package. Install with: uv pip install graphviz"
                )
        except Exception as e:
            log.error(f"Error generating PNG diagram: {e}")
            raise

    def generate_svg_diagram(
        self, output_path: str, layout_style: str = "hierarchical"
    ) -> None:
        """
        Generate an SVG diagram using Graphviz with hierarchical layout.

        Args:
            output_path: Path to save the SVG file
            layout_style: 'hierarchical' (default, top-down) or 'wide' (left-right)
        """
        try:
            import graphviz

            # Generate DOT source with hierarchical layout
            dot_source = self._generate_dot_source(layout_style=layout_style)

            # Render to SVG
            graph = graphviz.Source(dot_source)
            output_base = str(output_path).replace(".svg", "")
            graph.render(output_base, format="svg", cleanup=True, view=False)

            log.info(f"Generated SVG diagram ({layout_style} layout): {output_path}")

        except ImportError:
            log.error(
                "graphviz package not installed. Install with: uv pip install graphviz"
            )
            with open(output_path, "w") as f:
                f.write(
                    "SVG generation requires 'graphviz' package. Install with: uv pip install graphviz"
                )
        except Exception as e:
            log.error(f"Error generating SVG diagram: {e}")
            raise

    def _generate_dot_source(
        self, layout_style: str = "hierarchical", infrastructure_only: bool = True
    ) -> str:
        """Generate Graphviz DOT source code with device type hierarchy.

        Creates a compact, readable diagram with devices grouped by type.
        By default, only shows UniFi infrastructure (gateway, switches, APs).

        Args:
            layout_style: 'hierarchical' (top-down) or 'wide' (left-right)
            infrastructure_only: If True, exclude wired endpoints (default: True)

        Returns:
            DOT format source code as string
        """
        lines = ["digraph NetworkTopology {"]
        # Use dot layout with vertical hierarchy - centered layout
        lines.append(
            "  graph [rankdir=TB, splines=spline, nodesep=0.8, ranksep=1.2, "
            "compound=true, concentrate=true, center=true];"
        )
        # Fixed size nodes for visual consistency - all devices same size
        lines.append(
            '  node [shape=box, style="filled,rounded", fontname="Arial", '
            'fontsize=9, fixedsize=true, width=1.4, height=0.5];'
        )
        lines.append('  edge [color="#666666", arrowsize=0.5, penwidth=1.5, fontsize=9];')

        # Group devices by type
        routers = []
        switches = []
        aps = []
        others = []

        for device_id, device in self.devices.items():
            device_type = self._determine_device_type(device)
            if device_type == "router":
                routers.append((device_id, device))
            elif device_type == "switch":
                switches.append((device_id, device))
            elif device_type == "ap":
                aps.append((device_id, device))
            else:
                others.append((device_id, device))

        # Build set of infrastructure device IDs for filtering connections
        infra_ids = {d[0] for d in routers + switches + aps}

        # Extract WAN/ISP information from ALL device port names
        # ISP info is often stored in switch port names like "Virgin Media to UDM Pro Port 11"
        isp_connections = []
        for device_id, device in routers + switches:
            for port in device.ports:
                port_name = port.name if port.name else ""
                port_name_lower = port_name.lower()
                # Look for ISP provider names in port descriptions
                if "virgin" in port_name_lower:
                    isp_connections.append(("Virgin Media", port_name))
                elif "bt " in port_name_lower or "bt isp" in port_name_lower:
                    isp_connections.append(("BT", port_name))
                elif "sky" in port_name_lower:
                    isp_connections.append(("Sky", port_name))
                elif "talktalk" in port_name_lower:
                    isp_connections.append(("TalkTalk", port_name))
                elif "isp" in port_name_lower and "virgin" not in port_name_lower and "bt" not in port_name_lower:
                    isp_connections.append(("ISP", port_name))

        # Deduplicate ISP names
        unique_isps = list(set(isp[0] for isp in isp_connections))
        if unique_isps:
            log.info(f"Detected ISP connections: {unique_isps}")
        if isp_connections:
            for isp_name, port_name in isp_connections:
                log.debug(f"  ISP '{isp_name}' from port: {port_name}")

        # Use subgraph clusters to enforce vertical hierarchy
        lines.append("")
        lines.append("  // Layer 0: Internet/ISP connections")
        lines.append('  subgraph cluster_internet {')
        lines.append('    style=invis;')
        lines.append('    rank=source;')
        lines.append(
            '    "Internet" [label="🌐 Internet", '
            'fillcolor="#607D8B", fontcolor="white"];'
        )
        # Add ISP nodes if detected
        for isp_name in unique_isps:
            safe_id = isp_name.replace(" ", "_")
            lines.append(
                f'    "ISP_{safe_id}" [label="{isp_name}", '
                f'fillcolor="#FF5722", fontcolor="white"];'
            )
        lines.append('  }')

        # Layer 1: Gateway/Router
        if routers:
            lines.append("")
            lines.append("  // Layer 1: Gateway")
            lines.append('  subgraph cluster_gateway {')
            lines.append('    style=invis;')
            for device_id, device in routers:
                wrapped_name = self._wrap_name(device.name)
                lines.append(
                    f'    "{device_id}" [label="{wrapped_name}", fillcolor="#4CAF50", '
                    f'fontcolor="white"];'
                )
            lines.append('  }')

        # Layer 2: Core Switches (all switches for simplicity)
        if switches:
            lines.append("")
            lines.append("  // Layer 2: Switches")
            lines.append('  subgraph cluster_switches {')
            lines.append('    style=invis;')
            for device_id, device in switches:
                wrapped_name = self._wrap_name(device.name)
                lines.append(
                    f'    "{device_id}" [label="{wrapped_name}", fillcolor="#2196F3", '
                    f'fontcolor="white"];'
                )
            lines.append('  }')

        # Layer 3: Access Points
        if aps:
            lines.append("")
            lines.append("  // Layer 3: Access Points")
            lines.append('  subgraph cluster_aps {')
            lines.append('    style=invis;')
            for device_id, device in aps:
                wrapped_name = self._wrap_name(device.name)
                lines.append(
                    f'    "{device_id}" [label="{wrapped_name}", fillcolor="#9C27B0", '
                    f'fontcolor="white"];'
                )
            lines.append('  }')

        # Only include other devices if not infrastructure_only
        if not infrastructure_only and others:
            lines.append("")
            lines.append("  // Layer 4: Other devices")
            lines.append('  subgraph cluster_others {')
            lines.append('    style=invis;')
            for device_id, device in others:
                wrapped_name = self._wrap_name(device.name)
                lines.append(
                    f'    "{device_id}" [label="{wrapped_name}", fillcolor="#FF9800"];'
                )
            lines.append('  }')

        # Add invisible edges to enforce layer ordering (only where visible edges don't exist)
        lines.append("")
        lines.append("  // Invisible edges to enforce vertical hierarchy")

        # Internet -> router hierarchy is handled by visible edges below
        # Only add invisible edges between layers that don't have visible connections

        # First router -> first switch (if exists and no direct LLDP connection)
        if routers and switches:
            lines.append(f'  "{routers[0][0]}" -> "{switches[0][0]}" [style=invis, weight=100];')

        # First switch -> first AP (if exists)
        if switches and aps:
            lines.append(f'  "{switches[0][0]}" -> "{aps[0][0]}" [style=invis, weight=100];')

        # Connections (visible edges)
        lines.append("")
        lines.append("  // Actual connections")

        # Internet to routers - through ISP nodes if available
        if unique_isps:
            # Connect Internet to each ISP
            for isp_name in unique_isps:
                safe_id = isp_name.replace(" ", "_")
                lines.append(f'  "Internet" -> "ISP_{safe_id}" [color="#FF5722", penwidth=2.5];')
            # Connect ISPs to routers
            for device_id, _ in routers:
                for isp_name in unique_isps:
                    safe_id = isp_name.replace(" ", "_")
                    lines.append(f'  "ISP_{safe_id}" -> "{device_id}" [color="#4CAF50", penwidth=2.0];')
        else:
            # Direct Internet to routers if no ISP info found
            for device_id, _ in routers:
                lines.append(f'  "Internet" -> "{device_id}" [color="#4CAF50", penwidth=2.5, label="WAN"];')

        # Device connections from LLDP data
        added_edges = set()
        for conn in self.connections:
            src = conn.get("source_device_id", "")
            tgt = conn.get("target_device_id", "")

            if not src or not tgt:
                continue
            if src not in self.devices or tgt not in self.devices:
                continue

            # Skip connections involving non-infrastructure devices
            if infrastructure_only:
                if src not in infra_ids or tgt not in infra_ids:
                    continue

            # Avoid duplicate edges
            edge_key = tuple(sorted([src, tgt]))
            if edge_key in added_edges:
                continue
            added_edges.add(edge_key)

            lines.append(f'  "{src}" -> "{tgt}" [dir=none];')

        # Compact title with legend info as a note
        lines.append("")
        lines.append("  // Title node with legend")
        lines.append('  labelloc="t";')
        lines.append('  label="UniFi Network Topology\\n🟢 Gateway  🔵 Switch  🟣 AP  🟠 ISP";')
        lines.append('  fontsize=14;')

        lines.append("}")
        return "\n".join(lines)

    def _shorten_name(self, name: str) -> str:
        """Shorten device name for cleaner diagram display."""
        if not name:
            return "Unknown"
        # Remove common prefixes/suffixes
        name = name.replace("USW ", "").replace("U6-", "U6 ")
        # Truncate long names
        if len(name) > 18:
            return name[:16] + "..."
        return name

    def _wrap_name(self, name: str, max_chars: int = 14) -> str:
        """Wrap device name to fit in fixed-size nodes.

        Args:
            name: Device name to wrap
            max_chars: Maximum characters per line

        Returns:
            Name with newlines for wrapping
        """
        if not name:
            return "Unknown"

        # Clean up common prefixes for shorter labels
        name = name.replace("USW ", "").replace("U6-", "U6 ").replace("USW-", "")

        # If short enough, return as-is
        if len(name) <= max_chars:
            return name

        # Split into words and wrap
        words = name.split()
        lines = []
        current_line = ""

        for word in words:
            if not current_line:
                current_line = word
            elif len(current_line) + 1 + len(word) <= max_chars:
                current_line += " " + word
            else:
                lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        # Limit to 2 lines max, truncate if needed
        if len(lines) > 2:
            lines = lines[:2]
            if len(lines[1]) > max_chars - 2:
                lines[1] = lines[1][:max_chars - 3] + "..."

        return "\\n".join(lines)

    def _group_devices_by_location_and_type(self) -> dict:
        """
        Group devices by location and type for hierarchical layout.

        Returns:
            Dict[location, Dict[type, List[device]]]
        """
        groups = {}

        for device_id, device in self.devices.items():
            # Extract location from device name
            location = self._extract_location(device.name)
            device_type = self._determine_device_type(device)

            if location not in groups:
                groups[location] = {}

            if device_type not in groups[location]:
                groups[location][device_type] = []

            groups[location][device_type].append(device)

        return groups

    def _extract_location(self, name: str) -> str:
        """
        Extract location from device name.

        Args:
            name: Device name (e.g., "Office Switch" or "Lounge US 8")

        Returns:
            Location name or "Core" if not found
        """
        name_lower = name.lower()

        # Common location keywords
        locations = [
            "office",
            "lounge",
            "bedroom",
            "kitchen",
            "shed",
            "hallway",
            "dining",
            "garage",
            "basement",
            "attic",
            "bob",
            "sian",
            "reece",
        ]

        for loc in locations:
            if loc in name_lower:
                return loc.title()

        # Check for "Tower", "Desk", "Hub", "Core" identifiers
        if any(x in name_lower for x in ["tower", "core", "main", "hub"]):
            return "Core"

        return "Network"

    def _get_device_color(self, device_type: str) -> str:
        """Get fill color based on device type."""
        colors = {
            "router": "#3498db",
            "switch": "#2ecc71",
            "ap": "#e74c3c",
            "unknown": "#95a5a6",
        }
        return colors.get(device_type, colors["unknown"])

    def _get_device_icon(self, device_type: str) -> str:
        """Get emoji icon based on device type."""
        icons = {"router": "🌐", "switch": "🔄", "ap": "📶", "unknown": "💻"}
        return icons.get(device_type, icons["unknown"])

    def _determine_device_type(self, device: DeviceInfo) -> str:
        """Determine device type from model name.

        Args:
            device: DeviceInfo object

        Returns:
            Device type: 'router', 'switch', 'ap', or 'unknown'
        """
        model_lower = device.model.lower() if device.model else ""
        name_lower = device.name.lower() if device.name else ""

        # Check model patterns - order matters (most specific first)
        # Routers/Gateways
        if any(x in model_lower for x in ["udm", "usg", "ugw", "gateway", "dream"]):
            return "router"

        # Switches - includes US-8, US-16, US-24, US-48 series
        if any(x in model_lower for x in [
            "usw", "usl", "usm", "switch", "flex",
            "us8", "us16", "us24", "us48",  # US series without hyphen
            "us-8", "us-16", "us-24", "us-48",  # US series with hyphen
        ]):
            return "switch"

        # Access Points - includes all UAP and U6/U7 variants
        if any(x in model_lower for x in [
            "uap", "u6", "u7", "ualr",  # U6 LR is UALR6v2
            "ac", "iw", "nanohd", "hd", "shd", "xg",
        ]):
            return "ap"

        # Check name patterns as fallback
        if any(x in name_lower for x in ["router", "gateway", "udm", "dream"]):
            return "router"
        if any(x in name_lower for x in ["switch", "sw", "us-8", "us 8", "us8"]):
            return "switch"
        if any(x in name_lower for x in [
            "ap", "wifi", "access", "u6", "u7", "lr", "pro", "iw"
        ]):
            return "ap"

        return "unknown"

    def generate_dot_diagram(self, output_path: str) -> None:
        """
        Generate a DOT diagram of the network topology.

        Args:
            output_path: Path to save the DOT file
        """
        # Create a simple text file as a placeholder
        with open(output_path, "w") as f:
            f.write("DOT diagram would be generated here")

    def generate_mermaid_diagram(self, output_path: str) -> None:
        """
        Generate a Mermaid diagram of the network topology.

        Args:
            output_path: Path to save the Mermaid file
        """
        # Create a simple text file as a placeholder
        with open(output_path, "w") as f:
            f.write("Mermaid diagram would be generated here")

    def generate_html_diagram(
        self, output_path: str, show_connected_devices: bool = False
    ) -> None:
        """
        Generate an HTML diagram of the network topology.

        Args:
            output_path: Path to save the HTML file
            show_connected_devices: Whether to show non-UniFi connected devices
        """
        # First, infer any missing connections to ensure all switches are connected
        self.infer_missing_connections()

        # Create nodes and links for D3.js
        nodes = []
        node_ids = set()  # Keep track of added node IDs
        links = []

        # First pass: Add all UniFi devices to nodes
        for device_id, device in self.devices.items():
            # Check if this is a UniFi device
            is_unifi = self.is_unifi_device(device_id)

            # Skip non-UniFi devices if show_connected_devices is False
            if not is_unifi and not show_connected_devices:
                continue

            # Define node style based on device type
            device_type = "other"
            color = "#95a5a6"  # Default grey
            icon = "💻"  # Default icon

            # Determine device type
            if self.is_router(device_id):
                color = "#3498db"  # Blue
                icon = "🌐"
                device_type = "router"
            elif self.is_switch(device_id):
                color = "#2ecc71"  # Green
                icon = "🔄"
                device_type = "switch"
            elif self.is_ap(device_id):
                color = "#e74c3c"  # Red
                icon = "📶"
                device_type = "ap"

            # Extract location from name
            location = "unknown"
            name_parts = device.name.lower().split() if device.name else []
            for loc in [
                "office",
                "lounge",
                "bedroom",
                "kitchen",
                "dining",
                "shed",
                "reece",
            ]:
                if loc in name_parts:
                    location = loc.capitalize()
                    break

            nodes.append(
                {
                    "id": device_id,
                    "name": device.name,
                    "model": device.model,
                    "ip": device.ip,
                    "type": device_type,
                    "color": color,
                    "icon": icon,
                    "location": location,
                    "group": location,
                }
            )
            node_ids.add(device_id)

        # Process connections
        for connection in self.connections:
            source_id = connection.get("source_device_id")
            target_id = connection.get("target_device_id")

            # Skip connections with None IDs
            if source_id is None or target_id is None:
                continue

            # Skip connections to non-UniFi devices if show_connected_devices is False
            if not show_connected_devices:
                if source_id not in node_ids or target_id not in node_ids:
                    continue

            # Skip if either device is not in the nodes list
            if source_id not in node_ids or target_id not in node_ids:
                continue

            source_port = connection.get("source_port_name", "Auto")
            target_port = connection.get("target_port_name", "Auto")

            # Check if this link already exists (to avoid duplicates)
            link_exists = False
            for link in links:
                if (link["source"] == source_id and link["target"] == target_id) or (
                    link["source"] == target_id and link["target"] == source_id
                ):
                    link_exists = True
                    break

            if not link_exists:
                links.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "sourcePort": source_port,
                        "targetPort": target_port,
                    }
                )

        # Create HTML template
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>UniFi Network Topology</title>
            <script src="https://d3js.org/d3.v7.min.js"></script>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 0;
                    padding: 0;
                    background-color: #f5f5f5;
                }
                #topology {
                    width: 100%;
                    height: 100vh;
                    background-color: white;
                }
                .node {
                    cursor: pointer;
                }
                .node text {
                    font-size: 12px;
                    fill: #333;
                }
                .link {
                    stroke: #999;
                    stroke-opacity: 0.6;
                }
                .link-label {
                    font-size: 10px;
                    fill: #666;
                }
                .legend {
                    position: absolute;
                    top: 20px;
                    right: 20px;
                    background-color: rgba(255, 255, 255, 0.8);
                    padding: 10px;
                    border-radius: 5px;
                    border: 1px solid #ddd;
                }
                .legend-item {
                    display: flex;
                    align-items: center;
                    margin-bottom: 5px;
                }
                .legend-color {
                    width: 15px;
                    height: 15px;
                    margin-right: 5px;
                    border-radius: 3px;
                }
                .legend-icon {
                    margin-right: 5px;
                    font-size: 16px;
                }
                .tooltip {
                    position: absolute;
                    background-color: rgba(255, 255, 255, 0.9);
                    padding: 10px;
                    border-radius: 5px;
                    border: 1px solid #ddd;
                    pointer-events: none;
                    font-size: 12px;
                    z-index: 1000;
                }
                .controls {
                    position: absolute;
                    top: 10px;
                    left: 10px;
                    background-color: rgba(255, 255, 255, 0.8);
                    padding: 10px;
                    border-radius: 5px;
                    border: 1px solid #ddd;
                }
                button {
                    margin: 2px;
                    padding: 5px 10px;
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 3px;
                    cursor: pointer;
                }
                button:hover {
                    background-color: #45a049;
                }
            </style>
        </head>
        <body>
            <div id="topology"></div>
            <div class="controls">
                <button id="reset">Reset View</button>
                <button id="save">Save Layout</button>
                <button id="load">Load Layout</button>
            </div>
            <div class="legend">
                <h3>Device Types</h3>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #3498db;"></div>
                    <div class="legend-icon">🌐</div>
                    <div>Routers/Gateways</div>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #2ecc71;"></div>
                    <div class="legend-icon">🔄</div>
                    <div>Switches</div>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #e74c3c;"></div>
                    <div class="legend-icon">📶</div>
                    <div>Access Points</div>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background-color: #95a5a6;"></div>
                    <div class="legend-icon">💻</div>
                    <div>Other Devices</div>
                </div>
            </div>
            <script>
                // Network data
                const nodes = NODES_PLACEHOLDER;
                const links = LINKS_PLACEHOLDER;

                // Create a tooltip
                const tooltip = d3.select("body").append("div")
                    .attr("class", "tooltip")
                    .style("opacity", 0);

                // Set up the SVG
                const width = window.innerWidth;
                const height = window.innerHeight;

                const svg = d3.select("#topology")
                    .append("svg")
                    .attr("width", width)
                    .attr("height", height);

                // Create a group for the network
                const g = svg.append("g");

                // Set up zoom behavior
                const zoom = d3.zoom()
                    .scaleExtent([0.1, 4])
                    .on("zoom", (event) => {
                        g.attr("transform", event.transform);
                    });

                svg.call(zoom);

                // Create a force simulation
                const simulation = d3.forceSimulation(nodes)
                    .force("link", d3.forceLink(links).id(d => d.id).distance(150))
                    .force("charge", d3.forceManyBody().strength(-500))
                    .force("center", d3.forceCenter(width / 2, height / 2))
                    .force("x", d3.forceX(width / 2).strength(0.1))
                    .force("y", d3.forceY(height / 2).strength(0.1))
                    .force("collision", d3.forceCollide().radius(30));

                // Create links
                const link = g.append("g")
                    .selectAll("line")
                    .data(links)
                    .enter()
                    .append("line")
                    .attr("class", "link")
                    .attr("stroke-width", 2);

                // Create link labels
                const linkLabel = g.append("g")
                    .selectAll("text")
                    .data(links)
                    .enter()
                    .append("text")
                    .attr("class", "link-label")
                    .text(d => `${d.sourcePort} → ${d.targetPort}`);

                // Create nodes
                const node = g.append("g")
                    .selectAll(".node")
                    .data(nodes)
                    .enter()
                    .append("g")
                    .attr("class", "node")
                    .call(d3.drag()
                        .on("start", dragstarted)
                        .on("drag", dragged)
                        .on("end", dragended));

                // Add circles to nodes
                node.append("circle")
                    .attr("r", 20)
                    .attr("fill", d => d.color)
                    .on("mouseover", function(event, d) {
                        tooltip.transition()
                            .duration(200)
                            .style("opacity", .9);
                        tooltip.html(`<strong>${d.name}</strong><br>Model: ${d.model}<br>IP: ${d.ip}<br>Type: ${d.type}`)
                            .style("left", (event.pageX + 10) + "px")
                            .style("top", (event.pageY - 28) + "px");
                    })
                    .on("mouseout", function() {
                        tooltip.transition()
                            .duration(500)
                            .style("opacity", 0);
                    });

                // Add icons to nodes
                node.append("text")
                    .attr("text-anchor", "middle")
                    .attr("dy", "0.3em")
                    .text(d => d.icon)
                    .style("font-size", "16px")
                    .style("pointer-events", "none");

                // Add labels to nodes
                node.append("text")
                    .attr("dx", 25)
                    .attr("dy", ".35em")
                    .text(d => d.name);

                // Update positions on each tick
                simulation.on("tick", () => {
                    link
                        .attr("x1", d => d.source.x)
                        .attr("y1", d => d.source.y)
                        .attr("x2", d => d.target.x)
                        .attr("y2", d => d.target.y);

                    linkLabel
                        .attr("x", d => (d.source.x + d.target.x) / 2)
                        .attr("y", d => (d.source.y + d.target.y) / 2);

                    node
                        .attr("transform", d => `translate(${d.x}, ${d.y})`);
                });

                // Drag functions
                function dragstarted(event, d) {
                    if (!event.active) simulation.alphaTarget(0.3).restart();
                    d.fx = d.x;
                    d.fy = d.y;
                }

                function dragged(event, d) {
                    d.fx = event.x;
                    d.fy = event.y;
                }

                function dragended(event, d) {
                    if (!event.active) simulation.alphaTarget(0);
                    // Keep the node fixed where it was dragged
                    // d.fx = null;
                    // d.fy = null;
                }

                // Reset button
                document.getElementById("reset").addEventListener("click", () => {
                    svg.transition().duration(750).call(
                        zoom.transform,
                        d3.zoomIdentity,
                        d3.zoomTransform(svg.node()).invert([width / 2, height / 2])
                    );

                    // Reset node positions
                    nodes.forEach(d => {
                        d.fx = null;
                        d.fy = null;
                    });

                    simulation.alpha(1).restart();
                });

                // Save layout
                document.getElementById("save").addEventListener("click", () => {
                    const layout = nodes.map(d => ({
                        id: d.id,
                        x: d.x,
                        y: d.y,
                        fx: d.fx,
                        fy: d.fy
                    }));

                    localStorage.setItem("networkLayout", JSON.stringify(layout));
                    alert("Layout saved!");
                });

                // Load layout
                document.getElementById("load").addEventListener("click", () => {
                    const savedLayout = JSON.parse(localStorage.getItem("networkLayout"));

                    if (savedLayout) {
                        savedLayout.forEach(saved => {
                            const device = nodes.find(d => d.id === saved.id);
                            if (device) {
                                device.fx = saved.fx;
                                device.fy = saved.fy;
                            }
                        });

                        simulation.alpha(1).restart();
                        alert("Layout loaded!");
                    } else {
                        alert("No saved layout found!");
                    }
                });
            </script>
        </body>
        </html>
        """

        # Replace placeholders with actual data
        html_content = html_template.replace(
            "NODES_PLACEHOLDER", json.dumps(nodes)
        ).replace("LINKS_PLACEHOLDER", json.dumps(links))

        # Write HTML file
        with open(output_path, "w") as f:
            f.write(html_content)
