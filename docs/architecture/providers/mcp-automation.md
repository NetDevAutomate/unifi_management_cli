# MCP and Automation Interface Architecture

> **See also**: [C4 Architecture](../c4-architecture.md) | [MCP Server Guide](../../mcp-server/MCP_SERVER_GUIDE.md) | [Implementation Prompt](../../mcp-server/IMPLEMENTATION_PROMPT.md)

## Scope

The MCP interface lives under `src/unifi_mapper/mcp/` and exposes UniFi tooling to MCP-compatible assistants. The current public FastMCP server exposes three discovery meta-tools:

- `search_tools`
- `list_categories`
- `get_tool_info`

The registry also supports executable `ToolProxy` objects through `ToolRegistry.get_tool(name).execute(...)`. That execution path is available to host code/tests, but it is not currently exposed as a public `@mcp.tool()` in `server.py`.

## Component Diagram

```mermaid
C4Component
    title Component Diagram - MCP and Automation Interface

    Person_Ext(assistant, "MCP Client / AI Assistant", "Claude Desktop or another MCP-compatible client")

    Container_Boundary(mcp, "MCP Interface") {
        Component(server, "mcp/server.py", "FastMCP", "Stdio server named unifi-management with public discovery meta-tools")
        Component(registry, "mcp/registry.py / ToolRegistry", "Python", "Loads manifests lazily, indexes metadata, supports category/tag/query search")
        Component(proxy, "mcp/registry.py / ToolProxy", "Python", "Thread-safe lazy import and sync/async handler execution")
        Component(metadata, "mcp/registry.py / ToolMetadata", "dataclass", "Tool contract: name, module, handler, description, category, priority, tags, parameters")
        Component(manifests, "mcp/manifests/*.yaml", "YAML", "53 registered tool contracts across analysis, diagnostics, discovery, connectivity, network, and protect")
        Component(network_tools, "mcp/tools/network.py", "Python", "Network control tool handlers")
        Component(protect_tools, "mcp/tools/protect.py", "Python", "Protect inventory tool handlers")
    }

    Container_Boundary(domain, "Domain Tool Modules") {
        Component(analysis, "analysis/*.py", "Python", "Analysis handlers: STP, VLAN, MTU, SFP, QoS, traffic, capacity, firmware, radio, etc.")
        Component(diagnostics, "diagnostics/*.py", "Python", "Health, performance, security, connectivity diagnostics")
        Component(discovery, "discovery/*.py", "Python", "Device, IP, MAC, and client trace discovery")
        Component(connectivity, "connectivity/*.py", "Python", "Firewall, path, traceroute, inter-VLAN checks")
        Component(network, "network/*.py", "Python", "Network control plane")
        Component(protect, "protect/*.py", "Python", "Protect client and device access")
    }

    Rel(assistant, server, "Calls discovery meta-tools", "MCP / JSON-RPC stdio")
    Rel(server, registry, "Searches and reads metadata")
    Rel(registry, manifests, "Loads on first access")
    Rel(registry, metadata, "Creates records")
    Rel(registry, proxy, "Creates executable proxy on demand")
    Rel(proxy, network_tools, "Lazy imports")
    Rel(proxy, protect_tools, "Lazy imports")
    Rel(proxy, analysis, "Lazy imports")
    Rel(proxy, diagnostics, "Lazy imports")
    Rel(proxy, discovery, "Lazy imports")
    Rel(proxy, connectivity, "Lazy imports")
    Rel(network_tools, network, "Delegates")
    Rel(protect_tools, protect, "Delegates")
```

## PlantUML Class View

