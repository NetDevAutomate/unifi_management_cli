# Tool Contracts: UniFi Network MCP Server

**Feature**: 001-unifi-mcp-server
**Date**: 2024-12-28

## Tool Signatures

All tools follow the FastMCP async pattern with Annotated type hints and prescriptive docstrings.

---

## Discovery Tools

### find_device

```python
async def find_device(
    identifier: Annotated[str, Field(
        description='Device identifier: MAC address, IP address, hostname, or partial name'
    )],
) -> Device:
    '''Find a device on the network by various identifiers.

    When to use:
    - Before traceroute to verify endpoint exists
    - To look up device details by MAC, IP, or name
    - When troubleshooting connectivity and need device info

    Common workflow:
    1. Use find_device() to locate and verify the device
    2. Use get_port_map() to see its physical connection
    3. Use traceroute() if you need to trace the path

    What to do next:
    - If device found: Use traceroute() or client_trace()
    - If device not found: Check if device is online, verify identifier

    Args:
        identifier: MAC (aa:bb:cc:dd:ee:ff), IP (192.168.1.100),
                   hostname, or partial device name

    Returns:
        Device model with full details

    Raises:
        ToolError: DEVICE_NOT_FOUND if device cannot be located
    '''
```

### find_mac

```python
async def find_mac(
    mac: Annotated[str, Field(description='MAC address to locate')],
) -> dict[str, Any]:
    '''Find the physical location of a MAC address on the network.

    When to use:
    - Locating where a device is physically connected
    - Identifying unknown devices on the network
    - Verifying device placement

    Common workflow:
    1. Use find_mac() to locate the device's switch port
    2. Use port_config() to check port settings
    3. Use vlan_info() to verify VLAN assignment

    Returns:
        Dictionary with switch name, port number, VLAN, and timestamps
    '''
```

### find_ip

```python
async def find_ip(
    ip: Annotated[str, Field(description='IP address to locate')],
) -> dict[str, Any]:
    '''Find a device by its IP address.

    When to use:
    - Looking up device info from IP
    - Identifying what's using a specific IP
    - Troubleshooting IP conflicts

    Returns:
        Dictionary with device details and connection info
    '''
```

### client_trace

```python
async def client_trace(
    client: Annotated[str, Field(description='Client identifier (MAC, IP, or hostname)')],
) -> NetworkPath:
    '''Trace a client's connection path from their device to the gateway.

    When to use:
    - Understanding how a client connects to the network
    - Troubleshooting client connectivity issues
    - Verifying client VLAN assignment

    Returns:
        NetworkPath from client device through APs/switches to gateway
    '''
```

---

## Topology Tools

### get_network_topology

```python
async def get_network_topology(
    include_clients: Annotated[bool, Field(
        description='Include client devices in topology'
    )] = False,
    format: Annotated[Literal['json', 'mermaid', 'table'], Field(
        description='Output format'
    )] = 'json',
) -> dict[str, Any] | str:
    '''Get complete network topology.

    When to use:
    - Understanding overall network structure
    - Generating network documentation
    - Identifying potential issues in network design

    Common workflow:
    1. Use get_network_topology() for overview
    2. Use get_device_tree() for specific device relationships
    3. Use get_port_map() for port-level details

    Returns:
        Network topology in requested format
    '''
```

### get_device_tree

```python
async def get_device_tree(
    root_device: Annotated[str | None, Field(
        description='Root device identifier (defaults to gateway)'
    )] = None,
) -> dict[str, Any]:
    '''Get hierarchical device tree from gateway to clients.

    When to use:
    - Visualizing device hierarchy
    - Understanding upstream/downstream relationships
    - Finding devices connected to a specific switch

    Returns:
        Hierarchical tree structure with device relationships
    '''
```

### get_port_map

```python
async def get_port_map(
    device: Annotated[str | None, Field(
        description='Specific device to get port map for (defaults to all switches)'
    )] = None,
    include_empty: Annotated[bool, Field(
        description='Include ports with no connection'
    )] = False,
) -> list[Port]:
    '''Get port status and connections for switches.

    When to use:
    - Viewing all port statuses at once
    - Finding available ports
    - Auditing port naming and VLAN assignments

    Returns:
        List of Port models with status and connection info
    '''
```

