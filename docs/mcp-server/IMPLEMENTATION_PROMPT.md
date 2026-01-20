# UniFi Management MCP Server Implementation Prompt

This document provides comprehensive instructions for implementing an MCP (Model Context Protocol) Server based on the Code Mode architecture pattern. The server will expose 30+ network management tools from the `unifi_management_cli` codebase for AI-assisted network troubleshooting and management.

## Project Goal

Create a uvx-installable MCP Server that implements the **Code Mode** architecture pattern, enabling:
- **Dynamic tool discovery** via a `search_tools` entry point
- **Lazy loading** of tool definitions to minimize context overhead
- **Code-based composition** where agents write code to compose tool calls
- **Progressive disclosure** of tool capabilities

## Source Codebase Reference

**Repository**: `/Users/ataylor/code/personal/network/unifi_management_cli`

### Tool Categories (30+ tools total)

The source codebase organizes tools into these categories:

#### 1. Analysis Tools (14 tools)
**Location**: `src/unifi_mapper/analysis/`

| Tool | Function | Priority |
|------|----------|----------|
| `detect_ip_conflicts` | Find IP address conflicts between devices | P1 (High) |
| `detect_storms` | Detect broadcast/multicast storms | P1 (High) |
| `diagnose_vlans` | Comprehensive VLAN diagnostics | P1 (High) |
| `analyze_link_quality` | Port health and error analysis | P2 (Medium) |
| `get_capacity_report` | Network capacity planning | P2 (Medium) |
| `monitor_lags` | LAG health monitoring | P2 (Medium) |
| `validate_qos` | QoS configuration validation | P2 (Medium) |
| `analyze_mac_table` | MAC address table analysis and flapping detection | P3 (Lower) |
| `get_firmware_report` | Firmware security assessment | P3 (Lower) |
| `discover_stp_topology` | Discover current STP topology | STP |
| `calculate_optimal_priorities` | Calculate optimal bridge priorities | STP |
| `generate_stp_report` | Generate STP optimization report | STP |
| `apply_stp_changes` | Apply priority changes via API | STP |
| `format_stp_report_markdown` | Format STP report as markdown | STP |

#### 2. Diagnostics Tools (4 tools)
**Location**: `src/unifi_mapper/diagnostics/`

| Tool | Function |
|------|----------|
| `network_health_check` | Overall infrastructure health monitoring |
| `performance_analysis` | Bottleneck identification |
| `security_audit` | Security configuration review |
| `connectivity_analysis` | Connection troubleshooting |

#### 3. Discovery Tools (4 tools)
**Location**: `src/unifi_mapper/discovery/`

| Tool | Function |
|------|----------|
| `find_device` | Search by name/IP/MAC |
| `find_ip` | Locate device/port by IP address |
| `find_mac` | MAC address location tracking |
| `client_trace` | End-to-end client path analysis |

#### 4. Connectivity Tools (3 tools)
**Location**: `src/unifi_mapper/connectivity/`

| Tool | Function |
|------|----------|
| `firewall_check` | Verify firewall rules and policies |
| `path_analysis` | Network path analysis |
| `traceroute` | Layer 3 path tracing |

#### 5. Network Control Plane (8+ managers)
**Location**: `src/unifi_mapper/network/`

| Manager | Capabilities |
|---------|--------------|
| `UniFiNetworkClient` | Base async HTTP client |
| `FirewallManager` | Zone and policy management |
| `ACLManager` | Access control list automation |
| `DNSPolicyManager` | DNS policy management |
| `DPIAnalytics` | Deep packet inspection analytics |
| `ClientManager` | Client fingerprinting and management |
| `NetworkManager` | VLAN and network configuration |
| `SiteManager` | Multi-site operations |
| `TrafficMatchingListManager` | Traffic matching rules |

#### 6. Protect Integration (8+ components)
**Location**: `src/unifi_mapper/protect/`

| Component | Capabilities |
|-----------|--------------|
| `UniFiProtectClient` | Async Protect client wrapper |
| `EventAnalytics` | Real-time event correlation |
| `AIPortManager` | Smart detection subscriptions |
| `DeviceHealthMonitor` | Proactive health tracking |
| `MQTTBridge` | Home Assistant integration |
| `DeviceRepository` | Device caching and repository |

---

## Code Mode Architecture

### Key Principles (from Cloudflare/Anthropic research)

