#!/usr/bin/env python3
"""
Network topology module for the UniFi Port Mapper.
Contains the NetworkTopology class for managing network topology visualization.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from .models import DeviceInfo, PortInfo

log = logging.getLogger(__name__)

class NetworkTopology:
    """
    Class for managing network topology visualization.
    """
    
    def __init__(self):
        """
        Initialize the NetworkTopology class.
        """
        self.devices = {}  # Dictionary of devices by ID
        self.connections = []  # List of connections between devices
    
    def add_device(self, device: DeviceInfo):
        """
        Add a device to the topology.
        
        Args:
            device (DeviceInfo): Device information
        """
        # Determine device type based on model
        device_type = self._determine_device_type(device.model)
        device.device_type = device_type
        
        self.devices[device.id] = device
    
    def _determine_device_type(self, model: str) -> str:
        """
        Determine the device type based on the model.
        
        Args:
            model (str): Device model
        
        Returns:
            str: Device type (router, switch, ap, other)
        """
        model_lower = model.lower()
        
        # Check for routers/gateways
        if any(x in model_lower for x in ['ugw', 'usg', 'udm', 'gateway', 'router', 'dream machine']):
            return 'router'
        
        # Check for switches - expanded to catch all switch models
        if any(x in model_lower for x in ['usw', 'switch', 'flex', 'ultra', 'us-', 'us8', 'us16', 'us24', 'us48', 
                                         'usl', 'enterprise', 'lite', 'poe', '2.5g', 'aggregation']):
            return 'switch'
        
        # Check for access points
        if any(x in model_lower for x in ['uap', 'ap', 'u6', 'u7', 'ac', 'nanostation', 'litebeam', 'iw']):
            return 'ap'
        
        # Default to other
        return 'other'
    
    def add_connection(self, source_device_id: str, source_port_name: str, 
                      target_device_id: str, target_port_name: str):
        """
        Add a connection between devices.
        
        Args:
            source_device_id (str): Source device ID
            source_port_name (str): Source port name
            target_device_id (str): Target device ID
            target_port_name (str): Target port name
        """
        self.connections.append({
            'source_device_id': source_device_id,
            'source_port_name': source_port_name,
            'target_device_id': target_device_id,
            'target_port_name': target_port_name
        })
    
    def generate_dot_diagram(self) -> str:
        """
        Generate a DOT format diagram of the network topology.
        
        Returns:
            str: DOT diagram
        """
        dot = ["digraph G {"]
        dot.append("    graph [overlap=false, splines=true, rankdir=TB];")
        dot.append("    node [shape=box, style=filled, fontname=Arial, fontsize=10];")
        dot.append("    edge [fontname=Arial, fontsize=9];")
        
        # Add devices
        for device_id, device in self.devices.items():
            # Define node style based on device model/name
            if "udm" in device.model.lower() or "usg" in device.model.lower() or "dream machine" in device.name.lower():
                color = "#3498db"
                icon = "🌐"
            elif "usw" in device.model.lower() or "switch" in device.name.lower():
                color = "#2ecc71"
                icon = "🔄"
            elif "uap" in device.model.lower() or "ap" in device.name.lower() or "u6" in device.model.lower():
                color = "#e74c3c"
                icon = "📶"
            else:
                color = "#95a5a6"
                icon = "💻"
            
            # Extract location from name
            location = "unknown"
            name_parts = device.name.lower().split()
            for loc in ["office", "lounge", "bedroom", "kitchen", "dining", "shed", "reece"]:
                if loc in name_parts:
                    location = loc.capitalize()
                    break
            
            # Add node with location as subgraph
            label = f"{icon} {device.name}\\n{device.model}"
            dot.append(f'    "{device_id}" [label="{label}", fillcolor="{color}", group="{location}"];')
        
        # Add connections
        for connection in self.connections:
            source_id = connection.get('source_device_id')
            target_id = connection.get('target_device_id')
            
            # Skip connections with None IDs
            if source_id is None or target_id is None:
                continue
                
            source_port = connection.get('source_port_name', 'Auto')
            target_port = connection.get('target_port_name', 'Auto')
            
            # Add connection
            if source_port == "Auto" and target_port == "Auto":
                dot.append(f'    "{source_id}" -> "{target_id}";')
            else:
                # Shorten port names for readability
                source_port_short = source_port
                target_port_short = target_port
                
                if len(source_port) > 15:
                    source_port_short = source_port[:12] + "..."
                if len(target_port) > 15:
                    target_port_short = target_port[:12] + "..."
                
                dot.append(f'    "{source_id}" -> "{target_id}" [label="{source_port_short} <-> {target_port_short}"];')
        
        dot.append("}")
        return "\n".join(dot)
        
    def generate_interactive_html(self, output_path: str) -> None:
        """
        Generate an interactive HTML visualization of the network topology.

        Args:
            output_path: Path to save the HTML file
        """
        # Create a dictionary of devices
        devices_json = []
        for device_id, device in self.devices.items():
            # Define node style based on device model/name
            if "udm" in device.model.lower() or "usg" in device.model.lower() or "dream machine" in device.name.lower():
                color = "#3498db"
                icon = "🌐"
                group = 1
            elif "usw" in device.model.lower() or "switch" in device.name.lower():
                color = "#2ecc71"
                icon = "🔄"
                group = 2
            elif "uap" in device.model.lower() or "ap" in device.name.lower() or "u6" in device.model.lower():
                color = "#e74c3c"
                icon = "📶"
                group = 3
            else:
                color = "#95a5a6"
                icon = "💻"
                group = 4

            # Extract location from name
            location = "unknown"
            name_parts = device.name.lower().split()
            for loc in ["office", "lounge", "bedroom", "kitchen", "dining", "shed", "reece"]:
                if loc in name_parts:
                    location = loc.capitalize()
                    break

            devices_json.append({
                "id": device_id,
                "name": device.name,
                "model": device.model,
                "color": color,
                "icon": icon,
                "group": group,
                "location": location
            })

        # Create a list of connections
        connections_json = []
        for connection in self.connections:
            source_id = connection.get('source_device_id')
            target_id = connection.get('target_device_id')

            # Skip connections with None IDs
            if source_id is None or target_id is None:
                continue

            source_port = connection.get('source_port_name', 'Auto')
            target_port = connection.get('target_port_name', 'Auto')

            connections_json.append({
                "source": source_id,
                "target": target_id,
                "source_port": source_port,
                "target_port": target_port
            })

        # Create the HTML file
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>UniFi Network Topology</title>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        #container {{
            width: 100%;
            height: 100vh;
            overflow: hidden;
        }}
        .node {{
            cursor: pointer;
            stroke: #333;
            stroke-width: 1.5px;
        }}
        .link {{
            stroke: #999;
            stroke-opacity: 0.6;
            stroke-width: 1px;
        }}
        .label {{
            font-size: 12px;
            pointer-events: none;
            text-shadow: 0 1px 0 #fff, 1px 0 0 #fff, 0 -1px 0 #fff, -1px 0 0 #fff;
        }}
        .link-label {{
            font-size: 10px;
            pointer-events: none;
            text-shadow: 0 1px 0 #fff, 1px 0 0 #fff, 0 -1px 0 #fff, -1px 0 0 #fff;
        }}
        .controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
        }}
        button {{
            margin: 5px;
            padding: 5px 10px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
        }}
        button:hover {{
            background: #45a049;
        }}
        .legend {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            background: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);

      }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 5px;
        }}
        .legend-color {{
            width: 15px;
            height: 15px;
            margin-right: 5px;
            border-radius: 3px;
        }}
    </style>
    <script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
    <div id="container"></div>
    <div class="controls">
        <button id="reset">Reset View</button>
        <button id="save">Save Layout</button>
        <button id="load">Load Layout</button>
    </div>
    <div class="legend">
        <h3>Device Types</h3>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #3498db;"></div>
            <div>🌐 Routers/Gateways (UDM, USG)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #2ecc71;"></div>
            <div>🔄 Switches (USW)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #e74c3c;"></div>
            <div>📶 Access Points (UAP, U6)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #95a5a6;"></div>
            <div>💻 Other Devices</div>
        </div>
    </div>
    <script>
        // Network data
        const devices = {json.dumps(devices_json)};
        const connections = {json.dumps(connections_json)};

        // Create a force-directed graph
        const width = window.innerWidth;
        const height = window.innerHeight;

        // Create the SVG container
        const svg = d3.select("#container")
            .append("svg")
            .attr("width", width)
            .attr("height", height);

        // Create a group for the graph
        const g = svg.append("g");

        // Create a zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 10])
            .on("zoom", (event) => {{
                g.attr("transform", event.transform);
            }});

        // Apply zoom behavior to the SVG
        svg.call(zoom);

        // Create the force simulation
        const simulation = d3.forceSimulation()
            .force("link", d3.forceLink().id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("x", d3.forceX(width / 2).strength(0.05))
            .force("y", d3.forceY(height / 2).strength(0.05))
            .force("collision", d3.forceCollide().radius(60));

        // Create the links
        const link = g.append("g")
            .selectAll("line")
            .data(connections)
            .enter()
            .append("line")
            .attr("class", "link");

        // Create the link labels
        const linkLabel = g.append("g")
            .selectAll("text")
            .data(connections)
            .enter()
            .append("text")
            .attr("class", "link-label")
            .attr("text-anchor", "middle")
            .text(d => {{
                if (d.source_port === "Auto" && d.target_port === "Auto") {{
                    return "";
                }}
                return `${{d.source_port}} <-> ${{d.target_port}}`;
            }});

        // Create the nodes
        const node = g.append("g")
            .selectAll("circle")
            .data(devices)
            .enter()
            .append("circle")
            .attr("class", "node")
            .attr("r", 25)
            .attr("fill", d => d.color)
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        // Create the node labels
        const nodeLabel = g.append("g")
            .selectAll("text")
            .data(devices)
            .enter()
            .append("text")
            .attr("class", "label")
            .attr("text-anchor", "middle")
            .attr("dy", 35)
            .text(d => `${{d.icon}} ${{d.name}}`);

        // Set up the simulation
        simulation.nodes(devices);
        simulation.force("link").links(connections);

        // Update positions on each tick
        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            linkLabel
                .attr("x", d => (d.source.x + d.target.x) / 2)
                .attr("y", d => (d.source.y + d.target.y) / 2);

            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);

            nodeLabel
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        }});

        // Drag functions
        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            // Keep the node fixed where it was dragged
            // d.fx = null;
            // d.fy = null;
        }}

        // Reset button
        document.getElementById("reset").addEventListener("click", () => {{
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity,
                d3.zoomTransform(svg.node()).invert([width / 2, height / 2])
            );

            // Reset node positions
            devices.forEach(d => {{
                d.fx = null;
                d.fy = null;
            }});

            simulation.alpha(1).restart();
        }});

        // Save layout
        document.getElementById("save").addEventListener("click", () => {{
            const layout = devices.map(d => ({{
                id: d.id,
                x: d.x,
                y: d.y,
                fx: d.fx,
                fy: d.fy
            }}));

            localStorage.setItem("networkLayout", JSON.stringify(layout));
            alert("Layout saved!");
        }});

        // Load layout
        document.getElementById("load").addEventListener("click", () => {{
            const savedLayout = JSON.parse(localStorage.getItem("networkLayout"));

            if (savedLayout) {{
                savedLayout.forEach(saved => {{
                    const device = devices.find(d => d.id === saved.id);
                    if (device) {{
                        device.fx = saved.fx;
                        device.fy = saved.fy;
                    }}
                }});

                simulation.alpha(1).restart();
                alert("Layout loaded!");
            }} else {{
                alert("No saved layout found!");
            }}
        }});
    </script>
</body>
</html>
"""

        # Save the HTML file
        with open(output_path, 'w') as f:
            f.write(html)
    def generate_network_diagram(self, output_path: Optional[str] = None, format: str = 'png') -> None:
        """
        Generate a network diagram.

        Args:
            output_path: Path to save the diagram
            format: Format of the diagram (png, svg, dot, mermaid, html)
        """
        if not output_path:
            if format == 'mermaid':
                output_path = 'diagrams/network_diagram.md'
            elif format == 'dot':
                output_path = 'diagrams/network_diagram.dot'
            elif format == 'html':
                output_path = 'diagrams/network_diagram.html'
            else:
                output_path = f'diagrams/network_diagram.{format}'

        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Check if we have enough connections
        if len(self.connections) < 2:
            log.info("Not enough connections found, trying to infer more connections")
            # self.infer_connections()  # This method doesn't exist yet

        if format == 'mermaid':
            # Generate Mermaid diagram
            mermaid_diagram = self.generate_dot_diagram()  # Placeholder until we implement Mermaid

            # Save the diagram
            with open(output_path, 'w') as f:
                f.write(mermaid_diagram)
        elif format == 'html':
            # Generate interactive HTML visualization
            self.generate_interactive_html(output_path)
        else:
            # For other formats, generate a PNG or SVG using Graphviz
            try:
                import graphviz

                # Create a Graphviz graph
                G = graphviz.Digraph(format=format)
                G.attr('graph', rankdir='TB', overlap='false', splines='true')
                G.attr('node', shape='box', style='filled', fontname='Arial', fontsize='10')
                G.attr('edge', fontname='Arial', fontsize='9')

                # Add devices
                for device_id, device in self.devices.items():
                    # Define node style based on device model/name
                    if "udm" in device.model.lower() or "usg" in device.model.lower() or "dream machine" in device.name.lower():
                        color = "#3498db"
                        icon = "🌐"
                    elif "usw" in device.model.lower() or "switch" in device.name.lower():
                        color = "#2ecc71"
                        icon = "🔄"
                    elif "uap" in device.model.lower() or "ap" in device.name.lower() or "u6" in device.model.lower():
                        color = "#e74c3c"
                        icon = "📶"
                    else:
                        color = "#95a5a6"
                        icon = "💻"

                    # Extract location from name
                    location = "unknown"
                    name_parts = device.name.lower().split()
                    for loc in ["office", "lounge", "bedroom", "kitchen", "dining", "shed", "reece"]:
                        if loc in name_parts:
                            location = loc.capitalize()
                            break

                    # Add node with location as subgraph
                    with G.subgraph(name=f"cluster_{location}") as c:
                        c.attr(label=location)
                        c.node(device_id, f"{icon} {device.name}\\n{device.model}", fillcolor=color, style="filled")

                # Add connections
                for connection in self.connections:
                    source_id = connection.get('source_device_id')
                    target_id = connection.get('target_device_id')

                    # Skip connections with None IDs
                    if source_id is None or target_id is None:
                        continue

                    source_port = connection.get('source_port_name', 'Auto')
                    target_port = connection.get('target_port_name', 'Auto')

                    # Add connection
                    if source_port == "Auto" and target_port == "Auto":
                        G.edge(source_id, target_id)
                    else:
                        # Shorten port names for readability
                        source_port_short = source_port
                        target_port_short = target_port

                        if len(source_port) > 15:
                            source_port_short = source_port[:12] + "..."
                        if len(target_port) > 15:
                            target_port_short = target_port[:12] + "..."

                        G.edge(source_id, target_id, label=f"{source_port_short} <-> {target_port_short}")

                # Render the graph
                G.render(output_path.replace(f'.{format}', ''), cleanup=True)
            except ImportError:
                log.error(f"Graphviz Python package not installed, cannot generate {format} diagram")
                log.error("Please install graphviz: pip install graphviz")

                # Fall back to DOT diagram
                dot_diagram = self.generate_dot_diagram()

                # Save the diagram
                with open(output_path.replace(f'.{format}', '.dot'), 'w') as f:
                    f.write(dot_diagram)
    def generate_interactive_html(self, output_path: str) -> None:
        """
        Generate an interactive HTML visualization of the network topology.

        Args:
            output_path: Path to save the HTML file
        """
        # Create a dictionary of devices
        devices_json = []
        for device_id, device in self.devices.items():
            # Define node style based on device model/name
            if "udm" in device.model.lower() or "usg" in device.model.lower() or "dream machine" in device.name.lower():
                color = "#3498db"
                icon = "🌐"
                group = 1
            elif "usw" in device.model.lower() or "switch" in device.name.lower():
                color = "#2ecc71"
                icon = "🔄"
                group = 2
            elif "uap" in device.model.lower() or "ap" in device.name.lower() or "u6" in device.model.lower():
                color = "#e74c3c"
                icon = "📶"
                group = 3
            else:
                color = "#95a5a6"
                icon = "💻"
                group = 4

            # Extract location from name
            location = "unknown"
            name_parts = device.name.lower().split()
            for loc in ["office", "lounge", "bedroom", "kitchen", "dining", "shed", "reece"]:
                if loc in name_parts:
                    location = loc.capitalize()
                    break

            devices_json.append({
                "id": device_id,
                "name": device.name,
                "model": device.model,
                "color": color,
                "icon": icon,
                "group": group,
                "location": location
            })

        # Create a list of connections
        connections_json = []
        for connection in self.connections:
            source_id = connection.get('source_device_id')
            target_id = connection.get('target_device_id')

            # Skip connections with None IDs
            if source_id is None or target_id is None:
                continue

            source_port = connection.get('source_port_name', 'Auto')
            target_port = connection.get('target_port_name', 'Auto')

            connections_json.append({
                "source": source_id,
                "target": target_id,
                "source_port": source_port,
                "target_port": target_port
            })

        # Create the HTML file
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>UniFi Network Topology</title>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        #container {{
            width: 100%;
            height: 100vh;
            overflow: hidden;
        }}
        .node {{
            cursor: pointer;
            stroke: #333;
            stroke-width: 1.5px;
        }}
        .link {{
            stroke: #999;
            stroke-opacity: 0.6;
            stroke-width: 1px;
        }}
        .label {{
            font-size: 12px;
            pointer-events: none;
            text-shadow: 0 1px 0 #fff, 1px 0 0 #fff, 0 -1px 0 #fff, -1px 0 0 #fff;
        }}
        .link-label {{
            font-size: 10px;
            pointer-events: none;
            text-shadow: 0 1px 0 #fff, 1px 0 0 #fff, 0 -1px 0 #fff, -1px 0 0 #fff;
        }}
        .controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
        }}
        button {{
            margin: 5px;
            padding: 5px 10px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
        }}
        button:hover {{
            background: #45a049;
        }}
        .legend {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            background: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);

      }}
        .legend-item {{
            display: flex;
            align-items: center;
            margin-bottom: 5px;
        }}
        .legend-color {{
            width: 15px;
            height: 15px;
            margin-right: 5px;
            border-radius: 3px;
        }}
    </style>
    <script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
    <div id="container"></div>
    <div class="controls">
        <button id="reset">Reset View</button>
        <button id="save">Save Layout</button>
        <button id="load">Load Layout</button>
    </div>
    <div class="legend">
        <h3>Device Types</h3>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #3498db;"></div>
            <div>🌐 Routers/Gateways (UDM, USG)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #2ecc71;"></div>
            <div>🔄 Switches (USW)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #e74c3c;"></div>
            <div>📶 Access Points (UAP, U6)</div>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background-color: #95a5a6;"></div>
            <div>💻 Other Devices</div>
        </div>
    </div>
    <script>
        // Network data
        const devices = {json.dumps(devices_json)};
        const connections = {json.dumps(connections_json)};

        // Create a force-directed graph
        const width = window.innerWidth;
        const height = window.innerHeight;

        // Create the SVG container
        const svg = d3.select("#container")
            .append("svg")
            .attr("width", width)
            .attr("height", height);

        // Create a group for the graph
        const g = svg.append("g");

        // Create a zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 10])
            .on("zoom", (event) => {{
                g.attr("transform", event.transform);
            }});

        // Apply zoom behavior to the SVG
        svg.call(zoom);

        // Create the force simulation
        const simulation = d3.forceSimulation()
            .force("link", d3.forceLink().id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-500))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("x", d3.forceX(width / 2).strength(0.05))
            .force("y", d3.forceY(height / 2).strength(0.05))
            .force("collision", d3.forceCollide().radius(60));

        // Create the links
        const link = g.append("g")
            .selectAll("line")
            .data(connections)
            .enter()
            .append("line")
            .attr("class", "link");

        // Create the link labels
        const linkLabel = g.append("g")
            .selectAll("text")
            .data(connections)
            .enter()
            .append("text")
            .attr("class", "link-label")
            .attr("text-anchor", "middle")
            .text(d => {{
                if (d.source_port === "Auto" && d.target_port === "Auto") {{
                    return "";
                }}
                return `${{d.source_port}} <-> ${{d.target_port}}`;
            }});

        // Create the nodes
        const node = g.append("g")
            .selectAll("circle")
            .data(devices)
            .enter()
            .append("circle")
            .attr("class", "node")
            .attr("r", 25)
            .attr("fill", d => d.color)
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        // Create the node labels
        const nodeLabel = g.append("g")
            .selectAll("text")
            .data(devices)
            .enter()
            .append("text")
            .attr("class", "label")
            .attr("text-anchor", "middle")
            .attr("dy", 35)
            .text(d => `${{d.icon}} ${{d.name}}`);

        // Set up the simulation
        simulation.nodes(devices);
        simulation.force("link").links(connections);

        // Update positions on each tick
        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            linkLabel
                .attr("x", d => (d.source.x + d.target.x) / 2)
                .attr("y", d => (d.source.y + d.target.y) / 2);

            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);

            nodeLabel
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        }});

        // Drag functions
        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            // Keep the node fixed where it was dragged
            // d.fx = null;
            // d.fy = null;
        }}

        // Reset button
        document.getElementById("reset").addEventListener("click", () => {{
            svg.transition().duration(750).call(
                zoom.transform,
                d3.zoomIdentity,
                d3.zoomTransform(svg.node()).invert([width / 2, height / 2])
            );

            // Reset node positions
            devices.forEach(d => {{
                d.fx = null;
                d.fy = null;
            }});

            simulation.alpha(1).restart();
        }});

        // Save layout
        document.getElementById("save").addEventListener("click", () => {{
            const layout = devices.map(d => ({{
                id: d.id,
                x: d.x,
                y: d.y,
                fx: d.fx,
                fy: d.fy
            }}));

            localStorage.setItem("networkLayout", JSON.stringify(layout));
            alert("Layout saved!");
        }});

        // Load layout
        document.getElementById("load").addEventListener("click", () => {{
            const savedLayout = JSON.parse(localStorage.getItem("networkLayout"));

            if (savedLayout) {{
                savedLayout.forEach(saved => {{
                    const device = devices.find(d => d.id === saved.id);
                    if (device) {{
                        device.fx = saved.fx;
                        device.fy = saved.fy;
                    }}
                }});

                simulation.alpha(1).restart();
                alert("Layout loaded!");
            }} else {{
                alert("No saved layout found!");
            }}
        }});
    </script>