---

## Connectivity Tools

### traceroute

```python
async def traceroute(
    source: Annotated[str, Field(
        description='Source endpoint (IP, MAC, hostname, or "gateway")'
    )],
    destination: Annotated[str, Field(
        description='Destination endpoint (IP, MAC, hostname, or "internet")'
    )],
    include_firewall: Annotated[bool, Field(
        description='Check firewall rules along path'
    )] = True,
    verbosity: Annotated[Literal['guided', 'expert'], Field(
        description='Output detail level'
    )] = 'guided',
) -> NetworkPath:
    '''Trace network path between two endpoints with firewall analysis.

    When to use:
    - Troubleshooting connectivity between devices
    - Understanding the path traffic takes
    - Identifying where traffic is being blocked

    Common workflow:
    1. Use find_device() if you're unsure of exact identifiers
    2. Run traceroute() to see the path
    3. If blocked, use firewall_check() for detailed rule analysis
    4. Use get_port_map() to verify physical connections

    What to do next:
    - If path shows DENY: Use firewall_check() for detailed analysis
    - If path incomplete: Check if destination is online
    - If high latency: Use link_quality() on slow hops
    - If crosses VLANs: Verify inter-VLAN routing configuration

    Args:
        source: Starting point - IP, MAC, hostname, switch:port, or "gateway"
        destination: End point - same formats, plus "internet"
        include_firewall: Whether to analyze firewall rules
        verbosity: 'guided' for plain English, 'expert' for technical details

    Returns:
        NetworkPath with hops, latency, VLANs, and firewall verdict

    Raises:
        ToolError: ENDPOINT_NOT_FOUND if source or destination not found
        ToolError: PATH_INCOMPLETE if path cannot be fully traced
    '''
```

### path_analysis

```python
async def path_analysis(
    path: Annotated[NetworkPath, Field(description='Path to analyze')],
) -> dict[str, Any]:
    '''Perform detailed analysis of a network path.

    When to use:
    - After traceroute for deeper analysis
    - Identifying potential bottlenecks
    - Understanding path characteristics

    Returns:
        Analysis with latency breakdown, VLAN crossings, and recommendations
    '''
```

### firewall_check

```python
async def firewall_check(
    source: Annotated[str, Field(description='Source network/IP/VLAN')],
    destination: Annotated[str, Field(description='Destination network/IP/VLAN')],
    protocol: Annotated[str, Field(description='Protocol (tcp, udp, icmp, all)')] = 'all',
    port: Annotated[str | None, Field(description='Port number or range')] = None,
) -> dict[str, Any]:
    '''Check firewall rules between source and destination.

    When to use:
    - Understanding why traffic is blocked
    - Verifying firewall rule configuration
    - Planning new firewall rules

    Common workflow:
    1. Run traceroute() to identify blocking point
    2. Use firewall_check() for detailed rule analysis
    3. Review vlan_info() to understand network segmentation

    Returns:
        Dictionary with:
        - verdict: 'allow' or 'deny'
        - matching_rules: Rules that apply to this traffic
        - rule_order: How rules are evaluated
        - recommendations: Suggestions for changes
    '''
```

---

## Diagnostics Tools

### link_quality

```python
async def link_quality(
    device: Annotated[str | None, Field(
        description='Device to check (defaults to all)'
    )] = None,
) -> list[dict[str, Any]]:
    '''Check link quality and interface statistics.

    When to use:
    - Diagnosing slow connections
    - Finding interfaces with errors
    - Monitoring network health

    Returns:
        List of interfaces with stats (errors, drops, utilization)
    '''
```

### storm_detector

```python
async def storm_detector() -> dict[str, Any]:
    '''Detect broadcast/multicast storms on the network.

    When to use:
    - Network suddenly slows down
    - High CPU on switches
    - Suspected loop or storm

    Returns:
        Storm detection results with affected ports
    '''
```

### lag_monitor

```python
async def lag_monitor(
    device: Annotated[str | None, Field(
        description='Device to check (defaults to all)'
    )] = None,
) -> list[dict[str, Any]]:
    '''Monitor Link Aggregation Group (LAG) status.

    When to use:
    - Verifying LAG health
    - Checking load distribution
    - Troubleshooting LAG issues

    Returns:
        LAG status with member ports and distribution
    '''
```