1. **Progressive Tool Discovery**: Instead of loading 30+ tool definitions upfront, expose a `search_tools` function that returns only relevant tools based on the agent's current needs.

2. **Code-Based Composition**: Transform tool interactions into TypeScript/Python APIs rather than direct MCP tool calls. Agents write code to compose operations.

3. **Sandboxed Execution**: Tool code runs in isolated environments with data processing happening in-sandbox to prevent context bloat.

4. **Lazy Loading**: Tool implementations are loaded only when actually invoked, not at startup.

### Reference Architecture

```
unifi_mcp/
├── __init__.py
├── server.py              # FastMCP server entry point
├── registry/
│   ├── __init__.py
│   ├── tool_registry.py   # Central tool registry
│   ├── manifests/         # YAML tool metadata
│   │   ├── analysis.yaml
│   │   ├── diagnostics.yaml
│   │   ├── discovery.yaml
│   │   ├── connectivity.yaml
│   │   ├── network.yaml
│   │   └── protect.yaml
│   └── search.py          # search_tools implementation
├── tools/
│   ├── __init__.py
│   ├── base.py            # Base tool interface
│   ├── analysis/          # Analysis tool wrappers
│   ├── diagnostics/       # Diagnostics tool wrappers
│   ├── discovery/         # Discovery tool wrappers
│   ├── connectivity/      # Connectivity tool wrappers
│   ├── network/           # Network control wrappers
│   └── protect/           # Protect integration wrappers
├── execution/
│   ├── __init__.py
│   ├── sandbox.py         # Execution sandbox
│   └── code_generator.py  # TypeScript/Python API generation
└── pyproject.toml         # uvx packaging
```

---

## Multi-Model Design Consensus

Five diverse AI models (DeepSeek R1, Qwen3, Llama 4, Cohere R+, Mixtral) recommended these critical patterns:

### 1. Service Registry Pattern (Unanimous)
All models recommend a centralized registry where tools register themselves:

```python
class ToolRegistry:
    def __init__(self):
        self.categories = {}
        self._tools = {}
        self._loaded = {}

    def register(self, name: str, metadata: ToolMetadata):
        """Register tool metadata without loading implementation"""
        self._tools[name] = metadata
        self.categories.setdefault(metadata.category, []).append(name)

    def get(self, name: str) -> Tool:
        """Lazy-load and return tool implementation"""
        if name not in self._loaded:
            self._loaded[name] = self._load_tool(name)
        return self._loaded[name]
```

### 2. Lazy Initialization / Proxy Pattern (Unanimous)
Delay tool loading until actually needed:

```python
class ToolProxy:
    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata
        self._implementation = None

    def execute(self, **params):
        if self._implementation is None:
            self._load_implementation()
        return self._implementation.run(**params)

    def _load_implementation(self):
        module = importlib.import_module(self.metadata.module)
        cls = getattr(module, self.metadata.handler)
        self._implementation = cls()
```

### 3. Plugin Architecture Pattern (Unanimous)
Enable modular tool packaging:

```python
class ToolPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict: ...

    @abstractmethod
    async def execute(self, **kwargs) -> Any: ...
```

### 4. Factory Pattern (DeepSeek R1, Qwen3, Llama 4)
Create tools dynamically based on metadata:

```python
class ToolFactory:
    @staticmethod
    def create(tool_name: str, registry: ToolRegistry) -> Tool:
        metadata = registry.get_metadata(tool_name)
        return ToolProxy(metadata)
```

---

## Implementation Steps

### Step 1: Create Project Structure

```bash
mkdir -p unifi_mcp/{registry/manifests,tools/{analysis,diagnostics,discovery,connectivity,network,protect},execution}
touch unifi_mcp/__init__.py
```

### Step 2: Define Tool Manifests (YAML)

Example `manifests/analysis.yaml`:

```yaml
category: analysis
description: Network analysis tools for UniFi infrastructure
tools:
  detect_ip_conflicts:
    module: unifi_mapper.analysis.ip_conflicts
    handler: detect_ip_conflicts
    description: "Find IP address conflicts between devices"
    priority: P1
    tags: [ip, conflict, layer3]
    parameters:
      device:
        type: string
        optional: true
        description: "Specific device to check"

  detect_storms:
    module: unifi_mapper.analysis.storm_detection
    handler: detect_storms
    description: "Detect broadcast/multicast storms"
    priority: P1
    tags: [broadcast, multicast, storm, layer2]
    parameters:
      threshold:
        type: number
        default: 1000
        description: "Packets per second threshold"
```