</body>
</html>
"""

        # Save the HTML file
        with open(output_path, 'w') as f:
            f.write(html)
    def generate_html_diagram(self, output_path: str) -> None:
        """
        Generate an interactive HTML network diagram using D3.js.
        
        Args:
            output_path (str): Path to the output HTML file
        """
        # Create nodes and links for D3.js
        nodes = []
        links = []
        
        # Add nodes
        for device_id, device in self.devices.items():
            # Define node style based on device model/name
            if device.device_type == "router":
                color = "#3498db"  # Blue
                icon = "🌐"
            elif device.device_type == "switch":
                color = "#2ecc71"  # Green
                icon = "🔄"
            elif device.device_type == "ap":
                color = "#e74c3c"  # Red
                icon = "📶"
            else:
                color = "#95a5a6"  # Grey
                icon = "💻"
                
            nodes.append({
                'id': device_id,
                'name': device.name,
                'model': device.model,
                'ip': device.ip,
                'type': device.device_type,
                'color': color,
                'icon': icon
            })
        
        # Add links
        for connection in self.connections:
            source_device_id = connection['source_device_id']
            target_device_id = connection['target_device_id']
            source_port_name = connection['source_port_name']
            target_port_name = connection['target_port_name']
            
            # Skip if either device is not in the topology
            if source_device_id not in self.devices or target_device_id not in self.devices:
                continue
            
            links.append({
                'source': source_device_id,
                'target': target_device_id,
                'sourcePort': source_port_name,
                'targetPort': target_port_name
            })
        
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
        html_content = html_template.replace('NODES_PLACEHOLDER', json.dumps(nodes)).replace('LINKS_PLACEHOLDER', json.dumps(links))
        
        # Write HTML file
        with open(output_path, 'w') as f:
            f.write(html_content)