### system_load

```python
async def system_load(
    device: Annotated[str | None, Field(
        description='Device to check (defaults to all)'
    )] = None,
    format: Annotated[Literal['json', 'table', 'tui'], Field(
        description='Output format'
    )] = 'table',
) -> list[Device] | str:
    '''Get system load metrics for UniFi devices.

    When to use:
    - Diagnosing slow network performance
    - Identifying overloaded devices
    - Capacity planning

    Returns:
        Device list with CPU, memory, load average
    '''
```

---

## Config Tools

### vlan_info

```python
async def vlan_info(
    vlan_id: Annotated[int | None, Field(
        description='Specific VLAN ID (defaults to all)'
    )] = None,
) -> list[VLAN]:
    '''Get VLAN configuration details.

    When to use:
    - Understanding network segmentation
    - Verifying VLAN settings
    - Planning inter-VLAN routing

    Returns:
        List of VLAN configurations
    '''
```

### qos_status

```python
async def qos_status() -> dict[str, Any]:
    '''Get QoS configuration and status.

    When to use:
    - Verifying traffic prioritization
    - Troubleshooting voice/video quality
    - Understanding bandwidth allocation

    Returns:
        QoS settings and active queues
    '''
```

### port_config

```python
async def port_config(
    device: Annotated[str, Field(description='Switch identifier')],
    port: Annotated[int, Field(description='Port number')],
) -> Port:
    '''Get detailed port configuration.

    When to use:
    - Checking specific port settings
    - Troubleshooting port issues
    - Verifying VLAN assignment

    Returns:
        Complete port configuration
    '''
```

### config_diff

```python
async def config_diff(
    hours: Annotated[int, Field(description='Hours to look back')] = 24,
    category: Annotated[str | None, Field(
        description='Filter by category (vlan, firewall, port, profile)'
    )] = None,
) -> list[dict[str, Any]]:
    '''Show configuration changes over time.

    When to use:
    - Correlating issues with recent changes
    - Auditing configuration changes
    - Understanding what changed

    Returns:
        List of changes with timestamps and details
    '''
```

---

## Validation Tools

### config_validator

```python
async def config_validator(
    checks: Annotated[list[str] | None, Field(
        description='Specific checks to run (defaults to all)'
    )] = None,
) -> dict[str, Any]:
    '''Validate network configuration.

    When to use:
    - Regular health checks
    - Before/after changes
    - Troubleshooting configuration issues

    Returns:
        Validation results with pass/fail for each check
    '''
```

### best_practice_check

```python
async def best_practice_check() -> dict[str, Any]:
    '''Check configuration against best practices.

    When to use:
    - Network optimization
    - Security hardening
    - Configuration review

    Returns:
        Best practice compliance with recommendations
    '''
```

### capacity_planner

```python
async def capacity_planner() -> dict[str, Any]:
    '''Analyze network capacity and scaling.

    When to use:
    - Planning network growth
    - Identifying capacity limits
    - Upgrade planning

    Returns:
        Capacity analysis with recommendations
    '''
```

---

## Utility Tools

### format_table

```python
async def format_table(
    data: Annotated[list[dict], Field(description='Data to format')],
    columns: Annotated[list[str] | None, Field(
        description='Columns to include'
    )] = None,
) -> str:
    '''Format data as a rich table.

    Internal utility for formatting tool output.
    '''
```

### render_mermaid

```python
async def render_mermaid(
    diagram_type: Annotated[Literal['graph', 'flowchart', 'sequence'], Field(
        description='Mermaid diagram type'
    )],
    data: Annotated[Any, Field(description='Data to render')],
) -> str:
    '''Render data as Mermaid diagram.

    Internal utility for generating diagrams.
    '''
```

### export_markdown

```python
async def export_markdown(
    content: Annotated[Any, Field(description='Content to export')],
    include_diagram: Annotated[bool, Field(
        description='Include Mermaid diagram'
    )] = True,
) -> str:
    '''Export results as markdown document.

    Internal utility for markdown export.
    '''
```