```plantuml
@startuml MCPAutomationClasses
class FastMCPServer {
  +search_tools(query, category, tags, detail_level) list
  +list_categories() dict
  +get_tool_info(tool_name) dict
}

class ToolMetadata {
  +name: str
  +module: str
  +handler: str
  +description: str
  +category: str
  +priority: str
  +tags: list[str]
  +parameters: dict
}

class ToolProxy {
  +metadata: ToolMetadata
  +execute(**params) Any
  +is_loaded: bool
  -_load_implementation() None
}

class ToolRegistry {
  -_metadata: dict[str, ToolMetadata]
  -_categories: dict[str, list[str]]
  -_proxies: dict[str, ToolProxy]
  +search(query, category, tags, detail_level) list
  +get_categories() dict
  +get_tool(name) ToolProxy
  +get_metadata(name) ToolMetadata
}

FastMCPServer --> ToolRegistry : uses singleton
ToolRegistry "1" --> "*" ToolMetadata : indexes
ToolRegistry "1" --> "*" ToolProxy : creates lazily
ToolProxy --> ToolMetadata : holds
ToolProxy ..> "importlib" : imports handler module
@enduml
```

## Tool Catalogue

| Manifest | Category | Registered tools | Examples |
| --- | --- | ---: | --- |
| `analysis.yaml` | analysis | 30 | `discover_stp_topology`, `calculate_optimal_priorities`, `audit_mtu_consistency`, `validate_qos`, `analyze_traffic_matrix` |
| `diagnostics.yaml` | diagnostics | 4 | `network_health_check`, `performance_analysis`, `security_audit`, `connectivity_analysis` |
| `discovery.yaml` | discovery | 4 | `find_device`, `find_ip`, `find_mac`, `client_trace` |
| `connectivity.yaml` | connectivity | 4 | `firewall_check`, `path_analysis`, `check_inter_vlan_routing`, `traceroute` |
| `network.yaml` | network | 6 | `get_firewall_zones`, `get_firewall_policies`, `get_acl_rules`, `get_dns_policies`, `get_clients`, `get_networks` |
| `protect.yaml` | protect | 5 | `get_cameras`, `get_nvr_info`, `get_sensors`, `get_lights`, `get_doorbells` |

Total registered automation tools: **53**.

## Discovery Flow

```mermaid
sequenceDiagram
    autonumber
    participant Assistant as MCP Client
    participant Server as FastMCP server.py
    participant Registry as ToolRegistry
    participant YAML as manifests/*.yaml

    Assistant->>Server: search_tools(query="vlan")
    Server->>Registry: search(query="vlan")
    Registry->>YAML: load all manifests if not loaded
    YAML-->>Registry: metadata records
    Registry-->>Server: summary results
    Server-->>Assistant: name + description list
    Assistant->>Server: get_tool_info("diagnose_vlans")
    Server->>Registry: get_metadata("diagnose_vlans")
    Registry-->>Server: category, tags, parameters, module, handler
    Server-->>Assistant: full tool metadata
```

## Lazy Execution Flow

```mermaid
sequenceDiagram
    autonumber
    participant Host as Host code / test
    participant Registry as ToolRegistry
    participant Proxy as ToolProxy
    participant Module as Handler module
    participant Domain as Domain API/client code

    Host->>Registry: get_tool("get_clients")
    Registry-->>Host: ToolProxy
    Host->>Proxy: execute(**params)
    Proxy->>Module: importlib.import_module(metadata.module)
    Proxy->>Module: getattr(metadata.handler)(**params)
    Module->>Domain: call Network or Protect implementation
    Domain-->>Module: structured result
    Module-->>Proxy: result or coroutine
    Proxy-->>Host: awaited or direct result
```

## Current Implementation Notes

- Public MCP meta-tools are intentionally small and stable: discovery is cheap, and full parameter schema is fetched only when needed.
- YAML manifests are the tool contract. Keep descriptions, tags, and parameters accurate whenever handler signatures change.
- `ToolProxy.execute()` handles both synchronous and asynchronous handlers, which lets Network and Protect wrappers coexist behind the same registry.
- The server entry point is `unifi_mapper.mcp.server:main`, installed as `unifi-mcp` in `pyproject.toml`.
- If public MCP execution is added later, document it as a new server capability rather than implying it already exists.