### Step 3: Implement Tool Registry

```python
# registry/tool_registry.py
from pathlib import Path
import yaml
from dataclasses import dataclass
from typing import Optional

@dataclass
class ToolMetadata:
    name: str
    module: str
    handler: str
    description: str
    category: str
    priority: str
    tags: list[str]
    parameters: dict

class ToolRegistry:
    def __init__(self, manifests_dir: Path):
        self.manifests_dir = manifests_dir
        self._metadata: dict[str, ToolMetadata] = {}
        self._categories: dict[str, list[str]] = {}
        self._loaded: dict[str, Any] = {}
        self._load_manifests()

    def _load_manifests(self):
        for manifest_file in self.manifests_dir.glob("*.yaml"):
            with open(manifest_file) as f:
                data = yaml.safe_load(f)
                category = data["category"]
                for tool_name, tool_data in data["tools"].items():
                    metadata = ToolMetadata(
                        name=tool_name,
                        category=category,
                        **tool_data
                    )
                    self._metadata[tool_name] = metadata
                    self._categories.setdefault(category, []).append(tool_name)

    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[list[str]] = None,
        detail_level: str = "summary"
    ) -> list[dict]:
        """Search tools with progressive disclosure"""
        results = []
        for name, meta in self._metadata.items():
            # Filter by category
            if category and meta.category != category:
                continue
            # Filter by tags
            if tags and not any(t in meta.tags for t in tags):
                continue
            # Filter by query
            if query and query.lower() not in f"{name} {meta.description}".lower():
                continue

            if detail_level == "summary":
                results.append({"name": name, "description": meta.description})
            elif detail_level == "full":
                results.append({
                    "name": name,
                    "description": meta.description,
                    "category": meta.category,
                    "tags": meta.tags,
                    "parameters": meta.parameters
                })
        return results
```

### Step 4: Implement search_tools MCP Tool

```python
# server.py
from fastmcp import FastMCP
from registry.tool_registry import ToolRegistry

mcp = FastMCP("unifi-management")
registry = ToolRegistry(Path(__file__).parent / "registry/manifests")

@mcp.tool()
async def search_tools(
    query: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    detail_level: str = "summary"
) -> list[dict]:
    """
    Search available UniFi management tools.

    Use this to discover tools before executing them.

    Args:
        query: Text search in tool names and descriptions
        category: Filter by category (analysis, diagnostics, discovery, connectivity, network, protect)
        tags: Filter by tags (e.g., ["ip", "vlan", "stp"])
        detail_level: "summary" (name + description) or "full" (includes parameters)

    Returns:
        List of matching tools with requested detail level
    """
    return registry.search(query, category, tags, detail_level)

@mcp.tool()
async def list_categories() -> dict[str, list[str]]:
    """
    List all tool categories and their tools.

    Returns:
        Dictionary mapping category names to tool lists
    """
    return registry._categories
```

### Step 5: Create Tool Wrappers

```python
# tools/base.py
from abc import ABC, abstractmethod
from typing import Any

class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def execute(self, **params) -> Any: ...

# tools/analysis/ip_conflicts.py
from tools.base import BaseTool
from unifi_mapper.analysis import detect_ip_conflicts as _detect_ip_conflicts

class IPConflictsTool(BaseTool):
    name = "detect_ip_conflicts"
    description = "Find IP address conflicts between devices"

    async def execute(self, device: str | None = None) -> dict:
        return await _detect_ip_conflicts(device=device)
```

### Step 6: uvx Packaging

```toml
# pyproject.toml
[project]
name = "unifi-management-mcp"
version = "0.1.0"
description = "MCP Server for UniFi network management with Code Mode architecture"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=0.5",
    "pyyaml>=6.0",
    "unifi-management-cli",  # Reference the source CLI
]

[project.scripts]
unifi-mcp = "unifi_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]
```

### Step 7: MCP Server Entry Point

