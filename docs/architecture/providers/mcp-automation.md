# MCP and Automation Interface Architecture

> **See also**: [C4 Architecture](../c4-architecture.md) | [MCP Server Guide](../../mcp-server/MCP_SERVER_GUIDE.md) | [MCP Standards Review](../../mcp-server/MCP_STANDARDS_REVIEW.md)

## Scope

The MCP interface lives under `src/unifi_mapper/mcp/` and exposes UniFi tooling to MCP-compatible assistants. The server (`unifi-mcp`, on the FastMCP bundled with the `mcp` SDK) exposes four public meta-tools:

- `search_tools`
- `list_categories`
- `get_tool_info`
- `execute_tool`, which runs any non-mutating catalog tool through `ToolRunner` (`mcp/runner.py`) and refuses mutating ones with `MUTATION_REFUSED`

With `--surface direct` (or `UNIFI_MCP_TOOL_SURFACE=direct`) it also lists the non-mutating, non-pipeline catalog tools directly, built by `ToolCatalog` (`mcp/catalog.py`) and run through the same `ToolRunner`. Config discovery is in `mcp/config.py`. Launch modes and client configs: [MCP Server Guide](../../mcp-server/MCP_SERVER_GUIDE.md). `ToolRegistry.get_tool(name).execute(...)` (`ToolProxy`) remains for host code and tests. The diagrams below show the registry and lazy-loading core; the runner, catalog and config modules are described in the guide and the [architecture overview](../architecture-overview.md#mcp-server-mcpserverpy).

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
        Component(manifests, "mcp/manifests/*.yaml", "YAML", "76 registered tool contracts across analysis, connectivity, diagnostics, discovery, network, observability and protect")
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
class "server.py meta-tools" as MetaTools <<module>> {
  +search_tools(query, category, tags, detail_level) list
  +list_categories() dict
  +get_tool_info(tool_name) dict
  +execute_tool(tool_name, params) CallToolResult
}

class UnifiFastMCP {
  +runner: ToolRunner
  +call_tool(name, arguments) Any
  +list_tools() list
}

class ToolRunner {
  +registry: ToolRegistry
  +catalog: ToolCatalog
  +settings: ServerSettings
  +is_direct(name) bool
  +run(name, params, surface) CallToolResult
}

class ToolCatalog {
  +registry: ToolRegistry
  +get(name) Tool
  +find(name) Tool
  +is_direct(name) bool
  +direct_tools() list
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
  +credentials: str
  +mutates: bool
  +pipeline: bool
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

MetaTools --> ToolRegistry : searches
MetaTools --> ToolRunner : execute_tool runs through
UnifiFastMCP --> ToolRunner : routes direct tools to
ToolRunner --> ToolCatalog : builds tools through
ToolCatalog --> ToolRegistry : reads metadata from
ToolRegistry "1" --> "*" ToolMetadata : indexes
ToolRegistry "1" --> "*" ToolProxy : creates lazily
ToolProxy --> ToolMetadata : holds
ToolProxy ..> "importlib" : imports handler module
@enduml
```

## Tool Catalogue

| Manifest | Category | Registered tools | Examples |
| --- | --- | ---: | --- |
| `analysis.yaml` | analysis | 46 | `discover_stp_topology`, `audit_link_speeds`, `audit_port_profile_usage`, `check_poe_budget`, `audit_mtu_consistency`, `validate_qos` |
| `diagnostics.yaml` | diagnostics | 8 | `network_health_check`, `inspect_switch_port`, `diagnose_switch_port`, `get_switch_ports`, `diff_port_profiles` |
| `discovery.yaml` | discovery | 5 | `find_device`, `find_ip`, `find_mac`, `client_trace`, `get_client_history` |
| `observability.yaml` | observability | 2 | `get_device_events`, `get_port_counter_rates` |
| `connectivity.yaml` | connectivity | 4 | `firewall_check`, `path_analysis`, `check_inter_vlan_routing`, `traceroute` |
| `network.yaml` | network | 6 | `get_firewall_zones`, `get_firewall_policies`, `get_acl_rules`, `get_dns_policies`, `get_clients`, `get_networks` |
| `protect.yaml` | protect | 5 | `get_cameras`, `get_nvr_info`, `get_sensors`, `get_lights`, `get_doorbells` |

Total registered tools: **76** (3 mutating, never run over MCP; 11 pipeline tools, reachable only through `execute_tool`).

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
- Every call over MCP (`execute_tool` or a direct tool) goes through `ToolRunner`: mutation gate, signature validation, credential gate, error codes with `isError: true`, and secret masking.
