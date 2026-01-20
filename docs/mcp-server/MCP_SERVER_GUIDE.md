# UniFi Management MCP Server

## Overview

MCP Server implementing Code Mode architecture for UniFi network management. Exposes 30+ tools from `unifi_management_cli` with dynamic discovery and lazy loading.

## Technology Stack

- Python 3.12+
- FastMCP >= 0.5
- PyYAML >= 6.0
- uv/uvx for packaging
- Pydantic >= 2.10

## Project Structure

```text
unifi_mcp/
├── server.py              # FastMCP entry point
├── registry/
│   ├── tool_registry.py   # Central registry
│   ├── manifests/         # YAML tool metadata
│   └── search.py          # search_tools implementation
├── tools/                 # Tool wrappers by category
└── execution/             # Sandboxed execution
```

## Key Commands

```bash
# Development
uv sync --group dev
uv run pytest tests/ -v
uv run ruff check .
uv run ruff format .

# Run server
uv run unifi-mcp

# Install globally
uvx install .
```

## Architecture

Implements Code Mode pattern:
1. **search_tools** - Dynamic tool discovery entry point
2. **Lazy Loading** - Tools loaded on-demand via Proxy pattern
3. **Manifest-based** - Tool metadata in YAML files
4. **Progressive Disclosure** - Summary vs full detail levels

## Tool Categories

- **analysis** (14 tools): IP conflicts, storms, VLAN, STP, QoS
- **diagnostics** (4 tools): Health, performance, security, connectivity
- **discovery** (4 tools): Find device/IP/MAC, client trace
- **connectivity** (3 tools): Firewall, path analysis, traceroute
- **network** (8 managers): Firewall, ACL, DNS, DPI, VLAN
- **protect** (8 components): Camera, events, AI port, MQTT

## Source Dependency

This MCP server imports from `unifi_management_cli`:
```python
from unifi_mapper.analysis import detect_ip_conflicts
from unifi_mapper.diagnostics import network_health_check
```

## Implementation Reference

See `IMPLEMENTATION_PROMPT.md` for detailed architecture and implementation guide.