```python
# server.py (continued)
import importlib
from pathlib import Path

def main():
    """Entry point for uvx run unifi-mcp"""
    mcp.run()

# Dynamic tool registration from manifests
for category in registry._categories:
    for tool_name in registry._categories[category]:
        metadata = registry._metadata[tool_name]

        # Create dynamic MCP tool wrapper
        @mcp.tool(name=tool_name)
        async def _tool_wrapper(
            __meta=metadata,
            **params
        ):
            """Dynamically generated tool wrapper"""
            module = importlib.import_module(__meta.module)
            handler = getattr(module, __meta.handler)
            return await handler(**params)

        _tool_wrapper.__doc__ = metadata.description
```

---

## Key Design Decisions

### 1. Progressive Disclosure Strategy

Reduce token usage from ~150,000 tokens (all 30+ tools) to ~2,000 tokens per relevant query:

```python
# Minimal response for search (default)
{"name": "detect_ip_conflicts", "description": "Find IP conflicts"}

# Full response when needed
{
    "name": "detect_ip_conflicts",
    "description": "Find IP conflicts",
    "parameters": {"device": {"type": "string", "optional": true}},
    "category": "analysis",
    "tags": ["ip", "conflict"]
}
```

### 2. Dependency on Source CLI

The MCP server imports from `unifi_management_cli` rather than duplicating code:

```python
# Import from existing CLI
from unifi_mapper.analysis import detect_ip_conflicts
from unifi_mapper.diagnostics import network_health_check
```

### 3. Async-First Design

All tool wrappers should be async to support concurrent operations:

```python
async def execute_tool_chain(tools: list[str], params: dict):
    """Execute multiple tools concurrently"""
    tasks = [registry.get(t).execute(**params.get(t, {})) for t in tools]
    return await asyncio.gather(*tasks)
```

### 4. Security Considerations (from DeepSeek R1)

```yaml
# In manifests, include permission requirements
permissions:
  required_roles: [network-admin]
  allowed_contexts: [production, staging]
  requires_confirmation: true  # For destructive operations
```

---

## Testing Strategy

```python
# tests/test_registry.py
import pytest
from unifi_mcp.registry import ToolRegistry

def test_search_by_category():
    registry = ToolRegistry(Path("manifests"))
    results = registry.search(category="analysis")
    assert len(results) >= 10  # Analysis has 14 tools

def test_search_by_query():
    registry = ToolRegistry(Path("manifests"))
    results = registry.search(query="ip")
    assert any("ip_conflicts" in r["name"] for r in results)

def test_lazy_loading():
    registry = ToolRegistry(Path("manifests"))
    # Tool not loaded until execute
    assert "detect_ip_conflicts" not in registry._loaded
    tool = registry.get("detect_ip_conflicts")
    # Now loaded
    assert "detect_ip_conflicts" in registry._loaded
```

---

## Installation and Usage

### Installation via uvx

```bash
# Install globally via uvx
uvx install unifi-management-mcp

# Or run directly
uvx run unifi-management-mcp
```

### Claude Desktop Configuration

```json
{
  "mcpServers": {
    "unifi-management": {
      "command": "uvx",
      "args": ["run", "unifi-management-mcp"]
    }
  }
}
```

### Usage Pattern

```
Agent: I need to diagnose network issues on the UniFi infrastructure.

1. First, search for relevant tools:
   search_tools(query="health", category="diagnostics")

2. Then execute specific tools:
   network_health_check()
   detect_ip_conflicts()

3. Compose analysis:
   # Get STP topology and optimize
   topology = discover_stp_topology()
   changes = calculate_optimal_priorities(topology)
   generate_stp_report(topology, changes)
```

---

## References

- [Cloudflare Code Mode Blog Post](https://blog.cloudflare.com/code-mode/)
- [Universal Tool Calling Protocol - Code Mode](https://github.com/universal-tool-calling-protocol/code-mode)
- [Anthropic Engineering - Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- Source CLI: `/Users/ataylor/code/personal/network/unifi_management_cli`

---

## Summary

This MCP Server implements the Code Mode architecture pattern to efficiently expose 30+ UniFi network management tools. Key features:

1. **search_tools entry point** - Progressive tool discovery reducing context overhead
2. **Lazy loading** - Tools loaded only when needed via Proxy pattern
3. **uvx packaging** - Easy installation with `uvx install unifi-management-mcp`
4. **Code composition** - Agents write code to compose tool chains
5. **Hierarchical organization** - Tools organized by category with manifest-based metadata

The architecture draws from consensus recommendations of 5 diverse AI models (DeepSeek R1, Qwen3, Llama 4, Cohere R+, Mixtral) and Cloudflare/Anthropic's Code Mode research.
